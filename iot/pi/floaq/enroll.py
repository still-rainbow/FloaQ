"""선박 등록·승인 루프. 키오스크가 넣어둔 값을 서버에 올리고 승인을 기다린다.

정본은 `docs/edge/api.json` 이다.

    ① POST /api/pi/ships          X-Ship-Register-Key   → ship_id · ship_key · status
    ② GET  /api/pi/ships/{id}     X-Ship-Secret-Key     → status 가 ACTIVE 가 될 때까지
    ③ 그 밖의 전송                 X-Ship-Secret-Key

한 스레드가 이 셋을 순서대로 민다. **주기가 느려도 되는 일**이라 메인 루프에 얹지 않고
별도 스레드로 둔다 — 네트워크가 죽으면 여기가 타임아웃만큼 서는데, 그 자리에
`tick()` 이 있으면 30초 카운트다운 판정이 같이 밀린다.

🔴 **`ship_key` 는 등록 응답에 한 번만 온다.** 받자마자 DB 에 쓴다. 로그도 그 뒤에
   찍는다 — 사이에 예외가 나면 그 배는 영영 못 붙는다.
"""

from __future__ import annotations

import logging
import threading

from floaq import provision
from floaq.adapters.ec2 import Action, EdgeClient

log = logging.getLogger(__name__)

#: 등록 재시도 간격(초). 인터넷이 없을 때 이 간격으로 다시 시도한다.
#:
#: ⚠ **신청 직후에는 이 값을 안 기다린다.** `wake()` 가 루프를 깨워 즉시 올린다 —
#:   화면 앞에 사람이 서 있는 순간이라 30초를 세는 건 고장으로 보인다.
RETRY_SEC = 30

#: 승인 폴링 간격(초). 사람이 관제 웹에서 버튼을 누르는 걸 기다린다.
#: 승인된 순간 화면이 바로 바뀌어야 해서 짧게 잡는다.
APPROVAL_POLL_SEC = 5


class Enroller:
    """등록되지 않은 배를 등록하고, 승인될 때까지 상태를 갱신한다.

    ⚠ 이 객체가 `EdgeClient` 의 키를 갈아끼운다. 전송 펌프는 같은 클라이언트를 쓰되
      `client.has_ship_key` 가 True 이고 승인 상태가 ACTIVE 일 때만 보낸다.
    """

    def __init__(self, conn, client: EdgeClient, pending: provision.PendingShip,
                 clock, *, on_ready=None) -> None:
        self.conn = conn
        self.client = client
        self.pending = pending
        self.clock = clock
        #: 승인까지 끝났을 때 한 번 불린다. `(ship_id)` 를 받는다.
        self._on_ready = on_ready
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._said_waiting = False
        #: `wake()` 가 이걸 set 한다. 대기를 깨우는 용도라 stopping 과 따로 둔다 —
        #: stopping 으로 깨우면 루프가 종료로 오해한다
        self._wake = threading.Event()

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="enroll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()          # 대기 중이면 깨워서 바로 끝낸다
        if self._thread:
            self._thread.join(timeout=3.0)

    def wake(self) -> None:
        """대기를 깨운다. `POST /api/ship` 이 신청을 받으면 부른다.

        🔴 이게 없으면 신청 직후 최대 RETRY_SEC(30초)를 기다린다. 키오스크 화면
          앞에 사람이 서 있는 순간이라 그 침묵이 고장으로 읽힌다.
        """
        self._wake.set()

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                wait = self.step()
            except Exception:
                # 🔴 이 스레드가 죽으면 배가 영영 등록되지 않는데 아무도 모른다.
                #   예외를 남기고 계속 돈다
                log.exception("등록 루프 오류")
                wait = RETRY_SEC
            if wait <= 0:
                return
            # 둘 중 먼저 오는 것에 깬다. wake 면 즉시 다시 돈다
            self._wake.wait(wait)
            self._wake.clear()
            if self._stopping.is_set():
                return

    # ── 한 걸음 ──────────────────────────────────────────────────────
    def step(self) -> float:
        """할 일을 한 번 한다. 다음 호출까지 기다릴 초를 돌려준다. 0 이면 끝이다."""
        ship = provision.registered_ship(self.conn)
        if ship is None:
            return self._enroll()
        return self._check_approval(ship[0])

    def _enroll(self) -> float:
        reg = self.pending.read()
        if reg is None:
            # 키오스크가 아직 안 넣었다. 오류가 아니지만 **한 번은 알린다** —
            # 완전히 조용하면 "신청했는데 안 올라간다" 를 진단할 단서가 없다.
            # 파일 경로를 같이 찍는다: 이름이 어긋나면 여기서만 드러난다
            if not self._said_waiting:
                self._said_waiting = True
                log.info("등록 신청 대기 중. 키오스크가 POST /api/ship 을 부르면 올린다"
                         " (대기 파일 %s)", self.pending.path)
            return RETRY_SEC
        self._said_waiting = False

        got, res = self.client.register_ship(reg)
        if got is None:
            if res.action is Action.HALT:
                # 등록 키가 틀렸거나 서버가 응답을 덜 줬다. 재시도로 안 풀린다
                if res.code == "NO_SHIP_KEY":
                    # 위 ec2.register_ship 이 이미 원인을 적었다. 여기서 반복하지 않는다
                    log.error("선박 등록 중단 — 새 registration_no 로 다시 신청할 것")
                else:
                    log.error("선박 등록 거부 %s %s — 등록 키"
                              "(X-Ship-Register-Key)를 확인할 것", res.status, res.code)
            return RETRY_SEC

        ship_id, ship_key, status = got
        # 🔴 **먼저 쓴다.** 로그·통지는 그다음이다. 여기서 예외가 나면 키를 잃는다
        provision.register_ship(self.conn, ship_id, ship_key, status,
                                reg, self.clock.now())
        self.pending.clear()
        # 등록 키를 버리고 선박 키로 갈아탄다. 한 요청에 키는 하나다
        self.client.use_ship_key(ship_key)
        log.warning("선박 등록 완료 %s  ship_id=%s  status=%s  (키는 저장됨)",
                    reg.name, ship_id, status)
        if status == "ACTIVE":
            self._ready(ship_id)
            return 0.0
        return APPROVAL_POLL_SEC

    def _check_approval(self, ship_id: str) -> float:
        cred = provision.credential(self.conn, ship_id)
        if cred is None:
            # 🔴 pi_ship 은 있는데 키가 없다. 등록 응답을 놓친 상태고, 서버는 같은 키를
            #   다시 주지 않는다. 사람이 풀어야 한다 — 계속 돌아봐야 소용없다
            log.error("ship_id %s 의 ship_key 가 없다. 재등록이 필요하다", ship_id)
            return 0.0

        ship_key, status = cred
        if status == "ACTIVE":
            self.client.use_ship_key(ship_key)
            self._ready(ship_id)
            return 0.0
        if status == "REJECTED":
            # 자동 재시도로 안 풀린다. 사람이 고쳐서 다시 신청해야 한다
            log.error("선박 등록이 반려됐다. 관제 웹에서 사유를 확인할 것")
            return 0.0

        self.client.use_ship_key(ship_key)
        got, res = self.client.ship_status(ship_id)
        if got is None:
            return APPROVAL_POLL_SEC
        if got != status:
            provision.set_status(self.conn, ship_id, got, self.clock.now())
            log.warning("선박 승인 상태 %s -> %s", status, got)
        if got == "ACTIVE":
            self._ready(ship_id)
            return 0.0
        if got == "REJECTED":
            log.error("선박 등록이 반려됐다. 관제 웹에서 사유를 확인할 것")
            return 0.0
        log.info("선박 승인 대기 중 (%s)", got)
        return APPROVAL_POLL_SEC

    def _ready(self, ship_id: str) -> None:
        log.warning("선박 승인 완료 %s — EC2 전송을 시작할 수 있다", ship_id)
        if self._on_ready:
            self._on_ready(ship_id)

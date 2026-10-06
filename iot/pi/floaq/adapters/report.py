"""조난 신고 발신. `ports.Reporter` 의 UDP 구현.

**이 파일이 소켓을 아는 유일한 곳이다.** 규격은 `protocols/`, 문장 형식은
`adapters/nmea.py` 가 맡고, 여기는 언제 몇 번 어디로 보낼지만 정한다.

발신 주체는 Pi 다 `확정` 2026-09-11. Pi 가 직접 쏴야 인터넷·장비 두절을 Pi 가
바로 알고 화면에 띄울 수 있다.

── 채널 3개, 동작이 서로 다르다 ────────────────────────────────────
    AIS_MOB    MMSI 972…  위치보고 1분 8회 + 4분마다 "MOB ACTIVE"
    AIS_SART   MMSI 970…  같은 주기, 문구만 "SART ACTIVE"
    DSC        선박 MMSI  약 4분 간격, **ACK 받으면 자동 중지**

🔴 **채널별 분기를 한 루프에 욱여넣지 않는다.** DSC 는 ACK 으로 멈추고 AIS 둘은
   수동으로만 멈춘다. `database/pi.sql` 의 `CHECK (acked_at IS NULL OR channel = 'DSC')`
   가 같은 규칙을 DB 에서 한 번 더 막는다. 한 루프로 돌리면 반드시 빠뜨린다.

── 전송 ────────────────────────────────────────────────────────────
NMEA 0183 문장을 UDP 로 보낸다. 포트 10110 은 NMEA 0183 over TCP/UDP 로 IETF 가
할당한 번호이고, 항해 소프트웨어 대부분이 이 값을 기본으로 쓴다.

🔴 **이건 시뮬레이션이다.** 실제 전파가 나가지 않는다. 형식 승인된 GMDSS 장비를
   대신할 수 없다. 목적지 주소를 반드시 확인하고 쓸 것 — 사내망 밖으로 나가면
   남의 해도에 허위 조난 표적이 뜬다.
"""

from __future__ import annotations

import logging
import random
import socket
import threading
import time
from dataclasses import dataclass, field

from floaq import config
from floaq.adapters import nmea
from floaq.contracts import ReportChannel
from floaq.protocols import ais, dsc

log = logging.getLogger(__name__)

#: IETF 가 NMEA 0183 over TCP/UDP 에 할당한 포트.
NMEA_UDP_PORT = 10110

#: 조난 장치 MMSI 는 선박 MMSI 와 별개다. 접두가 장치 종류를 뜻한다.
#: `미정`⚠ TODO(IoT) — 실제 발급 절차가 없다. 시연용으로 선박 MMSI 뒤 6자리를 빌린다.
def device_mmsi(ship_mmsi: str, prefix: str) -> str:
    """`972` + 선박 MMSI 뒤 6자리. 9자리를 맞춘다."""
    return prefix + ship_mmsi[-6:]


@dataclass
class ChannelState:
    """채널 하나의 진행 상황. `pi_report` 한 행에 대응한다."""

    channel: ReportChannel
    #: `pi_report.trigger_kind`. AUTO/MANUAL 은 시작할 때, RESCUE 는 중지할 때 정해진다.
    #: ⚠ `pi_accident.report_type`(DISTRESS/URGENCY)과 다른 것이다 (`api.json` IPiReportRequest 설명).
    trigger_kind: str = "AUTO"
    sent_count: int = 0
    first_sent_at: int | None = None
    last_sent_at: int | None = None
    acked_at: int | None = None
    acked_by: str | None = None
    stopped: bool = False
    fail_reason: str | None = None

    @property
    def status(self) -> str:
        if self.fail_reason:
            return "FAILED"
        if self.acked_at is not None:
            return "ACKED"
        if self.stopped:
            return "STOPPED"
        return "SENDING"


@dataclass
class _Incident:
    accident_id: str
    lat: float
    lon: float
    dsc_nature: int | None
    started_at: int
    trigger_kind: str = "AUTO"
    channels: dict[ReportChannel, ChannelState] = field(default_factory=dict)


class UdpReporter:
    """`ports.Reporter` 의 UDP 구현.

    ⚠ 전송은 전용 스레드가 한다. 오케스트레이터 루프에서 직접 쏘면 `tick()` 이
      전송 시간만큼 늦어지고, 그만큼 카운트다운 판정이 밀린다.
    """

    def __init__(
        self,
        *,
        ship_mmsi: str,
        host: str = "255.255.255.255",
        port: int = NMEA_UDP_PORT,
        on_status=None,
    ) -> None:
        """`on_status(accident_id, ChannelState)` 로 상태 변화를 알린다.

        오케스트레이터가 그걸 `pi/report/status` 로 발행하고 DB 에 남긴다.
        여기서 MQTT 나 SQLite 를 만지지 않는다 — 어댑터끼리 엮이면 갈아끼울 수 없다.
        """
        if len(ship_mmsi) != 9 or not ship_mmsi.isdigit():
            raise ValueError(f"선박 MMSI 는 숫자 9자리: {ship_mmsi!r}")
        self.ship_mmsi = ship_mmsi
        self.addr = (host, port)
        self._on_status = on_status

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 브로드캐스트 주소로 보내려면 명시적으로 켜야 한다. 기본값은 꺼짐이다.
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._lock = threading.RLock()
        self._active: _Incident | None = None
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._rx_sock: socket.socket | None = None
        self._rx_thread: threading.Thread | None = None

    # ── ports.Reporter ───────────────────────────────────────────────
    def start(self, accident_id: str, lat: float, lon: float, dsc: int | None,
              *, trigger_kind: str = "AUTO") -> None:
        """세 채널 전부 시작. 이미 진행 중이면 좌표만 갱신한다.

        ⚠ 같은 사고로 두 번 불려도 중복 발신하지 않는다. QoS 1 재전송이나
          사용자 연타로 신고가 두 번 나가면 안 된다.
        """
        with self._lock:
            if self._active and self._active.accident_id == accident_id:
                self._active.lat, self._active.lon = lat, lon
                return
            now = int(time.time())
            self._active = _Incident(
                accident_id=accident_id, lat=lat, lon=lon,
                dsc_nature=dsc, started_at=now, trigger_kind=trigger_kind,
                channels={c: ChannelState(c, trigger_kind=trigger_kind)
                          for c in ReportChannel},
            )
            log.warning("조난 신고 시작 %s  (%.6f, %.6f)  DSC=%s  %s",
                        accident_id, lat, lon, dsc, trigger_kind)
        # 🔴 아직 한 발도 못 쏜 채널의 행을 여기서 만든다. `first_sent_at` 이 NULL 인
        #   행이 그것이다 — "신고가 시작됐는데 아직 안 나갔다"를 관제가 보려면 필요하다.
        #   전송 후에만 알리면 인터넷·소켓이 죽었을 때 아무 행도 안 생긴다.
        for st in self._active.channels.values():
            self._notify(accident_id, st)
        self._ensure_thread()

    def stop(self, accident_id: str, reason: str) -> None:
        """수동 중지. 구조 확정·사고 종료 (IOT-12).

        🔴 구조 확정(`TABLET_RESCUE`)이면 `trigger_kind` 를 RESCUE 로 바꾼다.
          "자동으로 나간 신고"와 "사람을 건져서 멈춘 신고"는 사후 분석에서 전혀 다른
          기록이고, 멈춘 사유를 여기 안 남기면 `status='STOPPED'` 만으로는 못 가른다.
        """
        rescued = reason == "TABLET_RESCUE"
        with self._lock:
            if not self._active or self._active.accident_id != accident_id:
                return
            for st in self._active.channels.values():
                if rescued:
                    st.trigger_kind = "RESCUE"
                if not st.stopped and st.acked_at is None:
                    st.stopped = True
                self._notify(accident_id, st)
            log.warning("조난 신고 중지 %s (%s)", accident_id, reason)
            self._active = None

    # ── 수신 (Table 4.2 조난 확인응답) ───────────────────────────────
    def listen(self, *, bind_port: int | None = None) -> None:
        """확인응답 수신을 시작한다. 별도 스레드가 UDP 를 읽는다.

        🔴 **이 호출이 없으면 `on_dsc_ack` 를 부를 사람이 없다.**
           DSC 는 ACK 으로 멈추는 유일한 채널인데, 수신 경로가 없으면 영원히 쏜다.

        실제 배에서는 DSC 무전기가 Ch70 에서 확인응답을 받아 NMEA 포트로 `$CDDSC`
        를 뱉는다. 여기서는 그 자리에 UDP 를 둔다 — 무전기를 시리얼로 붙이게 되면
        이 메서드만 갈아끼운다.

        ⚠ 송신 포트와 같은 번호로 바인드하면 자기가 쏜 걸 자기가 받는다.
          기본값을 송신 포트와 같게 두되, 자기 MMSI 가 보낸 것은 걸러낸다.
        """
        port = bind_port if bind_port is not None else self.addr[1]
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._rx_sock.bind(("0.0.0.0", port))
        self._rx_sock.settimeout(1.0)
        self._rx_thread = threading.Thread(target=self._rx_loop, name="reporter-rx",
                                           daemon=True)
        self._rx_thread.start()
        log.info("조난 확인응답 수신 대기 0.0.0.0:%d", port)

    def _rx_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                data, _ = self._rx_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            for line in data.decode("ascii", "replace").splitlines():
                self.handle_sentence(line)

    def handle_sentence(self, line: str) -> None:
        """받은 NMEA 한 줄을 처리한다. 시리얼로 바꿔도 이 메서드는 그대로 쓴다.

        ⚠ 예외를 던지지 않는다. 수신 경로에서 죽으면 그 뒤 확인응답을 영영 못 받는다.
        """
        parsed = nmea.parse_dsc(line)
        if parsed is None or not parsed.is_distress_acknowledgement:
            return
        # 자기가 쏜 것을 되받은 경우. 같은 포트로 브로드캐스트하면 흔히 생긴다.
        if parsed.sender_mmsi == self.ship_mmsi:
            return
        with self._lock:
            inc = self._active
        if inc is None:
            return
        # 우리 배를 지목한 확인응답인가. 다른 배 조난에 대한 응답이 같은 망에 흐른다.
        if parsed.distress_mmsi != self.ship_mmsi:
            log.debug("남의 배 확인응답 무시: %s", parsed.distress_mmsi)
            return
        self.on_dsc_ack(inc.accident_id, parsed.sender_mmsi)

    # ── DSC ACK ──────────────────────────────────────────────────────
    def on_dsc_ack(self, accident_id: str, by_mmsi: str) -> None:
        """DSC 조난 확인응답 수신. 해당 채널만 멈춘다.

        🔴 **AIS 두 채널은 계속 간다.** AIS 는 단방향 브로드캐스트라 ACK 이 없고,
           구조 완료 전에 멈추면 표류 중인 익수자를 놓친다.
        """
        if not config.DSC_AUTO_STOP_ON_ACK:
            return
        with self._lock:
            if not self._active or self._active.accident_id != accident_id:
                return
            st = self._active.channels[ReportChannel.DSC]
            if st.acked_at is not None:
                return
            st.acked_at = int(time.time())
            st.acked_by = by_mmsi
            log.warning("DSC ACK 수신 %s <- %s. DSC 만 중지한다", accident_id, by_mmsi)
            self._notify(accident_id, st)

    # ── 내부 ─────────────────────────────────────────────────────────
    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="reporter", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stopping.set()
        for t in (self._thread, self._rx_thread):
            if t:
                t.join(timeout=2.0)
        if self._rx_sock:
            self._rx_sock.close()
        self._sock.close()

    def _notify(self, accident_id: str, st: ChannelState) -> None:
        if self._on_status:
            try:
                self._on_status(accident_id, st)
            except Exception:
                # 상태 통지가 실패해도 **발신은 계속한다.** 신고가 우선이다.
                log.exception("신고 상태 통지 실패")

    def _send(self, lines: tuple[str, ...], st: ChannelState, accident_id: str) -> None:
        payload = "".join(lines).encode("ascii")
        try:
            self._sock.sendto(payload, self.addr)
        except OSError as e:
            # 조용히 삼키면 사용자는 신고가 나간 줄 안다 (ports.Reporter 문서)
            st.fail_reason = "NO_RECEIVER"
            log.error("신고 전송 실패 %s: %s", st.channel, e)
            self._notify(accident_id, st)
            return
        now = int(time.time())
        st.sent_count += 1
        st.first_sent_at = st.first_sent_at or now
        st.last_sent_at = now
        self._notify(accident_id, st)

    def _loop(self) -> None:
        """채널별 주기를 각자 돌린다.

        AIS 두 채널: `REPORT_BURST_COUNT` 회를 `REPORT_BURST_WINDOW_SEC` 에 나눠 보내고,
                     `TEXT_EVERY_SEC` 마다 한 번 Message 14 를 섞는다.
        DSC:         `DSC_RETRY_SEC` 간격. ACK 오면 중지.
        """
        ais_period = config.REPORT_BURST_WINDOW_SEC / config.REPORT_BURST_COUNT
        next_ais = 0.0
        next_dsc = 0.0
        last_text = 0.0

        while not self._stopping.is_set():
            with self._lock:
                inc = self._active
                if inc is None:
                    time.sleep(0.5)
                    continue
                lat, lon, aid = inc.lat, inc.lon, inc.accident_id
                nature = inc.dsc_nature
                ch = inc.channels

            now = time.monotonic()

            if now >= next_ais:
                next_ais = now + ais_period
                # 4분마다 한 번만 문구를 섞는다 (IEC 61097-14)
                with_text = (now - last_text) >= ais.TEXT_EVERY_SEC
                if with_text:
                    last_text = now

                st = ch[ReportChannel.AIS_MOB]
                if not st.stopped:
                    self._send(nmea.ais_mob_sentences(
                        mmsi=device_mmsi(self.ship_mmsi, ais.MMSI_PREFIX_MOB),
                        lat=lat, lon=lon, second=time.gmtime().tm_sec,
                        with_text=with_text), st, aid)

                st = ch[ReportChannel.AIS_SART]
                if not st.stopped:
                    self._send(nmea.ais_sart_sentences(
                        mmsi=device_mmsi(self.ship_mmsi, ais.MMSI_PREFIX_SART),
                        lat=lat, lon=lon, second=time.gmtime().tm_sec,
                        with_text=with_text), st, aid)

            if now >= next_dsc:
                # 🔴 다음 시도까지의 지연을 **매번 새로 뽑는다** (M.541 §3.1.3.1).
                #   고정 간격이면 재전송이 확인응답 수신 창을 같은 자리에서 계속 막는다.
                #   확인응답은 해안국 운용자가 수동으로 보내므로 도착 시각이 무작위다.
                next_dsc = now + random.uniform(config.DSC_REPEAT_MIN_SEC,
                                                config.DSC_REPEAT_MAX_SEC)
                st = ch[ReportChannel.DSC]
                # ACK 을 받았으면 DSC 만 멈춘다. AIS 는 위에서 계속 나간다.
                if not st.stopped and st.acked_at is None:
                    utc = time.gmtime()
                    lines = nmea.dsc_distress_sentences(
                        mmsi=self.ship_mmsi,
                        nature=nature if nature is not None else int(dsc.Nature.UNDESIGNATED),
                        lat=lat, lon=lon,
                        hour=utc.tm_hour, minute=utc.tm_min)
                    # 한 번의 호출 시도 = 연속 5회 (M.541 §3.1.3.1).
                    # ⚠ 확장 메시지(DSE)는 **마지막 호출 뒤에 한 번만** 붙인다
                    #   (M.493 §11.4.1). 매 호출마다 붙이면 규격에 어긋난다.
                    alert, *expansion = lines
                    for n in range(config.DSC_ATTEMPT_CALLS):
                        last = n == config.DSC_ATTEMPT_CALLS - 1
                        self._send((alert, *expansion) if last else (alert,), st, aid)
                        if st.acked_at is not None or self._stopping.is_set():
                            break   # 시도 도중 확인응답이 오면 멈춘다

            time.sleep(0.2)

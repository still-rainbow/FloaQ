"""키오스크 장치 패널 (`pi/device/status`).

🔴 **아무도 이걸 발행하지 않았다.** 키오스크의 `DevicePane`(카메라·AI 감지·
   흔들림·부표)은 통째로 이 한 토픽으로 그려진다. 계약(`contracts/pi.DeviceStatus`)
   도 받는 쪽(`kiosk/src/pi/decode.ts`)도 처음부터 있었고 **보내는 쪽만 없었다** —
   그래서 시연 내내 전 장치가 '모름' 이었다. 2026-09-22 에 찾았다.

⚠ **주기마다 무조건 보낸다.** 값이 바뀔 때만 보내면 키오스크가 '값이 안 옴' 과
  'Pi 가 죽음' 을 구분하지 못한다(계약 주석). retained 라 늦게 켠 화면도 바로 찬다.

세 상태의 뜻을 한 줄로:

    UNKNOWN  그 장치를 아예 안 붙였다 (`--imu off`, `--lora off` …)
    ERROR    붙였는데 신호가 끊겼다
    OK       최근에 값이 들어왔다

🔴 "안 붙임" 과 "붙였는데 죽음" 을 같은 값으로 뭉뚱그리면 안 된다. 앞은 정상이고
   뒤는 사람이 가서 봐야 한다.
"""

from __future__ import annotations

import logging
import threading
import time

from floaq.contracts import DeviceHealth, DeviceStatus

log = logging.getLogger(__name__)

#: 발행 주기. 계약이 "5초 + 변화 시" 라고 적어 두었다.
PERIOD_SEC = 5.0

#: `jetson/status` 를 이만큼 못 받으면 젯슨이 죽은 것으로 본다.
#: 계약(`contracts/jetson.JetsonStatus`)이 정한 값이라 여기서 바꾸면 갈라진다.
JETSON_DEAD_SEC = 15.0

#: GPS fix 나이 한계. 플로터가 1Hz 로 뱉으므로 이보다 오래면 선이 빠진 것이다.
GPS_STALE_SEC = 10.0

#: IMU 는 1Hz 다 (`floaq/imu.py PERIOD_SEC`). 한 주기를 놓칠 여유를 준다.
IMU_STALE_SEC = 8.0

#: 부표 하트비트. 실물 부표가 1Hz 로 쏘지만 LoRa 는 잘 빠진다.
BUOY_STALE_SEC = 30.0

#: EC2 가 마지막으로 대답한 뒤 이만큼 지나면 인터넷이 끊긴 것으로 본다.
#: 전송 펌프가 놀고 있을 때도 주기적으로 무언가는 오가므로 넉넉히 잡는다.
INTERNET_STALE_SEC = 120.0


class JetsonWatch:
    """마지막 `jetson/status`.

    🔴 **Pi 는 이 토픽을 구독조차 하지 않았다.** 카메라 L/R 과 AI 의 상태는
       젯슨만 알고, 키오스크는 Pi 를 통해서만 본다. 중간이 비어 있었다.

    ⚠ MQTT 워커 스레드가 쓰고 발행 펌프 스레드가 읽는다. 잠근다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = None
        self._at = 0.0

    def put(self, status) -> None:
        with self._lock:
            self._last, self._at = status, time.monotonic()

    def get(self):
        """`(마지막 상태, 받은 지 몇 초)`. 한 번도 못 받았으면 `(None, inf)`."""
        with self._lock:
            if self._last is None:
                return None, float("inf")
            return self._last, time.monotonic() - self._at


def health(attached: bool, fresh: bool) -> DeviceHealth:
    """모듈 맨 위의 세 상태 규칙. 한 곳에서만 정한다."""
    if not attached:
        return DeviceHealth.UNKNOWN
    return DeviceHealth.OK if fresh else DeviceHealth.ERROR


class _Counter:
    """카운터가 늘었나로 살아 있는지 본다.

    ⚠ 어댑터에 "마지막 수신 시각" 을 새로 달지 않으려는 것이다. LoRa 링크도
      IMU 펌프도 이미 누적 카운터를 갖고 있고, 그 값이 한 주기 안에 늘었으면
      그 사이에 무언가 들어온 것이다.
    """

    def __init__(self) -> None:
        self._prev: int | None = None
        self.last_at: float = 0.0

    def feed(self, value: int | None) -> None:
        if value is None:
            return
        if self._prev is not None and value > self._prev:
            self.last_at = time.monotonic()
        self._prev = value

    def age(self) -> float:
        return float("inf") if self.last_at == 0.0 else time.monotonic() - self.last_at


class DeviceStatusPump:
    """5초마다 `pi/device/status` 를 낸다.

    어댑터를 직접 받되 **없으면 None** 이다. None 은 UNKNOWN 이 되고, 그게
    "안 붙였다" 의 표현이다.
    """

    def __init__(self, bus, clock, *, launcher, jetson: JetsonWatch,
                 gnss=None, buoy=None, imu=None, edge=None,
                 period: float = PERIOD_SEC) -> None:
        self.bus = bus
        self.clock = clock
        self.launcher = launcher
        self.jetson = jetson
        #: `adapters.gps._ThreadedGnss`. `age()` 로 fix 나이를 준다
        self.gnss = gnss
        #: `adapters.lora._ThreadedLink`. `stats.ok` 가 누적 수신 프레임 수다
        self.buoy = buoy
        #: `floaq.imu.ImuPump`. `written` 이 누적 기록 행 수다
        self.imu = imu
        #: `adapters.ec2.EdgeClient`. `last_ok_at` 이 마지막 응답 시각이다
        self.edge = edge
        self.period = period
        self._buoy_rx = _Counter()
        self._imu_rx = _Counter()
        #: 부표를 마지막으로 받은 **Unix 시각**. 계약이 Unix 를 요구한다
        self._last_buoy_unix: int | None = None
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.published = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="device-status",
                                        daemon=True)
        self._thread.start()
        log.info("장치 상태 발행 시작 (%.0f초 주기)", self.period)

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.round_once()
            except Exception:
                # ⚠ 화면 장치 표시가 죽는다고 사고 처리를 멈추지 않는다
                log.exception("장치 상태 발행 오류")
            self._stopping.wait(self.period)

    # ── 한 회차 ──────────────────────────────────────────────────────
    def round_once(self) -> None:
        self._sample()
        self.bus.publish("pi/device/status", self.snapshot(), retain=True)
        self.published += 1

    def _sample(self) -> None:
        """누적 카운터를 읽어 '방금 들어왔나' 를 갱신한다."""
        before = self._buoy_rx.last_at
        self._buoy_rx.feed(getattr(getattr(self.buoy, "stats", None), "ok", None))
        if self._buoy_rx.last_at != before and self.clock.is_valid():
            self._last_buoy_unix = self.clock.now()
        self._imu_rx.feed(getattr(self.imu, "written", None))

    def snapshot(self) -> DeviceStatus:
        """지금 상태. 시험이 스레드 없이 이것만 부른다."""
        status, age = self.jetson.get()
        alive = age <= JETSON_DEAD_SEC

        # 🔴 젯슨이 살아 있을 때만 그쪽 값을 믿는다. 마지막으로 받은 retained 를
        #    계속 OK 로 보여주면 젯슨을 뽑아도 화면은 정상으로 남는다.
        if status is not None and alive:
            camera_l, camera_r = status.camera_l, status.camera_r
            camera_dirty = bool(status.camera_dirty)
            ai = DeviceHealth.OK
        else:
            # 한 번도 못 받았으면 '안 붙임', 받다가 끊겼으면 '고장'
            never = status is None
            camera_l = camera_r = ai = health(not never, False)
            camera_dirty = False

        return DeviceStatus(
            is_loaded=bool(self.launcher.is_loaded()),
            camera_l=camera_l,
            camera_r=camera_r,
            camera_dirty=camera_dirty,
            ai=ai,
            imu=health(self.imu is not None, self._imu_rx.age() <= IMU_STALE_SEC),
            lora=health(self.buoy is not None, self._buoy_rx.age() <= BUOY_STALE_SEC),
            gps=health(self.gnss is not None, self._gps_age() <= GPS_STALE_SEC),
            internet=self._internet(),
            last_buoy_rx_at=self._last_buoy_unix,
        )

    def _gps_age(self) -> float:
        if self.gnss is None:
            return float("inf")
        try:
            return float(self.gnss.age())
        except Exception:
            return float("inf")

    def _internet(self) -> bool:
        """🔴 모르면 False 다. 키오스크가 '신고 불가' 를 띄우는 쪽이 안전하다."""
        last = getattr(self.edge, "last_ok_at", 0.0)
        if not last:
            return False
        return (time.monotonic() - last) <= INTERNET_STALE_SEC

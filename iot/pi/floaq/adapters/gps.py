"""배 GPS. NMEA 0183 `$xxRMC` 를 읽는다.

🔴 **Pi 에 GPS 모듈을 달지 않는다.** 배가 이미 갖고 있다 — DSC·AIS 장비는 GPS 없이
   동작하지 못하므로, 그런 장비를 단 배에는 반드시 측위원이 있고 플로터가 NMEA 를
   뱉는다. 우리는 그 선에 붙는다.

RMC 한 문장에 필요한 게 다 들어 있다:

    $GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
            │      │  │         │          │     │     │
            시각   상태 위도      경도       SOG   COG   날짜

    위치     조난 신고 좌표, 사고 기록
    UTC      시계. Pi 5 는 RTC 가 없고 폐쇄망이라 NTP 도 없다
    COG      Jetson 의 조준 해 (선수 기준 각도를 절대 좌표로 옮길 때)

── 함정 넷 ─────────────────────────────────────────────────────────

🔴 **토커 ID 를 `$GP` 로 고정하지 않는다.**
   $GPRMC GPS 단독 / $GNRMC 멀티 GNSS / $GLRMC GLONASS / $GARMC Galileo.
   요즘 수신기는 대부분 **$GNRMC** 를 낸다. `$GP` 만 매칭하면 한 줄도 안 잡힌다.

🔴 **좌표가 십진도가 아니다.** `4807.038` 은 48.07도가 아니라 **48도 07.038분**이다.
   그냥 float() 하면 약 5.7km 틀어진다.

🔴 **상태 필드 A/V.** `V` 면 fix 가 없다는 뜻이라 좌표도 시각도 쓸 수 없다.
   `clock.is_valid()` 가 이 값을 본다.

🔴 **날짜가 2자리 연도.** `230394` 는 1994-03-23 이다. 세기 보정을 해야 한다.

── 시계 ────────────────────────────────────────────────────────────
`GpsClock` 은 마지막 fix 의 UTC 를 그대로 돌려주지 않는다. RMC 가 1Hz 라 그러면
`now()` 가 1초씩 멈춰 있다. fix 를 받은 monotonic 시점을 함께 기억해 두고 그 차이를
더한다 — fix 사이에도 시간이 흐르고, 잠깐 끊겨도 계속 간다.
"""

from __future__ import annotations

import calendar
import logging
import math
import socket
import threading
import time
from dataclasses import dataclass
from typing import Final

from floaq import config

log = logging.getLogger(__name__)

#: 이 시간 넘게 fix 가 없으면 시계를 믿지 않는다.
#: LWT(22.5초)나 30초 카운트다운보다 짧게 둔다 — 시계가 죽은 채로 자동 신고가
#: 나가는 것보다 보류가 낫다.
FIX_STALE_SEC = 10.0

#: NMEA 0183 표준 속도. 플로터도 USB GPS 도 대개 이 값이다.
NMEA_BAUD = 4800

#: IETF 가 NMEA 0183 over TCP/UDP 에 할당한 포트. 조난 신고 송출과 같은 선이다.
NMEA_UDP_PORT = 10110


@dataclass(frozen=True, slots=True)
class Fix:
    """측위 한 건. `$xxRMC` 를 그대로 옮긴 것."""

    lat: float
    lon: float
    #: UTC epoch 초. 날짜와 시각을 합친 값이다.
    utc: int
    sog_knots: float | None
    cog_deg: float | None
    #: RMC 상태 필드. A 면 True, V 면 False.
    valid: bool


def _checksum(body: str) -> str:
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}"


def _dm_to_degrees(raw: str, hemi: str) -> float | None:
    """`ddmm.mmmm` -> 십진도. 경도는 `dddmm.mmmm` 라 자릿수가 하나 많다.

    🔴 분이 앞 2자리를 뺀 **나머지 전부**다. 점 위치로 자르면 안 된다 —
       `4807.038` 에서 도는 48, 분은 07.038 이다.
    """
    if not raw:
        return None
    dot = raw.find(".")
    if dot < 3:                      # 도 자리가 최소 2자리 + 분 2자리
        return None
    deg = int(raw[:dot - 2])
    minutes = float(raw[dot - 2:])
    value = deg + minutes / 60.0
    if hemi in ("S", "W"):
        value = -value
    return value


def _utc_epoch(hhmmss: str, ddmmyy: str) -> int | None:
    """RMC 의 시각·날짜 -> epoch 초.

    ⚠ 연도가 2자리다. NMEA 0183 규격이 세기를 주지 않으므로 2000년대로 본다 —
      이 장비가 1900년대에 쓰일 일은 없다.
    """
    if len(hhmmss) < 6 or len(ddmmyy) != 6:
        return None
    try:
        h, m, s = int(hhmmss[0:2]), int(hhmmss[2:4]), int(float(hhmmss[4:]))
        d, mo, y = int(ddmmyy[0:2]), int(ddmmyy[2:4]), int(ddmmyy[4:6])
    except ValueError:
        return None
    return calendar.timegm((2000 + y, mo, d, h, m, s, 0, 0, 0))


def parse_rmc(line: str) -> Fix | None:
    """`$xxRMC` 한 줄 -> `Fix`. 아니거나 깨졌으면 None.

    ⚠ 예외를 던지지 않는다. 수신 경로에서 죽으면 그 뒤 측위를 영영 못 받는다.
    """
    line = line.strip()
    # 🔴 토커 ID 를 고정하지 않는다. $GPRMC / $GNRMC / $GLRMC 전부 받는다.
    if len(line) < 7 or line[0] != "$" or line[3:6] != "RMC":
        return None
    if "*" not in line:
        return None
    body, _, cs = line[1:].partition("*")
    if cs[:2].upper() != _checksum(body):
        return None

    f = body.split(",")
    if len(f) < 10:
        return None

    valid = f[2] == "A"
    lat = _dm_to_degrees(f[3], f[4])
    lon = _dm_to_degrees(f[5], f[6])
    utc = _utc_epoch(f[1], f[9])
    if lat is None or lon is None or utc is None:
        return None

    def _num(v: str) -> float | None:
        try:
            return float(v)
        except ValueError:
            return None

    return Fix(lat=lat, lon=lon, utc=utc, sog_knots=_num(f[7]),
               cog_deg=_num(f[8]), valid=valid)


# ── 소스 ─────────────────────────────────────────────────────────────
class _Latest:
    """최신 fix 만 들고 있는 상자. 읽기 스레드와 호출자 사이의 경계다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fix: Fix | None = None
        self._at: float = 0.0

    def put(self, fix: Fix) -> None:
        with self._lock:
            self._fix, self._at = fix, time.monotonic()

    def get(self) -> tuple[Fix | None, float]:
        with self._lock:
            return self._fix, self._at


class _ThreadedGnss:
    """공통 수명주기. 자식이 `_lines()` 만 구현한다."""

    def __init__(self) -> None:
        self._latest = _Latest()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="gnss", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def read(self) -> Fix | None:
        """`ports.GnssSource`. 마지막 측위 스냅샷."""
        return self._latest.get()[0]

    def age(self) -> float:
        fix, at = self._latest.get()
        return 1e9 if fix is None else time.monotonic() - at

    def _lines(self):
        raise NotImplementedError

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                for line in self._lines():
                    if self._stopping.is_set():
                        return
                    fix = parse_rmc(line)
                    if fix is not None:
                        self._latest.put(fix)
            except Exception:
                # 케이블이 빠지거나 포트가 닫혀도 죽지 않는다. 쉬었다 다시 연다.
                log.exception("GPS 읽기 실패 — 재시도한다")
                time.sleep(2.0)


class SerialGnss(_ThreadedGnss):
    """플로터 RS-422 또는 USB GPS.

    ⚠ pyserial 을 여기서만 import 한다. UDP·가짜만 쓸 때 설치를 강요하지 않는다.
    """

    def __init__(self, port: str, baud: int = NMEA_BAUD) -> None:
        super().__init__()
        self.port, self.baud = port, baud

    def _lines(self):
        import serial  # noqa: PLC0415

        with serial.Serial(self.port, self.baud, timeout=2.0) as ser:
            while not self._stopping.is_set():
                raw = ser.readline()
                if raw:
                    yield raw.decode("ascii", "replace")


class UdpGnss(_ThreadedGnss):
    """망으로 뿌리는 플로터. NMEA 0183 은 양방향이라 조난 신고와 같은 포트를 쓴다.

    ⚠ 우리가 내보내는 `$CDDSC` 가 되돌아올 수 있다. `parse_rmc` 가 RMC 아닌 문장을
      None 으로 흘리므로 해가 없다.
    """

    def __init__(self, port: int = NMEA_UDP_PORT, bind: str = "0.0.0.0") -> None:
        super().__init__()
        self.port, self.bind = port, bind

    def _lines(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind, self.port))
        sock.settimeout(1.0)
        try:
            while not self._stopping.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                yield from data.decode("ascii", "replace").splitlines()
        finally:
            sock.close()


#: 시연 기본 위치 — 부산 앞바다. 오륙도 남동쪽 약 5km 의 개방 수역이다.
#: 웹 팀 요청 `확정` 2026-09-17: 화면에 뜰 때 부산 앞바다로 보여야 한다.
#: ⚠ 육지 좌표를 쓰면 해도에서 배가 산 위에 뜬다. 바꿀 때 물 위인지 확인할 것.
BUSAN_OFFSHORE: Final[tuple[float, float]] = (35.0500, 129.1000)


class FakeGnss(_ThreadedGnss):
    """고정 좌표에서 출발해 1Hz 로 흘린다. **GPS 없이도 Jetson 이 조준 해를 짠다.**

    실제 문장을 만들어 `parse_rmc` 를 거치게 한다 — 파서를 우회하면 파서 버그가
    시연 날까지 안 드러난다.

    🔴 이동량을 `sog`·`cog` 에서 계산한다. 예전에는 위경도에 고정 증분을 더하면서
      `sog` 는 따로 8.0 을 싣고 있었다 — 실제 이동이 약 1.8kn 인데 문장은 8.0kn
      이라고 말하는 상태였다. Jetson 의 조준 해는 "착수 예상 시점의 배 위치"를
      `speed_kn` 으로 예측하므로(DES-38 §5) 그 둘이 어긋나면 조준이 빗나간다.
    """

    def __init__(self, lat: float | None = None, lon: float | None = None,
                 cog: float = 84.4, sog: float = 8.0) -> None:
        super().__init__()
        self.lat = BUSAN_OFFSHORE[0] if lat is None else lat
        self.lon = BUSAN_OFFSHORE[1] if lon is None else lon
        self.cog, self.sog = cog, sog

    def sentence(self, when: float | None = None) -> str:
        t = time.gmtime(when if when is not None else time.time())
        body = ",".join([
            "GNRMC", time.strftime("%H%M%S", t), "A",
            _to_dm(self.lat, 2), "N" if self.lat >= 0 else "S",
            _to_dm(self.lon, 3), "E" if self.lon >= 0 else "W",
            f"{self.sog:.1f}", f"{self.cog:.1f}",
            time.strftime("%d%m%y", t), "", "",
        ])
        return f"${body}*{_checksum(body)}\r\n"

    def _advance(self, dt: float) -> None:
        """`cog` 방향으로 `sog` 만큼 움직인다. 배가 움직이는 게 화면에 보여야 한다."""
        metres = self.sog * _KNOT_MS * dt
        rad = math.radians(self.cog)
        self.lat += metres * math.cos(rad) / _M_PER_DEG_LAT
        # 경도 1도의 거리는 위도에 따라 줄어든다. 적도 기준으로 두면 부산에서 22% 빠르다
        self.lon += metres * math.sin(rad) / (_M_PER_DEG_LON_EQ
                                              * math.cos(math.radians(self.lat)))

    def _lines(self):
        while not self._stopping.is_set():
            self._advance(config.GPS_PUBLISH_SEC)
            yield self.sentence()
            time.sleep(config.GPS_PUBLISH_SEC)


_KNOT_MS: Final[float] = 0.514444          # 1 knot = 1852 m / 3600 s
_M_PER_DEG_LAT: Final[float] = 111_132.0   # 위도 1도. 위도에 따라 거의 안 변한다
_M_PER_DEG_LON_EQ: Final[float] = 111_320.0  # 적도에서 경도 1도. cos(위도)를 곱해 쓴다


def _to_dm(value: float, deg_digits: int) -> str:
    """십진도 -> `ddmm.mmmm`. 경도는 도가 3자리다."""
    a = abs(value)
    deg = int(a)
    return f"{deg:0{deg_digits}d}{(a - deg) * 60.0:07.4f}"


# ── 시계 ─────────────────────────────────────────────────────────────
class GpsClock:
    """`ports.Clock` 을 GPS UTC 로 구현한다.

    Pi 5 에는 RTC 배터리가 없고 폐쇄망이라 NTP 도 없다. 시각 기준이 GPS UTC 다
    `확정` 2026-09-11.

    🔴 마지막 fix 의 UTC 를 그대로 돌려주지 않는다. RMC 가 1Hz 라 그러면 `now()` 가
       1초씩 멈춰 있고, 30초 카운트다운이 그 위에서 돈다. fix 를 받은 monotonic
       시점을 함께 기억해 그 차이를 더한다 — fix 사이에도 시간이 흐르고 잠깐
       끊겨도 계속 간다.

    ⚠ `is_valid()` 가 False 인 동안 orchestrator 는 **자동 전이를 하지 않는다.**
      시계를 못 믿는 채로 `report_due_at` 을 비교하면 전원만 넣어도 신고가 나간다.
    """

    def __init__(self, source: _ThreadedGnss) -> None:
        self.source = source
        self._base_utc: int | None = None
        self._base_mono: float = 0.0

    def _sync(self) -> None:
        fix = self.source.read()
        if fix is not None and fix.valid:
            # fix 수신 시점의 monotonic 을 같이 잡아둔다
            self._base_utc = fix.utc
            self._base_mono = time.monotonic() - self.source.age()

    def now(self) -> int:
        self._sync()
        if self._base_utc is None:
            # 아직 fix 가 없다. 시스템 시계를 주되 is_valid() 가 False 라
            # orchestrator 가 자동 전이를 보류한다.
            return int(time.time())
        return int(self._base_utc + (time.monotonic() - self._base_mono))

    def is_valid(self) -> bool:
        fix = self.source.read()
        if fix is None or not fix.valid:
            return False
        if self.source.age() > FIX_STALE_SEC:
            return False
        # 부팅 직후의 엉뚱한 값도 걸러낸다 (config.clock_is_valid)
        return config.clock_is_valid(self.now())

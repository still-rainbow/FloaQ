"""부표 LoRa 수신기. `ports.BuoyLink` 구현.

라디오는 **Ebyte E22-900T22D(SX1262) 2개**다. 하나는 부표, 하나는 배(Pi).
단방향이다 — 부표가 1Hz 로 쏘고 Pi 가 받기만 한다.

    부표 GPS --19바이트 프레임--> E22 --무선--> E22 --UART--> Pi(여기)
                                                              |
                                             contracts/lora.unpack
                                                              |
                                         ship_tag 검사 -> 큐 -> drain()

코덱은 `contracts/lora.py` 가 정본이다. 여기는 **바이트를 프레임으로 자르는 일**만 한다.

── 왜 프레이밍이 따로 필요한가 ─────────────────────────────────────
E22 는 투명전송(transparent) 모드다. 무선 패킷이 그대로 UART 로 흘러나오는데,
**UART 에는 경계가 없다.** 한 바이트만 밀려도 그 뒤가 전부 깨진다.

🔴 **`readline()` 을 쓰지 않는다.** 19바이트 이진 프레임은 개행(0x0A)을 **값으로**
   포함한다 — lat/lon/measured_at 어디서나 나온다. 줄 단위로 읽으면 프레임이
   중간에서 잘린다. 시험용 `LoRa/lora_test.py` 가 `readline()` 이었던 건 그게 텍스트
   PING/ACK 이었기 때문이고, 본방 이진 프레임에는 그대로 쓸 수 없다.

대신 **CRC 로 재동기**한다. 19바이트 창을 한 바이트씩 밀며 CRC 가 맞는 자리를 찾는다.
별도 동기 워드(0x7E 등)를 안 넣는 이유가 이것이다 — CRC 가 그 일까지 한다.
버전 니블을 같이 보므로 헛동기 확률은 1/65536 의 다시 1/16 이다.

── E22 설정이 프레이밍에 미치는 영향 ───────────────────────────────
🔴 **RSSI 바이트.** REG3 bit7 을 켜면 모듈이 수신 패킷 **뒤에 1바이트를 덧붙인다.**
   그러면 UART 한 단위가 19 가 아니라 **20바이트**가 된다. `rssi=True` 로 알려줘야
   한다. 안 맞추면 매 프레임 1바이트씩 밀려 전부 버려진다.

   dBm 환산은 `rssi_byte - 256` 이다 (0xB4 -> -76dBm).

⚠ 2026-09-18 Pi 에 써넣은 값은 `C0 00 09 | 00 00 00 62 03 48 13 00 00` 이다.
    REG0 0x62  9600 8N1 / air rate 2.4k
    REG1 0x03  240B 패킷 / TX **10dBm** (최저. 거리 시험 전에 0x00 = 22dBm 으로)
    REG2 0x48  채널 72 -> 922.125MHz (한국 대역)
    REG3 0x13  LBT on / 투명전송 / **RSSI 바이트 OFF**
  이 설정 그대로면 `pi_buoy.rssi` 가 전부 NULL 이다. 켜려면 REG3 을 0x93 으로.

⚠ air rate 2.4k 는 19바이트 airtime 이 `docs/lora.md` §4 의 SF7 51.4ms 가 아니다.
  훨씬 길어 1Hz 에 여유가 좁다. REG0 하위 3비트를 3(4.8k)이나 4(9.6k)로 올리면
  절반 이하가 되고 거리와 맞바꾼다. 실측 후 정할 것.

── 포트 ────────────────────────────────────────────────────────────
🔴 **포트 이름을 배선으로 정한다. 외우지 말 것.** Pi 5 는 UART 마다 핀이 다르다 —
   `ttyAMA0` = GPIO14/15(헤더 8·10번), `ttyAMA2` = GPIO4/5(헤더 7·29번, `dtoverlay=uart2`
   필요). 엉뚱한 포트를 열면 **영원히 0 바이트**인데, 증상이 "전파가 안 온다" 와
   똑같이 생겨서 배선과 안테나를 번갈아 의심하게 된다. 실제로 그렇게 몇 시간
   태웠다 (2026-09-22).

   확인은 `tools/uart_scan.py` 가 한다 — 전 포트를 훑어 바이트가 오는 곳을 찍는다.

⚠ **`/dev/serial0` 이 아니다.** Pi 4 까지의
  글이 전부 serial0 이라 그대로 따라 하면 포트를 못 연다.
"""

from __future__ import annotations

import logging
import math
import socket
import threading
import time
from collections import deque

from floaq import config
from floaq.adapters import gps
from floaq.contracts.lora import (
    FRAME_LEN,
    LORA_VERSION,
    BuoyFrame,
    LoraFrameError,
    Reception,
    crc16_ccitt,
    seq_gap,
    unpack,
)

log = logging.getLogger(__name__)

#: E22 UART 기본 속도. 설정 모드는 모듈 설정과 무관하게 항상 9600 이다.
LORA_BAUD = 9600

#: Pi 5 의 UART. Pi 4 까지 쓰던 `/dev/serial0` 이 아니다.
#: 실측으로 정한 값 (2026-09-22). 헤더 8·10번(GPIO14/15)에 물려 있다.
#: 배선을 바꾸면 이 값도 바꾼다 — `tools/uart_scan.py` 로 확인한 뒤.
LORA_PORT = "/dev/ttyAMA0"

#: 라디오 없이 시험할 때 쓰는 UDP 포트. 10110 은 NMEA 가 이미 쓴다.
LORA_UDP_PORT = 10111

#: 큐 상한. `drain()` 이 1초마다 불리므로 이만큼 쌓였다면 이미 뭔가 멈춘 것이다.
#: `deque(maxlen=)` 이라 넘치면 **오래된 것부터** 버린다 — 익수자 최신 위치를
#: 지키는 쪽이 옳다.
QUEUE_MAX = 256

#: 수신 버퍼 상한. 쓰레기만 들어오는 상황에서 무한히 자라지 않게 막는다.
_BUF_MAX = 1024


def link_summary(delta: dict[str, int], outcomes: dict[str, int], last=None, *,
                 our_tag: int | None = None, foreign_tag: int | None = None,
                 window_sec: int = 5) -> str:
    """몇 초 동안의 수신을 한 줄로. `main.py` 가 `BUOY_LOG_SEC` 마다 찍는다.

    `delta` 는 그 사이 `LinkStats` 증가분, `outcomes` 는 `Orchestrator.on_buoy` 가
    돌려준 결과별 개수(stored / no_accident / duplicate), `last` 는 마지막 `Reception`.
    """
    head = f"부표 LoRa {window_sec}초"
    got = delta.get("ok", 0)
    errs = (f"태그다름 {delta.get('foreign', 0)} · CRC {delta.get('bad_crc', 0)}"
            f" · 형식 {delta.get('bad_frame', 0)} · 유실 {delta.get('lost', 0)}")
    if got == 0 and not any(delta.get(k, 0) for k in ("foreign", "bad_crc", "bad_frame")):
        return f"{head} | 받은 쪽지 없음 (부표 전원·안테나·채널·배선 확인)"
    line = (f"{head} | 받음 {got} → 저장 {outcomes.get('stored', 0)}"
            f" · 사고없음 {outcomes.get('no_accident', 0)}"
            f" · 중복 {outcomes.get('duplicate', 0)} | {errs}")
    if last is not None:
        f = last.frame
        line += (f" | 마지막 seq {f.seq} ({f.lat:.6f}, {f.lon:.6f})"
                 f" 버튼 {'눌림' if f.is_pressed else '안눌림'}")
    if delta.get("foreign", 0) and foreign_tag is not None:
        ours = f"0x{our_tag:02X}" if our_tag is not None else "?"
        line += (f" | ⚠ 태그 0x{foreign_tag:02X} 가 왔다 (우리 {ours})"
                 " — 부표를 이 배 표식으로 다시 굽는다")
    if outcomes.get("no_accident", 0) and not outcomes.get("stored", 0):
        line += " | 진행 중 사고가 없어 기록하지 않는다 (정상)"
    return line


class LinkStats:
    """링크 품질. `docs/lora.md` §5 가 재라고 한 것이 이 숫자들이다.

    RSSI 가 정상인데 `lost` 가 크면 충돌, RSSI 가 낮으면 거리다.
    """

    __slots__ = ("ok", "resync_bytes", "bad_crc", "foreign", "bad_frame", "lost")

    def __init__(self) -> None:
        self.ok = 0
        #: CRC 가 맞는 자리를 못 찾아 버린 바이트 수 (재동기 비용)
        self.resync_bytes = 0
        self.bad_crc = 0
        #: 남의 배 부표. **CRC 는 통과한다** — 그쪽에서 제대로 만든 패킷이다
        self.foreign = 0
        #: CRC 는 맞는데 버전·값이 틀렸다
        self.bad_frame = 0
        #: seq 구멍 누적
        self.lost = 0

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in self.__slots__}


class _ThreadedLink:
    """공통 수명주기. 자식이 `_packets()` 만 구현한다.

    `gps._ThreadedGnss` 와 같은 구조인데 **보관 방식이 다르다.** GPS 는 최신값 하나만
    들고 있으면 되지만(다음 fix 가 1초 뒤에 온다), 부표는 한 프레임이 `pi_buoy` 한
    행이라 사이를 버리면 익수자 궤적에 구멍이 난다. 그래서 큐다.
    """

    def __init__(self, ship_tag: int | None = None) -> None:
        #: None 이면 **전부 받는다**. 벤치 시험용이고 운영에서는 반드시 넣는다 —
        #: 안 넣으면 남의 배 익수자 좌표가 우리 사고에 기록된다
        self.ship_tag = ship_tag
        self.stats = LinkStats()
        self._q: deque[Reception] = deque(maxlen=QUEUE_MAX)
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_seq: int | None = None
        #: 마지막으로 거른 남의 태그. 태그가 안 맞을 때 **어떤 값이 왔는지** 로그에 찍는다
        self.last_foreign_tag: int | None = None

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="lora", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    # ── ports.BuoyLink ───────────────────────────────────────────────
    def drain(self) -> list[Reception]:
        """쌓인 수신을 전부 가져가고 큐를 비운다.

        `age_sec` 을 여기서 계산한다 — 큐에 있던 시간이 곧 지연이다.
        """
        now = time.monotonic()
        with self._lock:
            got = list(self._q)
            self._q.clear()
        return [Reception(frame=r.frame, rssi=r.rssi, age_sec=max(0.0, now - r.age_sec))
                for r in got]

    # ── 자식이 구현 ──────────────────────────────────────────────────
    def _packets(self):
        """`(19바이트, rssi dBm 또는 None)` 을 계속 내놓는다."""
        raise NotImplementedError

    # ── 루프 ─────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                for raw, rssi in self._packets():
                    if self._stopping.is_set():
                        return
                    self._accept(raw, rssi)
            except Exception:
                # 케이블이 빠지거나 포트가 닫혀도 죽지 않는다. 쉬었다 다시 연다.
                log.exception("LoRa 읽기 실패 — 재시도한다")
                time.sleep(2.0)

    def _accept(self, raw: bytes, rssi: float | None) -> None:
        try:
            frame = unpack(raw)
        except LoraFrameError as e:
            self.stats.bad_frame += 1
            log.debug("LoRa 프레임 버림: %s", e)
            return

        # 🔴 남의 배 부표는 **깨끗하게 수신되고 CRC 도 통과한다.** 걸러낼 곳이 여기뿐이다.
        #   빠뜨리면 남의 익수자 좌표가 우리 사고에 기록된다 (`docs/lora.md` §3.4).
        if self.ship_tag is not None and frame.ship_tag != self.ship_tag:
            self.stats.foreign += 1
            self.last_foreign_tag = frame.ship_tag
            return

        if self._last_seq is not None:
            self.stats.lost += seq_gap(self._last_seq, frame.seq)
        self._last_seq = frame.seq
        self.stats.ok += 1

        # ⚠ age_sec 자리에 **수신 monotonic 을 넣어 둔다.** drain() 이 now 에서 빼
        #   진짜 경과로 바꾼다. 바깥에 나가는 건 언제나 환산된 값이다.
        with self._lock:
            self._q.append(Reception(frame=frame, rssi=rssi, age_sec=time.monotonic()))


# ── 실물: E22 UART ───────────────────────────────────────────────────
class SerialLoRa(_ThreadedLink):
    """E22 를 Pi UART 에 직결한 경우.

    ⚠ pyserial 을 여기서만 import 한다. UDP·가짜만 쓸 때 설치를 강요하지 않는다.
    """

    def __init__(self, ship_tag: int | None = None, *, port: str = LORA_PORT,
                 baud: int = LORA_BAUD, rssi: bool = False,
                 m0_pin: int | None = None, m1_pin: int | None = None) -> None:
        super().__init__(ship_tag)
        self.port, self.baud = port, baud
        #: E22 REG3 bit7. True 면 패킷 뒤에 RSSI 1바이트가 붙어 단위가 20바이트가 된다
        self.rssi = rssi
        #: M0/M1 을 GPIO 로 잡고 있으면 핀 번호(BCM)를 준다. GND 고정 배선이면 None
        self.m0_pin, self.m1_pin = m0_pin, m1_pin

    @property
    def unit(self) -> int:
        """UART 한 단위의 길이. RSSI 바이트가 붙으면 20 이다."""
        return FRAME_LEN + (1 if self.rssi else 0)

    def _packets(self):
        import serial  # noqa: PLC0415

        self._normal_mode()
        buf = bytearray()
        with serial.Serial(self.port, self.baud, timeout=0.5) as ser:
            while not self._stopping.is_set():
                chunk = ser.read(64)
                if chunk:
                    buf.extend(chunk)
                yield from self._cut(buf)
                if len(buf) > _BUF_MAX:
                    # 쓰레기만 들어온다. 최근 한 단위만 남기고 버린다
                    self.stats.resync_bytes += len(buf) - self.unit
                    del buf[:-self.unit]

    def _cut(self, buf: bytearray):
        """CRC 로 프레임 경계를 찾는다. 맞을 때까지 한 바이트씩 민다."""
        while len(buf) >= self.unit:
            if _looks_like_frame(buf):
                raw = bytes(buf[:FRAME_LEN])
                rssi = float(buf[FRAME_LEN] - 256) if self.rssi else None
                del buf[:self.unit]
                yield raw, rssi
                continue
            # 경계가 아니다. 한 바이트 버리고 다시 본다
            del buf[:1]
            self.stats.resync_bytes += 1
            self.stats.bad_crc += 1

    def _normal_mode(self) -> None:
        if self.m0_pin is None or self.m1_pin is None:
            return
        try:
            set_normal_mode(self.m0_pin, self.m1_pin)
        except Exception as e:
            # 배선이 이미 통신 모드면 이게 실패해도 수신은 된다. 죽이지 않는다
            log.warning("E22 모드 핀 설정 실패 (%s). 배선이 통신 모드인지 확인할 것", e)


def _looks_like_frame(buf) -> bool:
    """CRC 와 버전 니블이 둘 다 맞나.

    CRC 만 보면 무작위 바이트가 65536분의 1 로 통과한다. 1Hz 로 며칠 돌리면 실제로
    한 번 나온다. 버전 니블을 같이 보면 그 확률이 다시 16분의 1 이 되고,
    `unpack` 이 어차피 전부 재검사하므로 비용이 0 이다.
    """
    if buf[0] >> 4 != LORA_VERSION:
        return False
    return crc16_ccitt(bytes(buf[:17])) == (buf[17] << 8 | buf[18])


def set_normal_mode(m0_pin: int, m1_pin: int) -> None:
    """M0=0, M1=0. **설정 모드로 남아 있으면 무선이 아예 안 뜬다.**

    🔴 M0/M1 이 GND 에 납땜돼 있으면 부르지 않는다. GPIO 로 HIGH 를 주는 것이
      곧 단락이다. 그래서 `SerialLoRa` 의 기본값은 핀 없음이다.
    """
    import RPi.GPIO as GPIO  # noqa: PLC0415, N812

    GPIO.setmode(GPIO.BCM)
    GPIO.setup([m0_pin, m1_pin], GPIO.OUT)
    GPIO.output(m0_pin, 0)
    GPIO.output(m1_pin, 0)
    time.sleep(0.05)          # AUX 가 안정될 시간


# ── 라디오 없이: UDP ─────────────────────────────────────────────────
class UdpLoRa(_ThreadedLink):
    """UDP 로 프레임을 받는다. `tools/lora_ab.py a --link udp` 와 짝이다.

    데이터그램 자체가 프레임 경계라 재동기가 필요 없다 — 그래서 **프레이밍 버그를
    숨긴다.** 실물 대체가 아니라 상류(저장·발행) 시험용이다.
    """

    def __init__(self, ship_tag: int | None = None, *,
                 port: int = LORA_UDP_PORT, bind: str = "0.0.0.0") -> None:
        super().__init__(ship_tag)
        self.port, self.bind = port, bind

    def _packets(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind, self.port))
        sock.settimeout(1.0)
        try:
            while not self._stopping.is_set():
                try:
                    data, _ = sock.recvfrom(256)
                except socket.timeout:
                    continue
                if len(data) >= FRAME_LEN:
                    yield data[:FRAME_LEN], None
        finally:
            sock.close()


# ── 가짜 부표 ────────────────────────────────────────────────────────
#: 익수자 표류 속도. 조류·바람이 없어도 사람은 가만히 있지 않는다.
FAKE_DRIFT_KN = 0.6

_KNOT_MS = 0.514444
_M_PER_DEG_LAT = 111_132.0
_M_PER_DEG_LON_EQ = 111_320.0


class FakeLoRa(_ThreadedLink):
    """라디오도 부표도 없이 1Hz 로 흘린다.

    실제 프레임을 `pack()` 해서 `unpack()` 을 거치게 한다 — 코덱을 우회하면
    코덱 버그가 시연 날까지 안 드러난다 (`gps.FakeGnss` 와 같은 이유).

    ⚠ 프레이밍은 우회한다. 재동기 코드는 이걸로 검증되지 않는다.
    """

    def __init__(self, ship_tag: int = 0, *, lat: float | None = None,
                 lon: float | None = None, cog: float = 90.0,
                 drift_kn: float = FAKE_DRIFT_KN, is_pressed: bool = True) -> None:
        super().__init__(ship_tag)
        self.tag = ship_tag
        # 시연 기본 위치는 배와 같은 곳이다 — 부산 앞바다 (gps.BUSAN_OFFSHORE).
        # None 을 그대로 받으면 --gps-lat 을 안 준 경우에 터진다.
        self.lat = gps.BUSAN_OFFSHORE[0] if lat is None else lat
        self.lon = gps.BUSAN_OFFSHORE[1] if lon is None else lon
        self.cog, self.drift_kn = cog, drift_kn
        self.is_pressed = is_pressed
        self.seq = 0

    def _advance(self, dt: float) -> None:
        metres = self.drift_kn * _KNOT_MS * dt
        rad = math.radians(self.cog)
        self.lat += metres * math.cos(rad) / _M_PER_DEG_LAT
        # 경도 1도는 위도에 따라 짧아진다. 적도 기준으로 두면 부산에서 22% 빠르다
        self.lon += metres * math.sin(rad) / (_M_PER_DEG_LON_EQ
                                              * math.cos(math.radians(self.lat)))

    def frame(self, measured_at: int | None = None) -> BuoyFrame:
        return BuoyFrame(
            ship_tag=self.tag, seq=self.seq, lat=self.lat, lon=self.lon,
            measured_at=int(time.time()) if measured_at is None else measured_at,
            is_pressed=self.is_pressed, gps_fix=True, battery=3)

    def _packets(self):
        while not self._stopping.is_set():
            self._advance(config.BUOY_TX_SEC)
            raw = self.frame().pack()
            self.seq = (self.seq + 1) & 0xFFFF
            # RSSI 도 흉내낸다. DB·화면이 None 만 보면 그 경로가 시험되지 않는다
            yield raw, -70.0
            time.sleep(config.BUOY_TX_SEC)

"""부표 LoRa 프레임 코덱. **MQTT 계약과 다른 매체라 별도 규약이다.**

MQTT 쪽은 JSON 봉투를 쓴다. 여기는 못 쓴다 — LoRa 는 airtime 이 비용이고
`BuoyPosition` 을 JSON 으로 만들면 200바이트가 넘는다. 1Hz 로 쏘면 대역이 죽는다.
그래서 **고정 19바이트 이진 프레임**이다.

⚠ TLV 를 쓰지 않는다. 송신(부표 펌웨어)과 수신(adapters/lora.py)이 같은 팀·같은
  저장소라 "모르는 tag 를 건너뛴다"는 TLV 의 유일한 값어치를 쓸 일이 없다.
  같은 내용이 TLV 면 29바이트다. 필드마다 tag 1 + len 1 을 더 낸다.

── airtime ─────────────────────────────────────────────────────────
LoRa 는 바이트가 아니라 **심볼 단위로 양자화**된다.
SF7 / BW125 / CR4:5 / explicit header / CRC on 기준:

    n_sym = 8 + ceil((8*PL + 16) / 28) * 5

    12~15 B -> 33 심볼 -> 46.3 ms
    16~19 B -> 38 심볼 -> 51.4 ms      <- 여기
    20~22 B -> 43 심볼 -> 56.6 ms

16바이트와 19바이트의 airtime 이 **같다**. 그래서 ship_tag 도 crc16 도 공짜다.
비트 패킹으로 더 줄여도 절약이 0 이다.

⚠ 이 경계는 SF7 전용이다. SF 를 바꾸면 분모 `4*(SF-2*DE)` 가 바뀌어 전부 이동한다.

── 프레임 (빅엔디안 19바이트) ──────────────────────────────────────
    오프셋  크기  필드          인코딩
    0       1     ver_type      상위 4비트 버전, 하위 4비트 메시지 종류
    1       1     ship_tag      sha256(ship_id) 첫 바이트
    2       2     seq           uint16, 전원 인가 시 0, 18.2시간 순환
    4       4     lat           int32, 1e-7 deg
    8       4     lon           int32, 1e-7 deg
    12      4     measured_at   uint32, Unix 초
    16      1     flags         bit0 is_pressed / bit1 gps_fix / bit2-3 배터리 / bit4-7 예비
    17      2     crc16         CRC-16/CCITT-FALSE, 0~16바이트 대상

⚠ 빅엔디안을 명시한다(`>`). 네이티브 `@` 는 컴파일러 정렬을 따라가서
  Pi 와 부표 MCU 가 다른 레이아웃을 만들 수 있다.

⚠ `accident_id` 를 싣지 않는다. 탐지 시점에 Pi 가 만드는데 부표는 그때 발사관 안이고
  다운링크가 없다 — 전달 경로가 없다. Pi 가 `repo.active()` 로 붙인다.
  남의 배 부표와 섞이는 건 `ship_tag` 가 막는다.

── 부표 펌웨어 참고 (C) ────────────────────────────────────────────
    #pragma pack(push, 1)
    typedef struct {
        uint8_t  ver_type;
        uint8_t  ship_tag;
        uint16_t seq;          /* 전부 빅엔디안으로 써야 한다 */
        int32_t  lat;
        int32_t  lon;
        uint32_t measured_at;
        uint8_t  flags;
        uint16_t crc16;
    } buoy_frame_t;           /* sizeof == 19 */
    #pragma pack(pop)

  ⚠ MCU 는 보통 리틀엔디안이다. 구조체에 그냥 대입하면 안 되고
    바이트마다 명시적으로 채워야 한다.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

# ── 규격 상수 ────────────────────────────────────────────────────────
#: 프레임 버전. 포맷이 바뀌면 올리고 구파서를 남긴다.
LORA_VERSION: int = 1

#: 메시지 종류. 지금은 부표 위치 하나뿐이다.
MSG_BUOY_POSITION: int = 0

FRAME_LEN: int = 19

#: 좌표 스케일. float32(4바이트)를 쓰면 경도 129도대에서 약 1m 오차가 난다 —
#: 유효숫자가 7자리뿐이라서다. int32 * 1e-7 은 같은 4바이트로 1.1cm 다.
COORD_SCALE: int = 10_000_000

_STRUCT = struct.Struct(">BBHiiIBH")
assert _STRUCT.size == FRAME_LEN

#: flags 비트 배치
_F_PRESSED = 0x01
_F_GPS_FIX = 0x02
_F_BATTERY_SHIFT = 2
_F_BATTERY_MASK = 0x03


# ── 예외 ─────────────────────────────────────────────────────────────
class LoraFrameError(ValueError):
    """프레임을 해석할 수 없다. **버리고 로그만 남긴다 — 죽지 않는다.**"""


class BadLength(LoraFrameError):
    pass


class BadCrc(LoraFrameError):
    pass


class UnknownVersion(LoraFrameError):
    """수신기가 모르는 버전. 부표만 먼저 업데이트된 경우가 이것이다."""


class UnknownMessageType(LoraFrameError):
    pass


class BadValue(LoraFrameError):
    """범위를 벗어난 좌표 등. CRC 가 통과해도 값이 틀릴 수 있다."""


# ── CRC ──────────────────────────────────────────────────────────────
def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF).

    ⚠ LoRa PHY 가 이미 CRC 를 건다. 이건 그 위에 한 겹 더 두는 것이다 —
      라디오를 UART AT 모듈로 붙이면 모듈~MCU 시리얼 구간은 PHY CRC 밖이다.
      SPI 직결이면 빼도 되지만, 19바이트가 16바이트와 airtime 이 같아서 공짜다.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def ship_tag(ship_id: str) -> int:
    """`ship_id` -> 1바이트 태그.

    🔴 내장 `hash()` 를 쓰지 않는다. 파이썬 문자열 해시는 프로세스마다 난수화되어
       (PYTHONHASHSEED) 재시작할 때마다 값이 바뀐다. 부표 펌웨어와도 맞출 수 없다.
       sha256 첫 바이트를 쓴다 — 어느 언어에서든 같은 값이 나온다.

    충돌 확률 1/256. 근처 FloaQ 선박이 서너 척이면 충분하다.
    """
    return hashlib.sha256(ship_id.encode()).digest()[0]


# ── 프레임 ───────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class BuoyFrame:
    """부표가 1Hz 로 보내는 것. `contracts.pi.BuoyPosition` 의 무선 절반이다.

    `rssi` 와 `received_at` 은 여기 없다 — Pi 수신기가 잰다.
    `buoy_log_id` 도 없다 — DB 가 채운다.
    """

    ship_tag: int
    seq: int
    lat: float
    lon: float
    measured_at: int
    is_pressed: bool = False
    gps_fix: bool = True
    #: 0~3. 정밀한 전압이 아니라 눈금 4칸이다. 1바이트도 아까운 매체다.
    battery: int = 3
    version: int = LORA_VERSION
    msg_type: int = MSG_BUOY_POSITION

    def pack(self) -> bytes:
        if not 0 <= self.ship_tag <= 0xFF:
            raise BadValue(f"ship_tag 범위 밖: {self.ship_tag}")
        if not 0 <= self.battery <= 3:
            raise BadValue(f"battery 는 0~3: {self.battery}")
        if not -90 <= self.lat <= 90:
            raise BadValue(f"lat 범위 밖: {self.lat}")
        if not -180 <= self.lon <= 180:
            raise BadValue(f"lon 범위 밖: {self.lon}")
        if not 0 <= self.measured_at <= 0xFFFFFFFF:
            raise BadValue(f"measured_at 범위 밖: {self.measured_at}")

        flags = (
            (_F_PRESSED if self.is_pressed else 0)
            | (_F_GPS_FIX if self.gps_fix else 0)
            | ((self.battery & _F_BATTERY_MASK) << _F_BATTERY_SHIFT)
        )
        body = struct.pack(
            ">BBHiiIB",
            (self.version << 4) | (self.msg_type & 0x0F),
            self.ship_tag,
            self.seq & 0xFFFF,          # uint16 순환은 정상 동작이다
            round(self.lat * COORD_SCALE),
            round(self.lon * COORD_SCALE),
            self.measured_at,
            flags,
        )
        return body + struct.pack(">H", crc16_ccitt(body))


def unpack(raw: bytes) -> BuoyFrame:
    """수신 프레임 해석. 실패하면 `LoraFrameError` — **호출자가 버린다.**

    검사 순서가 중요하다. 길이 -> CRC -> 버전 -> 값.
    CRC 를 먼저 보지 않으면 깨진 바이트로 버전을 판단하게 된다.
    """
    if len(raw) != FRAME_LEN:
        raise BadLength(f"{FRAME_LEN}바이트여야 한다: {len(raw)}")

    got = struct.unpack(">H", raw[17:19])[0]
    want = crc16_ccitt(raw[:17])
    if got != want:
        raise BadCrc(f"CRC 불일치: 받은 0x{got:04X}, 계산 0x{want:04X}")

    ver_type, tag, seq, lat_i, lon_i, measured_at, flags = struct.unpack(">BBHiiIB", raw[:17])
    version, msg_type = ver_type >> 4, ver_type & 0x0F
    if version != LORA_VERSION:
        raise UnknownVersion(f"모르는 버전 {version} (아는 것 {LORA_VERSION})")
    if msg_type != MSG_BUOY_POSITION:
        raise UnknownMessageType(f"모르는 메시지 종류 {msg_type}")

    lat, lon = lat_i / COORD_SCALE, lon_i / COORD_SCALE
    # CRC 가 통과해도 값이 틀릴 수 있다 — 송신 측 GPS 가 이상한 값을 냈을 때다.
    if not -90 <= lat <= 90:
        raise BadValue(f"lat 범위 밖: {lat}")
    if not -180 <= lon <= 180:
        raise BadValue(f"lon 범위 밖: {lon}")

    return BuoyFrame(
        ship_tag=tag,
        seq=seq,
        lat=lat,
        lon=lon,
        measured_at=measured_at,
        is_pressed=bool(flags & _F_PRESSED),
        gps_fix=bool(flags & _F_GPS_FIX),
        battery=(flags >> _F_BATTERY_SHIFT) & _F_BATTERY_MASK,
        version=version,
        msg_type=msg_type,
    )


@dataclass(frozen=True, slots=True)
class Reception:
    """수신 한 건. 프레임 + **라디오가 잰 것**이다.

    `rssi` 와 경과 시간은 프레임 안에 없다 — 수신기가 만든다.

    🔴 **epoch 초가 아니라 `age_sec` 이다.** 수신 스레드는 GPS 시계를 안 본다.
      Pi 5 는 RTC 가 없어 fix 전의 `time.time()` 이 1970년이거나 지난 부팅 시각이다.
      그 값을 `pi_buoy.received_at` 에 넣으면 CHECK 를 통과하면서 조용히 틀린다.
      호출자가 `clock.now() - round(age_sec)` 로 환산한다 — `gps.GpsClock` 이
      fix 사이를 monotonic 으로 메우는 것과 같은 방식이다.
    """

    frame: BuoyFrame
    #: dBm. 모듈이 RSSI 바이트를 꺼두면 None 이다 (E22 REG3 bit7).
    rssi: float | None = None
    #: 수신 시점부터 지금까지 흐른 초. drain 이 늦으면 커진다.
    age_sec: float = 0.0


def seq_gap(prev: int, cur: int) -> int:
    """`seq` 구멍 개수. uint16 순환을 감안한다.

    유실률 측정에 쓴다. 간섭·거리 판단의 근거가 이 숫자다 —
    RSSI 는 정상인데 구멍이 크면 충돌, RSSI 가 낮으면 거리다.
    """
    return (cur - prev - 1) & 0xFFFF

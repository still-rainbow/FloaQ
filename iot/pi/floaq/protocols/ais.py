"""ITU-R M.1371 자동식별장치(AIS). **규격 자체의 구현이다.**

두 계층을 나눠 담는다.

    메시지 계층   Message 1 / Message 14 의 비트 배치 (M.1371 §3.3.8, Table 45·55)
    링크 계층     훈련열 · 플래그 · CRC · 비트 스터핑 · NRZI (M.1371 Annex 2 §3.2)

`adapters/nmea.py` 는 **메시지 계층만** 가져다 AIVDM 문장으로 옮긴다. AIVDM 이
실어 나르는 것이 메시지 비트뿐이기 때문이다 — CRC 와 스터핑은 수신기가 이미 벗겨낸다.
링크 계층은 규격 완결성과 시험용으로 여기 둔다.

근거
    Recommendation ITU-R M.1371-5, Annex 2 §3.2 (링크 계층), Annex 8 (메시지)
    gpsd AIVDM/AIVDO Protocol Decoding (비트 배치 대조)

── 조난 장치 (M.1371 / IEC 61097-14) ───────────────────────────────
AIS-SART·MOB·EPIRB 는 별도 메시지 종류가 없다. 일반 위치보고(Message 1)를 쓰되
**항행상태 14** 를 넣고, MMSI 접두로 장치 종류를 구분하며, Message 14 로 규정된
문구를 함께 보낸다.

    970MIDXXX  SART      "SART ACTIVE" / "SART TEST"
    972XXXXXX  MOB       "MOB ACTIVE"  / "MOB TEST"
    974XXXXXX  EPIRB     "EPIRB ACTIVE"

송신 주기도 규정돼 있다 — 위치보고를 1분에 8회 버스트로 보내고, 4분마다 한 번
위치보고 하나를 Message 14 로 대체한다.

🔴 **이건 시뮬레이션이다.** 이 비트열을 AIS 주파수(161.975 / 162.025 MHz)로 변조해
   송신하면 불법이며, 인근 선박과 해상교통관제에 허위 조난 표적을 띄운다.
   UDP 로 보내 항해 소프트웨어에서 확인하는 용도까지만 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# ── 항행 상태 (Table 45) ─────────────────────────────────────────────
class NavStatus(IntEnum):
    UNDER_WAY_ENGINE = 0
    AT_ANCHOR = 1
    NOT_UNDER_COMMAND = 2
    RESTRICTED_MANOEUVRABILITY = 3
    CONSTRAINED_BY_DRAUGHT = 4
    MOORED = 5
    AGROUND = 6
    ENGAGED_IN_FISHING = 7
    UNDER_WAY_SAILING = 8
    #: 🔴 AIS-SART / MOB / EPIRB 가 **활성**임을 뜻한다. 이 값이 있어야 수신기가
    #:    일반 선박이 아니라 조난 표적으로 처리한다.
    SART_ACTIVE = 14
    UNDEFINED = 15


#: MMSI 접두로 장치 종류를 구분한다.
MMSI_PREFIX_SART = "970"
MMSI_PREFIX_MOB = "972"
MMSI_PREFIX_EPIRB = "974"

#: Message 14 로 보내는 문구. 규격이 문자열까지 정한다.
TEXT_SART_ACTIVE = "SART ACTIVE"
TEXT_SART_TEST = "SART TEST"
TEXT_MOB_ACTIVE = "MOB ACTIVE"
TEXT_MOB_TEST = "MOB TEST"

#: 값 없음을 뜻하는 규격 상수
SOG_NOT_AVAILABLE = 1023        # 0.1노트 단위
COG_NOT_AVAILABLE = 3600        # 0.1도 단위
HEADING_NOT_AVAILABLE = 511
ROT_NOT_AVAILABLE = -128
TIMESTAMP_NOT_AVAILABLE = 60

#: 좌표 스케일. 1/10000 분 단위 정수다.
#: 십진도 -> 정수: deg * 60 * 10000 = deg * 600000
COORD_SCALE = 600000

#: 경도는 28비트, 위도는 27비트. **자릿수가 다르다.**
LON_BITS = 28
LAT_BITS = 27

#: 좌표를 못 넣을 때. 경도 181도, 위도 91도.
LON_NOT_AVAILABLE = 181 * COORD_SCALE
LAT_NOT_AVAILABLE = 91 * COORD_SCALE

#: 기본 전송 패킷의 데이터 길이. Message 1 이 정확히 이 값이다.
DEFAULT_PACKET_BITS = 168

#: 조난 장치 송신 주기 (IEC 61097-14)
BURST_COUNT = 8                 # 1분에 위치보고 8회
BURST_PERIOD_SEC = 60
TEXT_EVERY_SEC = 240            # 4분마다 Message 14 가 위치보고 하나를 대체


# ── 비트 도구 ────────────────────────────────────────────────────────
def u(value: int, width: int) -> str:
    """부호 없는 정수 → width 비트. MSB 먼저."""
    if not 0 <= value < (1 << width):
        raise ValueError(f"{value} 는 부호 없는 {width}비트에 안 들어간다")
    return format(value, f"0{width}b")


def i(value: int, width: int) -> str:
    """부호 있는 정수 → width 비트 2의 보수.

    🔴 좌표가 여기를 탄다. 2의 보수를 틀리면 남위·서경이 지구 반대편에 찍힌다.
    """
    lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
    if not lo <= value <= hi:
        raise ValueError(f"{value} 는 부호 있는 {width}비트에 안 들어간다")
    return format(value & ((1 << width) - 1), f"0{width}b")


def encode_text(text: str) -> str:
    """AIS 6비트 문자 집합. M.1371 Table 47

        0~31  -> '@' + v     (@ A-Z [ \\ ] ^ _)
        32~63 -> chr(v)      (공백 ! " … 0-9 : ; < = > ?)

    ⚠ 표에 없는 문자는 공백으로 바꾼다. 예외를 던지면 조난 신고가 통째로 막힌다.
    """
    out = []
    for ch in text.upper():
        v = ord(ch)
        if 64 <= v <= 95:
            out.append(u(v - 64, 6))
        elif 32 <= v <= 63:
            out.append(u(v, 6))
        else:
            out.append(u(32, 6))
    return "".join(out)


def decode_text(bits: str) -> str:
    """`encode_text` 의 역. 시험과 수신 처리에 쓴다."""
    out = []
    for p in range(0, len(bits) - 5, 6):
        v = int(bits[p:p + 6], 2)
        out.append(chr(v + 64) if v < 32 else chr(v))
    return "".join(out)


def encode_coord(value: float, width: int) -> str:
    """십진도 → 1/10000 분 단위 2의 보수 정수 비트."""
    return i(round(value * COORD_SCALE), width)


# ── 메시지 계층 ──────────────────────────────────────────────────────
def message_1(
    *,
    mmsi: str,
    lat: float,
    lon: float,
    nav_status: NavStatus | int = NavStatus.SART_ACTIVE,
    sog_knots: float | None = None,
    cog_deg: float | None = None,
    second: int | None = None,
    repeat: int = 0,
    position_accuracy: int = 0,
    raim: int = 0,
) -> str:
    """Message 1 — Position report (Class A). 168비트.

    비트 배치 (M.1371 Table 45):

        0-5     6   메시지 종류 = 1
        6-7     2   반복 지시자
        8-37    30  MMSI
        38-41   4   항행 상태
        42-49   8   선회율 (부호 있음)
        50-59   10  대지속력 0.1노트
        60      1   위치 정확도 (1 = DGNSS <10m)
        61-88   28  경도  1/10000 분 (부호 있음)
        89-115  27  위도  1/10000 분 (부호 있음)
        116-127 12  대지침로 0.1도
        128-136 9   진침수
        137-142 6   타임스탬프 (UTC 초)
        143-144 2   특수조작 지시자
        145-147 3   예비
        148     1   RAIM
        149-167 19  무선 상태

    ⚠ 경도가 위도보다 **앞에** 오고 비트 폭도 하나 더 크다. 순서나 폭을 바꿔 넣으면
      값이 조용히 잘린다.
    """
    if len(mmsi) != 9 or not mmsi.isdigit():
        raise ValueError(f"MMSI 는 숫자 9자리: {mmsi!r}")

    sog = SOG_NOT_AVAILABLE if sog_knots is None else min(1022, round(sog_knots * 10))
    cog = COG_NOT_AVAILABLE if cog_deg is None else min(3599, round(cog_deg * 10))
    ts = TIMESTAMP_NOT_AVAILABLE if second is None else second

    bits = (
        u(1, 6)
        + u(repeat, 2)
        + u(int(mmsi), 30)
        + u(int(nav_status), 4)
        + i(ROT_NOT_AVAILABLE, 8)
        + u(sog, 10)
        + u(position_accuracy, 1)
        + encode_coord(lon, LON_BITS)
        + encode_coord(lat, LAT_BITS)
        + u(cog, 12)
        + u(HEADING_NOT_AVAILABLE, 9)
        + u(ts, 6)
        + u(0, 2)          # 특수조작 지시자
        + u(0, 3)          # 예비
        + u(raim, 1)
        + u(0, 19)         # 무선 상태
    )
    assert len(bits) == DEFAULT_PACKET_BITS, len(bits)
    return bits


def message_14(*, mmsi: str, text: str, repeat: int = 0) -> str:
    """Message 14 — Safety related broadcast message.

    비트 배치 (M.1371 Table 55):

        0-5    6   메시지 종류 = 14
        6-7    2   반복 지시자
        8-37   30  MMSI
        38-39  2   예비
        40-    6n  안전 관련 문구 (6비트 문자, 최대 161자)

    ⚠ 길이가 6의 배수가 아니면 AIVDM 의 fill 비트가 생긴다. 그건 직렬화 계층이 맡는다.
    """
    if len(mmsi) != 9 or not mmsi.isdigit():
        raise ValueError(f"MMSI 는 숫자 9자리: {mmsi!r}")
    if len(text) > 161:
        raise ValueError(f"안전 문구는 161자까지: {len(text)}자")
    return u(14, 6) + u(repeat, 2) + u(int(mmsi), 30) + u(0, 2) + encode_text(text)


# ── 링크 계층 (Annex 2 §3.2) ─────────────────────────────────────────
#: 훈련열. 0/1 교번 24비트. 비트 스터핑 대상이 아니다.
TRAINING_SEQUENCE = "01" * 12

#: HDLC 플래그 01111110 (0x7E). 시작·종료가 같다.
#: ⚠ 1 이 여섯 개 연속이지만 **스터핑하지 않는다.** 그래야 경계로 쓸 수 있다.
HDLC_FLAG = "01111110"


def crc16_ccitt(bits: str) -> int:
    """FCS. CRC-ITU-T 16비트 (ISO/IEC 3309). 초기값 전부 1.

    다항식 x^16 + x^12 + x^5 + 1 (0x1021), 반사형 구현이라 0x8408 을 쓴다.
    AIS 는 LSB 먼저 보내므로 반사형이 맞다.
    """
    crc = 0xFFFF
    for bit in bits:
        crc ^= int(bit)
        for _ in range(1):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def bit_stuff(bits: str) -> str:
    """1 이 다섯 번 연속되면 0 을 끼워 넣는다. Annex 2 §3.2.2.4

    플래그(01111110)와 구별하기 위한 것이다. 훈련열과 플래그에는 적용하지 않는다.
    """
    out, ones = [], 0
    for b in bits:
        out.append(b)
        if b == "1":
            ones += 1
            if ones == 5:
                out.append("0")
                ones = 0
        else:
            ones = 0
    return "".join(out)


def bit_unstuff(bits: str) -> str:
    """다섯 개의 1 뒤에 오는 0 하나를 제거한다. 수신 측 처리."""
    out, ones, skip = [], 0, False
    for b in bits:
        if skip:
            skip = False
            ones = 0
            continue
        out.append(b)
        if b == "1":
            ones += 1
            if ones == 5:
                skip = True
        else:
            ones = 0
    return "".join(out)


def nrzi_encode(bits: str, *, initial: int = 0) -> str:
    """NRZI. **0 에서 레벨을 바꾸고 1 에서 유지한다.**

    ⚠ 방향이 직관과 반대다. AIS·HDLC 계열은 '0 에서 전이'가 규약이다.
    """
    level, out = initial, []
    for b in bits:
        if b == "0":
            level ^= 1
        out.append(str(level))
    return "".join(out)


def nrzi_decode(levels: str, *, initial: int = 0) -> str:
    prev, out = initial, []
    for lv in levels:
        cur = int(lv)
        out.append("1" if cur == prev else "0")
        prev = cur
    return "".join(out)


@dataclass(frozen=True, slots=True)
class LinkFrame:
    """무선에 실리는 한 패킷. Annex 2 §3.2

        훈련열(24) · 시작플래그 · [데이터 + FCS] 스터핑 · 종료플래그 · 버퍼
    """

    payload_bits: str

    def fcs(self) -> int:
        return crc16_ccitt(self.payload_bits)

    def bits(self, *, buffer_bits: int = 24, nrzi: bool = True) -> str:
        """송신 비트열.

        ⚠ FCS 는 **LSB 먼저** 실린다. MSB 먼저 넣으면 수신기가 전부 버린다.
        ⚠ 스터핑 대상은 데이터와 FCS 뿐이다. 훈련열·플래그·버퍼는 제외한다.
        """
        fcs = self.fcs()
        fcs_bits = "".join(str((fcs >> n) & 1) for n in range(16))   # LSB first
        stuffed = bit_stuff(self.payload_bits + fcs_bits)
        raw = TRAINING_SEQUENCE + HDLC_FLAG + stuffed + HDLC_FLAG + "0" * buffer_bits
        return nrzi_encode(raw) if nrzi else raw


# ── 조난 장치 묶음 ───────────────────────────────────────────────────
def mob_position(*, mmsi: str, lat: float, lon: float, second: int | None = None) -> str:
    """AIS-MOB 위치보고. 항행상태 14 고정."""
    if not mmsi.startswith(MMSI_PREFIX_MOB):
        raise ValueError(f"MOB MMSI 는 {MMSI_PREFIX_MOB} 로 시작해야 한다: {mmsi}")
    return message_1(mmsi=mmsi, lat=lat, lon=lon,
                     nav_status=NavStatus.SART_ACTIVE, second=second)


def sart_position(*, mmsi: str, lat: float, lon: float, second: int | None = None) -> str:
    if not mmsi.startswith(MMSI_PREFIX_SART):
        raise ValueError(f"SART MMSI 는 {MMSI_PREFIX_SART} 로 시작해야 한다: {mmsi}")
    return message_1(mmsi=mmsi, lat=lat, lon=lon,
                     nav_status=NavStatus.SART_ACTIVE, second=second)

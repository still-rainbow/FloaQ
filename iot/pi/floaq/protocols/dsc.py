"""ITU-R M.493 디지털 선택 호출(DSC). **규격 자체의 구현이다.**

무선 링크에 실리는 것은 NMEA 문장이 아니라 **10비트 심볼 스트림**이다. 이 모듈이
그 스트림을 만든다. `$CDDSC` 는 무전기가 플로터에게 보고할 때 쓰는 별개 계층이고,
`adapters/nmea.py` 가 여기서 만든 호출을 그 형식으로 옮긴다.

    protocols/dsc.py   M.493 심볼 프레임      <- 정본
    adapters/nmea.py   $CDDSC / $CDDSE        <- 직렬화 형식 하나

근거: Recommendation ITU-R M.493-11, §1 ~ §11, Table 1~4.1

── 심볼 (§1.1) ─────────────────────────────────────────────────────
10비트. 앞 7비트가 정보, 뒤 3비트가 체크다.

    체크 3비트 = 7개 정보비트 중 **B 요소(0)의 개수**를 2진수로 표현한 것
    정보비트는 **LSB 먼저**, 체크비트는 **MSB 먼저** 송신한다 (§1.1.1)

⚠ 송신 순서가 정보와 체크에서 서로 반대다. 한쪽 기준으로 통일해 짜면 전부 틀린다.

── 시간분산 (§1.2) ─────────────────────────────────────────────────
phasing 을 제외한 모든 문자를 두 번 보낸다. 첫 송신(DX) 뒤 **다른 문자 4개**가 지난 뒤
같은 문자를 다시 보낸다(RX). 짝수 위치가 DX, 홀수 위치가 RX이고, 위치 p 의 DX 는
위치 p+5 에서 RX 로 다시 나온다.

VHF 에서 이 간격은 33⅓ ms, HF/MF 에서는 400 ms 다.

── 조난 경보 구성 (Table 4.1) ──────────────────────────────────────
    형식지정자(2개 동일)  자기식별(5)  조난성격(1)  조난좌표(5)
    시각(2)  후속통신(1)  EOS(1)  ECC(1)

🔴 **이건 시뮬레이션이다.** 이 심볼 스트림을 실제 조난 주파수(VHF Ch70 156.525MHz,
   MF 2187.5kHz 등)로 변조해 송신하면 불법이고 수색구조 자원을 낭비시킨다.
   UDP 로 보내 항해 소프트웨어에서 확인하는 용도까지만 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# ── 심볼 상수 (Table 3) ──────────────────────────────────────────────
class Format(IntEnum):
    """형식 지정자. §4.1"""

    GEOGRAPHIC_AREA = 102
    SHIPS_COMMON_INTEREST = 114
    ALL_SHIPS = 116
    INDIVIDUAL = 120
    DISTRESS = 112              # §4.1.1 조난 경보


class Category(IntEnum):
    """카테고리. §6

    ⚠ 조난 경보에는 **카테고리 문자가 들어가지 않는다** (§6.2).
      우선순위를 형식지정자가 이미 정하기 때문이다.
    """

    ROUTINE = 100
    SAFETY = 108
    URGENCY = 110
    DISTRESS = 112


class Nature(IntEnum):
    """조난 성격. §8.1.1, Table 3.

    `pi_accident.report_dsc` 가 이 값을 그대로 쓴다.

    ⚠ 111 은 이 표에 없다. EPIRB 는 112 다.
      `database/pi.sql` 의 `CHECK (report_dsc BETWEEN 100 AND 111)` 은 111 을 허용하고
      112 를 막는다 — 규격과 어긋난다. Pi 가 EPIRB 를 발신하지 않아 지금은 무해하나
      스키마를 손볼 때 같이 고칠 것.
    """

    FIRE = 100
    FLOODING = 101
    COLLISION = 102
    GROUNDING = 103
    LISTING = 104
    SINKING = 105
    DISABLED_ADRIFT = 106
    UNDESIGNATED = 107
    ABANDONING_SHIP = 108
    PIRACY = 109
    MAN_OVERBOARD = 110
    EPIRB_EMISSION = 112


class Telecommand1(IntEnum):
    """첫 번째 텔레커맨드. 조난 경보에서는 '후속 통신 수단'을 뜻한다 (§8.1.4)."""

    F3E_G3E_ALL_MODES_TP = 100     # VHF 무선전화
    F3E_G3E_DUPLEX_TP = 101
    POLLING = 103
    UNABLE_TO_COMPLY = 104
    END_OF_CALL = 105
    DATA = 106
    J3E_TP = 109                   # MF/HF 무선전화
    DISTRESS_ACK = 110
    DISTRESS_RELAY = 112
    F1B_J2B_TTY_FEC = 113
    F1B_J2B_TTY_ARQ = 115
    TEST = 118
    NO_INFORMATION = 126


class EOS(IntEnum):
    """종료 문자. §9"""

    ACK_RQ = 117        # 응답을 요구하는 호출. 개별·자동 호출 전용
    ACK_BQ = 122        # 응답을 요구한 호출에 대한 답신
    OTHER = 127         # 그 밖의 모든 호출 — **조난 경보가 여기 해당한다**


#: phasing. §3.2
PHASING_DX = 125
#: RX 위치 phasing. 104 가 RX-0 이고, 다음 RX 부터 정보문자 재전송이 시작된다.
PHASING_RX = (111, 110, 109, 108, 107, 106, 105, 104)

#: 점 패턴 길이. §3.4
DOT_PATTERN_BITS_HFMF_DISTRESS = 200
DOT_PATTERN_BITS_VHF = 20

#: 좌표·시각을 알 수 없을 때 넣는 값. §8.1.2.4 / §8.1.3.3
POSITION_UNKNOWN_DIGITS = "9" * 10
TIME_UNKNOWN_DIGITS = "8888"

#: DX 뒤 몇 위치 뒤에 RX 가 오는가. §1.2.1 "4개 문자가 지난 뒤"
DX_RX_OFFSET = 5


# ── 심볼 부호화 (§1.1) ───────────────────────────────────────────────
def check_bits(symbol: int) -> int:
    """7개 정보비트 중 0(B 요소)의 개수. 이것이 체크 3비트의 값이다."""
    return 7 - bin(symbol & 0x7F).count("1")


def symbol_to_bits(symbol: int) -> str:
    """심볼 번호 → 송신 순서대로 늘어놓은 10비트 문자열.

    정보 7비트는 **LSB 먼저**, 체크 3비트는 **MSB 먼저** (§1.1.1).
    """
    if not 0 <= symbol <= 127:
        raise ValueError(f"심볼은 0~127: {symbol}")
    info = "".join(str((symbol >> i) & 1) for i in range(7))      # LSB first
    check = format(check_bits(symbol), "03b")                      # MSB first
    return info + check


def bits_to_symbol(bits: str) -> int:
    """10비트 → 심볼 번호. 체크비트가 안 맞으면 `ValueError`.

    수신 측 검증용이며 시험에서 왕복을 확인하는 데 쓴다.
    """
    if len(bits) != 10:
        raise ValueError(f"10비트여야 한다: {len(bits)}")
    symbol = sum(int(b) << i for i, b in enumerate(bits[:7]))
    if int(bits[7:], 2) != check_bits(symbol):
        raise ValueError(f"체크비트 불일치: {bits}")
    return symbol


# ── 숫자 묶기 (Table 2) ──────────────────────────────────────────────
def pack_digits(digits: str) -> list[int]:
    """십진 숫자열을 두 자리씩 묶어 심볼 번호로 바꾼다.

    Table 2 는 두 숫자를 하나의 10비트 문자로 싣는다. (X1,X2) -> 심볼 X1*10+X2.
    """
    if len(digits) % 2:
        raise ValueError(f"자릿수가 짝수여야 한다: {digits!r}")
    if not digits.isdigit():
        raise ValueError(f"숫자만 와야 한다: {digits!r}")
    return [int(digits[i:i + 2]) for i in range(0, len(digits), 2)]


def encode_mmsi(mmsi: str) -> list[int]:
    """MMSI 9자리 → 5심볼. §5.2 Note 1

    ⚠ 10번째 자리에 0 을 붙여 10자리로 만든 뒤 두 자리씩 묶는다.
      (M,I)(D,X4)(X5,X6)(X7,X8)(X9,0)
    """
    if len(mmsi) != 9 or not mmsi.isdigit():
        raise ValueError(f"MMSI 는 숫자 9자리: {mmsi!r}")
    return pack_digits(mmsi + "0")


def encode_position(lat: float | None, lon: float | None) -> list[int]:
    """조난 좌표 → 5심볼. §8.1.2

    10자리: 사분면(1) + 위도 도분(4) + 경도 도분(5)

        사분면  0=NE  1=NW  2=SE  3=SW           (§8.1.2.1)
        위도    도 2자리 + 분 2자리               (§8.1.2.2)
        경도    도 3자리 + 분 2자리               (§8.1.2.3)

    ⚠ 분이 정수라 해상도가 1분 = 약 1.85km 다. 규격 자체의 한계이며 DSC 로는 더
      정밀하게 보낼 수 없다. 정밀 위치는 별도 수단(AIS, DSE 확장)이 맡는다.

    좌표가 없으면 9 를 10번 보낸다 (§8.1.2.4). 위치가 23.5시간 넘게 갱신되지
    않았을 때도 같다.
    """
    if lat is None or lon is None:
        return pack_digits(POSITION_UNKNOWN_DIGITS)

    quadrant = (0 if lat >= 0 else 2) + (0 if lon >= 0 else 1)
    lat_deg, lat_min = _deg_min(lat)
    lon_deg, lon_min = _deg_min(lon)
    return pack_digits(f"{quadrant}{lat_deg:02d}{lat_min:02d}{lon_deg:03d}{lon_min:02d}")


def _deg_min(value: float) -> tuple[int, int]:
    """십진도 → (도, 내림한 정수 분).

    ⚠ 반올림하지 않는다. 59.7 분을 60 으로 올리면 도가 하나 밀려 60해리가 틀어진다.
    """
    a = abs(value)
    return int(a), int((a - int(a)) * 60.0)


def encode_time(hour: int | None, minute: int | None) -> list[int]:
    """UTC 시각 → 2심볼. §8.1.3

    좌표가 유효했던 시각이지 송신 시각이 아니다. 알 수 없으면 8888 (§8.1.3.3).
    """
    if hour is None or minute is None:
        return pack_digits(TIME_UNKNOWN_DIGITS)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"UTC 시각 범위 밖: {hour}:{minute}")
    return pack_digits(f"{hour:02d}{minute:02d}")


# ── 호출 ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DscCall:
    """DSC 호출 하나. 심볼 수준의 값만 담는다 — 변조도 전송도 모른다."""

    format_specifier: int
    #: 형식지정자와 EOS 사이의 본문. 주소·자기식별·성격·좌표·시각·후속통신 등.
    #: **배치는 호출 종류마다 다르다.** `kind` 가 어느 표를 따르는지 가리킨다.
    body: tuple[int, ...]
    eos: int
    #: 어느 표의 배치인가. 직렬화 계층이 이걸 보고 필드를 꺼낸다.
    kind: str = "distress_alert"

    @property
    def information(self) -> tuple[int, ...]:
        """ECC 계산 대상. §10.2

        🔴 **형식지정자와 EOS 는 각각 하나씩만 들어간다.**
        형식지정자는 실제로 DX 에 두 번 실리고(Table 4.1 "2 identical") EOS 는 세 번
        실리지만, ECC 에는 한 번만 반영한다. 두 번 넣으면 XOR 이라 서로 상쇄되어
        형식지정자가 아예 빠진 것과 같아진다.

        phasing 과 RX 재전송도 제외한다 (§10.2).
        """
        return (self.format_specifier, *self.body, self.eos)

    @property
    def ecc(self) -> int:
        """오류검사 문자. 정보문자 7비트의 **짝수 수직 패리티**(= XOR). §10.2"""
        acc = 0
        for s in self.information:
            acc ^= s & 0x7F
        return acc

    def dx_stream(self) -> list[int]:
        """DX 위치에 실리는 문자 목록.

        형식지정자 2회 + 본문 + EOS + ECC. 꼬리의 EOS 두 번은 `symbols()` 가
        RX 를 빼내며 자동으로 채운다.
        """
        return [self.format_specifier, self.format_specifier,
                *self.body, self.eos, self.ecc]

    def symbols(self, *, with_phasing: bool = True) -> list[int]:
        """실제 송신 순서대로 늘어놓은 전체 심볼 열.

        짝수 위치 = DX, 홀수 위치 = RX. 위치 p 의 DX 가 p+5 에서 RX 로 다시 나온다.

        꼬리에서 DX 슬롯이 남으면 EOS 로 채운다. 그 결과 §9 가 요구하는
        "EOS 를 DX 위치에 3번, RX 위치에 1번" 이 자동으로 만족된다.
        """
        dx = self.dx_stream()
        out: list[int] = []

        if with_phasing:
            # DX 6개(125)를 RX phasing 111..106 과 번갈아 놓는다 (§3.2).
            for rx in PHASING_RX[:6]:
                out += [PHASING_DX, rx]
            #  이제 DX 슬롯부터 정보문자가 시작된다. 남은 RX phasing 105, 104 는
            #  아래 루프가 RX 슬롯에 순서대로 흘려 넣는다.
            pending_rx_phasing = list(PHASING_RX[6:])
        else:
            pending_rx_phasing = []

        base = len(out)                       # 첫 정보문자(DX)가 놓이는 위치
        last_dx_pos = base + 2 * (len(dx) - 1)
        end = last_dx_pos + DX_RX_OFFSET      # 마지막 DX 의 RX 재전송 위치

        next_dx = 0
        for pos in range(base, end + 1):
            if pos % 2 == base % 2:           # DX 슬롯
                # 정보문자가 떨어지면 EOS 로 채운다. 그래야 RX 가 다 빠져나가고,
                # §9 의 "EOS 를 DX 에 3번, RX 에 1번" 이 저절로 만족된다.
                out.append(dx[next_dx] if next_dx < len(dx) else self.eos)
                next_dx += 1
            else:                             # RX 슬롯 — 5칸 앞의 DX 를 다시 보낸다
                src = pos - DX_RX_OFFSET
                if src < base:
                    out.append(pending_rx_phasing.pop(0) if pending_rx_phasing
                               else PHASING_RX[-1])
                else:
                    out.append(out[src])
        return out

    def bits(self, *, with_phasing: bool = True, dot_pattern_bits: int = 0) -> str:
        """무선에 실릴 비트열. 점 패턴 + phasing + 심볼들.

        점 패턴은 B-Y 교번 신호다 (§3.4). VHF 는 20비트, HF/MF 조난은 200비트.
        """
        dots = "01" * (dot_pattern_bits // 2)
        return dots + "".join(symbol_to_bits(s) for s in self.symbols(with_phasing=with_phasing))


def distress_alert(
    *,
    mmsi: str,
    nature: Nature | int,
    lat: float | None,
    lon: float | None,
    hour: int | None,
    minute: int | None,
    subsequent: Telecommand1 | int = Telecommand1.F3E_G3E_ALL_MODES_TP,
) -> DscCall:
    """조난 경보(Distress alert). Table 4.1

    문자 순서:
        형식지정자 112 (2개 동일) · 자기식별 5 · 조난성격 1 · 조난좌표 5
        · 시각 2 · 후속통신 1 · EOS 1        ... 그 뒤에 ECC 가 붙는다

    ⚠ 조난 경보에는 주소도 카테고리도 없다 (§5.1, §6.2). 전 국에 암묵적으로 보낸다.

    ⚠ EOS 는 127 이다. 117(Ack RQ)은 개별·자동 호출 전용이라 여기 쓸 수 없다 (§9.1).

    `subsequent` 는 조난 후 통신 수단이다. VHF 는 100(F3E/G3E all modes TP),
    MF/HF 는 109(J3E TP)를 쓴다 (§8.1.4, Table 3 first telecommand).
    """
    body: list[int] = []
    body += encode_mmsi(mmsi)                      # 자기식별 (5)
    body.append(int(nature))                       # 조난 성격 (1)
    body += encode_position(lat, lon)              # 조난 좌표 (5)
    body += encode_time(hour, minute)              # 시각 (2)
    body.append(int(subsequent))                   # 후속 통신 (1)

    return DscCall(format_specifier=int(Format.DISTRESS),
                   body=tuple(body),
                   eos=int(EOS.OTHER))


def distress_acknowledgement(
    *,
    coast_mmsi: str,
    distress_mmsi: str,
    nature: Nature | int,
    lat: float | None,
    lon: float | None,
    hour: int | None,
    minute: int | None,
    subsequent: Telecommand1 | int = Telecommand1.F3E_G3E_ALL_MODES_TP,
) -> DscCall:
    """조난 확인응답(Distress acknowledgement). Table 4.2

    **해안국이 보낸다.** 조난선은 이걸 받으면 DSC 경보 반복을 멈춘다.

    VHF RT 기준 문자 배치:

        형식지정자 116 (2개 동일) · 카테고리 112 · 자기식별 5 · 텔레커맨드 110
        · 조난선 MMSI 5 · 조난성격 1 · 조난좌표 5 · 시각 2 · 후속통신 100
        · EOS 127 · ECC

    ⚠ 조난 **경보**와 배치가 다르다. 경보에는 카테고리도 텔레커맨드도 없다(§6.2).
      확인응답에는 둘 다 있고, 게다가 MMSI 가 **둘** 실린다 —
      자기식별(해안국)과 조난선 MMSI. 순서를 바꾸면 엉뚱한 배를 지목한다.

    ⚠ 형식지정자는 120(개별)이 아니라 **116(전선박)** 이다. 조난 확인응답은 조난선
      한 척이 아니라 그 구역 모두가 들어야 한다.

    ⚠ EOS 는 122(Ack BQ)가 아니라 **127** 이다. Table 4.2 가 그렇게 적고 있다.
      122 는 distress relay acknowledgement 쪽이다(§9.2).

    MF/HF 에서는 `subsequent` 가 109(J3E TP)다. VHF 는 100.
    """
    body: list[int] = [int(Category.DISTRESS)]
    body += encode_mmsi(coast_mmsi)                # 자기식별 (해안국)
    body.append(int(Telecommand1.DISTRESS_ACK))    # 110
    body += encode_mmsi(distress_mmsi)             # 조난선 MMSI
    body.append(int(nature))
    body += encode_position(lat, lon)
    body += encode_time(hour, minute)
    body.append(int(subsequent))

    return DscCall(format_specifier=int(Format.ALL_SHIPS),
                   body=tuple(body),
                   eos=int(EOS.OTHER),
                   kind="distress_acknowledgement")

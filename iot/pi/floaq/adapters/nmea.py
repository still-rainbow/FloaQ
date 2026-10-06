"""NMEA 0183 / IEC 61162-1 직렬화. **규격 계층의 출력 형식 하나일 뿐이다.**

정본은 `floaq/protocols/` 다. 여기는 그걸 배 위 장비끼리 주고받는 문장으로 옮긴다.

    protocols/dsc.py  M.493 심볼 프레임   ──▶  $CDDSC + $CDDSE
    protocols/ais.py  M.1371 메시지 비트  ──▶  !AIVDM

왜 이 계층이 따로 필요한가
    무선에 실리는 것은 심볼·비트다. 그러나 무전기와 플로터 사이는 NMEA 로 말한다.
    실제 DSC 무전기가 조난 호출을 수신하면 `$CDDSC` 로 플로터에 넘긴다.
    우리가 그 자리에 서면 항해 소프트웨어가 우리 신고를 그대로 알아본다.

⚠ **소켓을 모른다.** 순수 함수만 있다. UDP 송신은 `adapters/report.py` 가 한다.

── 심볼값 대응 ─────────────────────────────────────────────────────
NMEA DSC 문장의 숫자 필드는 **M.493 심볼 번호에서 100 을 뺀 값**이다.

    형식지정자  112 조난   -> 12        116 전선박 -> 16
                120 개별   -> 20        102 지역   -> 02
    카테고리    112 조난   -> 12
    조난성격    110 익수자 -> 10
    후속통신    100 F3E/G3E TP -> 00

🔴 `pi_accident.report_dsc` 는 심볼값(110)을 담는다. 문장에 그대로 넣으면 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from floaq.protocols import ais, dsc

#: NMEA 숫자 필드는 심볼 번호에서 이만큼 뺀 값이다.
SYMBOL_OFFSET = 100

#: 확인응답 필드(field 10). M.493 의 EOS 문자에 대응한다.
_EOS_TO_ACK = {
    dsc.EOS.ACK_RQ: "R",     # 117 응답 요구
    dsc.EOS.ACK_BQ: "B",     # 122 응답
    dsc.EOS.OTHER: "S",      # 127 그 외 — 조난 경보가 여기
}


# ── 공통 ─────────────────────────────────────────────────────────────
def checksum(body: str) -> str:
    """`$`/`!` 와 `*` 사이를 XOR 한 2자리 대문자 16진수.

    ⚠ 수신기는 체크섬이 틀리면 **조용히 버린다.** 문장이 안 보이면 여기부터 의심한다.
    """
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}"


def sentence(body: str, *, start: str = "$") -> str:
    """시작 문자와 체크섬을 붙여 완성한다. CRLF 까지 포함한다.

    AIS 는 `!`(캡슐화 문장), 그 외는 `$`(질의·응답 문장)로 시작한다.
    """
    return f"{start}{body}*{checksum(body)}\r\n"


# ── DSC ──────────────────────────────────────────────────────────────
def _position_digits(call: dsc.DscCall) -> str:
    """호출 안의 조난좌표 5심볼을 10자리 숫자로 되돌린다.

    본문 배치: 자기식별(5) · 성격(1) · 좌표(5) · 시각(2) · 후속통신(1)
    """
    return "".join(f"{s:02d}" for s in call.body[6:11])


def _time_digits(call: dsc.DscCall) -> str:
    return "".join(f"{s:02d}" for s in call.body[11:13])


def _mmsi_digits(call: dsc.DscCall) -> str:
    """자기식별 5심볼 → 10자리. M.493 §5.2 의 (X9,0) 규칙대로 끝에 0 이 붙어 있다.

    ⚠ 9자리로 줄여 보내지 않는다. 실제 무전기가 10자리로 내보내고, 수신 측이
      앞 9자리를 취한다.
    """
    return "".join(f"{s:02d}" for s in call.body[0:5])


def dsc_sentence(call: dsc.DscCall) -> str:
    """M.493 호출 → `$CDDSC`.

    필드 순서 (IEC 61162-1):

        1 형식지정자   2 주소/발신 MMSI(10자리)   3 카테고리
        4 성격 또는 telecommand1                 5 telecommand2
        6 위치 또는 채널·주파수                   7 시각 또는 전화번호
        8 조난선 MMSI(중계)                      9 성격(중계)
        10 확인응답                              11 확장지시자

    ⚠ 조난 경보에는 M.493 상 카테고리 문자가 없다(§6.2). 그러나 NMEA 문장에는 칸이
      있어서 무전기들이 조난(12)을 채워 보낸다. 여기서도 그렇게 한다.
    """
    nature = call.body[5]
    subsequent = call.body[13]
    pos = _position_digits(call)

    body = ",".join([
        "CDDSC",
        f"{call.format_specifier - SYMBOL_OFFSET:02d}",
        _mmsi_digits(call),
        f"{int(dsc.Category.DISTRESS) - SYMBOL_OFFSET:02d}",
        f"{nature - SYMBOL_OFFSET:02d}",
        f"{subsequent - SYMBOL_OFFSET:02d}",
        pos,
        _time_digits(call),
        "",                                        # 조난선 MMSI — 중계일 때만
        "",                                        # 성격 — 중계일 때만
        _EOS_TO_ACK[dsc.EOS(call.eos)],
        "E" if pos != dsc.POSITION_UNKNOWN_DIGITS else "",
    ])
    return sentence(body)


def dse_sentence(*, mmsi: str, lat: float, lon: float) -> str:
    """`$CDDSE` 위치 정밀 보정.

    DSC 좌표는 분이 정수라 해상도가 1분 = 약 1.85km 다(M.493 §8.1.2). 익수자 위치에
    쓰기엔 거칠어서, 남은 소수부를 **1/10000 분** 단위로 따로 싣는다.

    확장 데이터 심볼 `00` = 위치. 8자리 = 위도 4 + 경도 4.

    ⚠ 부호는 싣지 않는다. 수신 측이 DSC 좌표의 부호를 따라 더한다.
    ⚠ 확장지시자가 `E` 인 DSC 바로 뒤에 보내야 한다. 수신기가 오래 기다리지 않는다.
    """
    lat_frac = (abs(lat) * 60.0) % 1.0
    lon_frac = (abs(lon) * 60.0) % 1.0
    # 9999 를 넘기면 자릿수가 밀려 위도가 경도 칸을 침범한다
    lat_d = min(9999, round(lat_frac * 10000))
    lon_d = min(9999, round(lon_frac * 10000))

    body = ",".join([
        "CDDSE",
        "1",                      # 전체 문장 수
        "1",                      # 이 문장 번호
        "F",                      # query/reply 플래그. F = 자동 응답 아님
        mmsi + "0",               # M.493 과 같은 10자리 표기
        "00",                     # 확장 데이터 심볼 00 = 위치
        f"{lat_d:04d}{lon_d:04d}",
    ])
    return sentence(body)


def dsc_distress_sentences(
    *, mmsi: str, nature: int, lat: float | None, lon: float | None,
    hour: int | None, minute: int | None,
    subsequent: int = int(dsc.Telecommand1.F3E_G3E_ALL_MODES_TP),
) -> tuple[str, ...]:
    """조난 경보를 문장들로. 위치가 있으면 DSE 를 함께 낸다."""
    call = dsc.distress_alert(mmsi=mmsi, nature=nature, lat=lat, lon=lon,
                              hour=hour, minute=minute, subsequent=subsequent)
    out = [dsc_sentence(call)]
    if lat is not None and lon is not None:
        out.append(dse_sentence(mmsi=mmsi, lat=lat, lon=lon))
    return tuple(out)


# ── AIS ──────────────────────────────────────────────────────────────
def armor(bits: str) -> tuple[str, int]:
    """비트열 → AIVDM 페이로드 문자와 fill 비트 수.

    6비트씩 끊어 값 v 를 문자로: `v < 40 ? v + 48 : v + 56`.
    (수신 측은 `ASCII - 48`, 40 을 넘으면 다시 8 을 뺀다.)
    """
    fill = (6 - len(bits) % 6) % 6
    padded = bits + "0" * fill
    out = []
    for p in range(0, len(padded), 6):
        v = int(padded[p:p + 6], 2)
        out.append(chr(v + 48 if v < 40 else v + 56))
    return "".join(out), fill


def dearmor(payload: str, fill: int = 0) -> str:
    """AIVDM 페이로드 → 비트열. 시험과 수신 처리에 쓴다."""
    bits = ""
    for ch in payload:
        v = ord(ch) - 48
        if v > 40:
            v -= 8
        bits += format(v, "06b")
    return bits[:len(bits) - fill] if fill else bits


def aivdm(payload_bits: str, *, channel: str = "A", talker: str = "AI") -> str:
    """메시지 비트 → `!AIVDM` 문장 하나.

    ⚠ 여러 문장으로 쪼개는 경우는 다루지 않는다. Message 1 은 168비트로 늘 한 문장이고,
      Message 14 도 규정 문구 길이면 한 문장에 들어간다.

    ⚠ AIVDM 은 **메시지 비트만** 싣는다. CRC·비트 스터핑·NRZI 는 무선 링크 계층이라
      수신기가 이미 벗겨냈다. 그쪽은 `protocols/ais.LinkFrame` 이 담당한다.
    """
    body_payload, fill = armor(payload_bits)
    return sentence(f"{talker}VDM,1,1,,{channel},{body_payload},{fill}", start="!")


def ais_mob_sentences(*, mmsi: str, lat: float, lon: float,
                      second: int | None = None,
                      with_text: bool = False,
                      channel: str = "A") -> tuple[str, ...]:
    """AIS-MOB 위치보고. `with_text` 면 Message 14 를 덧붙인다.

    실제 장비는 위치보고를 1분에 8회 보내고 4분마다 한 번만 Message 14 를 섞는다.
    그 주기는 `adapters/report.py` 가 맡는다.
    """
    out = [aivdm(ais.mob_position(mmsi=mmsi, lat=lat, lon=lon, second=second),
                 channel=channel)]
    if with_text:
        out.append(aivdm(ais.message_14(mmsi=mmsi, text=ais.TEXT_MOB_ACTIVE),
                         channel=channel))
    return tuple(out)


def ais_sart_sentences(*, mmsi: str, lat: float, lon: float,
                       second: int | None = None,
                       with_text: bool = False,
                       channel: str = "A") -> tuple[str, ...]:
    out = [aivdm(ais.sart_position(mmsi=mmsi, lat=lat, lon=lon, second=second),
                 channel=channel)]
    if with_text:
        out.append(aivdm(ais.message_14(mmsi=mmsi, text=ais.TEXT_SART_ACTIVE),
                         channel=channel))
    return tuple(out)


# ── DSC 확인응답 ─────────────────────────────────────────────────────
def _digits(call: dsc.DscCall, start: int, count: int) -> str:
    return "".join(f"{s:02d}" for s in call.body[start:start + count])


def dsc_acknowledgement_sentence(call: dsc.DscCall) -> str:
    """조난 확인응답 → `$CDDSC`. Table 4.2

    본문 배치가 조난 경보와 **다르다**:

        0     카테고리 112
        1-5   자기식별(해안국 MMSI)
        6     텔레커맨드 110 (distress acknowledgement)
        7-11  조난선 MMSI
        12    조난성격
        13-17 조난좌표
        18-19 시각
        20    후속통신

    NMEA 로 옮기면 MMSI 가 **두 칸**에 나뉜다 — 필드 2 는 보낸 쪽(해안국),
    필드 8 은 조난선. 수신 측은 형식지정자 16 + 카테고리 12 일 때만 필드 8 을 읽는다.
    """
    if call.kind != "distress_acknowledgement":
        raise ValueError(f"확인응답이 아니다: {call.kind}")

    pos = _digits(call, 13, 5)
    body = ",".join([
        "CDDSC",
        f"{call.format_specifier - SYMBOL_OFFSET:02d}",   # 116 -> 16
        _digits(call, 1, 5),                              # 해안국 MMSI (10자리)
        f"{call.body[0] - SYMBOL_OFFSET:02d}",            # 112 -> 12
        f"{call.body[6] - SYMBOL_OFFSET:02d}",            # 110 -> 10 텔레커맨드
        f"{call.body[20] - SYMBOL_OFFSET:02d}",           # 후속통신
        pos,
        _digits(call, 18, 2),
        _digits(call, 7, 5),                              # 조난선 MMSI (10자리)
        f"{call.body[12] - SYMBOL_OFFSET:02d}",           # 조난성격
        _EOS_TO_ACK[dsc.EOS(call.eos)],
        "E" if pos != dsc.POSITION_UNKNOWN_DIGITS else "",
    ])
    return sentence(body)


# ── 수신 ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ParsedDsc:
    """수신한 `$CDDSC` 에서 뽑아낸 것. 해석하지 않은 원값에 가깝다."""

    format_specifier: int          # 심볼값으로 되돌린 것 (16 -> 116)
    sender_mmsi: str               # 9자리
    category: int | None
    telecommand1: int | None
    distress_mmsi: str | None      # 전선박+조난 카테고리일 때만
    nature: int | None             # 심볼값 (110 = 익수자)

    @property
    def is_distress_acknowledgement(self) -> bool:
        """해안국이 보낸 조난 확인응답인가. Table 4.2

        전선박(116) + 조난(112) + 텔레커맨드 110 셋이 모두 맞아야 한다.
        """
        return (self.format_specifier == dsc.Format.ALL_SHIPS
                and self.category == dsc.Category.DISTRESS
                and self.telecommand1 == dsc.Telecommand1.DISTRESS_ACK)


def verify_checksum(line: str) -> bool:
    """`*` 뒤 두 자리와 대조한다. 안 맞으면 **버린다.**"""
    line = line.strip()
    if not line or line[0] not in "$!" or "*" not in line:
        return False
    body, _, cs = line[1:].partition("*")
    return cs[:2].upper() == checksum(body)


def parse_dsc(line: str) -> ParsedDsc | None:
    """수신한 `$CDDSC` 를 읽는다. 형식이 아니거나 체크섬이 틀리면 `None`.

    ⚠ 필드 4 는 형식에 따라 **조난성격이거나 텔레커맨드**다. 전선박+조난이면
      텔레커맨드이고 성격은 필드 9 에 있다. 한쪽으로만 읽으면 확인응답을 놓친다.

    ⚠ 예외를 던지지 않는다. 수신 경로에서 죽으면 그 뒤 신고 상태를 못 받는다.
    """
    line = line.strip()
    if not line.startswith("$") or line[3:6] != "DSC" or not verify_checksum(line):
        return None
    tok = line[1:].split("*")[0].split(",")
    if len(tok) < 10:
        return None
    try:
        fmt = int(tok[1]) + SYMBOL_OFFSET
        sender = tok[2][:9]
        cat = int(tok[3]) + SYMBOL_OFFSET if tok[3] else None
        field4 = int(tok[4]) + SYMBOL_OFFSET if tok[4] else None
    except ValueError:
        return None

    distress_mmsi, nature, telecommand1 = None, None, None
    if fmt == dsc.Format.ALL_SHIPS and cat == dsc.Category.DISTRESS:
        telecommand1 = field4
        distress_mmsi = tok[8][:9] if len(tok) > 8 and tok[8] else None
        if len(tok) > 9 and tok[9]:
            try:
                nature = int(tok[9]) + SYMBOL_OFFSET
            except ValueError:
                nature = None
    else:
        nature = field4

    return ParsedDsc(format_specifier=fmt, sender_mmsi=sender, category=cat,
                     telecommand1=telecommand1, distress_mmsi=distress_mmsi,
                     nature=nature)


def coastguard_acknowledgement(
    *, coast_mmsi: str, distress_mmsi: str, nature: int,
    lat: float | None, lon: float | None,
    hour: int | None, minute: int | None,
) -> str:
    """해안국 역할로 확인응답 한 문장을 만든다. 시연·시험용."""
    return dsc_acknowledgement_sentence(dsc.distress_acknowledgement(
        coast_mmsi=coast_mmsi, distress_mmsi=distress_mmsi, nature=nature,
        lat=lat, lon=lon, hour=hour, minute=minute))

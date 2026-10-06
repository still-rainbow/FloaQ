"""부표 아두이노 펌웨어의 정수 산술 시험.

🔴 **여기 있는 함수들은 `iot/buoy/buoy_tx/buoy_tx.ino` 를 손으로 옮긴 것이다.**
   한쪽을 고치면 다른 쪽도 고쳐야 한다. 옮긴 이유는 하나다 — 부표 코드는 AVR 에서만
   돌아서 시연 전까지 아무도 못 돌려보는데, **틀리면 조용히 틀린다.** Pi 는 CRC 나
   버전에서 전부 버리고 로그에는 카운터만 오른다.

여기서 실제로 잡는 것:

  - `int` 가 16비트인 AVR 에서 넘치는 식 (`era * 146097` 이 대표다)
  - `ddmm.mmmm` 를 십진도로 착각하는 실수 (약 5.7km 틀어진다)
  - 빅엔디안 바이트 채우기
  - RMC 시각 -> epoch 변환의 윤년·3월 경계

파이썬 정수는 무한 정밀도라 그냥 옮기면 **넘침이 재현되지 않는다.** 그래서 C 의 폭을
`_u16` / `_u32` / `_i32` 로 명시해 씌운다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.adapters import gps
from floaq.contracts.lora import BuoyFrame, unpack

INO = Path(__file__).resolve().parents[3] / "iot" / "buoy" / "buoy_tx" / "buoy_tx.ino"


# ── C 의 정수 폭 ─────────────────────────────────────────────────────
def _u16(v: int) -> int:
    return v & 0xFFFF


def _u32(v: int) -> int:
    return v & 0xFFFFFFFF


def _i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x1_0000_0000 if v >= 0x8000_0000 else v


# ── buoy_tx.ino 전사 ─────────────────────────────────────────────────
def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = _u16(crc ^ (b << 8))
        for _ in range(8):
            crc = _u16((crc << 1) ^ 0x1021) if crc & 0x8000 else _u16(crc << 1)
    return crc


def days_from_civil(y: int, m: int, d: int) -> int:
    yy = _u16(y - (1 if m <= 2 else 0))
    era = _u32(yy // 400)
    yoe = _u16(yy - _u16(era * 400))
    doy = _u16((153 * _u16(m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1)
    doe = _u32(yoe * 365 + yoe // 4 - yoe // 100 + doy)
    return _u32(era * 146097 + doe - 719468)


def build_frame(seq, lat_1e7, lon_1e7, measured_at, pressed, fix, battery, tag=0xC9):
    out = bytearray(19)
    out[0] = (1 << 4) | 0
    out[1] = tag
    out[2], out[3] = _u16(seq) >> 8 & 0xFF, _u16(seq) & 0xFF
    la = _u32(lat_1e7)
    out[4:8] = [(la >> s) & 0xFF for s in (24, 16, 8, 0)]
    lo = _u32(lon_1e7)
    out[8:12] = [(lo >> s) & 0xFF for s in (24, 16, 8, 0)]
    out[12:16] = [(measured_at >> s) & 0xFF for s in (24, 16, 8, 0)]
    out[16] = (0x01 if pressed else 0) | (0x02 if fix else 0) | ((battery & 3) << 2)
    crc = crc16_ccitt(bytes(out[:17]))
    out[17], out[18] = crc >> 8, crc & 0xFF
    return bytes(out)


def _digits(s: str, n: int) -> int:
    v = 0
    for i in range(n):
        if i >= len(s) or not s[i].isdigit():
            return 0
        v = v * 10 + int(s[i])
    return v


def dm_to_1e7(s: str, hemi: str):
    """`ddmm.mmmmm` -> 1e-7 도. 실패하면 None."""
    dot = -1
    for i, c in enumerate(s):
        if c == ",":
            break
        if c == ".":
            dot = i
            break
    if dot < 3:
        return None

    deg = _digits(s, dot - 2)
    min_int = _digits(s[dot - 2:], 2)

    frac, taken = 0, 0
    i = dot + 1
    while taken < 5:
        c = s[i] if i < len(s) else ""
        is_digit = c.isdigit()
        frac = frac * 10 + (int(c) if is_digit else 0)
        taken += 1
        if not is_digit:
            for _ in range(taken, 5):
                frac *= 10
            break
        i += 1

    min_1e5 = _u32(min_int * 100000 + frac)
    if min_1e5 >= 6_000_000 or deg > 180:
        return None
    v = _i32(_u32(deg * 10_000_000 + (min_1e5 * 100 + 30) // 60))
    return -v if hemi in ("S", "W") else v


def parse_rmc(s: str):
    """성공하면 `(lat, lon, utc)`. 실패하면 None."""
    if not s.startswith("$") or s[3:6] != "RMC":
        return None
    f = s.split(",")
    if len(f) < 10:
        return None
    if f[2] != "A":
        return None
    lat = dm_to_1e7(f[3], f[4])
    lon = dm_to_1e7(f[5], f[6])
    if lat is None or lon is None:
        return None
    hh, mi, ss = _digits(f[1], 2), _digits(f[1][2:], 2), _digits(f[1][4:], 2)
    dd, mo, yy = _digits(f[9], 2), _digits(f[9][2:], 2), _digits(f[9][4:], 2)
    if not 1 <= mo <= 12 or not 1 <= dd <= 31:
        return None
    days = days_from_civil(2000 + yy, mo, dd)
    return lat, lon, _u32(days * 86400 + hh * 3600 + mi * 60 + ss)


# ── 프레임 ───────────────────────────────────────────────────────────
def test_firmware_frame_matches_the_python_codec():
    """🔴 이게 어긋나면 부표가 쏜 걸 Pi 가 전부 버린다. 그것도 조용히."""
    got = build_frame(7, 350_500_000, 1_291_000_000, 1_789_000_000, 1, 1, 3)
    want = BuoyFrame(ship_tag=0xC9, seq=7, lat=35.05, lon=129.10,
                     measured_at=1_789_000_000, is_pressed=True,
                     gps_fix=True, battery=3).pack()
    assert got == want


def test_firmware_frame_decodes_on_the_pi_side():
    """펌웨어가 만든 바이트를 수신부가 실제로 푼다."""
    f = unpack(build_frame(1, -350_500_000, -1_291_000_000, 1_789_000_000, 0, 1, 1))
    assert f.lat == pytest.approx(-35.05)       # 남반구·서반구 2의 보수
    assert f.lon == pytest.approx(-129.10)
    assert f.is_pressed is False
    assert f.battery == 1


def test_firmware_crc_standard_check_value():
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_seq_wraps_in_uint16():
    """18.2시간마다 순환한다. 정상 동작이고 Pi 의 seq_gap 이 감안한다."""
    assert build_frame(65536, 0, 0, 0, 0, 1, 0)[2:4] == b"\x00\x00"


# ── 시각 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("y,m,d,h,mi,s,want", [
    (2026, 9, 18, 12, 34, 56, 1_789_734_896),
    (2000, 1, 1, 0, 0, 0, 946_684_800),
    (2026, 3, 1, 0, 0, 0, 1_772_323_200),     # 평년 3월 경계
    (2024, 2, 29, 23, 59, 59, 1_709_251_199),  # 윤일
])
def test_days_from_civil_survives_16bit_int(y, m, d, h, mi, s, want):
    """🔴 AVR 의 `int` 는 16비트다. `era * 146097` = 730,485 라 그냥 쓰면 넘친다.

    넘치면 시각이 엉뚱해지고, `pi_buoy.created_at` 이 그 값이라 **지도에서 익수자가
    엉뚱한 시간대에 찍힌다.** 값 자체는 CHECK 를 통과해서 아무도 못 알아챈다.
    """
    assert days_from_civil(y, m, d) * 86400 + h * 3600 + mi * 60 + s == want


# ── 좌표 ─────────────────────────────────────────────────────────────
def test_degrees_minutes_is_not_decimal_degrees():
    """🔴 `4807.038` 은 48.07도가 아니라 48도 07.038분이다. 그냥 읽으면 5.7km 틀어진다."""
    got = dm_to_1e7("4807.038,N", "N")
    assert got == pytest.approx(round((48 + 7.038 / 60) * 1e7), abs=2)
    # 십진도로 잘못 읽으면 48.07도다. 실제는 48.1173도 — 약 5.3km 어긋난다
    assert abs(got - 480_700_000) > 400_000


@pytest.mark.parametrize("raw,hemi,want", [
    ("3503.00000", "N", 350_500_000),
    ("12906.00000", "E", 1_291_000_000),
    ("3503.00000", "S", -350_500_000),
    ("12906.00000", "W", -1_291_000_000),
])
def test_coordinate_scaling(raw, hemi, want):
    assert dm_to_1e7(raw + "," + hemi, hemi) == want


def test_short_fraction_is_padded_not_truncated():
    """GPS 마다 소수 자릿수가 다르다. 3자리를 5자리로 착각하면 100배 틀어진다."""
    assert dm_to_1e7("3503.038,N", "N") == dm_to_1e7("3503.03800,N", "N")


def test_minutes_over_60_is_rejected():
    """CRC 가 통과해도 값이 틀릴 수 있다. 송신 쪽에서 먼저 막는다."""
    assert dm_to_1e7("3560.00000,N", "N") is None


# ── RMC ──────────────────────────────────────────────────────────────
RMC = "$GNRMC,123456,A,3503.00000,N,12906.00000,E,0.5,84.4,180926,,"


def _with_checksum(s: str) -> str:
    """Pi 파서는 체크섬을 본다. 부표 파서는 안 본다 — E22 위에 CRC16 이 또 있어서다."""
    body = s[1:]
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{s}*{x:02X}"


def test_firmware_parse_agrees_with_the_pi_parser():
    """같은 문장을 Pi(`adapters/gps.py`)와 부표가 같은 값으로 읽어야 한다.

    둘이 갈라지면 배 위치와 익수자 위치가 다른 좌표계처럼 보인다.
    """
    mine = parse_rmc(RMC)
    theirs = gps.parse_rmc(_with_checksum(RMC))
    assert mine is not None and theirs is not None
    assert mine[0] / 1e7 == pytest.approx(theirs.lat, abs=1e-6)
    assert mine[1] / 1e7 == pytest.approx(theirs.lon, abs=1e-6)
    assert mine[2] == theirs.utc


def test_talker_id_is_not_hardcoded_to_gp():
    """🔴 요즘 수신기는 대부분 `$GNRMC` 를 낸다. `$GP` 만 보면 한 줄도 안 잡힌다."""
    for talker in ("GP", "GN", "GL", "GA"):
        assert parse_rmc("$" + talker + RMC[3:]) is not None


def test_void_status_is_rejected():
    """🔴 `V` 면 fix 가 없다. 좌표도 시각도 쓸 수 없다."""
    assert parse_rmc(RMC.replace(",A,", ",V,")) is None


def test_non_rmc_sentences_are_ignored():
    assert parse_rmc("$GNGGA,123456,3503.00000,N,12906.00000,E,1,08,0.9,10.0,M,,,,") is None


# ── 전사본이 실물과 붙어 있는지 ──────────────────────────────────────
def test_ino_exists_and_pins_the_same_vector():
    """전사본이 혼자 맞는 것은 의미가 없다. `.ino` 의 selftest 상수와 같아야 한다."""
    assert INO.is_file(), f"{INO} 가 없다"
    src = INO.read_text(encoding="utf-8")
    want = build_frame(7, 350_500_000, 1_291_000_000, 1_789_000_000, 1, 1, 3)
    for b in want:
        assert f"0x{b:02X}" in src, f".ino selftest 벡터에 0x{b:02X} 가 없다"


# ── 컴파일 시각 -> epoch ─────────────────────────────────────────────
#
# 🔴 전에는 `FAKE_EPOCH_BASE` 라는 상수 하나였고, 아무도 안 고쳐서 실물 프레임의
#    measured_at 이 **12.2일 전**으로 왔다 (2026-09-22 실측). 지도와 타임라인에서
#    익수자가 12일 전에 표류한 것으로 그려지는데, 값이 CHECK 를 통과해서 아무도
#    안 알아챈다. 이제 `__DATE__`·`__TIME__` 에서 만든다 — 굽는 순간이 출발점이다.
#
# ⚠ 이 변환이 틀리면 **똑같이 조용히** 며칠 밀린다. 한 자리 일(공백 패딩)과 윤년이
#   단골 함정이라 여기서 못 박는다.
BUILD_TZ_OFFSET_SEC = 9 * 3600      # KST. .ino 의 같은 이름과 맞춰야 한다
_MONTHS = "JanFebMarAprMayJunJulAugSepOctNovDec"


def build_epoch(date_s: str, time_s: str, tz: int = BUILD_TZ_OFFSET_SEC) -> int:
    """`buoy_tx.ino` 의 `build_epoch()` 를 그대로 옮긴 것."""
    mon = 1
    for i in range(12):
        if _MONTHS[i * 3:i * 3 + 3] == date_s[0:3]:
            mon = i + 1
            break
    # 일이 한 자리면 date_s[4] 가 공백이다. 그대로 빼면 음수가 된다
    day = (0 if date_s[4] == " " else (ord(date_s[4]) - 48) * 10) + (ord(date_s[5]) - 48)
    year = ((ord(date_s[7]) - 48) * 1000 + (ord(date_s[8]) - 48) * 100
            + (ord(date_s[9]) - 48) * 10 + (ord(date_s[10]) - 48))
    hh = (ord(time_s[0]) - 48) * 10 + (ord(time_s[1]) - 48)
    mi = (ord(time_s[3]) - 48) * 10 + (ord(time_s[4]) - 48)
    ss = (ord(time_s[6]) - 48) * 10 + (ord(time_s[7]) - 48)
    local = days_from_civil(year, mon, day) * 86400 + hh * 3600 + mi * 60 + ss
    return _u32(local - tz)


@pytest.mark.parametrize("date_s,time_s,want_utc", [
    ("Sep 22 2026", "14:18:42", "2026-09-22 05:18:42"),
    # 🔴 한 자리 일. `__DATE__` 가 공백으로 채운다 — 그냥 빼면 -48 이 된다
    ("Jan  1 2027", "00:00:00", "2026-12-31 15:00:00"),
    # 윤년 2월 29일
    ("Feb 29 2028", "12:00:00", "2028-02-29 03:00:00"),
    # days_from_civil 의 단골 함정인 3월 경계
    ("Mar  1 2026", "09:00:00", "2026-03-01 00:00:00"),
    ("Dec 31 2026", "23:59:59", "2026-12-31 14:59:59"),
])
def test_build_epoch_matches_real_calendar(date_s, time_s, want_utc):
    import datetime

    got = build_epoch(date_s, time_s)
    assert datetime.datetime.fromtimestamp(
        got, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") == want_utc


def test_build_epoch_passes_the_firmware_sanity_range():
    """⚠ 펌웨어 selftest 가 쓰는 범위와 같다. 파싱이 깨지면 여기서 걸린다."""
    got = build_epoch("Sep 22 2026", "14:18:42")
    assert 1_767_225_600 <= got <= 4_102_444_800


def test_ino_no_longer_hardcodes_an_epoch():
    """🔴 상수로 되돌아가면 같은 버그가 다시 난다. 파일을 직접 본다."""
    src = INO.read_text(encoding="utf-8")
    assert "FAKE_EPOCH_BASE" not in src, "손으로 박는 epoch 상수가 되살아났다"
    assert "__DATE__" in src and "__TIME__" in src

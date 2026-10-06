"""ITU-R M.493 규격 준수 시험. **수신 소프트웨어와 무관하다.**

규격 조항을 하나씩 확인한다. 상호운용 확인(OpenCPN 등)은 `test_nmea.py` 가 따로 한다.

근거: Recommendation ITU-R M.493-11
"""

from __future__ import annotations

import sys
from functools import reduce
from operator import xor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.protocols import dsc

MMSI = "440123456"
LAT, LON = 35.1234567, 129.7654321


def call() -> dsc.DscCall:
    return dsc.distress_alert(mmsi=MMSI, nature=dsc.Nature.MAN_OVERBOARD,
                              lat=LAT, lon=LON, hour=14, minute=30)


# ── §1.1 심볼 부호화 ─────────────────────────────────────────────────
def test_check_bits_count_zeros_not_ones():
    """체크 3비트는 정보 7비트 중 **B 요소(0)의 개수**다 (§1.1.1)."""
    assert dsc.check_bits(0b1111111) == 0
    assert dsc.check_bits(0b0000000) == 7
    assert dsc.check_bits(0b1010101) == 3


def test_spec_example_BYY_means_three_zeros():
    """§1.1.1 예시: 체크비트 BYY(011) 이면 0 이 3개.

    0 이 3개 = 1 이 4개인 심볼을 골라 확인한다.
    """
    symbol = 0b0001111          # 1 이 4개 -> 0 이 3개
    assert dsc.check_bits(symbol) == 3
    assert dsc.symbol_to_bits(symbol)[7:] == "011"


def test_information_bits_lsb_first_check_bits_msb_first():
    """🔴 §1.1.1 — 정보비트는 LSB 먼저, 체크비트는 MSB 먼저. 방향이 서로 반대다."""
    bits = dsc.symbol_to_bits(1)            # 0000001
    assert bits[:7] == "1000000"            # LSB 먼저라 1 이 맨 앞
    assert bits[7:] == "110"                # 0 이 6개 -> 110 (MSB 먼저)


def test_symbol_bits_round_trip_all_values():
    for s in range(128):
        assert dsc.bits_to_symbol(dsc.symbol_to_bits(s)) == s


def test_corrupted_check_bits_rejected():
    bits = dsc.symbol_to_bits(42)
    bad = bits[:7] + format((dsc.check_bits(42) + 1) % 8, "03b")
    with pytest.raises(ValueError):
        dsc.bits_to_symbol(bad)


# ── Table 2 숫자 묶기 ────────────────────────────────────────────────
def test_mmsi_packs_into_five_symbols_with_trailing_zero():
    """§5.2 Note 1 — (M,I)(D,X4)(X5,X6)(X7,X8)(X9,0). 10번째 자리는 0 이다."""
    assert dsc.encode_mmsi("440123456") == [44, 1, 23, 45, 60]


def test_mmsi_must_be_nine_digits():
    for bad in ("12345", "44012345a", "4401234567"):
        with pytest.raises(ValueError):
            dsc.encode_mmsi(bad)


# ── §8.1.2 조난 좌표 ─────────────────────────────────────────────────
def test_position_is_quadrant_then_lat_then_lon():
    """§8.1.2 — 사분면 1자리 + 위도 도분 4자리 + 경도 도분 5자리."""
    # 35.1234567 -> 35도 07분,  129.7654321 -> 129도 45분,  NE -> 0
    assert dsc.encode_position(35.1234567, 129.7654321) == [3, 50, 71, 29, 45]
    assert "".join(f"{s:02d}" for s in
                   dsc.encode_position(35.1234567, 129.7654321)) == "0350712945"


@pytest.mark.parametrize("lat,lon,first_digit", [
    (35.1, 129.7, "0"),     # NE §8.1.2.1.1
    (35.1, -70.2, "1"),     # NW §8.1.2.1.2
    (-33.8, 151.2, "2"),    # SE §8.1.2.1.3
    (-33.8, -70.6, "3"),    # SW §8.1.2.1.4
])
def test_quadrant_digit(lat, lon, first_digit):
    digits = "".join(f"{s:02d}" for s in dsc.encode_position(lat, lon))
    assert digits[0] == first_digit


def test_minutes_are_truncated_not_rounded():
    """🔴 반올림하면 59.7분이 60분이 되어 도가 하나 밀린다. 60해리가 틀어진다."""
    digits = "".join(f"{s:02d}" for s in dsc.encode_position(35.995, 129.0))
    assert digits[1:5] == "3559"        # 35도 59.7분 -> 35도 59분


def test_unknown_position_is_ten_nines():
    """§8.1.2.4 — 좌표를 넣을 수 없으면 숫자 9 를 열 번."""
    assert dsc.encode_position(None, None) == [99, 99, 99, 99, 99]


def test_unknown_time_is_8888():
    """§8.1.3.3"""
    assert dsc.encode_time(None, None) == [88, 88]


def test_time_range_checked():
    with pytest.raises(ValueError):
        dsc.encode_time(24, 0)
    with pytest.raises(ValueError):
        dsc.encode_time(0, 60)


# ── Table 4.1 조난 경보 구성 ─────────────────────────────────────────
def test_distress_alert_body_layout():
    """자기식별(5) · 성격(1) · 좌표(5) · 시각(2) · 후속통신(1) = 14 문자."""
    c = call()
    assert len(c.body) == 14
    assert c.body[0:5] == (44, 1, 23, 45, 60)               # 자기식별
    assert c.body[5] == dsc.Nature.MAN_OVERBOARD == 110     # 성격
    assert c.body[6:11] == (3, 50, 71, 29, 45)              # 좌표
    assert c.body[11:13] == (14, 30)                        # 시각
    assert c.body[13] == dsc.Telecommand1.F3E_G3E_ALL_MODES_TP  # 후속통신


def test_format_specifier_is_112():
    """§4.1.1 — 조난 경보의 형식지정자는 심볼 112."""
    assert call().format_specifier == dsc.Format.DISTRESS == 112


def test_format_specifier_sent_twice_in_dx():
    """Table 4.1 — 형식지정자는 2개 동일."""
    dx = call().dx_stream()
    assert dx[0] == dx[1] == 112


def test_eos_is_127_not_117():
    """🔴 §9.1 — 117(Ack RQ)은 개별·자동 호출 전용이다. 조난 경보는 §9.3 의 127."""
    assert call().eos == dsc.EOS.OTHER == 127


def test_distress_alert_has_no_category_character():
    """§6.2 — 조난 경보는 형식지정자가 우선순위를 정하므로 카테고리를 넣지 않는다."""
    assert int(dsc.Category.DISTRESS) not in call().body


# ── §10 ECC ──────────────────────────────────────────────────────────
def test_ecc_is_xor_of_information_characters():
    """§10.2 — 정보문자 7비트의 짝수 수직 패리티."""
    c = call()
    assert c.ecc == reduce(xor, c.information)


def test_ecc_counts_format_specifier_exactly_once():
    """🔴 §10.2 — 형식지정자와 EOS 는 각각 하나만 쓴다.

    두 번 넣으면 XOR 이라 서로 상쇄돼 형식지정자가 빠진 것과 같아진다.
    실제로 이 버그를 냈다가 잡았다.
    """
    c = call()
    assert c.information.count(112) == 1
    assert c.information.count(127) == 1
    # 두 번 넣었을 때의 값과 달라야 한다
    assert c.ecc != reduce(xor, (112, *c.information))


def test_ecc_excludes_phasing_and_rx():
    """§10.2 — phasing 과 RX 재전송은 정보문자가 아니다.

    ⚠ 심볼 **번호로는 구별할 수 없다.** Table 3 은 100~127 을 열마다 재사용한다 —
      110 은 RX phasing 이면서 동시에 조난성격 '익수자'다. 뜻을 정하는 것은
      번호가 아니라 **호출 안에서의 위치**다. 그래서 개수로 확인한다.
    """
    c = call()
    assert c.information == (c.format_specifier, *c.body, c.eos)
    assert len(c.information) == len(c.body) + 2
    # 실제 송신 심볼은 phasing 14개와 RX 재전송이 더 붙어 훨씬 길다
    assert len(c.symbols()) > 2 * len(c.information)


# ── §3 phasing ───────────────────────────────────────────────────────
def test_phasing_has_six_dx_characters():
    """§3.2 — DX 위치에 6개."""
    syms = call().symbols()
    assert syms[:12:2] == [dsc.PHASING_DX] * 6


def test_phasing_rx_counts_down_from_111_to_104():
    """§3.2.2 — RX phasing 은 111,110,...,104 순서다. 104 가 RX-0."""
    syms = call().symbols()
    assert syms[1:12:2] == [111, 110, 109, 108, 107, 106]
    assert syms[13] == 105
    assert syms[15] == 104


def test_information_starts_right_after_phasing_dx():
    syms = call().symbols()
    assert syms[12] == 112      # 첫 정보문자 = 형식지정자


# ── §1.2 시간분산 ────────────────────────────────────────────────────
def test_rx_repeats_dx_five_positions_later():
    """🔴 §1.2.1 — DX 뒤 다른 문자 4개가 지난 뒤 같은 문자를 다시 보낸다."""
    syms = call().symbols()
    base = 12
    for p in range(base + dsc.DX_RX_OFFSET, len(syms), 2):
        assert syms[p] == syms[p - dsc.DX_RX_OFFSET], f"위치 {p}"


def test_eos_three_times_in_dx_once_in_rx():
    """§9 — EOS 는 DX 위치에 세 번, RX 위치에 한 번."""
    syms = call().symbols()
    base = 12
    assert syms[base::2].count(127) == 3
    assert syms[base + 1::2].count(127) == 1


def test_ecc_once_in_dx_and_once_in_rx():
    """§10.2 — ECC 도 DX 와 RX 양쪽에 실린다."""
    c = call()
    syms = c.symbols()
    base = 12
    assert syms[base::2].count(c.ecc) == 1
    assert syms[base + 1::2].count(c.ecc) == 1


# ── §3.4 점 패턴 ─────────────────────────────────────────────────────
def test_dot_pattern_lengths():
    """§3.4.1 HF/MF 조난 200비트, §3.4.2 VHF 20비트."""
    assert dsc.DOT_PATTERN_BITS_HFMF_DISTRESS == 200
    assert dsc.DOT_PATTERN_BITS_VHF == 20
    c = call()
    n = len(c.symbols())
    assert len(c.bits(dot_pattern_bits=20)) == 20 + n * 10
    assert len(c.bits(dot_pattern_bits=200)) == 200 + n * 10


def test_dot_pattern_alternates():
    """교번 B-Y 신호다."""
    bits = call().bits(dot_pattern_bits=20)
    assert bits[:20] == "01" * 10


def test_full_bitstream_round_trips_to_symbols():
    c = call()
    syms = c.symbols()
    bits = c.bits(dot_pattern_bits=20)[20:]
    assert [dsc.bits_to_symbol(bits[p:p + 10]) for p in range(0, len(bits), 10)] == syms


# ── Nature 표 (Table 3) ──────────────────────────────────────────────
def test_nature_values_match_table_3():
    assert dsc.Nature.FIRE == 100
    assert dsc.Nature.MAN_OVERBOARD == 110
    assert dsc.Nature.EPIRB_EMISSION == 112


def test_111_is_not_a_nature_value():
    """🔴 Table 3 에 111 은 없다. EPIRB 는 112 다.

    `database/pi.sql` 의 `CHECK (report_dsc BETWEEN 100 AND 111)` 은 111 을 허용하고
    112 를 막는다 — 규격과 어긋난다. 스키마를 손볼 때 같이 고칠 것.
    """
    assert 111 not in {int(n) for n in dsc.Nature}

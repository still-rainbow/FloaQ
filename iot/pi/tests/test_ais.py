"""ITU-R M.1371 규격 준수 시험.

메시지 계층(비트 배치)과 링크 계층(CRC·스터핑·NRZI)을 나눠 본다.
상호운용 확인은 `test_nmea.py` 가 따로 한다.

근거: Recommendation ITU-R M.1371-5, Annex 2 §3.2 · Annex 8
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.protocols import ais

MOB_MMSI = "972123456"
SART_MMSI = "970123456"
LAT, LON = 35.1234567, 129.7654321


def fields(bits: str) -> dict:
    """Table 45 의 비트 배치대로 되읽는다. 시험 쪽에 따로 적어 구현과 맞대본다."""
    def uu(a, b):
        return int(bits[a:b], 2)

    def ii(a, b):
        raw, width = int(bits[a:b], 2), b - a
        return raw - (1 << width) if raw & (1 << (width - 1)) else raw

    return {
        "type": uu(0, 6), "repeat": uu(6, 8), "mmsi": uu(8, 38),
        "nav_status": uu(38, 42), "rot": ii(42, 50), "sog": uu(50, 60),
        "accuracy": uu(60, 61),
        "lon": ii(61, 89) / ais.COORD_SCALE, "lat": ii(89, 116) / ais.COORD_SCALE,
        "cog": uu(116, 128), "heading": uu(128, 137), "second": uu(137, 143),
        "raim": uu(148, 149),
    }


# ── 메시지 1 ─────────────────────────────────────────────────────────
def test_message_1_is_168_bits():
    """Annex 2 §3.2 — 기본 전송 패킷의 데이터가 168비트."""
    assert len(ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)) == 168
    assert ais.DEFAULT_PACKET_BITS == 168


def test_message_1_field_layout():
    f = fields(ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON, second=42))
    assert f["type"] == 1
    assert f["mmsi"] == 972123456
    assert f["second"] == 42
    assert abs(f["lat"] - LAT) < 1e-5
    assert abs(f["lon"] - LON) < 1e-5


def test_longitude_comes_before_latitude_and_is_wider():
    """🔴 경도 28비트가 위도 27비트보다 **앞**이다. 바꿔 넣으면 값이 잘린다."""
    assert ais.LON_BITS == 28
    assert ais.LAT_BITS == 27
    # 경도만 바꾸면 위도 비트는 그대로여야 한다
    a = ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)
    b = ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=-LON)
    assert a[89:116] == b[89:116]
    assert a[61:89] != b[61:89]


@pytest.mark.parametrize("lat,lon", [
    (-33.8688, 151.2093),    # 남반구 동경
    (-33.4489, -70.6693),    # 남반구 서경
    (64.1466, -21.9426),     # 북반구 서경
    (0.0, 0.0),
])
def test_two_complement_coordinates_all_hemispheres(lat, lon):
    """🔴 2의 보수를 틀리면 남위·서경이 지구 반대편에 찍힌다."""
    f = fields(ais.message_1(mmsi=MOB_MMSI, lat=lat, lon=lon))
    assert abs(f["lat"] - lat) < 1e-5
    assert abs(f["lon"] - lon) < 1e-5


def test_coordinate_scale_is_ten_thousandths_of_a_minute():
    """1/10000 분 = 십진도 x 600000."""
    assert ais.COORD_SCALE == 600000
    f = fields(ais.message_1(mmsi=MOB_MMSI, lat=1 / 600000, lon=0))
    assert abs(f["lat"] - 1 / 600000) < 1e-9


def test_nav_status_14_means_sart_active():
    """🔴 AIS-SART / MOB / EPIRB 는 별도 메시지가 없다. 항행상태 14 가 표시다."""
    assert ais.NavStatus.SART_ACTIVE == 14
    assert fields(ais.mob_position(mmsi=MOB_MMSI, lat=LAT, lon=LON))["nav_status"] == 14
    assert fields(ais.sart_position(mmsi=SART_MMSI, lat=LAT, lon=LON))["nav_status"] == 14


def test_not_available_defaults():
    f = fields(ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON))
    assert f["sog"] == ais.SOG_NOT_AVAILABLE == 1023
    assert f["cog"] == ais.COG_NOT_AVAILABLE == 3600
    assert f["heading"] == ais.HEADING_NOT_AVAILABLE == 511
    assert f["second"] == ais.TIMESTAMP_NOT_AVAILABLE == 60
    assert f["rot"] == ais.ROT_NOT_AVAILABLE == -128


def test_mmsi_prefix_enforced():
    """장치 종류를 MMSI 접두로 구분한다. 틀리면 수신기가 다르게 처리한다."""
    assert ais.MMSI_PREFIX_MOB == "972"
    assert ais.MMSI_PREFIX_SART == "970"
    with pytest.raises(ValueError):
        ais.mob_position(mmsi=SART_MMSI, lat=LAT, lon=LON)
    with pytest.raises(ValueError):
        ais.sart_position(mmsi=MOB_MMSI, lat=LAT, lon=LON)


# ── 메시지 14 ────────────────────────────────────────────────────────
def test_message_14_layout_and_text():
    bits = ais.message_14(mmsi=MOB_MMSI, text=ais.TEXT_MOB_ACTIVE)
    assert int(bits[0:6], 2) == 14
    assert int(bits[8:38], 2) == 972123456
    assert int(bits[38:40], 2) == 0                 # 예비
    assert ais.decode_text(bits[40:]) == "MOB ACTIVE"


def test_regulated_texts():
    """규격이 문구까지 정한다. 임의로 바꾸면 수신기가 MOB 로 인식하지 않는다."""
    assert ais.TEXT_MOB_ACTIVE == "MOB ACTIVE"
    assert ais.TEXT_SART_ACTIVE == "SART ACTIVE"
    assert ais.TEXT_MOB_TEST == "MOB TEST"
    assert ais.TEXT_SART_TEST == "SART TEST"


def test_six_bit_text_round_trip():
    for t in ("MOB ACTIVE", "SART TEST", "A1 B2 C3", "@[]^_?<>"):
        assert ais.decode_text(ais.encode_text(t)) == t


def test_unknown_characters_become_space_not_exception():
    """조난 신고가 인코딩 예외로 막히면 안 된다."""
    # 6자 -> M O B + 공백 3개. 탭과 한글이 각각 공백 하나로 바뀐다
    assert ais.decode_text(ais.encode_text("MOB\t안녕")) == "MOB   "


def test_message_14_length_limit():
    with pytest.raises(ValueError):
        ais.message_14(mmsi=MOB_MMSI, text="X" * 162)


# ── 링크 계층 (Annex 2 §3.2) ─────────────────────────────────────────
def test_training_sequence_is_24_alternating_bits():
    assert ais.TRAINING_SEQUENCE == "01" * 12
    assert len(ais.TRAINING_SEQUENCE) == 24


def test_hdlc_flag_is_7e():
    assert ais.HDLC_FLAG == "01111110"
    assert int(ais.HDLC_FLAG, 2) == 0x7E


def test_bit_stuffing_inserts_zero_after_five_ones():
    """§3.2.2.4 — 1 이 다섯 번 연속되면 0 을 끼운다."""
    assert ais.bit_stuff("11111") == "111110"
    assert ais.bit_stuff("111110") == "1111100"
    assert ais.bit_stuff("0000") == "0000"


def test_bit_stuffing_round_trip():
    for s in ("1" * 20, "0" * 20, "1111101111011110", "101010111110111110"):
        assert ais.bit_unstuff(ais.bit_stuff(s)) == s


def test_flag_itself_is_never_stuffed():
    """플래그는 1 이 여섯 개지만 스터핑하지 않는다. 그래야 경계로 쓸 수 있다."""
    frame = ais.LinkFrame(ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON))
    raw = frame.bits(nrzi=False)
    body = raw[len(ais.TRAINING_SEQUENCE):]
    assert body.startswith(ais.HDLC_FLAG)
    assert body[len(ais.HDLC_FLAG):].find(ais.HDLC_FLAG) > 0     # 종료 플래그도 그대로


def test_nrzi_transitions_on_zero_not_one():
    """🔴 방향이 직관과 반대다. 0 에서 레벨이 바뀌고 1 에서 유지된다."""
    assert ais.nrzi_encode("1111") == "0000"       # 유지
    assert ais.nrzi_encode("0000") == "1010"       # 매번 전이


def test_nrzi_round_trip():
    for s in ("1010101100011110", "0" * 16, "1" * 16):
        assert ais.nrzi_decode(ais.nrzi_encode(s)) == s


def test_crc_is_preset_to_ones():
    """FCS 는 계산 시작 시 전부 1 로 예치한다 (ISO/IEC 3309)."""
    assert ais.crc16_ccitt("") == 0x0000            # 0xFFFF ^ 0xFFFF


def test_crc_detects_single_bit_flip():
    bits = ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)
    flipped = bits[:50] + ("0" if bits[50] == "1" else "1") + bits[51:]
    assert ais.crc16_ccitt(bits) != ais.crc16_ccitt(flipped)


def test_link_frame_structure():
    """훈련열 · 시작플래그 · [데이터+FCS] 스터핑 · 종료플래그 · 버퍼"""
    payload = ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)
    raw = ais.LinkFrame(payload).bits(nrzi=False, buffer_bits=24)
    assert raw.startswith(ais.TRAINING_SEQUENCE + ais.HDLC_FLAG)
    assert raw.endswith(ais.HDLC_FLAG + "0" * 24)
    # 스터핑 때문에 168+16 보다 길거나 같다
    inner = raw[24 + 8:-(8 + 24)]
    assert len(inner) >= 168 + 16
    assert ais.bit_unstuff(inner)[:168] == payload


def test_fcs_is_sent_lsb_first():
    """🔴 FCS 는 LSB 먼저 실린다. MSB 먼저 넣으면 수신기가 전부 버린다."""
    payload = ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)
    frame = ais.LinkFrame(payload)
    inner = ais.bit_unstuff(frame.bits(nrzi=False)[32:-32])
    fcs_bits = inner[168:184]
    assert int(fcs_bits[::-1], 2) == frame.fcs()

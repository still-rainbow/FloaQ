"""NMEA 0183 직렬화 + 상호운용 시험.

두 가지를 나눠서 본다.

    직렬화   규격 계층의 값이 문장 필드로 정확히 옮겨졌는가
    상호운용 실제 수신 소프트웨어가 그 문장을 어떻게 읽는가

상호운용 쪽은 **OpenCPN 의 디코더를 그대로 옮겨 와서** 역산한다. 규격을 OpenCPN 에
맞추는 것이 아니라, 규격대로 만든 문장이 실제 수신기에서 어떻게 보이는지 확인하는
것이다. 시연장에서 "안 뜬다"를 여기서 잡는다.

근거
    OpenCPN model/src/ais_decoder.cpp  ProcessDSx()
    gpsd AIVDM/AIVDO Protocol Decoding
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.adapters import nmea
from floaq.protocols import ais, dsc

MMSI = "440123456"
MOB_MMSI = "972123456"
LAT, LON = 35.1234567, 129.7654321


# ── 상호운용: OpenCPN 디코더 이식 ────────────────────────────────────
def opencpn_decode_dsc(line: str) -> dict:
    """`ProcessDSx()` 의 DSC 분기를 그대로 옮긴 것. 고치지 않는다."""
    tok = line.strip().split("*")[0].split(",")
    fmt = int(tok[1])
    mmsi = int(tok[2][:9]) if fmt in (12, 16) else 0 - int(float(tok[2]) / 10)
    nature = int(tok[4]) if tok[4] != "" else 99
    tmp = float(tok[6])

    quadrant = int(tmp / 1000000000.0)
    if quadrant > 3:                       # "위치 불명" 또는 9999999999
        return {"fmt": fmt, "mmsi": mmsi, "nature": nature, "pos": None}

    lat = int(tmp / 100000.0)
    lon = tmp - lat * 100000.0
    lat = lat - quadrant * 10000
    d = int(lat / 100.0)
    lat = d + (lat - d * 100.0) / 60.0
    d = int(lon / 100.0)
    lon = d + (lon - d * 100.0) / 60.0
    if quadrant == 1:
        lon = -lon
    elif quadrant == 2:
        lat = -lat
    elif quadrant == 3:
        lat, lon = -lat, -lon
    return {"fmt": fmt, "mmsi": mmsi, "nature": nature, "pos": (lat, lon)}


def opencpn_decode_dse(line: str) -> tuple[float, float]:
    tok = line.strip().split("*")[0].split(",")
    rest = tok[5:]
    for i in range(0, len(rest) - 1, 2):
        if rest[i] == "00":
            tmp = float(rest[i + 1])
            lat = int(tmp / 10000.0)
            lon = int(tmp - lat * 10000.0)
            return lat / 600000.0, lon / 600000.0
    raise AssertionError("DSE 에 위치 심볼 00 이 없다")


def opencpn_apply_dse(pos, dse):
    lat, lon = pos
    dlat, dlon = dse
    return (lat + (dlat if lat >= 0 else -dlat),
            lon + (dlon if lon >= 0 else -dlon))


def decode_aivdm(line: str) -> dict:
    tok = line.strip().split("*")[0].split(",")
    bits = nmea.dearmor(tok[5], int(tok[6]))
    out = {"type": int(bits[0:6], 2), "mmsi": int(bits[8:38], 2), "bits": len(bits)}
    if out["type"] == 1:
        out["nav_status"] = int(bits[38:42], 2)

        def s(a, b):
            raw, w = int(bits[a:b], 2), b - a
            return raw - (1 << w) if raw & (1 << (w - 1)) else raw

        out["lon"] = s(61, 89) / 600000.0
        out["lat"] = s(89, 116) / 600000.0
    elif out["type"] == 14:
        out["text"] = ais.decode_text(bits[40:])
    return out


def distress(**kw) -> tuple[str, ...]:
    base = dict(mmsi=MMSI, nature=int(dsc.Nature.MAN_OVERBOARD),
                lat=LAT, lon=LON, hour=14, minute=30)
    return nmea.dsc_distress_sentences(**{**base, **kw})


# ── 체크섬 ───────────────────────────────────────────────────────────
def test_checksum_matches_known_gpsd_sample():
    """외부 기준으로 검증. gpsd 문서의 예제 문장이다."""
    assert nmea.checksum("AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0") == "5C"


def test_dearmor_known_sample_gives_known_mmsi():
    got = decode_aivdm("!AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C")
    assert got["type"] == 1 and got["mmsi"] == 477553000


def test_sentences_end_with_crlf():
    for s in distress():
        assert s.endswith("\r\n")


def test_armor_round_trip():
    for bits in ("0" * 168, "1" * 168, ais.message_1(mmsi=MOB_MMSI, lat=LAT, lon=LON)):
        payload, fill = nmea.armor(bits)
        assert nmea.dearmor(payload, fill) == bits


# ── DSC 직렬화 ───────────────────────────────────────────────────────
def test_numeric_fields_are_symbol_minus_100():
    """🔴 NMEA 숫자 필드는 M.493 심볼에서 100 을 뺀 값이다.

    형식지정자 112 -> 12, 조난성격 110 -> 10, 후속통신 100 -> 00.
    `pi_accident.report_dsc`(110)을 그대로 넣으면 수신기가 종류를 못 읽는다.
    """
    tok = distress()[0].split("*")[0].split(",")
    assert tok[1] == "12"        # 112 조난
    assert tok[3] == "12"        # 112 카테고리 조난
    assert tok[4] == "10"        # 110 익수자
    assert tok[5] == "00"        # 100 F3E/G3E TP
    assert nmea.SYMBOL_OFFSET == 100


def test_mmsi_field_is_ten_digits():
    """M.493 §5.2 의 (X9,0) 규칙대로 10자리로 내보낸다. 수신 측이 앞 9자리를 취한다."""
    tok = distress()[0].split(",")
    assert tok[2] == MMSI + "0"
    assert len(tok[2]) == 10


def test_acknowledgement_field_maps_from_eos():
    """EOS 127(그 외) -> 'S'. 조난 경보가 여기 해당한다."""
    assert distress()[0].split("*")[0].split(",")[10] == "S"


def test_expansion_indicator_set_only_when_position_known():
    assert distress()[0].split("*")[0].split(",")[11] == "E"
    only = distress(lat=None, lon=None)
    assert only[0].split("*")[0].split(",")[11] == ""
    assert len(only) == 1                       # 위치가 없으면 DSE 도 안 보낸다


def test_unknown_position_field_is_ten_nines():
    tok = distress(lat=None, lon=None)[0].split(",")
    assert tok[6] == "9999999999"


# ── DSC 상호운용 ─────────────────────────────────────────────────────
def test_opencpn_reads_it_as_distress():
    got = opencpn_decode_dsc(distress()[0])
    assert got["fmt"] == 12                 # "DISTRESS {mmsi}" 로 표시된다
    assert got["mmsi"] == 440123456
    assert got["nature"] == 10              # GetNatureofDistress(10) = Man overboard


def test_dsc_alone_is_coarse_by_design():
    """M.493 §8.1.2 는 분을 정수로만 싣는다. 1분 = 약 1.85km 오차가 규격상 정상이다."""
    lat, lon = opencpn_decode_dsc(distress()[0])["pos"]
    assert abs(lat - LAT) < 1 / 60
    assert abs(lon - LON) < 1 / 60


def test_dsc_plus_dse_recovers_position_precisely():
    """🔴 시연의 핵심. DSE 까지 적용하면 실제 좌표로 수렴한다."""
    d, e = distress()
    pos = opencpn_apply_dse(opencpn_decode_dsc(d)["pos"], opencpn_decode_dse(e))
    assert abs(pos[0] - LAT) < 1e-5
    assert abs(pos[1] - LON) < 1e-5


@pytest.mark.parametrize("lat,lon", [
    (35.1234567, 129.7654321),
    (35.1234567, -70.2345678),
    (-33.8765432, 151.2345678),
    (-33.8765432, -70.6543210),
])
def test_all_quadrants_recover(lat, lon):
    """사분면 부호를 틀리면 지구 반대편에 찍힌다."""
    d, e = distress(lat=lat, lon=lon)
    pos = opencpn_apply_dse(opencpn_decode_dsc(d)["pos"], opencpn_decode_dse(e))
    assert abs(pos[0] - lat) < 1e-5
    assert abs(pos[1] - lon) < 1e-5


def test_unknown_position_is_not_plotted_by_receiver():
    """사분면이 9 라 3 을 넘는다. 수신기가 표적을 만들지 않는다."""
    assert opencpn_decode_dsc(distress(lat=None, lon=None)[0])["pos"] is None


# ── AIS 직렬화·상호운용 ──────────────────────────────────────────────
def test_aivdm_wraps_message_1():
    line = nmea.ais_mob_sentences(mmsi=MOB_MMSI, lat=LAT, lon=LON, second=42)[0]
    assert line.startswith("!AIVDM,1,1,,A,")
    got = decode_aivdm(line)
    assert got["type"] == 1 and got["bits"] == 168
    assert got["mmsi"] == 972123456
    assert got["nav_status"] == 14
    assert abs(got["lat"] - LAT) < 1e-5
    assert abs(got["lon"] - LON) < 1e-5


def test_message_1_needs_no_fill_bits():
    """168 은 6의 배수라 fill 이 0 이다."""
    line = nmea.ais_mob_sentences(mmsi=MOB_MMSI, lat=LAT, lon=LON)[0]
    assert line.split("*")[0].split(",")[6] == "0"


def test_mob_text_sentence():
    lines = nmea.ais_mob_sentences(mmsi=MOB_MMSI, lat=LAT, lon=LON, with_text=True)
    assert len(lines) == 2
    got = decode_aivdm(lines[1])
    assert got["type"] == 14
    assert got["text"] == "MOB ACTIVE"


def test_sart_sentences():
    lines = nmea.ais_sart_sentences(mmsi="970123456", lat=LAT, lon=LON, with_text=True)
    assert decode_aivdm(lines[0])["nav_status"] == 14
    assert decode_aivdm(lines[1])["text"] == "SART ACTIVE"


def test_channel_field():
    a = nmea.ais_mob_sentences(mmsi=MOB_MMSI, lat=LAT, lon=LON, channel="A")[0]
    b = nmea.ais_mob_sentences(mmsi=MOB_MMSI, lat=LAT, lon=LON, channel="B")[0]
    assert a.split(",")[4] == "A"
    assert b.split(",")[4] == "B"

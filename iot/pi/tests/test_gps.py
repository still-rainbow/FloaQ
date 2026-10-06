"""배 GPS 시험. NMEA `$xxRMC` 파서와 시계.

여기 걸린 것 넷이 전부 **조용히 틀리는** 종류다. 시험이 없으면 좌표가 5.7km
어긋난 채로 시연까지 간다.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq import config
from floaq.adapters import gps

#: NMEA 0183 규격 문서의 예제 문장.
SPEC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"


def test_spec_example_parses():
    """외부 기준으로 검증. 규격 문서 예제 그대로다."""
    f = gps.parse_rmc(SPEC)
    assert f is not None
    assert f.valid is True
    assert f.sog_knots == 22.4
    assert f.cog_deg == 84.4


# ── 🔴 함정 ① 토커 ID ───────────────────────────────────────────────
@pytest.mark.parametrize("talker", ["GP", "GN", "GL", "GA", "BD"])
def test_all_talker_ids_accepted(talker):
    """🔴 `$GP` 로 고정하면 요즘 수신기($GNRMC)에서 한 줄도 안 잡힌다."""
    body = SPEC[1:].split("*")[0].replace("GPRMC", f"{talker}RMC", 1)
    line = f"${body}*{gps._checksum(body)}"
    assert gps.parse_rmc(line) is not None


def test_non_rmc_sentence_ignored():
    """조난 신고를 같은 UDP 포트로 내보내면 되돌아온다. 흘려야 한다."""
    assert gps.parse_rmc("$CDDSC,12,4401234560,12,10,00,0350712945,0620,,,S,E*61") is None
    assert gps.parse_rmc("!AIVDM,1,1,,A,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C") is None
    assert gps.parse_rmc("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,,,,*47") is None


# ── 🔴 함정 ② 좌표 형식 ─────────────────────────────────────────────
def test_coordinates_are_degrees_and_minutes_not_decimal():
    """🔴 `4807.038` 은 48.07도가 아니라 48도 07.038분 = 48.1173도.

    그냥 float() 하면 약 5.7km 틀어진다.
    """
    f = gps.parse_rmc(SPEC)
    assert abs(f.lat - (48 + 7.038 / 60)) < 1e-9
    assert abs(f.lat - 48.1173) < 1e-4
    assert f.lat != pytest.approx(48.07038, abs=1e-4)      # 잘못 짰을 때의 값


def test_longitude_has_three_degree_digits():
    """경도는 `dddmm.mmmm` 라 자릿수가 하나 많다."""
    f = gps.parse_rmc(SPEC)
    assert abs(f.lon - (11 + 31.0 / 60)) < 1e-9


@pytest.mark.parametrize("lat_h,lon_h,lat_sign,lon_sign", [
    ("N", "E", 1, 1), ("S", "E", -1, 1), ("N", "W", 1, -1), ("S", "W", -1, -1),
])
def test_hemispheres(lat_h, lon_h, lat_sign, lon_sign):
    body = f"GNRMC,123519,A,4807.038,{lat_h},01131.000,{lon_h},0.0,0.0,230394,,"
    f = gps.parse_rmc(f"${body}*{gps._checksum(body)}")
    assert (f.lat > 0) == (lat_sign > 0)
    assert (f.lon > 0) == (lon_sign > 0)


# ── 🔴 함정 ③ 상태 필드 ─────────────────────────────────────────────
def test_status_V_means_no_fix():
    """`V` 면 fix 가 없다. 좌표도 시각도 쓸 수 없다."""
    body = SPEC[1:].split("*")[0].replace(",A,", ",V,", 1)
    f = gps.parse_rmc(f"${body}*{gps._checksum(body)}")
    assert f.valid is False


# ── 🔴 함정 ④ 2자리 연도 ────────────────────────────────────────────
def test_two_digit_year_is_2000s():
    """🔴 연도가 2자리다. `230394` 의 `94` 를 2094 로 본다.

    NMEA 0183 이 세기를 주지 않는다. 1900년대로 잡으면 1994년이 되고,
    `config.clock_is_valid` 가 전부 거부해 자동 신고가 아예 멈춘다.
    """
    assert time.gmtime(gps.parse_rmc(SPEC).utc).tm_year == 2094


def test_utc_combines_date_and_time():
    body = "GNRMC,010203,A,4807.038,N,01131.000,E,0.0,0.0,150925,,"
    f = gps.parse_rmc(f"${body}*{gps._checksum(body)}")
    t = time.gmtime(f.utc)
    assert (t.tm_year, t.tm_mon, t.tm_mday) == (2025, 9, 15)
    assert (t.tm_hour, t.tm_min, t.tm_sec) == (1, 2, 3)


# ── 거부 ─────────────────────────────────────────────────────────────
def test_bad_checksum_rejected():
    assert gps.parse_rmc(SPEC[:-2] + "00") is None


def test_truncated_sentence_rejected():
    assert gps.parse_rmc("$GNRMC,123519,A*00") is None


def test_garbage_does_not_raise():
    """수신 경로에서 죽으면 그 뒤 측위를 영영 못 받는다."""
    for junk in ("", "쓰레기", "$", "$GN", "$GNRMC", "$GNRMC*", "\x00\xff"):
        assert gps.parse_rmc(junk) is None


# ── 가짜 소스 ────────────────────────────────────────────────────────
def test_fake_sentence_round_trips():
    """가짜도 실제 문장을 만들어 파서를 거친다. 우회하면 파서 버그가 안 드러난다."""
    fake = gps.FakeGnss(lat=35.1234567, lon=129.7654321, cog=84.4, sog=8.0)
    f = gps.parse_rmc(fake.sentence(1_757_000_000))
    assert f is not None and f.valid
    assert abs(f.lat - 35.1234567) < 1e-5
    assert abs(f.lon - 129.7654321) < 1e-5
    assert f.cog_deg == 84.4


def test_fake_source_produces_fixes():
    fake = gps.FakeGnss()
    fake.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and fake.read() is None:
            time.sleep(0.1)
        assert fake.read() is not None
    finally:
        fake.stop()


# ── 시계 ─────────────────────────────────────────────────────────────
class _Source:
    """fix 를 손으로 넣는 소스. 시계만 따로 본다."""

    def __init__(self, fix=None, age=0.0):
        self._fix, self._age = fix, age

    def read(self):
        return self._fix

    def age(self):
        return self._age


def _fix(utc, valid=True):
    return gps.Fix(lat=35.1, lon=129.0, utc=utc, sog_knots=0.0, cog_deg=0.0, valid=valid)


def test_clock_invalid_without_fix():
    """🔴 시계를 못 믿는 동안 orchestrator 는 자동 전이를 보류한다.

    없으면 전원만 넣어도 신고가 나간다.
    """
    assert gps.GpsClock(_Source(None)).is_valid() is False


def test_clock_invalid_when_status_V():
    c = gps.GpsClock(_Source(_fix(1_800_000_000, valid=False)))
    assert c.is_valid() is False


def test_clock_invalid_when_fix_is_stale():
    """케이블이 빠져도 마지막 fix 는 남아 있다. 나이를 봐야 한다."""
    c = gps.GpsClock(_Source(_fix(1_800_000_000), age=gps.FIX_STALE_SEC + 1))
    assert c.is_valid() is False


def test_clock_rejects_pre_sanity_epoch():
    """부팅 직후의 엉뚱한 값도 걸러낸다."""
    c = gps.GpsClock(_Source(_fix(config.CLOCK_SANITY_MIN_EPOCH - 1)))
    assert c.is_valid() is False


def test_clock_valid_with_fresh_fix():
    c = gps.GpsClock(_Source(_fix(1_800_000_000)))
    assert c.is_valid() is True
    assert abs(c.now() - 1_800_000_000) < 2


def test_clock_keeps_ticking_between_fixes():
    """🔴 RMC 는 1Hz 다. 마지막 fix 의 UTC 를 그대로 주면 `now()` 가 1초씩 멈춘다.

    30초 카운트다운이 그 위에서 돈다.
    """
    src = _Source(_fix(1_800_000_000), age=0.0)
    c = gps.GpsClock(src)
    first = c.now()
    src._age = 0.6                      # fix 는 그대로, 0.6초 지났다
    time.sleep(0.6)
    assert c.now() >= first
    # 같은 fix 인데도 시간이 흘러야 한다
    src._age = 3.0
    time.sleep(0.1)
    assert c.now() > first

# ── 시연 기본 위치 ───────────────────────────────────────────────────
def test_fake_starts_at_busan_offshore():
    """웹 팀 요청 `확정` 2026-09-17 — 화면에 뜰 때 부산 앞바다여야 한다.

    ⚠ 이 좌표는 오륙도 남동쪽 약 5km 의 **물 위**다. 육지 좌표로 바꾸면
      해도에서 배가 산 위에 뜬다.
    """
    g = gps.FakeGnss()
    assert (g.lat, g.lon) == gps.BUSAN_OFFSHORE
    assert 34.9 < g.lat < 35.3 and 128.9 < g.lon < 129.3


def test_fake_speed_matches_actual_movement():
    """🔴 문장이 말하는 `sog` 와 실제 이동량이 같아야 한다.

    예전에는 위경도에 고정 증분을 더하면서 sog 는 8.0 을 싣고 있었다 — 실제로는
    약 1.8kn 이었다. Jetson 이 `speed_kn` 으로 착수 시점의 배 위치를 예측하므로
    (DES-38 §5) 어긋나면 조준이 빗나간다. 조용히 틀리는 종류라 시험으로 고정한다.
    """
    g = gps.FakeGnss(sog=12.0, cog=90.0)
    lat0, lon0 = g.lat, g.lon
    for _ in range(60):
        g._advance(1.0)

    metres = math.hypot((g.lat - lat0) * 111_132.0,
                        (g.lon - lon0) * 111_320.0 * math.cos(math.radians(g.lat)))
    assert abs(metres / 60.0 / 0.514444 - 12.0) < 0.05
    # cog 90 = 정동. 위도는 거의 안 움직인다
    assert abs(g.lat - lat0) < 1e-6
    assert g.lon > lon0


def test_fake_movement_survives_round_trip():
    """이동한 좌표가 문장 -> 파서를 거쳐도 같아야 한다. dm 변환이 도를 넘길 때가 위험하다."""
    g = gps.FakeGnss(lat=35.0499, lon=128.9999, sog=20.0, cog=45.0)
    for _ in range(300):
        g._advance(1.0)
    fix = gps.parse_rmc(g.sentence().strip())
    assert fix is not None
    assert abs(fix.lat - g.lat) < 1e-4
    assert abs(fix.lon - g.lon) < 1e-4

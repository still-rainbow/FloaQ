"""표류 추정 시험. **관제와 같은 값이 나오는가가 전부다.**

「Pi ↔ 관제 표류 위치 추정 공통 구현 명세」의 절 번호를 그대로 단다. 여기서
숫자를 고치려면 문서와 관제 쪽을 같이 고쳐야 한다 — 한쪽만 바꾸면 두 시스템이
다른 답을 내고, 그걸 알아챌 방법이 없다.

⚠ 여기 있는 상수는 **우리가 고른 값이 아니라 합의한 값**이다. "더 맞는 값"을
  알게 돼도 이 파일에서 바꾸지 않는다.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq import drift as D

LAT, LON = 35.05, 129.10
HOUR = 3600.0


def ocean(**kw) -> D.Ocean:
    base = dict(current_speed=None, current_dir=None, current_spread=None,
                wind_speed=None, wind_dir=None, observed_at=1_789_000_000)
    return D.Ocean(**{**base, **kw})


def run(**kw) -> D.Drift:
    base = dict(base_lat=LAT, base_lon=LON, elapsed_sec=HOUR, leeway=D.BUOY)
    return D.estimate(**{**base, **kw})


def offset_m(d: D.Drift) -> tuple[float, float]:
    """중심이 출발점에서 얼마나 갔나. `(동, 북)` 미터."""
    dy = (d.center_lat - LAT) * D._M_PER_DEG_LAT
    dx = (d.center_lon - LON) * D._M_PER_DEG_LON_EQ * math.cos(math.radians(LAT))
    return dx, dy


# ── §2 합의한 상수 ───────────────────────────────────────────────────
def test_leeway_constants_match_the_spec():
    """🔴 이 숫자가 관제와 다르면 두 시스템이 다른 곳을 수색한다."""
    assert (D.BUOY.down, D.BUOY.down_min, D.BUOY.down_max, D.BUOY.cross) == \
        (0.0300, 0.0248, 0.0370, 0.0110)
    assert (D.PERSON.down, D.PERSON.down_min, D.PERSON.down_max, D.PERSON.cross) == \
        (0.0096, 0.0048, 0.0171, 0.0054)


def test_scale_factors_are_the_calibrated_ones_not_gaussian():
    """⚠ 정규분포 이론값이 아니다. 4만 입자로 보정한 값이다 (§6).

    이론값을 "고쳐" 넣으면 관제와 갈린다.
    """
    assert D.SIGMA_SCALE == {50: 1.22, 75: 1.69, 95: 2.36}
    theory = {p: math.sqrt(-2 * math.log(1 - p / 100)) for p in (50, 75, 95)}
    assert D.SIGMA_SCALE[50] > theory[50]      # 꼬리가 얇아 아래가 크다
    assert D.SIGMA_SCALE[95] < theory[95]


def test_position_error_and_time_cap():
    assert D.POSITION_ERROR_M == 50.0
    assert D.MAX_ELAPSED_SEC == 6 * 3600


# ── §2 · §4 풍향 변환 ────────────────────────────────────────────────
def test_wind_from_is_flipped_to_toward():
    """🔴 기상 풍향은 **불어오는** 쪽이다. +180 을 빼먹으면 정확히 반대로 간다.

    중심만 틀리고 타원은 멀쩡해서 화면만 봐서는 못 잡는다.
    """
    # 북풍(from 0) = 남쪽으로 간다
    dx, dy = offset_m(run(ocean=ocean(wind_speed=10.0, wind_dir=0.0)))
    assert dy < 0 and abs(dx) < 1e-6

    # 서풍(from 270) = 동쪽으로 간다
    dx, dy = offset_m(run(ocean=ocean(wind_speed=10.0, wind_dir=270.0)))
    assert dx > 0 and abs(dy) < 1e-6


def test_wind_displacement_uses_the_representative_coefficient():
    """중심은 대푯값(3.00%)이다. 범위의 가운데(3.09%)가 아니다 (§4)."""
    w, t = 10.0, HOUR
    dx, _ = offset_m(run(ocean=ocean(wind_speed=w, wind_dir=270.0), elapsed_sec=t))
    assert dx == pytest.approx(D.BUOY.down * w * t, rel=1e-9)
    # 범위 가운데를 썼다면 이만큼이었을 것 — 그 값이 **아니다**
    mid = (D.BUOY.down_min + D.BUOY.down_max) / 2
    assert dx != pytest.approx(mid * w * t, rel=1e-6)


def test_current_moves_toward_its_direction():
    """해류 방향은 **가는** 방향이다. 풍향과 달리 뒤집지 않는다."""
    dx, dy = offset_m(run(ocean=ocean(current_speed=0.5, current_dir=90.0)))
    assert dx == pytest.approx(0.5 * HOUR, rel=1e-9)
    assert abs(dy) < 1e-6


def test_crosswind_is_not_in_the_center():
    """§4 — crosswind 는 좌우를 모르므로 불확실성에만 들어간다."""
    dx, dy = offset_m(run(ocean=ocean(wind_speed=10.0, wind_dir=270.0)))
    # 동쪽으로만 간다. 남북 성분이 있으면 crosswind 가 중심에 샌 것이다
    assert abs(dy) < 1e-6


def test_person_drifts_less_than_buoy():
    """사람 0.96% vs 부표 3.00%. 3배 넘게 차이난다 — 같은 타원을 쓰면 안 된다."""
    o = ocean(wind_speed=10.0, wind_dir=270.0)
    b, _ = offset_m(run(ocean=o, leeway=D.BUOY))
    p, _ = offset_m(run(ocean=o, leeway=D.PERSON))
    assert p < b
    assert b / p == pytest.approx(D.BUOY.down / D.PERSON.down, rel=1e-9)


# ── §5 공분산 ────────────────────────────────────────────────────────
def test_position_error_alone_is_a_circle():
    """바람도 해류도 방향성이 없으면 타원이 아니라 원이다.

    축당 분산은 반지름 50m 균등 원판의 R²/4 = 625.
    """
    d = run(ocean=ocean(current_speed=0.0, current_dir=0.0), elapsed_sec=1.0)
    assert d.ellipse.major_m == pytest.approx(25.0, rel=1e-6)
    assert d.ellipse.minor_m == pytest.approx(25.0, rel=1e-6)


def test_ellipse_is_widest_across_the_wind_not_along_it():
    """⚠ 직관과 반대다. 타원은 바람 **직각**으로 길다.

    crosswind 는 좌우를 모르므로 [-a, a] 균등이라 분산이 a²/3 이고, downwind
    범위는 폭 w 균등이라 w²/12 다. 부표는 a(1.10%)와 w(1.22%)가 비슷한데
    나누는 수가 4배 차이나서 crosswind 가 3.3배 크다.

    수색은 바람 방향으로 길쭉할 것이라 생각하기 쉽다. 아니다.
    """
    # 서풍 -> 동쪽(90°)으로 간다. 장축은 그 직각인 남북(0°)이다
    d = run(ocean=ocean(wind_speed=12.0, wind_dir=270.0), elapsed_sec=2 * HOUR)
    assert d.ellipse.bearing_deg == pytest.approx(0.0, abs=1.0)
    assert d.ellipse.major_m > d.ellipse.minor_m


def test_bearing_never_comes_back_as_180():
    """🔴 `% 180` 은 각도가 0 바로 아래일 때 반올림으로 **정확히 180.0** 을 낸다.

    DB 의 `axis_bearing_deg` CHECK 와 화면의 0~180 가정을 깬다. 바람이 정확히
    동서남북일 때 Sxy 가 0 근처 음수로 떨어지면서 걸린다 — 시연에서 제일 흔한
    입력이다.
    """
    for from_dir in (0.0, 90.0, 180.0, 270.0):
        e = run(ocean=ocean(wind_speed=12.0, wind_dir=from_dir),
                elapsed_sec=2 * HOUR).ellipse
        assert 0.0 <= e.bearing_deg < 180.0


def test_covariance_matches_monte_carlo():
    """🔴 손으로 조립한 공분산이 실제 분포와 같은가. 여기가 제일 틀리기 쉽다.

    명세의 각 항을 그대로 표본추출해 비교한다. 1% 안에 들어야 한다.
    """
    random.seed(11)
    n, w, v, t = 60_000, 8.0, 0.4, HOUR
    from_dir, cur_dir, spread = 270.0, 45.0, 0.08
    lw, toward = D.BUOY, 90.0

    def draw():
        a = random.random() * 2 * math.pi
        r = D.POSITION_ERROR_M * math.sqrt(random.random())   # 균등 원판
        x, y = r * math.sin(a), r * math.cos(a)
        cv = random.gauss(v, spread / 2)                      # spread/2 = sigma
        rr = math.radians(cur_dir)
        x += cv * t * math.sin(rr); y += cv * t * math.cos(rr)
        dn = random.uniform(lw.down_min, lw.down_max)         # 범위 안 균등
        rr = math.radians(toward)
        x += dn * w * t * math.sin(rr); y += dn * w * t * math.cos(rr)
        cw = random.uniform(-1, 1) * lw.cross * w * t         # 양방향 균등
        rr = math.radians(toward + 90)
        x += cw * math.sin(rr); y += cw * math.cos(rr)
        return x, y

    pts = [draw() for _ in range(n)]
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n

    e = run(elapsed_sec=t, leeway=lw,
            ocean=ocean(current_speed=v, current_dir=cur_dir,
                        current_spread=spread, wind_speed=w,
                        wind_dir=from_dir)).ellipse
    th = math.radians(e.bearing_deg)
    a2, b2 = e.major_m ** 2, e.minor_m ** 2
    ux, uy = math.sin(th), math.cos(th)
    assert a2 * ux * ux + b2 * uy * uy == pytest.approx(sxx, rel=0.03)
    assert a2 * uy * uy + b2 * ux * ux == pytest.approx(syy, rel=0.03)


def test_spread_only_widens_never_moves():
    """주변 격자 차이는 불확실성이다. 중심을 옮기면 안 된다 (§5)."""
    o = dict(current_speed=0.4, current_dir=45.0, wind_speed=6.0, wind_dir=180.0)
    a = run(ocean=ocean(**o))
    b = run(ocean=ocean(**o, current_spread=0.2))
    assert offset_m(a) == pytest.approx(offset_m(b), rel=1e-9)
    assert b.ellipse.major_m > a.ellipse.major_m


def test_missing_spread_just_drops_that_term():
    """§5 — spread 가 없으면 그 항만 뺀다. 추정 자체는 한다."""
    d = run(ocean=ocean(current_speed=0.4, current_dir=45.0))
    assert d.ellipse.major_m > 0


# ── §6 배율 ──────────────────────────────────────────────────────────
def test_ranges_share_one_covariance():
    """세 범위는 같은 타원에 배율만 다르다. 따로 계산하지 않는다."""
    e = run(ocean=ocean(wind_speed=10.0, wind_dir=270.0)).ellipse
    m50, _ = e.at(50)
    m95, _ = e.at(95)
    assert m95 / m50 == pytest.approx(2.36 / 1.22, rel=1e-9)


def test_unknown_percent_fails_loudly():
    e = run(ocean=ocean(wind_speed=10.0, wind_dir=270.0)).ellipse
    with pytest.raises(ValueError):
        e.at(90)


def test_radius_m_is_the_95_major_axis():
    """하위 호환 값. 원으로 그리는 화면이 **과소평가하지 않게** 큰 쪽을 준다."""
    d = run(ocean=ocean(wind_speed=10.0, wind_dir=270.0))
    assert d.radius_m == pytest.approx(d.ellipse.at(95)[0], rel=1e-12)


# ── §7 부표 상태 불명 ────────────────────────────────────────────────
def test_unknown_hold_center_is_between_buoy_and_person():
    """§7 — 중심 down 은 두 대푯값의 평균 1.98% 다."""
    assert D.UNKNOWN.down == pytest.approx((0.0300 + 0.0096) / 2)
    assert D.UNKNOWN.cross == pytest.approx(0.0110)       # max(1.10, 0.54)
    assert (D.UNKNOWN.down_min, D.UNKNOWN.down_max) == (0.0048, 0.0370)


def test_unknown_hold_widens_along_the_wind():
    """두 갈래의 차이가 추가 불확실성으로 들어간다 (splitM²/4)."""
    o = ocean(wind_speed=10.0, wind_dir=270.0)
    a = run(ocean=o, leeway=D.UNKNOWN, elapsed_sec=2 * HOUR)
    b = run(ocean=o, leeway=D.UNKNOWN, elapsed_sec=2 * HOUR, unknown_hold=True)
    assert b.ellipse.major_m > a.ellipse.major_m
    # 중심은 그대로다 — 불확실성만 늘어난다
    assert offset_m(a) == pytest.approx(offset_m(b), rel=1e-9)


def test_split_m_uses_range_midpoints_not_representatives():
    """⚠ 명세가 "둘을 섞지 않는다" 고 못 박은 자리다.

    중심은 대푯값(3.00·0.96), splitM 은 범위 가운데(3.09·1.095)를 쓴다.
    """
    w, t = 10.0, HOUR
    want = ((0.0248 + 0.0370) / 2 - (0.0048 + 0.0171) / 2) * w * t
    assert D._split_m(w, t) == pytest.approx(want, rel=1e-12)


def test_unknown_hold_without_wind_changes_nothing():
    """바람이 없으면 leeway 가 0 이라 갈릴 것도 없다."""
    o = ocean(current_speed=0.4, current_dir=45.0)
    a = run(ocean=o, leeway=D.UNKNOWN)
    b = run(ocean=o, leeway=D.UNKNOWN, unknown_hold=True)
    assert a.ellipse.major_m == pytest.approx(b.ellipse.major_m, rel=1e-12)


# ── §2 결측 · §8 시간 제한 ───────────────────────────────────────────
def test_current_only_and_wind_only_are_labelled():
    """🔴 무엇으로 계산했는지 화면이 말해야 한다. 해류만으로 그린 원과
    둘 다로 그린 원은 화면에서 똑같이 생겼다."""
    assert run(ocean=ocean(current_speed=0.4, current_dir=45.0)).based_on == '해류만'
    assert run(ocean=ocean(wind_speed=8.0, wind_dir=270.0)).based_on == '바람만'
    assert run(ocean=ocean(current_speed=0.4, current_dir=45.0,
                           wind_speed=8.0, wind_dir=270.0)).based_on == '해류·바람'


def test_no_ocean_data_means_no_estimate():
    """§2 — 둘 다 없으면 추정하지 않는다. 0 으로 두고 그리지 않는다."""
    with pytest.raises(ValueError):
        run(ocean=ocean())


def test_half_missing_drops_that_term_only():
    """한쪽만 없으면 없는 쪽을 0 으로 둔다 (§2)."""
    dx, dy = offset_m(run(ocean=ocean(wind_speed=8.0, wind_dir=270.0)))
    assert dx > 0          # 바람 성분은 살아 있다
    assert abs(dy) < 1e-6  # 해류 성분은 0


def test_over_six_hours_refuses():
    """§8 — 조류가 바뀌어 중심 자체가 틀어진다. 그리지 않는 것이 맞다."""
    o = ocean(current_speed=0.4, current_dir=45.0)
    run(ocean=o, elapsed_sec=D.MAX_ELAPSED_SEC)            # 경계는 된다
    with pytest.raises(D.TooLong):
        run(ocean=o, elapsed_sec=D.MAX_ELAPSED_SEC + 1)


def test_zero_elapsed_refuses():
    """§3 — 수신 중이면 타원을 그리지 않는다."""
    with pytest.raises(ValueError):
        run(ocean=ocean(current_speed=0.4, current_dir=45.0), elapsed_sec=0)


# ── 방어 ─────────────────────────────────────────────────────────────
def test_longitude_scales_with_latitude():
    """🔴 경도 1도는 위도에 따라 짧아진다. 적도 기준으로 두면 부산에서 22% 빗나간다."""
    o = ocean(current_speed=1.0, current_dir=90.0)        # 정동
    near = D.estimate(base_lat=0.0, base_lon=0.0, elapsed_sec=HOUR,
                      leeway=D.BUOY, ocean=o)
    far = D.estimate(base_lat=60.0, base_lon=0.0, elapsed_sec=HOUR,
                     leeway=D.BUOY, ocean=o)
    # 같은 거리를 가도 고위도에서 경도 변화가 더 크다
    assert far.center_lon > near.center_lon * 1.9


def test_bearing_is_normalised_to_half_turn():
    """타원은 180° 대칭이다. 방위가 0~180 밖으로 나오면 화면이 뒤집어 그린다."""
    for from_dir in (0.0, 45.0, 90.0, 180.0, 275.0, 359.0):
        e = run(ocean=ocean(wind_speed=9.0, wind_dir=from_dir),
                elapsed_sec=2 * HOUR).ellipse
        assert 0.0 <= e.bearing_deg < 180.0


def test_major_is_never_shorter_than_minor():
    """DB 의 CHECK 와 같은 규칙. 뒤집히면 타원이 90도 돌아간다."""
    random.seed(3)
    for _ in range(50):
        e = run(elapsed_sec=random.uniform(1, D.MAX_ELAPSED_SEC),
                ocean=ocean(current_speed=random.uniform(0, 1),
                            current_dir=random.uniform(0, 360),
                            current_spread=random.choice([None, 0.05, 0.3]),
                            wind_speed=random.uniform(0, 20),
                            wind_dir=random.uniform(0, 360))).ellipse
        assert e.major_m >= e.minor_m > 0

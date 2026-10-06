"""표류 위치 추정. **Pi 와 관제가 같은 값을 내야 한다.**

정본은 웹 팀과 합의한 「Pi ↔ 관제 표류 위치 추정 공통 구현 명세」다. 이 파일은
그 문서를 그대로 옮긴 것이고, **여기서 수식을 고치지 않는다** — 한쪽만 바꾸면
두 시스템이 다른 답을 내고, 네트워크가 끊겼다 붙었을 때 비교할 수가 없다.
그게 문서의 존재 이유다.

    같은 사고 상태 + 같은 출발점 + 같은 경과시간 + 같은 해양 입력
      -> 같은 표류 추정

── 좌표 약속 (§2) ──────────────────────────────────────────────────
북 0°, 시계방향. x = 동, y = 북.

    dx = 거리 * sin(방위)      dy = 거리 * cos(방위)

🔴 **풍향은 from 이다.** 기상 관측의 풍향은 "바람이 불어오는 쪽"이라 이동
   방향으로 쓰려면 +180° 해야 한다. 안 하면 표류가 정확히 반대로 간다 —
   중심이 틀렸는데 타원은 멀쩡해 보여서 화면만 봐서는 모른다.

── 알려진 한계 (문서 §13, 고치지 않는다) ──────────────────────────
⚠ **유향 자체의 불확실성이 빠져 있다.** 해류 항은 주변 격자와의 크기 차이만
  보고 방향 오차를 0 으로 둔다. 유속 0.5m/s 에서 유향이 10° 틀리면 6시간에
  횡방향 1.9km 인데 그만큼이 타원에 안 들어간다 — **수색 범위가 모자라는
  쪽으로** 틀린다. 웹 팀에 보고했고, 양쪽이 같이 넣기로 하면 그때 넣는다.

⚠ **짧은 경과시간에서 §6 배율이 맞지 않는다.** t 가 작으면 위치오차 원판만
  남는데 그건 가우시안이 아니라 균등 원판이다 (50% 는 1.41σ, 문서 배율은 1.22).
  4만 입자 검증은 그 분산 조합에서만 유효하다.

⚠ 조류의 시간 변화, Stokes drift, 관측 지점과 사고 위치의 거리, 해안선,
  두 봉우리로 갈리는 분포는 반영하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

# ── 상수 (§2 · §6 · §8) ─────────────────────────────────────────────

#: 위도 1도의 거리(m). 위도에 따라 거의 안 변한다.
_M_PER_DEG_LAT: Final[float] = 111_132.0
#: 적도에서 경도 1도. cos(위도)를 곱해 쓴다 — 부산에서 22% 짧다.
_M_PER_DEG_LON_EQ: Final[float] = 111_320.0

#: 출발점 위치 오차. 반지름 이만큼의 원 안에 균등하다고 본다 (§5).
#:
#: ⚠ `미정`. 문서 §12 가 "별도 검토" 로 적은 값이고, **짧은 경과시간을 통째로
#:   지배한다** — t=0 에서 50% 타원이 30m 다. 부표 GPS(u-blox NEO-6M)는 CEP
#:   2.5m 급이라 20배 보수적이다. 우리 DB 에 정확도 컬럼이 없어(NMEA RMC 에
#:   오차 필드가 없다) 실측값을 넣을 방법이 지금은 없다.
POSITION_ERROR_M: Final[float] = 50.0

#: 최대 추정 시간 (§8). 이 모델은 그동안 해류·바람이 일정하다고 가정한다.
#: 넘으면 추정하지 않고 마지막 수신 위치만 보여준다.
MAX_ELAPSED_SEC: Final[int] = 6 * 3600

#: 50/75/95% 배율 (§6).
#:
#: ⚠ 정규분포 이론값(1.177 / 1.665 / 2.448)이 **아니다.** 현재 모델을 4만 입자로
#:   검증해 보정한 값이다. 이론보다 아래가 크고 위가 작은 것은 입력이 균등분포라
#:   꼬리가 가우시안보다 얇기 때문이다. **모델이 바뀌면 다시 검증해야 한다.**
SIGMA_SCALE: Final[dict[int, float]] = {50: 1.22, 75: 1.69, 95: 2.36}


@dataclass(frozen=True, slots=True)
class Leeway:
    """풍력 표류 계수. 풍속 대비 비율이다 (§2).

    `down` 은 **대푯값**이다. 범위의 가운데가 아니다 — 문서가 그 둘을 섞지
    말라고 못 박은 자리다.
    """

    #: 바람 방향 성분. 중심 계산에 쓴다
    down: float
    #: 범위 하한·상한. 불확실성에만 쓴다 (중심 아님)
    down_min: float
    down_max: float
    #: 바람 직각 성분. **중심에 안 들어간다** — 좌우를 모르므로 양방향 불확실성이다
    cross: float


#: 부표 (§2)
BUOY: Final[Leeway] = Leeway(down=0.0300, down_min=0.0248, down_max=0.0370,
                             cross=0.0110)
#: 사람 (§2)
PERSON: Final[Leeway] = Leeway(down=0.0096, down_min=0.0048, down_max=0.0171,
                               cross=0.0054)

#: 부표를 잡고 있었지만 이후 상태를 모르는 경우 (§7).
#:
#: 🔴 중심 `down` 은 **대푯값의 평균**이고, `splitM`(아래 `_split_m`)은 **범위
#:   가운데의 차이**다. 문서가 "둘을 섞지 않는다" 고 적은 그 구분이다.
#:   ⚠ 그 구분 자체가 서로 어긋난다는 점을 웹 팀에 보고했다 — 혼합모형이라면
#:     중심과 퍼짐이 같은 정의를 써야 한다. 합의 전까지 **문서대로** 둔다.
UNKNOWN: Final[Leeway] = Leeway(
    down=(BUOY.down + PERSON.down) / 2,                 # 1.98%
    down_min=min(PERSON.down_min, BUOY.down_min),       # 0.48%
    down_max=max(PERSON.down_max, BUOY.down_max),       # 3.70%
    cross=max(BUOY.cross, PERSON.cross),                # 1.10%
)


def _mid(w: Leeway) -> float:
    """범위의 가운데. §7 의 `splitM` 에만 쓴다."""
    return (w.down_min + w.down_max) / 2


def _split_m(wind_speed: float, elapsed_sec: float) -> float:
    """§7 의 `splitM`. 두 경우(계속 잡음 / 놓음)의 거리 차이.

    ⚠ 대푯값이 아니라 **범위 가운데**의 차이다 (3.09% − 1.095%).
    """
    return (_mid(BUOY) - _mid(PERSON)) * wind_speed * elapsed_sec


# ── 공분산 ───────────────────────────────────────────────────────────

@dataclass
class _Cov:
    """2×2 공분산. x = 동, y = 북 (§5)."""

    xx: float = 0.0
    yy: float = 0.0
    xy: float = 0.0

    def add_directional(self, variance: float, bearing_deg: float) -> None:
        """방향 `d` 로 분산 `v` 를 더한다.

        분산이 한 방향으로만 퍼지면 그 방향의 단위벡터 바깥곱이 공분산이다:

            S += v * [[sin²d, sin d cos d], [sin d cos d, cos²d]]
        """
        r = math.radians(bearing_deg)
        s, c = math.sin(r), math.cos(r)
        self.xx += variance * s * s
        self.yy += variance * c * c
        self.xy += variance * s * c

    def add_isotropic(self, variance: float) -> None:
        """방향이 없는 분산. 두 축에 같이 더하고 상관은 건드리지 않는다."""
        self.xx += variance
        self.yy += variance


@dataclass(frozen=True, slots=True)
class Ellipse:
    """1σ 타원 (§5 타원 변환).

    🔴 **배율을 먹이기 전 값이다.** 50/75/95% 는 같은 공분산에 배율만 바꿔
       구하므로(§6), 미리 곱해 저장하면 화면이 어느 배율인지 모르고 또 곱한다.
    """

    #: 장축 반경(m). 1σ
    major_m: float
    #: 단축 반경(m). 1σ
    minor_m: float
    #: 장축 방위. 북 0°, 시계 (§2). 0~180 으로 정규화한다 — 타원은 180° 대칭이다
    bearing_deg: float

    def at(self, percent: int) -> tuple[float, float]:
        """`(장축, 단축)` 을 해당 범위 배율로. 50 · 75 · 95 만 받는다."""
        try:
            k = SIGMA_SCALE[percent]
        except KeyError:
            raise ValueError(f"50 · 75 · 95 만 있다: {percent}") from None
        return self.major_m * k, self.minor_m * k


def _to_ellipse(cov: _Cov) -> Ellipse:
    """공분산 -> 타원. 2×2 대칭 행렬의 고유분해다.

    λ± = (xx+yy)/2 ± sqrt(((xx−yy)/2)² + xy²)

    ⚠ 두 고윳값이 같으면(원) 고유벡터가 하나로 안 정해진다. 그때 방위는 아무
      값이나 맞으므로 0 을 준다 — 원에는 장축이 없다.
    """
    half = (cov.xx + cov.yy) / 2
    diff = (cov.xx - cov.yy) / 2
    root = math.hypot(diff, cov.xy)
    lam_max, lam_min = half + root, max(0.0, half - root)

    if root < 1e-12:
        bearing = 0.0
    else:
        # λ_max 의 고유벡터. (xy, λ_max − xx) 는 (S − λI)v = 0 을 만족한다
        ex, ey = cov.xy, lam_max - cov.xx
        if abs(ex) < 1e-12 and abs(ey) < 1e-12:
            ex, ey = lam_max - cov.yy, cov.xy
        # 북 0°, 시계 -> atan2(동, 북)
        bearing = math.degrees(math.atan2(ex, ey)) % 180.0
        # ⚠ 각도가 0 바로 아래면 `% 180` 이 반올림돼 **정확히 180.0** 이 나온다.
        #   0~180 약속(과 DB CHECK)을 깨므로 되돌린다. 타원은 180° 대칭이라
        #   180 과 0 은 같은 방향이다
        if bearing >= 180.0:
            bearing = 0.0

    return Ellipse(major_m=math.sqrt(max(0.0, lam_max)),
                   minor_m=math.sqrt(lam_min),
                   bearing_deg=bearing)


# ── 추정 ─────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Ocean:
    """계산에 쓴 해양 입력. 그대로 `pi_drift_estimate.input_*` 에 저장한다.

    🔴 `wind_dir` 은 **관측 원값(from)** 이다. 계산에 쓰는 toward 가 아니다 —
       저장 규약이 사고 행의 `ocean_wind_dir_deg` 와 같아야 한다 (§10).

    ⚠ 한쪽만 없으면 그 항을 0 으로 둔다. 둘 다 없으면 추정하지 않는다 (§2).
    """

    #: m/s
    current_speed: float | None = None
    #: 해류가 **가는** 방향. 북 0°, 시계
    current_dir: float | None = None
    #: 주변 격자와의 해류 차이(m/s). 없으면 그 항을 뺀다 (§5)
    current_spread: float | None = None
    #: m/s
    wind_speed: float | None = None
    #: 바람이 **불어오는** 방향(from). 계산할 때 +180 한다
    wind_dir: float | None = None
    #: 관측 시각. 화면이 반드시 같이 띄워야 한다
    observed_at: int | None = None

    @property
    def has_current(self) -> bool:
        return self.current_speed is not None and self.current_dir is not None

    @property
    def has_wind(self) -> bool:
        return self.wind_speed is not None and self.wind_dir is not None

    @property
    def usable(self) -> bool:
        """둘 중 하나라도 있으면 추정한다 (§2)."""
        return self.has_current or self.has_wind


@dataclass(frozen=True, slots=True)
class Drift:
    """추정 하나."""

    center_lat: float
    center_lon: float
    ellipse: Ellipse
    elapsed_sec: int
    #: 무엇으로 계산했는지. 화면이 "해류만" / "바람만" 을 말해야 한다 (§2)
    based_on: str

    @property
    def radius_m(self) -> float:
        """하위 호환용 원 반지름. **95% 장축**이다.

        타원을 못 그리는 화면이 과소평가하지 않게 큰 쪽을 준다 — 수색 범위다.
        """
        return self.ellipse.at(95)[0]


class TooLong(ValueError):
    """§8 의 6시간을 넘었다. 추정하지 않고 마지막 위치만 보여준다."""


def estimate(*, base_lat: float, base_lon: float, elapsed_sec: float,
             leeway: Leeway, ocean: Ocean,
             unknown_hold: bool = False) -> Drift:
    """표류 중심과 1σ 타원.

    `unknown_hold` 는 §7 — 마지막 패킷에서 부표를 잡고 있었지만 이후를 모르는
    경우다. 그때 `leeway` 로 `UNKNOWN` 을 주고 이 값을 True 로 둔다.

    🔴 경과시간이 0 이면 부르지 않는다. 수신 중이면 타원을 그리지 않는다 (§3).
    """
    if elapsed_sec <= 0:
        raise ValueError("경과시간이 0 이면 추정하지 않는다 (§3)")
    if elapsed_sec > MAX_ELAPSED_SEC:
        raise TooLong(f"{MAX_ELAPSED_SEC}초를 넘었다: {elapsed_sec:.0f}")
    if not ocean.usable:
        raise ValueError("해류·바람이 둘 다 없으면 추정하지 않는다 (§2)")

    t = float(elapsed_sec)
    cov = _Cov()

    # ── 중심 (§4) ────────────────────────────────────────────────────
    dx = dy = 0.0

    if ocean.has_current:
        v, d = ocean.current_speed, ocean.current_dir
        assert v is not None and d is not None
        r = math.radians(d)
        dx += v * t * math.sin(r)
        dy += v * t * math.cos(r)
        # 주변 격자와의 차이. spread 의 절반을 표준편차로 본다 (§5)
        if ocean.current_spread is not None:
            cov.add_directional((ocean.current_spread / 2 * t) ** 2, d)

    wind_toward = None
    if ocean.has_wind:
        w, from_dir = ocean.wind_speed, ocean.wind_dir
        assert w is not None and from_dir is not None
        # 🔴 from -> toward. 안 하면 정확히 반대로 간다
        wind_toward = (from_dir + 180.0) % 360.0
        r = math.radians(wind_toward)
        dx += leeway.down * w * t * math.sin(r)
        dy += leeway.down * w * t * math.cos(r)

        # leeway 계수 범위 — 균등분포 (§5)
        width = (leeway.down_max - leeway.down_min) * w * t
        cov.add_directional(width * width / 12.0, wind_toward)
        # crosswind — 좌우를 모르므로 양방향. 균등 [-a, a] 의 분산은 a²/3
        cross = leeway.cross * w * t
        cov.add_directional(cross * cross / 3.0, (wind_toward + 90.0) % 360.0)
        # 부표 상태 불명 (§7)
        if unknown_hold:
            sm = _split_m(w, t)
            cov.add_directional(sm * sm / 4.0, wind_toward)

    # ── 출발점 위치 오차 (§5) ────────────────────────────────────────
    # 반지름 R 균등 원판의 축당 분산은 R²/4 다. 방향이 없으므로 Sxy 는 0
    cov.add_isotropic(POSITION_ERROR_M ** 2 / 4.0)

    lat = base_lat + dy / _M_PER_DEG_LAT
    lon = base_lon + dx / (_M_PER_DEG_LON_EQ * math.cos(math.radians(base_lat)))

    based = ("해류·바람" if ocean.has_current and ocean.has_wind
             else "해류만" if ocean.has_current else "바람만")
    return Drift(center_lat=lat, center_lon=lon, ellipse=_to_ellipse(cov),
                 elapsed_sec=int(elapsed_sec), based_on=based)

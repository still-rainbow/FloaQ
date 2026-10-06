"""해양 데이터 캐시. **표류 계산을 오프라인에서도 하려고 미리 받아 둔다.**

표류 추정(`floaq.drift`)은 조류와 바람이 있어야 한다. 그런데 그 값이 필요한
순간은 **부표와 통신이 끊긴 때**이고, 어선은 그때 인터넷도 같이 끊겨 있다.
그래서 붙어 있을 때 받아서 `pi_ocean_data` 에 넣어 둔다.

    인터넷 있을 때:  EC2 /api/ocean/**  ->  pi_ocean_data
    두절 났을 때:    pi_ocean_data      ->  floaq.drift

── 소스 두 개 (§2 가 조류와 바람을 따로 본다) ──────────────────────
    KHOA  `/api/ocean/current`       ROMS 격자 유속·유향 + 이웃 산포
    KMA   `/api/ocean/observations`  기상청 해양 관측 지점의 풍속·풍향

한 행에 합치지 않는다. 관측 시각이 서로 다르고(ROMS 는 1시간 예측, 관측은
최대 90분 이르다), 한쪽만 들어오는 일이 흔하다. 합쳐 두면 늦은 쪽 시각으로
이른 쪽까지 늙어 보인다.

🔴 **풍향은 from 이다.** 기상청이 "불어오는 쪽"을 준다. 그대로 저장하고,
   `drift.Ocean.wind_dir` 도 그대로 받는다 — 뒤집는 것은 계산하는 곳
   한 군데뿐이다. 저장 단계에서 뒤집으면 DB 값과 사고 행의
   `ocean_wind_dir_deg` 가 서로 다른 뜻이 된다.

⚠ **`web.ocean.OceanProxy` 를 통해 받는다.** 키오스크 중계에 쓰는 그 객체다.
  EC2 를 부르는 곳을 둘로 두지 않으려는 것이고, 덤으로 이 폴링이 프록시 캐시도
  덥혀 준다 — 키오스크의 첫 조회가 바로 답을 받는다. 키오스크 키를 붙이는 쪽도
  거기다(`/api/ocean/current` 는 그 키가 맞을 때만 본선 주변 타일 수집을 부른다).

⚠ 값이 없는 것은 **정상 상태**다. 배가 새 해역에 들어가면 타일을 받기 전까지
  `OUTSIDE_AREA` 로 빈 값이 온다 — 장애가 아니다.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime
from typing import Any


log = logging.getLogger(__name__)

#: 폴링 주기. ROMS 가 1시간 간격이라 30분이면 새 예측을 한 번은 잡는다
PERIOD_SEC = 30 * 60
#: 못 받았을 때 다시 시도하기까지. 주기보다 짧다 — 방금 붙었을 수 있다
RETRY_SEC = 5 * 60
#: 이만큼 움직였으면 주기를 안 기다리고 받는다. ROMS 격자가 약 3km 라 그 절반이다
MOVED_M = 1_500.0
#: 이보다 오래된 관측은 지운다. 명세 §8 이 6시간에서 추정을 끊지만, 지난 사고를
#: 다시 그릴 때 그때의 해양 값이 필요하다
KEEP_SEC = 24 * 3600
#: 관측소를 찾는 반경(km). 넓히면 먼 지점의 바람을 이 자리 바람처럼 쓰게 된다
OBS_RADIUS_KM = 30.0

#: `pi_ocean_data.source` 는 CHECK 로 이 셋만 받는다 (database/pi.sql)
SRC_CURRENT = "KHOA"
SRC_WIND = "KMA"


def _iso_to_unix(text: str | None) -> int | None:
    """`2026-09-21T08:00:00Z` -> Unix 초. 못 읽으면 None.

    ⚠ 파이썬 3.10 의 `fromisoformat` 은 `Z` 를 못 읽는다. 젯슨이 3.10 이라
      여기서 갈아 끼운다 — Pi 만 3.12 라고 믿으면 이식할 때 조용히 깨진다.
    """
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        log.warning("해양 데이터 시각을 못 읽었다: %r", text)
        return None


def _num(v: Any) -> float | None:
    """숫자만 통과. `None` 과 문자열은 버린다."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def moved_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 위경도 사이 거리(m). 평면 근사다 — 수 km 에서 오차가 무시된다."""
    dy = (b[0] - a[0]) * 111_132.0
    dx = (b[1] - a[1]) * 111_320.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


class OceanPump:
    """주기적으로 해양 데이터를 받아 `pi_ocean_data` 에 넣는 스레드.

    ⚠ `OceanProxy` 는 스레드 안전하다(`requests.Session` + 락). 키오스크 중계와
      **같은 인스턴스**를 준다 — 캐시를 나눠 써야 이 폴링이 키오스크 조회를 덥힌다.
    """

    def __init__(self, repo, proxy, clock, ship_id: str, gnss) -> None:
        self.repo = repo
        #: `web.ocean.OceanProxy`
        self.proxy = proxy
        self.clock = clock
        self.ship_id = ship_id
        #: 본선 위치. 사고 지점이 아니라 **지금 배가 있는 곳**의 바다를 받아 둔다 —
        #: 사고는 배가 있는 곳에서 난다
        self.gnss = gnss
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        #: 마지막으로 받아 온 위치. 여기서 멀어지면 주기를 안 기다린다
        self._at: tuple[float, float] | None = None
        self.saved = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ocean", daemon=True)
        self._thread.start()
        log.info("해양 데이터 수집 시작 (%d분 주기)", PERIOD_SEC // 60)

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                wait = self.round_once()
            except Exception:
                # 🔴 죽으면 두절 났을 때 쓸 해양 값이 없는데, 그 사실을 그때 안다
                log.exception("해양 수집 루프 오류")
                wait = RETRY_SEC
            # 주기가 30분이라 그대로 자면 정지 요청에 30분 늦게 답한다.
            # 잘게 나눠 자면서 매번 확인한다
            self._sleep(wait)

    def _sleep(self, total: float) -> None:
        left = total
        while left > 0 and not self._stopping.is_set():
            step = min(30.0, left)
            self._stopping.wait(step)
            left -= step
            # 배가 움직였으면 남은 시간을 버리고 바로 받는다
            if self._moved_enough():
                return

    def _moved_enough(self) -> bool:
        here = self._here()
        if here is None or self._at is None:
            return False
        return moved_m(self._at, here) >= MOVED_M

    def _here(self) -> tuple[float, float] | None:
        """본선 위치. GPS 가 없거나 fix 가 안 잡혔으면 None."""
        fix = self.gnss.read() if self.gnss else None
        if fix is None or not getattr(fix, "valid", False):
            return None
        return float(fix.lat), float(fix.lon)

    # ── 한 회차 ──────────────────────────────────────────────────────
    def round_once(self) -> float:
        """한 번 받아 저장한다. 다음 회차까지 기다릴 초.

        🔴 **시계가 안 맞으면 저장하지 않는다.** `observed_at` 이 틀린 행은
           나중에 "6시간 넘었다"로 버려지거나, 더 나쁘게는 미래 값이 최신으로
           뽑힌다 (Pi 5 에는 RTC 가 없다).
        """
        if not self.clock.is_valid():
            return RETRY_SEC
        here = self._here()
        if here is None:
            # GPS 가 아직이다. 위치를 모르면 어느 바다를 받을지도 모른다
            return RETRY_SEC

        now = self.clock.now()
        got = self._fetch_current(here, now) + self._fetch_wind(here, now)
        self._at = here
        self.repo.prune_ocean(self.ship_id, now - KEEP_SEC)
        # 둘 다 못 받았으면 빨리 다시 본다. 방금 인터넷이 붙었을 수 있다
        return PERIOD_SEC if got else RETRY_SEC

    def _get(self, path: str, params: dict) -> Any:
        """프록시로 한 번. 성공 응답의 `data` 또는 None.

        ⚠ 프록시는 인터넷이 끊기면 **캐시로 답한다**(200 + `fresh: false`). 그래도
          저장한다 — `observed_at` 이 값 자체에 들어 있어서 나이는 그 값이 말한다.
          여기서 거르면 두절 직후 잠깐의 네트워크 끊김에 계산할 값이 사라진다.
        """
        body, status = self.proxy.get(path, params)
        if status != 200 or not body.get("success"):
            return None
        return body.get("data")

    def _fetch_current(self, here: tuple[float, float], now: int) -> int:
        """ROMS 격자 유속·유향. 저장한 행 수(0 또는 1)."""
        lat, lon = here
        d = self._get("current", {"lat": lat, "lon": lon})
        if not isinstance(d, dict):
            # `OUTSIDE_AREA` — 타일을 아직 못 받았다. **정상 상태다** (백엔드 주석)
            return 0
        observed = _iso_to_unix(d.get("predcDt"))
        speed, direction = _num(d.get("currentSpeedMs")), _num(d.get("currentDirDeg"))
        if observed is None or speed is None:
            return 0
        row = self.repo.save_ocean(
            self.ship_id, source=SRC_CURRENT, observed_at=observed,
            fetched_at=now, now=now,
            current_speed=speed, current_dir=direction,
            # ⚠ 이웃이 없으면 null 로 둔다. 0 으로 채우면 "확실하다"로 읽힌다
            current_spread=_num(d.get("neighborSpreadMs")),
            water_temp=_num(d.get("waterTempC")),
            # 격자 위치 그대로. 본선 위치를 넣으면 "이 자리 값"인 척하게 된다
            lat=_num(d.get("lat")), lon=_num(d.get("lon")),
            distance_km=_num(d.get("distanceKm")))
        if row is not None:
            self.saved += 1
        return 1 if row is not None else 0

    def _fetch_wind(self, here: tuple[float, float], now: int) -> int:
        """가장 가까운 관측소의 풍속·풍향. 저장한 행 수(0 또는 1).

        ⚠ 응답은 **거리순 목록**이다. 첫 원소가 제일 가깝지만 바람 값이 비어
          있을 수 있어서, 풍속이 있는 첫 지점을 고른다 — 조위만 주는 지점이 섞인다.
        """
        lat, lon = here
        rows = self._get("observations",
                         {"lat": lat, "lon": lon, "radiusKm": OBS_RADIUS_KM})
        if not isinstance(rows, list):
            return 0
        for st in rows:
            if not isinstance(st, dict):
                continue
            speed = _num(st.get("windSpeedMs"))
            observed = _iso_to_unix(st.get("observedAt"))
            if speed is None or observed is None:
                continue
            row = self.repo.save_ocean(
                self.ship_id, source=SRC_WIND, observed_at=observed,
                fetched_at=now, now=now,
                # 🔴 불어오는 쪽 그대로다. 뒤집는 것은 drift.estimate 하나뿐이다
                wind_speed=speed, wind_dir=_num(st.get("windDirDeg")),
                wave_height=_num(st.get("waveHeightM")),
                water_temp=_num(st.get("waterTempC")),
                lat=_num(st.get("lat")), lon=_num(st.get("lon")),
                distance_km=_num(st.get("distanceKm")))
            if row is not None:
                self.saved += 1
            return 1 if row is not None else 0
        return 0


#: 이보다 오래된 관측은 표류 계산에 쓰지 않는다.
#:
#: 🔴 명세 §8 이 "6시간 넘게 표류한 것은 추정하지 않는다"고 한 것과 같은 이유다.
#:    6시간 전 조류로 지금을 그리는 것은 6시간 표류를 그리는 것만큼 틀린다.
#: ⚠ 화면은 여기에 걸리지 않은 값도 **관측 시각을 같이 띄워야 한다.** 3시간 전
#:   조류로 그린 타원과 3분 전 조류로 그린 타원은 화면에서 똑같이 생겼다.
STALE_SEC = 6 * 3600


def load_ocean(repo, ship_id: str, now: int, *, stale_sec: int = STALE_SEC):
    """저장해 둔 값으로 `drift.Ocean` 을 만든다. 두 소스를 여기서 합친다.

    한쪽만 있어도 준다 — 명세 §2 가 "없는 항은 0 으로 두고 계산한다"고 했다.
    둘 다 없으면 `usable` 이 False 인 것을 주고, 부르는 쪽이 추정을 건너뛴다.

    ⚠ `observed_at` 은 **둘 중 이른 쪽**이다. 늦은 쪽을 쓰면 화면이 실제보다
      신선해 보인다 — 오래된 입력으로 그린 타원이 방금 값처럼 읽힌다.
    """
    from floaq import drift

    floor = now - stale_sec
    cur = repo.latest_ocean(ship_id, SRC_CURRENT, not_before=floor)
    wind = repo.latest_ocean(ship_id, SRC_WIND, not_before=floor)

    seen = [r["observed_at"] for r in (cur, wind) if r is not None]
    return drift.Ocean(
        current_speed=cur["current_speed"] if cur else None,
        current_dir=cur["current_dir"] if cur else None,
        current_spread=cur["current_spread"] if cur else None,
        wind_speed=wind["wind_speed"] if wind else None,
        wind_dir=wind["wind_dir"] if wind else None,
        observed_at=min(seen) if seen else None,
    )


class OceanStore:
    """`ports.OceanSource` 구현. 캐시에서만 읽는다.

    🔴 **여기서 EC2 를 부르지 않는다.** 이 값이 필요한 순간은 부표와 통신이
       끊긴 때고, 그때는 인터넷도 대개 끊겨 있다. 네트워크를 타면 tick 이
       타임아웃만큼 멈춘다 — 그 사이 카운트다운 만료 판정이 늦는다.
       받아 두는 것은 `OceanPump` 의 일이다.
    """

    def __init__(self, repo, ship_id: str) -> None:
        self.repo = repo
        self.ship_id = ship_id

    def ocean(self, now: int):
        return load_ocean(self.repo, self.ship_id, now)

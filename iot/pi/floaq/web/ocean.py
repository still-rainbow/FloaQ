"""해양 데이터 프록시. 키오스크 -> Pi -> EC2 `/api/ocean/**`.

**키오스크는 EC2 를 직접 부르지 않는다** `확정` 2026-09-17. Pi 가 전부 중계한다.
얻는 것이 셋이다.

    ① 키오스크 설정이 사라진다 — Pi 주소만 알면 된다. EC2 주소·키를 안 들고 있는다
    ② kiosk 키가 브라우저 번들에 안 들어간다. Pi 가 서버 쪽에서 붙인다
    ③ 인터넷이 끊겨도 **마지막 값**을 보여줄 수 있다 (아래 캐시)

🔴 **인터넷이 끊겼을 때 빈 응답을 주면 안 된다.** 화면이 "조류 0.0 m/s" 로 그려지고,
   그건 "잔잔하다"로 읽힌다. 표류 반경을 그 값으로 그리면 수색 범위가 거짓이 된다.
   그래서 캐시에서 주되 **`cached_at` 을 같이 실어** 화면이 언제 값인지 말하게 한다.
   캐시도 없으면 503 이다 — "값 없음"과 "수집 안 됨"을 가르는 것이 §5 원칙이다.

⚠ `/api/ocean/**` 는 EC2 에서 **인증이 없다**(api.json `security: -`). 해역 이동으로
  새 타일 수집을 부르는 것만 `x-floaq-kiosk-key` 를 요구한다. 그 키는 Pi 가 붙인다.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

#: 중계할 경로. 화이트리스트다 — `/api/ocean/{path}` 를 그대로 열면 Pi 가 EC2 의
#: 아무 경로나 부르는 통로가 된다.
ALLOWED = frozenset({
    "current", "grid", "series", "observations", "tide", "zones",
    "summary", "sources",
})

#: 같은 질의를 이 시간 안에 다시 물으면 캐시로 답한다. 해양 예측은 시간 단위로
#: 갱신되므로 초 단위로 다시 부를 이유가 없다 — EC2 쿼터를 태울 뿐이다.
FRESH_SEC = 60

#: 캐시 보관 상한. 인터넷이 끊긴 동안 이 나이까지는 옛 값이라도 준다.
STALE_MAX_SEC = 6 * 3600

TIMEOUT: tuple[float, float] = (3.0, 10.0)

#: 디스크에서 되살렸을 때의 `message`. 화면이 "저장된 값"이라고 말할 수 있어야 한다.
FROM_DISK = "FROM_DISK"


def _iso(unix: int) -> str:
    """서버가 주는 모양 그대로. 화면 파서가 그것만 읽는다."""
    return datetime.fromtimestamp(unix, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OceanProxy:
    """EC2 `/api/ocean/**` 중계 + 마지막 값 캐시.

    ⚠ 캐시는 메모리다. 재부팅하면 비는데, 그래도 되는 값이다 — 사고 기록이 아니라
      화면 표시용이고, 오래된 해양 값을 디스크에 남겨 봐야 쓸 데가 없다.
    """

    def __init__(self, base_url: str, *, kiosk_key: str = "",
                 timeout=TIMEOUT, repo=None, ship_id: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.kiosk_key = kiosk_key
        self.timeout = timeout
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()
        self._s = requests.Session()
        #: 마지막 보루. `pi_ocean_data` 에서 읽는다 (`floaq/ocean.py` 가 채운다).
        #: 🔴 메모리 캐시는 **재부팅하면 빈다.** 정박 중에 전원을 내렸다가 바다에서
        #:    인터넷 없이 켜는 것이 평범한 사용인데, 그때 화면에 조류·바람이 하나도
        #:    안 뜬다. 표류 계산은 이 표를 보고 있었으므로 값은 이미 디스크에 있었다
        self.repo = repo
        self.ship_id = ship_id

    def close(self) -> None:
        self._s.close()

    def get(self, path: str, params: dict) -> tuple[dict, int]:
        """중계한다. `(본문, HTTP 상태)`.

        본문에 `cached_at` 을 붙인다 — 화면이 "몇 분 전 값인가"를 말할 수 있어야
        한다. 3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 **화면에서 똑같이
        생겼다**.
        """
        if path not in ALLOWED:
            return {"code": "COMMON_NOT_FOUND", "message": f"중계하지 않는 경로: {path}"}, 404

        key = self._key(path, params)
        now = time.time()

        hit = self._peek(key)
        if hit and now - hit[0] < FRESH_SEC:
            return self._wrap(hit[1], hit[0], fresh=True), 200

        headers = {}
        # 해역 이동으로 새 타일 수집을 부르는 건 키가 있어야 한다. 브라우저 번들에
        # 넣지 않으려고 Pi 가 서버 쪽에서 붙인다
        if self.kiosk_key and "at" not in params:
            headers["x-floaq-kiosk-key"] = self.kiosk_key

        try:
            r = self._s.get(f"{self.base_url}/api/ocean/{path}",
                            params=params, headers=headers, timeout=self.timeout)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            log.info("해양 중계 실패 %s (%s) — 캐시를 본다", path, type(e).__name__)
            return self._fallback(key, now, path)

        if not r.ok or not body.get("success"):
            return self._fallback(key, now, path, upstream=body)

        with self._lock:
            self._cache[key] = (now, body)
        return self._wrap(body, now, fresh=True), 200

    # ── 내부 ─────────────────────────────────────────────────────────
    def _fallback(self, key: str, now: float, path: str,
                  upstream: dict | None = None) -> tuple[dict, int]:
        hit = self._peek(key)
        if hit and now - hit[0] < STALE_MAX_SEC:
            log.info("해양 %s — %d초 전 캐시로 답한다", path, int(now - hit[0]))
            return self._wrap(hit[1], hit[0], fresh=False), 200

        disk = self._from_db(path)
        if disk is not None:
            body, observed = disk
            log.info("해양 %s — pi_ocean_data 에서 답한다 (%d초 전 관측)",
                     path, int(now - observed))
            return self._wrap(body, observed, fresh=False), 200

        # 🔴 빈 200 을 주지 않는다. 화면이 0.0 을 "잔잔하다"로 그린다
        return upstream or {
            "code": "OCEAN_UNAVAILABLE",
            "message": "해양 데이터를 받을 수 없고 캐시도 없다",
        }, 503

    def _from_db(self, path: str) -> tuple[dict, float] | None:
        """`pi_ocean_data` 에서 되살린다. `(응답 본문, 관측 시각)` 또는 None.

        조류와 바람만 된다. 나머지 경로(grid·series·tide·zones…)는 계산에 안 쓰는
        값이라 저장하지 않는다 — 그건 인터넷이 있을 때만 보인다.

        ⚠ **격자·관측소의 좌표를 그대로 돌려준다.** 조회 좌표로 바꿔 넣으면
          `distanceKm` 이 0 이 돼서 "바로 이 자리 값"으로 읽힌다. 실제로는 관측소가
          30km 밖일 수 있고, 그 차이가 표류 타원의 신뢰도다.
        """
        if self.repo is None or path not in ("current", "observations"):
            return None
        try:
            from floaq.ocean import SRC_CURRENT, SRC_WIND
            src = SRC_CURRENT if path == "current" else SRC_WIND
            r = self.repo.latest_ocean(self.ship_id, src)
        except Exception:
            # 🔴 조회 하나 때문에 화면 전체가 죽지 않게 한다
            log.exception("pi_ocean_data 조회 실패")
            return None
        if r is None:
            return None

        at = _iso(r["observed_at"])
        if path == "current":
            data: object = {
                "predcDt": at, "lat": r["lat"], "lon": r["lon"],
                "currentDirDeg": r["current_dir"],
                "currentSpeedMs": r["current_speed"],
                "waterTempC": r["water_temp"],
                "distanceKm": r["distance_km"] or 0.0,
                "neighborSpreadMs": r["current_spread"],
                # 이웃 몇 칸으로 쟀는지는 저장하지 않는다. 1 은 "자기 자신뿐"이라
                # 산포를 못 쟀다는 뜻이고, spread 가 null 인 것과 앞뒤가 맞는다
                "neighborCount": 1,
            }
        else:
            data = [{
                "network": "KMA", "stn": "", "name": "마지막 관측",
                "lat": r["lat"], "lon": r["lon"],
                "distanceKm": r["distance_km"] or 0.0, "observedAt": at,
                "waveHeightM": r["wave_height"], "windDirDeg": r["wind_dir"],
                "windSpeedMs": r["wind_speed"], "windGustMs": None,
                "waterTempC": r["water_temp"], "airTempC": None,
                "pressureHpa": None, "humidityPct": None,
                "currentDirDeg": None, "currentSpeedMs": None, "tideLevelM": None,
            }]
        return {"success": True, "message": FROM_DISK, "data": data}, float(r["observed_at"])

    def _peek(self, key: str) -> tuple[float, dict] | None:
        with self._lock:
            return self._cache.get(key)

    @staticmethod
    def _wrap(body: dict, cached_at: float, *, fresh: bool) -> dict:
        out = dict(body)
        out["cached_at"] = int(cached_at)
        out["fresh"] = fresh          # False 면 화면이 "옛 값"이라고 말해야 한다
        return out

    @staticmethod
    def _key(path: str, params: dict) -> str:
        return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))

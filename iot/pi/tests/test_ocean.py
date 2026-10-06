"""해양 데이터 캐시와 두절 중 표류 발행.

`test_drift.py` 는 수식이 맞는가를 본다. 여기는 **그 수식에 들어가는 값이 제때
제자리에 있는가**를 본다 — 표류 추정이 실패하는 방식은 대부분 수식이 아니라
"그 순간 값이 없었다" 다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq import config, ocean
from floaq.adapters.memory import FakeClock, FakeLauncher, FakeReporter, MemoryBus, MemoryRepo
from floaq.contracts import JetsonDetection
from floaq.contracts.lora import BuoyFrame, Reception
from floaq.core.orchestrator import Orchestrator
from floaq.ids import uuid7

SHIP = uuid7()
T0 = 1_757_000_000


# ── 가짜들 ───────────────────────────────────────────────────────────
class FakeProxy:
    """`web.ocean.OceanProxy` 자리. 준 것을 그대로 돌려준다."""

    def __init__(self, **bodies) -> None:
        #: 경로 -> (data, status)
        self.bodies = bodies
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict):
        self.calls.append((path, params))
        if path not in self.bodies:
            return {"code": "OCEAN_UNAVAILABLE"}, 503
        data = self.bodies[path]
        return {"success": True, "data": data, "cached_at": T0, "fresh": True}, 200


class FakeFix:
    def __init__(self, lat: float, lon: float, valid: bool = True) -> None:
        self.lat, self.lon, self.valid = lat, lon, valid


class FakeGnss:
    def __init__(self, fix=None) -> None:
        self.fix = fix

    def read(self):
        return self.fix


class OceanRepo(MemoryRepo):
    """`pi_ocean_data` 대역."""

    def __init__(self) -> None:
        super().__init__()
        self.oceans: list[dict] = []
        self.pruned: list[int] = []

    def save_ocean(self, ship_id, *, source, observed_at, fetched_at, now, **kw):
        # UNIQUE (ship_id, source, observed_at) 를 흉내낸다
        for r in self.oceans:
            if (r["ship_id"], r["source"], r["observed_at"]) == (ship_id, source, observed_at):
                return None
        row = {"ocean_data_id": len(self.oceans) + 1, "ship_id": ship_id,
               "source": source, "observed_at": observed_at,
               "fetched_at": fetched_at, "wind_speed": None, "wind_dir": None,
               "current_speed": None, "current_dir": None, "current_spread": None,
               "wave_height": None, "water_temp": None, **kw}
        self.oceans.append(row)
        return row["ocean_data_id"]

    def latest_ocean(self, ship_id, source, *, not_before=None):
        rows = [r for r in self.oceans
                if r["ship_id"] == ship_id and r["source"] == source
                and (not_before is None or r["observed_at"] >= not_before)]
        return max(rows, key=lambda r: r["observed_at"]) if rows else None

    def prune_ocean(self, ship_id, before):
        self.pruned.append(before)
        n = len(self.oceans)
        self.oceans = [r for r in self.oceans if r["observed_at"] >= before]
        return n - len(self.oceans)


def iso(offset: int) -> str:
    """T0 기준 ISO 8601. 서버가 주는 모양 그대로 `Z` 로 끝낸다.

    ⚠ 고정 날짜 문자열을 쓰면 T0 과 몇 년씩 벌어져서 "오래됐나" 시험이
      의미를 잃는다. 처음에 그렇게 썼다가 걸렸다.
    """
    return (datetime.fromtimestamp(T0 + offset, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


CURRENT = {"predcDt": iso(0), "currentSpeedMs": 0.42,
           "currentDirDeg": 45.0, "neighborSpreadMs": 0.08, "waterTempC": 21.3}
#: 관측은 요청 시각보다 최대 90분 이르다 (백엔드 `SeaObsHistory.WINDOW`)
WIND = [{"observedAt": iso(-600), "windSpeedMs": 7.5,
         "windDirDeg": 270.0, "waveHeightM": 1.2, "waterTempC": 21.1}]


def pump(proxy=None, fix=FakeFix(35.05, 129.10), repo=None):
    repo = repo or OceanRepo()
    proxy = proxy or FakeProxy(current=CURRENT, observations=WIND)
    return ocean.OceanPump(repo, proxy, FakeClock(T0), SHIP, FakeGnss(fix)), repo, proxy


# ── 받아서 저장 ──────────────────────────────────────────────────────
def test_stores_current_and_wind_as_separate_rows():
    """🔴 한 행에 합치지 않는다. 관측 시각이 다르다 — 합치면 이른 쪽이 늦은 쪽
    시각으로 젊어 보인다."""
    p, repo, _ = pump()
    p.round_once()
    assert {r["source"] for r in repo.oceans} == {ocean.SRC_CURRENT, ocean.SRC_WIND}
    cur = repo.latest_ocean(SHIP, ocean.SRC_CURRENT)
    assert cur["current_speed"] == 0.42
    assert cur["current_spread"] == 0.08


def test_wind_dir_is_stored_as_observed_not_flipped():
    """🔴 저장은 **불어오는 쪽** 그대로다.

    뒤집는 곳이 두 군데가 되면 한 번 더 뒤집혀 표류가 정반대로 간다. 뒤집는 것은
    `drift.estimate` 하나뿐이다.
    """
    p, repo, _ = pump()
    p.round_once()
    assert repo.latest_ocean(SHIP, ocean.SRC_WIND)["wind_dir"] == 270.0


def test_missing_spread_stays_null():
    """⚠ 0 이 아니라 NULL 이다. 0 은 "확실하다"로 읽혀 타원이 실제보다 좁아진다."""
    body = {k: v for k, v in CURRENT.items() if k != "neighborSpreadMs"}
    p, repo, _ = pump(FakeProxy(current=body, observations=WIND))
    p.round_once()
    assert repo.latest_ocean(SHIP, ocean.SRC_CURRENT)["current_spread"] is None


def test_station_without_wind_is_skipped():
    """가까운 지점이 조위만 줄 수 있다. 거리순 첫 원소를 그냥 쓰면 바람이 사라진다."""
    rows = [{"observedAt": iso(-600), "tideLevelM": 1.1}] + WIND
    p, repo, _ = pump(FakeProxy(current=CURRENT, observations=rows))
    p.round_once()
    assert repo.latest_ocean(SHIP, ocean.SRC_WIND)["wind_speed"] == 7.5


def test_same_observation_twice_is_not_duplicated():
    """30분마다 물어도 ROMS 는 1시간 간격이다. 같은 관측이 다시 오는 게 정상이다."""
    p, repo, _ = pump()
    p.round_once()
    p.round_once()
    assert len(repo.oceans) == 2


def test_outside_area_is_not_an_error():
    """⚠ 배가 새 해역에 들어가면 타일을 받기 전까지 값이 없다. 정상 상태다."""
    p, repo, _ = pump(FakeProxy())          # 전부 503
    wait = p.round_once()
    assert repo.oceans == []
    assert wait == ocean.RETRY_SEC          # 빨리 다시 본다


def test_no_gps_means_no_fetch():
    """위치를 모르면 어느 바다를 받을지도 모른다."""
    p, _, proxy = pump(fix=FakeFix(0, 0, valid=False))
    assert p.round_once() == ocean.RETRY_SEC
    assert proxy.calls == []


def test_invalid_clock_means_no_fetch():
    """🔴 Pi 5 에는 RTC 가 없다. 시계가 틀리면 `observed_at` 도 틀리게 저장된다."""
    p, _, proxy = pump()
    p.clock.set_valid(False)
    assert p.round_once() == ocean.RETRY_SEC
    assert proxy.calls == []


def test_prunes_old_rows():
    p, repo, _ = pump()
    p.round_once()
    assert repo.pruned == [T0 - ocean.KEEP_SEC]


def test_moved_far_enough():
    """ROMS 격자가 약 3km 라 그 절반을 넘으면 다른 칸의 바다다."""
    here = (35.05, 129.10)
    assert ocean.moved_m(here, here) == 0
    assert not ocean.moved_m(here, (35.055, 129.10)) >= ocean.MOVED_M   # 약 556m
    assert ocean.moved_m(here, (35.07, 129.10)) >= ocean.MOVED_M        # 약 2.2km


# ── 캐시에서 읽기 ────────────────────────────────────────────────────
def test_load_ocean_merges_both_sources():
    p, repo, _ = pump()
    p.round_once()
    o = ocean.load_ocean(repo, SHIP, T0)
    assert o.usable and o.has_current and o.has_wind
    assert o.wind_speed == 7.5 and o.current_speed == 0.42


def test_load_ocean_takes_the_earlier_observed_at():
    """⚠ 늦은 쪽을 쓰면 화면이 실제보다 신선해 보인다."""
    p, repo, _ = pump()
    p.round_once()
    o = ocean.load_ocean(repo, SHIP, T0)
    assert o.observed_at == min(r["observed_at"] for r in repo.oceans)


def test_load_ocean_drops_stale_rows():
    """🔴 6시간 전 조류로 지금을 그리는 것은 6시간 표류를 그리는 것만큼 틀린다."""
    p, repo, _ = pump()
    p.round_once()
    later = T0 + ocean.STALE_SEC + 3600
    assert not ocean.load_ocean(repo, SHIP, later).usable


def test_load_ocean_with_one_source_still_works():
    """§2 — 한쪽만 있으면 없는 항을 0 으로 두고 계산한다."""
    p, repo, _ = pump(FakeProxy(current=CURRENT))
    p.round_once()
    o = ocean.load_ocean(repo, SHIP, T0)
    assert o.usable and o.has_current and not o.has_wind


# ── 두절 중 표류 발행 ────────────────────────────────────────────────
def detection() -> JetsonDetection:
    return JetsonDetection(
        detection_id=uuid7(), ship_id=SHIP, lat=35.1, lon=129.0, distance_m=12.5,
        confidence=0.93, frame_count=5, model_version="v1", camera="L",
        bbox=(10, 20, 30, 40), detected_at=T0,
        launch=dict(target_yaw_deg=12.5, target_pitch_deg=20.0,
                    launch_profile="demo-low-v1", target_lat=35.11,
                    target_lon=129.01, solved_at=T0))


def rx(seq: int = 0) -> Reception:
    return Reception(
        frame=BuoyFrame(ship_tag=0xC9, seq=seq, lat=35.11, lon=129.01,
                        measured_at=T0 + seq, is_pressed=True),
        rssi=-70.0, age_sec=0.0)


def lost(*, with_ocean=True):
    """사고 하나를 두절 상태까지 몰고 간다. `(orch, bus, repo, clock)`."""
    repo = OceanRepo()
    clock, bus = FakeClock(T0), MemoryBus()
    src = None
    if with_ocean:
        p = ocean.OceanPump(repo, FakeProxy(current=CURRENT, observations=WIND),
                            clock, SHIP, FakeGnss(FakeFix(35.05, 129.10)))
        p.round_once()
        src = ocean.OceanStore(repo, SHIP)
    orch = Orchestrator(ship_id=SHIP, clock=clock, bus=bus, repo=repo,
                        launcher=FakeLauncher(), reporter=FakeReporter(), ocean=src)
    orch.on_detection(detection())
    orch.on_buoy(rx())
    clock.advance(config.BUOY_TIMEOUT_SEC + 1)
    orch.tick()
    return orch, bus, repo, clock


def last_drift(bus):
    """마지막으로 낸 `pi/buoy/drift`. 지운 것(payload None)은 없는 것으로 친다."""
    sent = [p for p in bus.sent if p.subject == "pi/buoy/drift"]
    return sent[-1].payload if sent else None


def cleared(bus) -> bool:
    """마지막 `pi/buoy/drift` 동작이 "지움" 이었나."""
    sent = [p for p in bus.sent if p.subject == "pi/buoy/drift"]
    return bool(sent) and sent[-1].payload is None


def test_comm_loss_publishes_an_ellipse():
    """🔴 두절이 나면 수색 범위가 화면에 떠야 한다. 이게 이 기능의 전부다."""
    _, bus, repo, _ = lost()
    d = last_drift(bus)
    assert d is not None
    assert d.axis_major_m >= d.axis_minor_m > 0
    assert 0 <= d.axis_bearing_deg < 180
    assert d.target == "BUOY"
    assert len(repo.drifts) == 1


def test_published_axes_are_one_sigma_and_radius_is_the_95_major():
    """⚠ 축은 배율 **전** 값이고, `radius_m` 은 95% 장축이다. 섞이면 2.36배 틀린다."""
    from floaq import drift as D
    _, bus, _, _ = lost()
    d = last_drift(bus)
    assert d.radius_m == pytest.approx(d.axis_major_m * D.SIGMA_SCALE[95], rel=1e-9)


def test_drift_center_starts_at_the_last_received_position():
    """중심의 출발점은 마지막으로 **들은** 위치다. 사고 지점이 아니다."""
    _, bus, _, _ = lost()
    d = last_drift(bus)
    assert (d.base_lat, d.base_lon) == (35.11, 129.01)


def test_no_ocean_data_means_no_estimate():
    """🔴 위치오차 원판만 남은 타원은 "50m 안에 있다"고 말하는 셈이다. 안 그린다."""
    _, bus, repo, _ = lost(with_ocean=False)
    assert last_drift(bus) is None
    assert repo.drifts == []


def test_estimate_widens_as_time_passes():
    """시간이 갈수록 넓어지는 것이 보여야 한다. 멈춘 화면은 옛 범위를 지금으로 읽힌다."""
    orch, bus, _, clock = lost()
    first = last_drift(bus).axis_major_m
    clock.advance(1800)
    orch.tick()
    assert last_drift(bus).axis_major_m > first


def test_not_republished_every_tick():
    """⚠ 1초 사이 변화는 화면에 안 보이는데 DB 행만 초당 하나씩 쌓인다."""
    orch, _, repo, clock = lost()
    for _ in range(5):
        clock.advance(1)
        orch.tick()
    assert len(repo.drifts) == 1


def test_previous_estimate_is_demoted_not_overwritten():
    """🔴 덮어쓰면 "그때 어디를 수색 범위로 봤는지"가 사라진다."""
    orch, _, repo, clock = lost()
    clock.advance(config.DRIFT_PUBLISH_SEC + 1)
    orch.tick()
    assert len(repo.drifts) == 2
    assert [d["is_current"] for d in repo.drifts] == [0, 1]


def test_over_six_hours_clears_the_retained_estimate():
    """🔴 §8 을 넘으면 그리지 않는다. **남겨 두지도 않는다** — 틀린 범위가 화면에
    계속 떠 있으면 아무도 그게 멈춘 줄 모른다."""
    orch, bus, _, clock = lost()
    clock.advance(7 * 3600)
    orch.tick()
    assert cleared(bus)


def test_recovery_clears_the_estimate():
    """실제 위치가 다시 들어오면 추정은 의미가 없다."""
    orch, bus, _, clock = lost()
    clock.advance(5)
    orch.on_buoy(rx(seq=1))
    assert cleared(bus)


def test_first_estimate_after_a_second_loss_is_immediate():
    """⚠ 두절 직후가 제일 급하다. 주기 타이머가 남아 있으면 첫 범위가 늦게 뜬다."""
    orch, bus, repo, clock = lost()
    clock.advance(5)
    orch.on_buoy(rx(seq=1))             # 복구
    clock.advance(config.BUOY_TIMEOUT_SEC + 1)
    orch.tick()                          # 다시 두절
    assert len(repo.drifts) == 2


def test_stale_ocean_data_takes_the_estimate_down():
    """🔴 해양 값이 늙으면 **범위를 내린다.** 멈춘 타원은 지금 범위와 화면에서
    똑같이 생겨서, 구조 세력은 그게 옛 값인 줄 모른다."""
    orch, bus, _, clock = lost()
    assert last_drift(bus) is not None
    clock.advance(ocean.STALE_SEC + 60)
    orch.tick()
    assert cleared(bus)


def test_estimate_is_not_cleared_twice():
    """⚠ 낸 적이 없으면 지우지 않는다. 매 tick 마다 빈 발행이 쌓인다."""
    orch, bus, _, clock = lost()
    clock.advance(ocean.STALE_SEC + 60)
    for _ in range(3):
        orch.tick()
        clock.advance(config.DRIFT_PUBLISH_SEC + 1)
    assert len([p for p in bus.sent
                if p.subject == "pi/buoy/drift" and p.payload is None]) == 1


# ── 재부팅 뒤 (프록시가 디스크에서 답하기) ───────────────────────────
def test_proxy_answers_from_sqlite_when_memory_cache_is_empty():
    """🔴 정박 중에 전원을 내렸다가 바다에서 인터넷 없이 켜는 것이 평범한 사용이다.

    그때 메모리 캐시는 비어 있는데, 표류 계산이 보던 값은 이미 디스크에 있다.
    503 을 주면 화면에 조류·바람이 하나도 안 뜬다.
    """
    from floaq.web.ocean import FROM_DISK, OceanProxy

    p, repo, _ = pump()
    p.round_once()                                   # pi_ocean_data 를 채운다

    # 인터넷 없는 새 프로세스. 메모리 캐시가 비어 있다
    proxy = OceanProxy("http://nowhere.invalid", repo=repo, ship_id=SHIP)
    body, status = proxy.get("current", {"lat": 35.05, "lon": 129.10})
    assert status == 200
    assert body["message"] == FROM_DISK
    assert body["fresh"] is False                    # 화면이 "옛 값"이라고 말해야 한다
    assert body["data"]["currentSpeedMs"] == 0.42

    body, status = proxy.get("observations", {"lat": 35.05, "lon": 129.10})
    assert status == 200 and body["data"][0]["windSpeedMs"] == 7.5


def test_proxy_without_stored_rows_still_refuses():
    """⚠ 값이 없으면 503 이다. 빈 200 을 주면 화면이 0.0 을 "잔잔하다"로 그린다."""
    from floaq.web.ocean import OceanProxy

    proxy = OceanProxy("http://nowhere.invalid", repo=OceanRepo(), ship_id=SHIP)
    _, status = proxy.get("current", {"lat": 35.05, "lon": 129.10})
    assert status == 503


def test_proxy_keeps_the_measured_position_not_the_queried_one():
    """🔴 `distanceKm` 을 0 으로 채우면 30km 밖 관측소 값이 "이 자리 값"이 된다."""
    from floaq.web.ocean import OceanProxy

    rows = [{**WIND[0], "lat": 35.30, "lon": 129.40, "distanceKm": 28.4}]
    p, repo, _ = pump(FakeProxy(current=CURRENT, observations=rows))
    p.round_once()
    proxy = OceanProxy("http://nowhere.invalid", repo=repo, ship_id=SHIP)
    body, _ = proxy.get("observations", {"lat": 35.05, "lon": 129.10})
    st = body["data"][0]
    assert (st["lat"], st["lon"]) == (35.30, 129.40)
    assert st["distanceKm"] == 28.4

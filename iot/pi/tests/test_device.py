"""장치 상태 (`pi/device/status`).

🔴 **이 토픽이 키오스크 장치 패널의 전부다.** 발행하는 쪽이 없어서 카메라·AI·
   흔들림·부표가 시연 내내 '모름' 이었다 (2026-09-22). 그래서 여기서 비싼 것은
   각 장치의 세 상태를 **제대로 가르는가** 하나다:

       UNKNOWN  안 붙였다      — 정상이다
       ERROR    붙였는데 끊겼다 — 사람이 가서 봐야 한다
       OK       값이 들어온다
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq import device as dev
from floaq.adapters.memory import FakeClock, FakeLauncher, MemoryBus
from floaq.contracts import DeviceHealth as H
from floaq.contracts import JetsonStatus

T0 = 1_790_000_000
U, OK, ERR = H.UNKNOWN, H.OK, H.ERROR


class Stats:
    def __init__(self) -> None:
        self.ok = 0


class Link:
    def __init__(self) -> None:
        self.stats = Stats()


class Gnss:
    def __init__(self, age: float = 0.0) -> None:
        self._age = age

    def age(self) -> float:
        return self._age


class Imu:
    written = 0


class Edge:
    def __init__(self, last_ok_at: float = 0.0) -> None:
        self.last_ok_at = last_ok_at


def jetson(**kw) -> JetsonStatus:
    base = dict(model_version="v8", inference_fps=12.0, camera_l=OK, camera_r=OK,
                camera_dirty=False, gps_received=True, uptime_sec=60)
    return JetsonStatus(**{**base, **kw})


def build(**kw):
    bus, clock = MemoryBus(), FakeClock(T0)
    watch = dev.JetsonWatch()
    p = dev.DeviceStatusPump(bus, clock, launcher=FakeLauncher(),
                             jetson=watch, **kw)
    return p, bus, clock, watch


# ── 안 붙인 것과 죽은 것을 가른다 ────────────────────────────────────
def test_nothing_attached_is_unknown_not_error():
    """🔴 `--imu off` 로 띄운 Pi 가 '고장' 으로 보이면 안 된다."""
    p, _, _, _ = build()
    s = p.snapshot()
    assert (s.imu, s.lora, s.gps) == (U, U, U)
    assert (s.camera_l, s.camera_r, s.ai) == (U, U, U)


def test_attached_but_silent_is_error():
    """🔴 붙였는데 값이 안 오면 사람이 가서 봐야 한다. UNKNOWN 으로 숨기지 않는다."""
    p, _, _, _ = build(gnss=Gnss(age=9999), buoy=Link(), imu=Imu())
    s = p.snapshot()
    assert (s.imu, s.lora, s.gps) == (ERR, ERR, ERR)


def test_counters_moving_means_alive():
    """어댑터에 '마지막 수신 시각' 을 새로 안 달고 누적 카운터로 본다."""
    link, imu = Link(), Imu()
    p, _, _, _ = build(gnss=Gnss(age=1.0), buoy=link, imu=imu)
    p.round_once()                      # 첫 회차는 기준만 잡는다
    link.stats.ok += 3
    imu.written += 5
    p.round_once()
    s = p.snapshot()
    assert (s.imu, s.lora, s.gps) == (OK, OK, OK)


def test_first_round_does_not_claim_alive():
    """⚠ 처음 본 카운터 값은 '방금 들어온 것' 이 아니다. 재시작 직후가 그렇다."""
    link = Link()
    link.stats.ok = 4200               # 오래 돌던 링크를 뒤늦게 붙였다
    p, _, _, _ = build(buoy=link)
    p.round_once()
    assert p.snapshot().lora == ERR


# ── 젯슨 ─────────────────────────────────────────────────────────────
def test_jetson_values_pass_through():
    p, _, _, watch = build()
    watch.put(jetson(camera_r=ERR, camera_dirty=True))
    s = p.snapshot()
    assert (s.camera_l, s.camera_r, s.ai) == (OK, ERR, OK)
    assert s.camera_dirty is True


def test_dead_jetson_is_error_not_the_last_good_value():
    """🔴 젯슨을 뽑았는데 화면이 계속 정상이면 안 된다.

    마지막 retained 를 그대로 보여주면 그렇게 된다. 15초 규약을 여기서 건다.
    """
    p, _, _, watch = build()
    watch.put(jetson())
    watch._at -= dev.JETSON_DEAD_SEC + 1        # 15초 넘게 조용했다
    s = p.snapshot()
    assert (s.camera_l, s.camera_r, s.ai) == (ERR, ERR, ERR)
    assert s.camera_dirty is False


def test_never_seen_jetson_is_unknown():
    """한 번도 못 받은 것과 받다가 끊긴 것은 다르다."""
    p, _, _, _ = build()
    s = p.snapshot()
    assert (s.camera_l, s.ai) == (U, U)


# ── 인터넷 ───────────────────────────────────────────────────────────
def test_internet_is_false_when_unknown():
    """🔴 모르면 False 다. 키오스크가 '신고 불가' 를 띄우는 쪽이 안전하다."""
    p, _, _, _ = build()
    assert p.snapshot().internet is False


def test_any_server_answer_counts_as_internet():
    """⚠ 401 이든 409 든 대답이 왔으면 인터넷은 살아 있다.

    성공만 세면 보낼 게 없는 동안 끊긴 것으로 보인다.
    """
    p, _, _, _ = build(edge=Edge(last_ok_at=time.monotonic()))
    assert p.snapshot().internet is True


def test_old_answer_does_not_count():
    p, _, _, _ = build(edge=Edge(last_ok_at=time.monotonic()
                                 - dev.INTERNET_STALE_SEC - 1))
    assert p.snapshot().internet is False


# ── 발행 ─────────────────────────────────────────────────────────────
def test_publishes_every_round_even_when_nothing_changed():
    """🔴 변화 시에만 보내면 키오스크가 '값이 안 옴' 과 'Pi 가 죽음' 을 못 가른다."""
    p, bus, _, _ = build()
    p.round_once()
    p.round_once()
    sent = [m for m in bus.sent if m.subject == "pi/device/status"]
    assert len(sent) == 2
    assert all(m.retain for m in sent)          # 늦게 켠 화면도 바로 찬다


def test_is_loaded_comes_from_the_launcher():
    """장전 표시는 발사관이 말하는 것을 그대로 쓴다 (IOT-04 스위치 전까지 --loaded)."""
    p, _, _, _ = build()
    assert p.snapshot().is_loaded is True
    p.launcher.loaded = False
    assert p.snapshot().is_loaded is False


def test_last_buoy_rx_is_unix_and_only_set_on_real_reception():
    link = Link()
    p, _, clock, _ = build(buoy=link)
    p.round_once()
    assert p.snapshot().last_buoy_rx_at is None
    link.stats.ok += 1
    p.round_once()
    assert p.snapshot().last_buoy_rx_at == T0


def test_invalid_clock_does_not_stamp_a_wrong_time():
    """🔴 Pi 5 에는 RTC 가 없다. GPS fix 전의 시각을 박으면 1970 이 올라간다."""
    link = Link()
    p, _, clock, _ = build(buoy=link)
    clock.set_valid(False)
    p.round_once()
    link.stats.ok += 1
    p.round_once()
    assert p.snapshot().last_buoy_rx_at is None

"""부표 수신 -> 사고 붙이기 -> 저장 -> 발행 -> 두절 판정.

어댑터 시험(`test_lora_adapter.py`)이 "바이트를 프레임으로" 를 보고, 여기는
"프레임을 사고 기록으로" 를 본다. 라디오도 SQLite 도 없이 돈다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq import config
from floaq.adapters.memory import FakeClock, FakeLauncher, FakeReporter, MemoryBus, MemoryRepo
from floaq.contracts import JetsonDetection
from floaq.contracts.lora import BuoyFrame, Reception
from floaq.core.orchestrator import Orchestrator
from floaq.ids import uuid7

SHIP = uuid7()
T0 = 1_757_000_000
TAG = 0xC9


def build():
    clock = FakeClock(T0)
    bus, repo = MemoryBus(), MemoryRepo()
    orch = Orchestrator(ship_id=SHIP, clock=clock, bus=bus, repo=repo,
                        launcher=FakeLauncher(), reporter=FakeReporter())
    return orch, clock, bus, repo


def detection() -> JetsonDetection:
    return JetsonDetection(
        detection_id=uuid7(), ship_id=SHIP, lat=35.1, lon=129.0, distance_m=12.5,
        confidence=0.93, frame_count=5, model_version="v1", camera="L",
        bbox=(10, 20, 30, 40), detected_at=T0,
        launch=dict(target_yaw_deg=12.5, target_pitch_deg=20.0,
                    launch_profile="demo-low-v1", target_lat=35.11,
                    target_lon=129.01, solved_at=T0))


def rx(seq: int = 0, *, measured_at: int | None = None, rssi: float | None = -70.0,
       age: float = 0.0, lat: float = 35.11, lon: float = 129.01) -> Reception:
    return Reception(
        frame=BuoyFrame(ship_tag=TAG, seq=seq, lat=lat, lon=lon,
                        measured_at=T0 + seq if measured_at is None else measured_at,
                        is_pressed=True),
        rssi=rssi, age_sec=age)


def incident(orch):
    orch.on_detection(detection())
    return orch.repo.active()


# ── 사고에 붙이기 ────────────────────────────────────────────────────
def test_frame_without_accident_is_dropped():
    """🔴 프레임에 `accident_id` 가 없다. 붙일 사고가 없으면 기록할 곳도 없다.

    지난 사고 부표가 바다에 남아 계속 쏘는 경우가 이것이다.
    """
    orch, _, bus, repo = build()
    orch.on_buoy(rx())
    assert repo.buoys == []
    assert bus.count("pi/buoy/position") == 0


def test_frame_is_attached_to_the_active_accident():
    """동시 사고 1건(E1)이라 어느 사고인지 모호하지 않다."""
    orch, _, bus, repo = build()
    acc = incident(orch)
    orch.on_buoy(rx(0))

    assert len(repo.buoys) == 1
    assert repo.buoys[0]["accident_id"] == acc.accident_id
    msg = bus.last("pi/buoy/position")
    assert msg.accident_id == acc.accident_id
    assert msg.buoy_log_id == repo.buoys[0]["buoy_log_id"]
    assert msg.is_pressed == 1


def test_measured_at_and_received_at_are_different_columns():
    """🔴 지도에 찍는 건 측정 시각이다. 수신 시각으로 쓰면 두절 복귀 때
    몇 분 전 위치가 "방금"이 된다 (mqtt.md §3.4).
    """
    orch, clock, bus, repo = build()
    incident(orch)
    clock.advance(40)
    orch.on_buoy(rx(0, measured_at=T0 + 35))

    row = repo.buoys[0]
    assert row["created_at"] == T0 + 35        # 부표 GPS 가 잰 시각
    assert row["received_at"] == T0 + 40       # 우리가 들은 시각
    assert bus.last("pi/buoy/position").measured_at == T0 + 35


def test_received_at_subtracts_queue_age():
    """🔴 수신 스레드는 시계를 안 본다. 큐에 있던 시간을 빼서 환산한다."""
    orch, clock, _, repo = build()
    incident(orch)
    clock.advance(10)
    orch.on_buoy(rx(0, age=3.4))
    assert repo.buoys[0]["received_at"] == T0 + 10 - 3


def test_same_second_is_deduped_silently():
    """`UNIQUE (accident_id, created_at)` 이 초 단위다. 1Hz 전제의 의도한 dedup 이다."""
    orch, _, bus, repo = build()
    incident(orch)
    orch.on_buoy(rx(0, measured_at=T0))
    orch.on_buoy(rx(1, measured_at=T0))        # 같은 초, 다른 seq

    assert len(repo.buoys) == 1
    assert bus.count("pi/buoy/position") == 1  # 발행도 한 번뿐이다


def test_on_buoy_says_what_it_did():
    """`main.py` 가 이 값을 세어 5초 요약 로그로 찍는다."""
    orch, _, _, _ = build()
    assert orch.on_buoy(rx(0, measured_at=T0)) == "no_accident"
    incident(orch)
    assert orch.on_buoy(rx(1, measured_at=T0)) == "stored"
    assert orch.on_buoy(rx(2, measured_at=T0)) == "duplicate"


def test_rssi_passes_through_as_null_when_module_has_it_off():
    """E22 REG3 bit7 이 꺼져 있으면 RSSI 가 없다. 가짜 값을 지어내지 않는다."""
    orch, _, bus, repo = build()
    incident(orch)
    orch.on_buoy(rx(0, rssi=None))
    assert repo.buoys[0]["rssi"] is None
    assert bus.last("pi/buoy/position").rssi is None


# ── 두절 ─────────────────────────────────────────────────────────────
def test_no_comm_loss_before_the_first_frame():
    """🔴 한 번도 안 받은 상태는 두절이 아니다. 투하 전이다.

    안 막으면 **모든 사고가 두절로 시작한다.**
    """
    orch, clock, _, repo = build()
    incident(orch)
    clock.advance(config.BUOY_TIMEOUT_SEC + 10)
    orch.tick()
    assert repo.comm_losses == []


def test_comm_loss_opens_after_timeout():
    orch, clock, _, repo = build()
    acc = incident(orch)
    orch.on_buoy(rx(0))

    clock.advance(config.BUOY_TIMEOUT_SEC - 1)
    orch.tick()
    assert repo.comm_losses == []

    clock.advance(1)
    orch.tick()
    assert len(repo.comm_losses) == 1
    cl = repo.comm_losses[0]
    assert cl["accident_id"] == acc.accident_id
    assert cl["last_lat"] == 35.11
    # ⚠ 판정 기준을 행에 박제한다. 나중에 config 를 바꿔도 지난 구간이 설명돼야 한다
    assert cl["threshold_sec"] == config.BUOY_TIMEOUT_SEC
    assert cl["recovered_at"] is None


def test_comm_loss_is_opened_once_not_every_tick():
    orch, clock, _, repo = build()
    incident(orch)
    orch.on_buoy(rx(0))
    clock.advance(config.BUOY_TIMEOUT_SEC)
    for _ in range(5):
        orch.tick()
        clock.advance(1)
    assert len(repo.comm_losses) == 1


def test_next_frame_closes_the_loss_and_clears_drift():
    """표류 추정은 두절 중에만 의미가 있다. 실제 위치가 돌아오면 지운다."""
    orch, clock, bus, repo = build()
    incident(orch)
    orch.on_buoy(rx(0))
    clock.advance(config.BUOY_TIMEOUT_SEC)
    orch.tick()
    assert repo.comm_losses[0]["recovered_at"] is None

    clock.advance(5)
    orch.on_buoy(rx(1, measured_at=T0 + 65))
    assert repo.comm_losses[0]["recovered_at"] == T0 + 65
    assert "pi/buoy/drift" in [p.subject for p in bus.sent if p.payload is None]


def test_recovery_then_loss_opens_a_second_interval():
    orch, clock, _, repo = build()
    incident(orch)
    orch.on_buoy(rx(0))
    clock.advance(config.BUOY_TIMEOUT_SEC)
    orch.tick()

    clock.advance(1)
    orch.on_buoy(rx(1, measured_at=T0 + 61))
    clock.advance(config.BUOY_TIMEOUT_SEC)
    orch.tick()
    assert len(repo.comm_losses) == 2
    assert repo.comm_losses[0]["recovered_at"] is not None
    assert repo.comm_losses[1]["recovered_at"] is None


def test_broken_clock_holds_the_judgement():
    """🔴 RTC 없는 Pi 는 부팅 직후 시각이 과거다. 그러면 전부 "1분 넘게 안 왔다"로 보인다."""
    orch, clock, _, repo = build()
    incident(orch)
    orch.on_buoy(rx(0))
    clock.break_clock()
    orch.tick()
    assert repo.comm_losses == []


def test_buoy_is_watched_after_the_report_goes_out():
    """신고가 나간 뒤에도 익수자 위치는 계속 들어온다. 상태와 무관하게 본다."""
    orch, clock, _, repo = build()
    incident(orch)
    orch.on_buoy(rx(0))
    clock.advance(config.WAIT_SEC)
    orch.tick()                                     # 자동 신고로 REPORT 전이
    assert repo.active().status.value == "REPORT"

    clock.advance(config.BUOY_TIMEOUT_SEC)
    orch.tick()
    assert len(repo.comm_losses) == 1

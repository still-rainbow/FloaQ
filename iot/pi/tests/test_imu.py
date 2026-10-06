"""IMU 기록. **사고 10분 전 구간이 이 기능의 전부다.**

각도 수학은 싸다. 비싼 것은 "사고가 났을 때 그 앞 10분이 디스크에 있느냐" 다 —
없으면 사고 뒤에야 없다는 걸 안다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq import imu as pump_mod
from floaq.adapters.imu import G_MS2, FakeImu, Sample, Tilt, roll_pitch
from floaq.adapters.memory import FakeClock, MemoryBus, MemoryRepo
from floaq.contracts import AccidentStatus, AccidentType, ImuPosition, ReportType, TriggerSource
from floaq.core.domain import Accident
from floaq.ids import uuid7

SHIP = uuid7()
T0 = 1_757_000_000


# ── 각도 ─────────────────────────────────────────────────────────────
def test_level_board_is_zero():
    """+Z 만 서 있으면 수평이다."""
    r, p = roll_pitch(0.0, 0.0, 1.0)
    assert (round(r, 6), round(p, 6)) == (0.0, 0.0)


def test_real_measurement_from_the_boat():
    """🔴 배 바닥 실측값 (2026-09-22). 이 숫자가 바뀌면 부호 규약이 바뀐 것이다.

    ⚠ +X 가 뱃머리, +Z 가 위다. 반대로 붙이면 "선수가 들림" 과 "선미가 들림" 이
      뒤집힌다 — 화면에서 구분이 안 된다.
    """
    r, p = roll_pitch(-0.06, -0.02, 0.90)
    assert r == pytest.approx(-1.3, abs=0.1)
    assert p == pytest.approx(+3.8, abs=0.1)


def test_scale_error_does_not_move_the_angle():
    """⚠ 이 칩은 정지 |a| 가 0.90g 다(1.00 이어야 한다). 각도는 비율이라 상쇄된다.

    그래서 스케일을 억지로 1.0 으로 늘리지 않는다 — 늘리면 흔들릴 때 1.0 을 넘는
    진짜 가속을 가린다.
    """
    good = roll_pitch(-0.06, -0.02, 0.90)
    scaled = roll_pitch(-0.06 / 0.9, -0.02 / 0.9, 0.90 / 0.9)
    assert good == pytest.approx(scaled, abs=1e-9)


def test_zero_offset_cancels_the_mounting_tilt():
    z = Tilt(roll=-1.3, pitch=3.8)
    r, p = z.apply(*roll_pitch(-0.06, -0.02, 0.90))
    assert abs(r) < 0.1 and abs(p) < 0.1


def test_missing_zero_means_no_angle_not_zero_angle(tmp_path):
    """🔴 영점이 없으면 각도를 **모르는 것**이다. 0 은 "수평" 으로 읽힌다."""
    assert Tilt.load(tmp_path / "없다.json") is None
    assert FakeImu().sample().roll is None


def test_broken_zero_file_is_treated_as_missing(tmp_path):
    """⚠ 깨진 영점을 0 으로 대신하지 않는다. 그게 제일 나쁜 값이다."""
    p = tmp_path / "z.json"
    p.write_text("{쓰레기", encoding="utf-8")
    assert Tilt.load(p) is None


def test_zero_round_trips(tmp_path):
    p = tmp_path / "z.json"
    Tilt(roll=-1.25, pitch=3.75).save(p)
    z = Tilt.load(p)
    assert z is not None and (z.roll, z.pitch) == (-1.25, 3.75)


# ── 펌프 ─────────────────────────────────────────────────────────────
def build(*, zero=Tilt(0.0, 0.0)):
    repo, bus, clock = MemoryRepo(), MemoryBus(), FakeClock(T0)
    imu = FakeImu(roll=2.0, pitch=-3.0, zero=zero)
    p = pump_mod.ImuPump(repo, bus, clock, SHIP, imu)
    return p, repo, bus, clock


def accident(repo, clock, at: int) -> Accident:
    acc = Accident(
        accident_id=uuid7(), ship_id=SHIP, status=AccidentStatus.REPORT,
        accident_type=AccidentType.MOB, trigger_source=TriggerSource.AI,
        report_type=ReportType.DISTRESS, report_dsc=110,
        accident_lat=35.1, accident_lon=129.0, wait_sec=30, report_due_at=None,
        model_version="v1", created_at=at, updated_at=at)
    repo.create(acc)
    return acc


def run_for(p, clock, seconds: int) -> None:
    for _ in range(seconds):
        p.round_once()
        clock.advance(1)


def test_writes_to_disk_every_second():
    """🔴 인메모리 링버퍼를 쓰지 않는다. 재시작에 사고 전 구간이 사라진다."""
    p, repo, _, clock = build()
    run_for(p, clock, 5)
    assert len(repo.imu_log) == 5
    assert p.written == 5


def test_same_second_is_not_duplicated():
    """UNIQUE (ship_id, created_at, imu_position). 주기가 흔들려도 한 초 한 행"""
    p, repo, _, clock = build()
    p.round_once()
    p.round_once()                       # 시계를 안 돌렸다
    assert len(repo.imu_log) == 1


def test_publishes_for_the_kiosk():
    """키오스크는 사고가 없어도 자세를 봐야 한다."""
    p, _, bus, clock = build()
    run_for(p, clock, 3)
    sent = [m for m in bus.sent if m.subject == "pi/sensor/imu"]
    assert len(sent) == 3
    assert sent[0].payload.roll == pytest.approx(2.0)
    assert sent[0].payload.imu_position == ImuPosition.HULL


def test_no_zero_means_no_publish():
    """🔴 각도를 모르면 발행하지 않는다. 0 을 보내면 화면이 "수평" 으로 그린다.

    ⚠ 그래도 **기록은 한다** — 나중에 영점을 잡으면 그 구간을 다시 해석할 수 있다.
    """
    p, repo, bus, clock = build(zero=None)
    run_for(p, clock, 3)
    assert [m for m in bus.sent if m.subject == "pi/sensor/imu"] == []
    assert len(repo.imu_log) == 3


def test_invalid_clock_writes_nothing():
    """🔴 Pi 5 에는 RTC 가 없다. created_at 이 틀리면 창을 긁을 때 범위 밖이 된다."""
    p, repo, _, clock = build()
    clock.set_valid(False)
    run_for(p, clock, 3)
    assert repo.imu_log == []


# ── 사고 전 10분 ─────────────────────────────────────────────────────
def test_pre_accident_window_lands_in_pi_imu():
    """🔴 이게 이 기능의 존재 이유다. 사고 **전** 구간이 관제로 가야 한다.

    `pi_imu.accident_id` 가 NOT NULL 이라 사고가 생기기 전에는 거기 못 쓴다.
    상시 로그에 쌓아 두고 사고가 나면 창을 옮긴다.
    """
    p, repo, _, clock = build()
    run_for(p, clock, 30)                       # 사고 전 30초
    assert repo.imus == []                      # 아직 사고가 없다

    accident(repo, clock, clock.now())
    p.round_once()

    assert len(repo.imus) == 31                 # 앞 30초 + 지금
    assert all(r["accident_id"] for r in repo.imus)


def test_window_reaches_back_ten_minutes_not_further():
    """PRE_SEC 만큼만. 더 올리면 좁은 어선 상향 대역이 죽는다."""
    p, repo, _, clock = build()
    run_for(p, clock, 40)
    # 사고가 아주 옛날에 난 것처럼 두면 앞쪽 로그가 창 밖이다
    acc = accident(repo, clock, clock.now())
    p.round_once()
    oldest = min(r["created_at"] for r in repo.imus)
    assert oldest >= acc.created_at - pump_mod.PRE_SEC


def test_during_accident_the_window_keeps_extending():
    """사고 중 구간도 이어 붙어야 한다. 사고 시점에서 끊기면 안 된다."""
    p, repo, _, clock = build()
    run_for(p, clock, 5)
    accident(repo, clock, clock.now())
    run_for(p, clock, 10)
    assert len(repo.imus) == 15


def test_copy_is_idempotent():
    """⚠ 매 초 부른다. 두 번 옮겨도 행이 늘면 안 된다."""
    p, repo, _, clock = build()
    run_for(p, clock, 5)
    accident(repo, clock, clock.now())
    p.round_once()
    n = len(repo.imus)
    p.round_once()                              # 같은 초, 다시
    assert len(repo.imus) == n


def test_rows_without_angle_are_not_carried():
    """🔴 `pi_imu.roll` 은 NOT NULL 이다. 0 으로 채우면 "수평이었다" 는 거짓 기록이다."""
    p, repo, _, clock = build(zero=None)        # 각도를 모르는 상태로 기록
    run_for(p, clock, 5)
    accident(repo, clock, clock.now())
    p.round_once()
    assert repo.imus == []
    assert len(repo.imu_log) == 6               # 로그에는 남아 있다


def test_old_log_is_pruned():
    """🔴 1Hz 다. 프룬이 없으면 microSD 가 하루 8.6만 행씩 찬다."""
    p, repo, _, clock = build()
    p.round_once()
    clock.advance(pump_mod.KEEP_SEC + pump_mod.PRUNE_EVERY_SEC + 1)
    p.round_once()
    # 오래된 첫 행은 지워지고 방금 것만 남는다
    assert len(repo.imu_log) == 1


def test_keep_window_is_longer_than_what_we_upload():
    """⚠ 딱 맞추면 사고 직전 행이 프룬과 경합해 사라진다."""
    assert pump_mod.KEEP_SEC > pump_mod.PRE_SEC

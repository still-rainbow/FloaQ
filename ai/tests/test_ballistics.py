from __future__ import annotations

import math

from src.ballistics import solve_fixed_speed_aim, solve_line_of_sight_aim


def test_line_of_sight_aim_does_not_need_launch_speed() -> None:
    solution = solve_line_of_sight_aim(1.0, -1.0, 1.0)
    assert solution.reachable
    assert math.isclose(solution.yaw_deg, 45.0)
    assert solution.pitch_deg is not None
    assert math.isclose(solution.pitch_deg, math.degrees(math.atan2(1.0, math.sqrt(2.0))))


def test_missing_launch_speed_blocks_solution() -> None:
    solution = solve_fixed_speed_aim(0.0, 0.0, 10.0, None)
    assert not solution.reachable
    assert solution.pitch_deg is None
    assert solution.reason == "launch_speed_not_calibrated"


def test_level_target_uses_low_trajectory() -> None:
    solution = solve_fixed_speed_aim(0.0, 0.0, 10.0, 15.0)
    expected = math.degrees(0.5 * math.asin(9.80665 * 10.0 / 15.0**2))
    assert solution.reachable
    assert solution.pitch_deg is not None
    assert math.isclose(solution.pitch_deg, expected, abs_tol=1e-7)


def test_yaw_is_clockwise_to_camera_right() -> None:
    solution = solve_fixed_speed_aim(1.0, 0.0, 1.0, 10.0)
    assert math.isclose(solution.yaw_deg, 45.0)


def test_pitch_limit_rejects_trajectory() -> None:
    solution = solve_fixed_speed_aim(0.0, -5.0, 1.0, 10.0, max_pitch_deg=20.0)
    assert not solution.reachable
    assert solution.reason == "pitch_out_of_range"

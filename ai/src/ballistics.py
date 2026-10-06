from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AimSolution:
    yaw_deg: float
    pitch_deg: float | None
    horizontal_range_m: float
    height_m: float
    reachable: bool
    reason: str | None = None


def solve_line_of_sight_aim(
    x_m: float,
    y_down_m: float,
    z_m: float,
    *,
    min_pitch_deg: float = -45.0,
    max_pitch_deg: float = 45.0,
) -> AimSolution:
    """Point directly at a target without projectile-drop compensation."""
    horizontal_range = math.hypot(x_m, z_m)
    yaw_deg = math.degrees(math.atan2(x_m, z_m))
    height_m = -y_down_m
    if horizontal_range <= 0:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "target_too_close")
    pitch_deg = math.degrees(math.atan2(height_m, horizontal_range))
    if not min_pitch_deg <= pitch_deg <= max_pitch_deg:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "pitch_out_of_range")
    return AimSolution(yaw_deg, pitch_deg, horizontal_range, height_m, True)


def solve_fixed_speed_aim(
    x_m: float,
    y_down_m: float,
    z_m: float,
    launch_speed_mps: float | None,
    *,
    gravity_mps2: float = 9.80665,
    min_pitch_deg: float = -45.0,
    max_pitch_deg: float = 45.0,
) -> AimSolution:
    """Solve yaw/pitch in the camera frame (x right, y down, z forward).

    ``y_down_m`` is converted to conventional upward height for the projectile
    equation. The lower valid trajectory is preferred because it has the
    shorter flight time. A missing launch speed deliberately yields no pitch:
    fixed-force launchers must be measured before they can be aimed safely.
    """
    horizontal_range = math.hypot(x_m, z_m)
    yaw_deg = math.degrees(math.atan2(x_m, z_m))
    height_m = -y_down_m

    if horizontal_range <= 0:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "target_too_close")
    if launch_speed_mps is None or launch_speed_mps <= 0:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "launch_speed_not_calibrated")

    speed_sq = launch_speed_mps * launch_speed_mps
    discriminant = speed_sq * speed_sq - gravity_mps2 * (
        gravity_mps2 * horizontal_range * horizontal_range + 2.0 * height_m * speed_sq
    )
    if discriminant < 0:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "target_unreachable")

    root = math.sqrt(discriminant)
    pitches = sorted(
        math.degrees(math.atan((speed_sq + sign * root) / (gravity_mps2 * horizontal_range)))
        for sign in (-1.0, 1.0)
    )
    pitch = next((value for value in pitches if min_pitch_deg <= value <= max_pitch_deg), None)
    if pitch is None:
        return AimSolution(yaw_deg, None, horizontal_range, height_m, False, "pitch_out_of_range")
    return AimSolution(yaw_deg, pitch, horizontal_range, height_m, True)

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any


@dataclass(frozen=True)
class ServoEstimate:
    command: float | None
    calibrated: bool
    minimum_angle_deg: float
    maximum_angle_deg: float
    reason: str | None = None


def estimate_servo_command(
    angle_deg: float | None,
    calibration_points: Iterable[dict[str, Any]],
) -> ServoEstimate:
    """Linearly interpolate a command only inside the measured angle range."""
    points = sorted(
        (
            (float(point["angle_deg"]), float(point["command"]))
            for point in calibration_points
        ),
        key=lambda point: point[0],
    )
    if len(points) < 2:
        raise ValueError("at least two servo calibration points are required")
    if len({angle for angle, _ in points}) != len(points):
        raise ValueError("servo calibration angles must be unique")

    minimum_angle = points[0][0]
    maximum_angle = points[-1][0]
    if angle_deg is None:
        return ServoEstimate(
            None,
            False,
            minimum_angle,
            maximum_angle,
            "aim_angle_unavailable",
        )
    if not minimum_angle <= angle_deg <= maximum_angle:
        return ServoEstimate(
            None,
            False,
            minimum_angle,
            maximum_angle,
            "outside_calibrated_range",
        )

    for (angle_a, command_a), (angle_b, command_b) in pairwise(points):
        if angle_a <= angle_deg <= angle_b:
            ratio = (angle_deg - angle_a) / (angle_b - angle_a)
            command = command_a + ratio * (command_b - command_a)
            return ServoEstimate(command, True, minimum_angle, maximum_angle)
    raise RuntimeError("failed to find a servo calibration interval")

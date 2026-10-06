"""조준 해 계산.

⚠ 2026-09-22 에 방식이 통째로 바뀌었다 (`feat/jetson-headless-stereo-calibration`).
  OpenCV rectify + Q 행렬을 버리고, **원본 bbox 중심 광선 두 개를 교차**시킨다.
  보정 파일(`stereo_calibration.npz`)이 없어도 돌게 하려는 것이다 — 그 파일이
  저장소에 없어서 `--aim-only` 가 기동조차 못 했다.

  그래서 `rectified_to_launcher` 시험은 지웠다. 함수 자체가 없어졌다.
"""

from __future__ import annotations

import numpy as np
import pytest

from floaq_jetson._stereo_aiming import (
    solve_pointing, triangulate_raw_bboxes,
)

#: 실물 배치 (`configs/stereo_targeting.yaml`)
GEOM = dict(
    horizontal_fov_deg=52.0,
    left_position_m=[-0.170, -0.015, 0.090],
    right_position_m=[0.185, -0.015, 0.105],
    left_yaw_deg=8.5,
    right_yaw_deg=-5.5,
)
SIZE = (1280, 720)


def bbox_at(cx: float, cy: float = 360.0, w: float = 60.0, h: float = 160.0):
    """중심이 `(cx, cy)` 인 bbox. 입력은 (x, y, w, h) 다"""
    return (cx - w / 2, cy - h / 2, w, h)


def test_pointing_is_computed_in_launcher_frame() -> None:
    pointing = solve_pointing([1.0, -1.0, 1.0])
    assert pointing.yaw_deg == 45.0
    assert round(pointing.pitch_deg, 6) == round(35.264389682754654, 6)
    assert round(pointing.range_m, 6) == round(2**0.5, 6)


def test_parallel_rays_are_rejected() -> None:
    """🔴 두 광선이 평행하면 교점이 없다. 억지로 풀면 좌표가 발산한다."""
    same = bbox_at(640.0)
    got = triangulate_raw_bboxes(
        same, same, SIZE,
        **{**GEOM, "left_yaw_deg": 0.0, "right_yaw_deg": 0.0,
           "left_position_m": [0.0, 0.0, 0.0], "right_position_m": [0.0, 0.0, 0.5]})
    assert got is None


def test_target_is_in_front_not_behind() -> None:
    """🔴 뒤쪽 교차를 거부해야 한다. 카메라 뒤에 익수자가 있다고 나오면 안 된다."""
    got = triangulate_raw_bboxes(bbox_at(400.0), bbox_at(880.0), SIZE, **GEOM)
    if got is not None:
        assert got[2] > 0, "z 가 음수 — 뒤쪽이다"


def test_centre_bboxes_give_a_target_in_front() -> None:
    got = triangulate_raw_bboxes(bbox_at(700.0), bbox_at(560.0), SIZE, **GEOM)
    assert got is not None
    assert got[2] > 0


def test_ballistic_pitch_lowers_near_and_raises_far() -> None:
    """고정 스프링이라 거리는 발사각이 정한다. 가까우면 숙이고 멀면 든다."""
    from floaq_jetson._stereo_aiming import ballistic_pitch, landing_range

    speed, height = 2.75, 0.30
    near = ballistic_pitch(0.60, speed, height, -10.0, 25.0)
    far = ballistic_pitch(0.85, speed, height, -10.0, 25.0)
    assert -10.0 < near < far < 25.0
    # 곡선 그대로 풀었으니 그 각도로 쏘면 그 거리에 떨어진다
    assert abs(landing_range(near, speed, height) - 0.60) < 1e-6
    assert abs(landing_range(far, speed, height) - 0.85) < 1e-6
    # 아래 끝으로도 넘어가는 가까운 목표는 아래 끝, 못 닿는 목표는 위 끝
    assert ballistic_pitch(0.20, speed, height, -10.0, 25.0) == -10.0
    assert ballistic_pitch(5.00, speed, height, -10.0, 25.0) == 25.0


def test_fit_ballistics_recovers_speed_and_height() -> None:
    from floaq_jetson._stereo_aiming import fit_ballistics, landing_range

    shots = [(angle, landing_range(angle, 3.1, 0.42)) for angle in (-10.0, 15.0)]
    speed, height = fit_ballistics(*shots)
    assert abs(speed - 3.1) < 0.01 and abs(height - 0.42) < 0.01


def test_near_and_far_distances_map_to_the_pitch_limits() -> None:
    """yaml 에는 두 거리만 적는다 — 아래 끝·위 끝으로 쐈을 때 떨어지는 곳."""
    from floaq_jetson._stereo_aiming import ballistic_pitch, fit_ballistics

    speed, height = fit_ballistics((-10.0, 0.20), (25.0, 0.60))
    assert ballistic_pitch(0.20, speed, height, -10.0, 25.0) <= -9.9
    assert ballistic_pitch(0.60, speed, height, -10.0, 25.0) >= 24.9
    middle = ballistic_pitch(0.40, speed, height, -10.0, 25.0)
    assert -10.0 < middle < 25.0

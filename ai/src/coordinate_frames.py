from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def rectified_to_camera_frame(
    target_in_rectified_camera_m: Iterable[float],
    rotation_rectified_from_camera: Iterable[Iterable[float]],
) -> np.ndarray:
    """Return a rectified stereo point in the physical left-camera frame."""
    target = np.asarray(target_in_rectified_camera_m, dtype=float)
    rotation = np.asarray(rotation_rectified_from_camera, dtype=float)
    if target.shape != (3,):
        raise ValueError("target must contain three values")
    if rotation.shape != (3, 3):
        raise ValueError("rectification rotation must be a 3x3 matrix")
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(rotation)):
        raise ValueError("target and rectification rotation must be finite")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-5):
        raise ValueError("rectification rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-5):
        raise ValueError("rectification rotation must have determinant +1")
    return rotation.T @ target


def target_in_launcher_frame(
    target_in_camera_m: Iterable[float],
    launcher_origin_in_camera_m: Iterable[float],
    rotation_launcher_from_camera: Iterable[Iterable[float]],
) -> np.ndarray:
    """Transform a target from the camera frame into the launcher frame.

    ``rotation_launcher_from_camera`` rotates camera-frame vectors into the
    launcher frame. Both frames use x-right, y-down, z-forward axes.
    """
    target = np.asarray(target_in_camera_m, dtype=float)
    origin = np.asarray(launcher_origin_in_camera_m, dtype=float)
    rotation = np.asarray(rotation_launcher_from_camera, dtype=float)
    if target.shape != (3,) or origin.shape != (3,):
        raise ValueError("target and launcher origin must each contain three values")
    if rotation.shape != (3, 3):
        raise ValueError("rotation_launcher_from_camera must be a 3x3 matrix")
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(origin)):
        raise ValueError("target and launcher origin must be finite")
    if not np.all(np.isfinite(rotation)):
        raise ValueError("rotation matrix must be finite")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-5):
        raise ValueError("rotation matrix must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-5):
        raise ValueError("rotation matrix must have determinant +1")
    return rotation @ (target - origin)

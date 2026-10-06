import math

import numpy as np

from floaq_jetson.stereo_calibrate import _is_distinct_pose, _pose_descriptor


def test_pose_descriptor_normalizes_center_and_scale():
    corners = np.asarray([[[20.0, 20.0]], [[80.0, 20.0]], [[80.0, 60.0]]])

    descriptor = _pose_descriptor(corners, (100, 100))

    np.testing.assert_allclose(descriptor[:2], [0.6, 1 / 3])
    np.testing.assert_allclose(descriptor[2], math.hypot(0.6, 0.4))


def test_distinct_pose_rejects_near_duplicate():
    saved = [np.asarray([0.5, 0.5, 0.4, 0.0])]

    assert not _is_distinct_pose(np.asarray([0.51, 0.51, 0.41, 0.02]), saved)


def test_distinct_pose_accepts_translation_scale_or_rotation():
    saved = [np.asarray([0.5, 0.5, 0.4, 0.0])]

    assert _is_distinct_pose(np.asarray([0.56, 0.5, 0.4, 0.0]), saved)
    assert _is_distinct_pose(np.asarray([0.5, 0.5, 0.45, 0.0]), saved)
    assert _is_distinct_pose(np.asarray([0.5, 0.5, 0.4, math.radians(10)]), saved)

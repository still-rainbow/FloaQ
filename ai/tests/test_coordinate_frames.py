import unittest

import numpy as np

from src.coordinate_frames import rectified_to_camera_frame, target_in_launcher_frame


class CoordinateFramesTest(unittest.TestCase):
    def test_converts_rectified_point_back_to_physical_camera(self) -> None:
        rotation = [
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
        ]
        result = rectified_to_camera_frame([5.0, 2.0, -1.0], rotation)
        np.testing.assert_allclose(result, [1.0, 2.0, 5.0])

    def test_translates_camera_target_to_launcher_origin(self) -> None:
        result = target_in_launcher_frame(
            [1.0, 2.0, 5.0],
            [0.25, 0.5, 1.0],
            np.eye(3),
        )
        np.testing.assert_allclose(result, [0.75, 1.5, 4.0])

    def test_applies_launcher_axis_rotation(self) -> None:
        rotation = [
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
        ]
        result = target_in_launcher_frame([1.0, 2.0, 5.0], [0.0, 0.0, 0.0], rotation)
        np.testing.assert_allclose(result, [5.0, 2.0, -1.0])

    def test_rejects_non_rotation_matrix(self) -> None:
        with self.assertRaisesRegex(ValueError, "orthonormal"):
            target_in_launcher_frame(
                [1.0, 2.0, 5.0],
                [0.0, 0.0, 0.0],
                [[2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            )


if __name__ == "__main__":
    unittest.main()

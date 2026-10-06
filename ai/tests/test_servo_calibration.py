import unittest

from src.servo_calibration import estimate_servo_command

POINTS = [
    {"command": 110.0, "angle_deg": 2.5},
    {"command": 90.0, "angle_deg": 25.0},
]


class ServoCalibrationTest(unittest.TestCase):
    def test_returns_measured_endpoints(self) -> None:
        self.assertEqual(estimate_servo_command(2.5, POINTS).command, 110.0)
        self.assertEqual(estimate_servo_command(25.0, POINTS).command, 90.0)

    def test_interpolates_reversed_command_direction(self) -> None:
        estimate = estimate_servo_command(10.0, POINTS)
        self.assertTrue(estimate.calibrated)
        self.assertAlmostEqual(estimate.command or 0.0, 103.333333, places=5)

    def test_refuses_to_extrapolate(self) -> None:
        estimate = estimate_servo_command(1.0, POINTS)
        self.assertFalse(estimate.calibrated)
        self.assertIsNone(estimate.command)
        self.assertEqual(estimate.reason, "outside_calibrated_range")


if __name__ == "__main__":
    unittest.main()

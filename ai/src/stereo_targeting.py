from __future__ import annotations

import argparse
import json
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

from .ballistics import solve_fixed_speed_aim, solve_line_of_sight_aim
from .coordinate_frames import rectified_to_camera_frame, target_in_launcher_frame
from .servo_calibration import estimate_servo_command
from .utils import load_config


class StereoTargeting:
    def __init__(self, config: dict[str, Any], weights: str | Path) -> None:
        self.config = config
        calibration_path = Path(config["calibration_file"])
        if not calibration_path.is_file():
            raise FileNotFoundError(f"Calibration not found: {calibration_path}")
        calibration = np.load(calibration_path)
        self.image_size = tuple(int(value) for value in calibration["image_size"])
        self.q = calibration["q"]
        self.rotation_rectified_from_left_camera = calibration["left_r"]
        self.left_maps = cv2.initUndistortRectifyMap(
            calibration["left_k"],
            calibration["left_d"],
            calibration["left_r"],
            calibration["left_p"],
            self.image_size,
            cv2.CV_32FC1,
        )
        self.right_maps = cv2.initUndistortRectifyMap(
            calibration["right_k"],
            calibration["right_d"],
            calibration["right_r"],
            calibration["right_p"],
            self.image_size,
            cv2.CV_32FC1,
        )
        stereo = config["stereo"]
        num_disparities = int(stereo["num_disparities"])
        block_size = int(stereo["block_size"])
        if num_disparities <= 0 or num_disparities % 16:
            raise ValueError("stereo.num_disparities must be a positive multiple of 16")
        if block_size < 3 or block_size % 2 == 0:
            raise ValueError("stereo.block_size must be odd and at least 3")
        self.matcher = cv2.StereoSGBM_create(
            minDisparity=int(stereo.get("min_disparity", 0)),
            numDisparities=num_disparities,
            blockSize=block_size,
            P1=8 * 3 * block_size**2,
            P2=32 * 3 * block_size**2,
            disp12MaxDiff=int(stereo.get("disp12_max_diff", 1)),
            uniquenessRatio=int(stereo.get("uniqueness_ratio", 10)),
            speckleWindowSize=int(stereo.get("speckle_window_size", 100)),
            speckleRange=int(stereo.get("speckle_range", 2)),
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )
        self.model = YOLO(str(weights))
        matching_ids = [
            int(class_id)
            for class_id, name in self.model.names.items()
            if str(name).lower() == "person"
        ]
        if not matching_ids:
            raise ValueError(f"Model has no 'person' class: {self.model.names}")
        self.person_class_id = matching_ids[0]
        self.history: deque[np.ndarray] = deque(
            maxlen=int(config["stability"]["sample_count"])
        )

    def process(
        self,
        left_frame: np.ndarray,
        right_frame: np.ndarray,
        *,
        captured_at_s: float | None = None,
    ) -> tuple[dict[str, Any] | None, np.ndarray]:
        captured_at_s = captured_at_s if captured_at_s is not None else time.monotonic()
        if (left_frame.shape[1], left_frame.shape[0]) != self.image_size or (
            right_frame.shape[1],
            right_frame.shape[0],
        ) != self.image_size:
            raise ValueError(
                f"Camera frames must match calibration size {self.image_size}"
            )
        left = cv2.remap(left_frame, *self.left_maps, cv2.INTER_LINEAR)
        right = cv2.remap(right_frame, *self.right_maps, cv2.INTER_LINEAR)
        prediction = self.model.predict(
            left,
            conf=float(self.config["detection"]["confidence"]),
            iou=float(self.config["detection"].get("iou", 0.7)),
            classes=[self.person_class_id],
            device=self.config["detection"].get("device", 0),
            verbose=False,
        )[0]
        if prediction.boxes is None or len(prediction.boxes) == 0:
            self.history.clear()
            return None, left
        best_index = int(np.argmax(prediction.boxes.conf.cpu().numpy()))
        box = prediction.boxes.xyxy[best_index].cpu().numpy().astype(int)
        confidence = float(prediction.boxes.conf[best_index].item())
        disparity = (
            self.matcher.compute(
                cv2.cvtColor(left, cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(right, cv2.COLOR_BGR2GRAY),
            ).astype(np.float32)
            / 16.0
        )
        point_rectified = self._robust_target_point(disparity, box)
        if point_rectified is None:
            self.history.clear()
            return {
                "person_confidence": confidence,
                "valid_depth": False,
                "fire_allowed": False,
            }, left
        point_left_camera = rectified_to_camera_frame(
            point_rectified, self.rotation_rectified_from_left_camera
        )
        launcher = self.config["launcher"]
        target_launcher = target_in_launcher_frame(
            point_left_camera,
            launcher["origin_in_left_camera_m"],
            launcher.get("rotation_launcher_from_left_camera", np.eye(3)),
        )
        aim = solve_fixed_speed_aim(
            float(target_launcher[0]),
            float(target_launcher[1]),
            float(target_launcher[2]),
            launcher.get("launch_speed_mps"),
            gravity_mps2=float(launcher.get("gravity_mps2", 9.80665)),
            min_pitch_deg=float(launcher.get("min_pitch_deg", -45.0)),
            max_pitch_deg=float(launcher.get("max_pitch_deg", 45.0)),
        )
        pointing = solve_line_of_sight_aim(
            float(target_launcher[0]),
            float(target_launcher[1]),
            float(target_launcher[2]),
            min_pitch_deg=float(launcher.get("min_pitch_deg", -45.0)),
            max_pitch_deg=float(launcher.get("max_pitch_deg", 45.0)),
        )
        pitch_points = launcher.get("pitch_servo_calibration")
        pitch_servo = (
            asdict(estimate_servo_command(aim.pitch_deg, pitch_points))
            if pitch_points
            else {
                "command": None,
                "calibrated": False,
                "minimum_angle_deg": None,
                "maximum_angle_deg": None,
                "reason": "servo_calibration_unavailable",
            }
        )
        self.history.append(np.asarray([
            pointing.yaw_deg, pointing.pitch_deg or 0.0, pointing.horizontal_range_m
        ]))
        stable = self._is_stable() and pointing.reachable
        processed_at_s = time.monotonic()
        result = {
            "timestamp": time.time(),
            "capture_timestamp_s": captured_at_s,
            "processed_timestamp_s": processed_at_s,
            "processing_latency_s": processed_at_s - captured_at_s,
            "person_confidence": confidence,
            "valid_depth": True,
            "target_camera_m": {
                "x_right": float(point_left_camera[0]),
                "y_down": float(point_left_camera[1]),
                "z_forward": float(point_left_camera[2]),
            },
            "target_rectified_camera_m": {
                "x_right": float(point_rectified[0]),
                "y_down": float(point_rectified[1]),
                "z_forward": float(point_rectified[2]),
            },
            "target_launcher_m": {
                "x_right": float(target_launcher[0]),
                "y_down": float(target_launcher[1]),
                "z_forward": float(target_launcher[2]),
            },
            "aim": asdict(aim),
            "pointing": asdict(pointing),
            "actuator": {
                "pitch": pitch_servo,
                # Yaw command conversion is intentionally unavailable until
                # its zero, sign and measured calibration points are supplied.
                "yaw_command": None,
            },
            "stable": stable,
            # This module never actuates hardware. A separate controller must
            # perform interlocks and explicit fire authorization.
            "fire_allowed": False,
        }
        cv2.rectangle(left, tuple(box[:2]), tuple(box[2:]), (0, 255, 0), 2)
        cv2.putText(
            left,
            f"person {aim.horizontal_range_m:.2f}m yaw {aim.yaw_deg:.1f}",
            tuple(box[:2]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )
        return result, left

    def _robust_target_point(
        self, disparity: np.ndarray, box: np.ndarray
    ) -> np.ndarray | None:
        height, width = disparity.shape
        x1, y1, x2, y2 = box
        margin_x = max(2, int((x2 - x1) * 0.25))
        margin_y = max(2, int((y2 - y1) * 0.2))
        x1, x2 = max(0, x1 + margin_x), min(width, x2 - margin_x)
        y1, y2 = max(0, y1 + margin_y), min(height, y2 - margin_y)
        if x2 <= x1 or y2 <= y1:
            return None
        roi = disparity[y1:y2, x1:x2]
        minimum = float(self.config["stereo"].get("minimum_valid_disparity", 1.0))
        valid_y, valid_x = np.where(np.isfinite(roi) & (roi > minimum))
        minimum_pixels = int(self.config["stereo"].get("minimum_valid_pixels", 80))
        if valid_x.size < minimum_pixels:
            return None
        median_disparity = float(np.median(roi[valid_y, valid_x]))
        median_x = int(np.median(valid_x)) + x1
        median_y = int(np.median(valid_y)) + y1
        homogeneous = self.q @ np.asarray([median_x, median_y, median_disparity, 1.0])
        if abs(homogeneous[3]) < 1e-9:
            return None
        point = homogeneous[:3] / homogeneous[3]
        if not np.all(np.isfinite(point)) or point[2] <= 0:
            return None
        return point

    def _is_stable(self) -> bool:
        if len(self.history) < self.history.maxlen:
            return False
        deviation = np.std(np.stack(self.history), axis=0)
        stability = self.config["stability"]
        return bool(
            deviation[0] <= float(stability["max_yaw_std_deg"])
            and deviation[1] <= float(stability["max_pitch_std_deg"])
            and deviation[2] <= float(stability["max_range_std_m"])
        )


def _open_camera(index: int, image_size: tuple[int, int]) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, image_size[0])
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, image_size[1])
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open camera index {index}")
    return camera


def run(config_path: str, weights: str, headless: bool) -> None:
    config = load_config(config_path)
    targeting = StereoTargeting(config, weights)
    left_camera = _open_camera(
        int(config["cameras"]["left_index"]), targeting.image_size
    )
    right_camera = _open_camera(
        int(config["cameras"]["right_index"]), targeting.image_size
    )
    try:
        while True:
            ok_left, left = left_camera.read()
            ok_right, right = right_camera.read()
            if not ok_left or not ok_right:
                raise RuntimeError("Failed to read a synchronized stereo pair")
            result, preview = targeting.process(
                left, right, captured_at_s=time.monotonic()
            )
            if result is not None:
                print(json.dumps(result, ensure_ascii=False), flush=True)
            if not headless:
                cv2.imshow("stereo person targeting", preview)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    finally:
        left_camera.release()
        right_camera.release()
        cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect a person and estimate stereo range and launcher aim."
    )
    parser.add_argument("--config", default="configs/stereo_targeting.yaml")
    parser.add_argument(
        "--weights",
        default="models/best_performance.pt",
        help="Path to YOLO weights (default: models/best_performance.pt)",
    )
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.config, args.weights, args.headless)

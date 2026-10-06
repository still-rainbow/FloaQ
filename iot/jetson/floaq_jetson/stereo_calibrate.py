"""고정된 좌우 카메라의 내부·외부 파라미터를 체스보드로 생성한다."""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import cv2
import numpy as np


def _pose_descriptor(corners, image_size):
    """Return a scale-independent board pose summary for duplicate rejection."""
    points = corners.reshape(-1, 2)
    width, height = image_size
    center = points.mean(axis=0) / np.asarray([width, height], dtype=np.float32)
    span = np.ptp(points, axis=0)
    scale = float(np.linalg.norm(span / np.asarray([width, height])))
    edge = points[-1] - points[0]
    angle = math.atan2(float(edge[1]), float(edge[0]))
    return np.asarray([center[0], center[1], scale, angle], dtype=np.float32)


def _is_distinct_pose(descriptor, previous):
    """Require a visible translation, size change, or rotation from every saved pose."""
    if not previous:
        return True
    for saved in previous:
        center_change = float(np.linalg.norm(descriptor[:2] - saved[:2]))
        scale_change = abs(float(descriptor[2] - saved[2]))
        angle_delta = float(descriptor[3] - saved[3])
        # A checkerboard axis is equivalent after a 180-degree corner-order flip.
        angle_change = 0.5 * abs(math.atan2(
            math.sin(2 * angle_delta), math.cos(2 * angle_delta)
        ))
        if center_change < 0.04 and scale_change < 0.035 and angle_change < math.radians(6):
            return False
    return True


def _align_right_corners(left_corners, right_corners, pattern, image_size):
    """Match right-camera grid ordering to the same physical corners on the left."""
    cols, rows = pattern
    width, height = image_size
    left = left_corners.reshape(rows, cols, 2).astype(np.float32)
    right = right_corners.reshape(rows, cols, 2).astype(np.float32)
    scale = np.asarray([width, height], dtype=np.float32)
    left_normalized = left / scale
    left_normalized -= left_normalized.mean(axis=(0, 1), keepdims=True)
    candidates = (
        ("original", right),
        ("rotate-180", right[::-1, ::-1]),
        ("flip-rows", right[::-1, :]),
        ("flip-cols", right[:, ::-1]),
    )
    best_name, best, best_score = None, None, float("inf")
    for name, candidate in candidates:
        normalized = candidate / scale
        normalized -= normalized.mean(axis=(0, 1), keepdims=True)
        score = float(np.mean(np.linalg.norm(left_normalized - normalized, axis=2)))
        if score < best_score:
            best_name, best, best_score = name, candidate, score
    return best.reshape(right_corners.shape).copy(), best_name


def capture(args):
    cameras = [cv2.VideoCapture(args.left_camera), cv2.VideoCapture(args.right_camera)]
    for camera in cameras:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not all(camera.isOpened() for camera in cameras):
        for camera in cameras:
            camera.release()
        raise RuntimeError("could not open both cameras")
    pattern = (args.board_cols, args.board_rows)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    left_points, right_points = [], []
    saved_poses = []
    image_size = (args.width, args.height)
    next_capture_at = 0.0
    next_status_at = 0.0
    next_preview_at = 0.0
    preview_path = Path(args.preview_output)
    if args.headless_auto:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        print(
            "SSH auto calibration: keep the board visible in both cameras. "
            "After each capture, move/tilt the board to a clearly different pose."
        )
        print(f"latest preview: {preview_path}")
    try:
        while len(left_points) < args.pairs:
            ok_left, left = cameras[0].read()
            ok_right, right = cameras[1].read()
            if not ok_left or not ok_right:
                raise RuntimeError("failed to read both cameras")
            image_size = (left.shape[1], left.shape[0])
            gray_left = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
            gray_right = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
            found_left, corners_left = cv2.findChessboardCorners(gray_left, pattern)
            found_right, corners_right = cv2.findChessboardCorners(gray_right, pattern)
            preview = np.hstack((left, right))
            if found_left:
                cv2.drawChessboardCorners(preview, pattern, corners_left, found_left)
            if found_right:
                shifted = corners_right.copy()
                # OpenCV 4 returns (N, 1, 2), while OpenCV 5 may return (N, 2).
                shifted[..., 0] += left.shape[1]
                cv2.drawChessboardCorners(preview, pattern, shifted, found_right)
            cv2.putText(preview, f"pairs {len(left_points)}/{args.pairs} - SPACE capture",
                        (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            now = time.monotonic()
            if args.headless_auto:
                key = -1
                if now >= next_preview_at:
                    cv2.imwrite(str(preview_path), preview)
                    next_preview_at = now + 0.5
                if now >= next_status_at:
                    state = "both" if found_left and found_right else (
                        "left only" if found_left else "right only" if found_right else "none")
                    print(f"checkerboard={state} pairs={len(left_points)}/{args.pairs}")
                    next_status_at = now + 2.0
            else:
                cv2.imshow("stereo calibration", preview)
                key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                raise KeyboardInterrupt
            should_capture = key == ord(" ")
            descriptor = None
            if args.headless_auto and found_left and found_right and now >= next_capture_at:
                descriptor = _pose_descriptor(corners_left, image_size)
                should_capture = _is_distinct_pose(descriptor, saved_poses)
            if should_capture and found_left and found_right:
                refined_left = cv2.cornerSubPix(
                    gray_left, corners_left, (11, 11), (-1, -1), criteria)
                refined_right = cv2.cornerSubPix(
                    gray_right, corners_right, (11, 11), (-1, -1), criteria)
                refined_right, corner_order = _align_right_corners(
                    refined_left, refined_right, pattern, image_size)
                left_points.append(refined_left)
                right_points.append(refined_right)
                if args.headless_auto:
                    saved_poses.append(descriptor)
                    next_capture_at = now + args.capture_interval_s
                    print(
                        f"captured {len(left_points)}/{args.pairs}; "
                        f"right-order={corner_order}; move or tilt the board to a new pose"
                    )
    finally:
        for camera in cameras:
            camera.release()
        cv2.destroyAllWindows()
    return left_points, right_points, image_size


def calibrate(args, left_points, right_points, image_size):
    template = np.zeros((args.board_rows * args.board_cols, 3), np.float32)
    template[:, :2] = np.mgrid[0:args.board_cols, 0:args.board_rows].T.reshape(-1, 2)
    template *= args.square_size_m
    objects = [template.copy() for _ in left_points]
    _, left_k, left_d, _, _ = cv2.calibrateCamera(
        objects, left_points, image_size, None, None)
    _, right_k, right_d, _, _ = cv2.calibrateCamera(
        objects, right_points, image_size, None, None)
    rms, left_k, left_d, right_k, right_d, rotation, translation, _, _ = (
        cv2.stereoCalibrate(
            objects, left_points, right_points, left_k, left_d, right_k, right_d,
            image_size, flags=cv2.CALIB_FIX_INTRINSIC))
    left_r, right_r, left_p, right_p, q, _, _ = cv2.stereoRectify(
        left_k, left_d, right_k, right_d, image_size, rotation, translation, alpha=0)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output, image_size=np.asarray(image_size), rms=np.asarray(rms),
        left_k=left_k, left_d=left_d, right_k=right_k, right_d=right_d,
        rotation=rotation, translation=translation, left_r=left_r,
        right_r=right_r, left_p=left_p, right_p=right_p, q=q)
    print(f"saved={output} stereo_rms_px={rms:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the fixed stereo cameras")
    parser.add_argument("--left-camera", type=int, default=0)
    parser.add_argument("--right-camera", type=int, default=1)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--board-cols", type=int, default=9)
    parser.add_argument("--board-rows", type=int, default=6)
    parser.add_argument("--square-size-m", type=float, required=True)
    parser.add_argument("--pairs", type=int, default=25)
    parser.add_argument("--output", default="configs/stereo_calibration.npz")
    parser.add_argument(
        "--headless-auto", action="store_true",
        help="capture distinct checkerboard poses automatically without a GUI",
    )
    parser.add_argument(
        "--capture-interval-s", type=float, default=2.0,
        help="minimum seconds between automatic captures",
    )
    parser.add_argument(
        "--preview-output", default="/tmp/stereo_calibration_preview.jpg",
        help="latest side-by-side preview written in headless mode",
    )
    args = parser.parse_args()
    calibrate(args, *capture(args))


if __name__ == "__main__":
    main()

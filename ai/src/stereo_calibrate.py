from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def _open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    camera = cv2.VideoCapture(index)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open camera index {index}")
    return camera


def capture_points(
    left_index: int,
    right_index: int,
    board_cols: int,
    board_rows: int,
    pair_count: int,
    width: int,
    height: int,
) -> tuple[list[np.ndarray], list[np.ndarray], tuple[int, int]]:
    left_camera = _open_camera(left_index, width, height)
    right_camera = _open_camera(right_index, width, height)
    left_points: list[np.ndarray] = []
    right_points: list[np.ndarray] = []
    pattern = (board_cols, board_rows)
    image_size = (width, height)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    try:
        while len(left_points) < pair_count:
            ok_left, left = left_camera.read()
            ok_right, right = right_camera.read()
            if not ok_left or not ok_right:
                raise RuntimeError("Failed to read a synchronized stereo pair")
            image_size = (left.shape[1], left.shape[0])
            found_left, corners_left = cv2.findChessboardCorners(cv2.cvtColor(left, cv2.COLOR_BGR2GRAY), pattern)
            found_right, corners_right = cv2.findChessboardCorners(cv2.cvtColor(right, cv2.COLOR_BGR2GRAY), pattern)
            preview = np.hstack((left, right))
            message = f"pairs {len(left_points)}/{pair_count} - SPACE capture, Q quit"
            cv2.putText(preview, message, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("stereo calibration", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                raise KeyboardInterrupt("Calibration cancelled")
            if key == ord(" ") and found_left and found_right:
                gray_left = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
                gray_right = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
                left_points.append(cv2.cornerSubPix(gray_left, corners_left, (11, 11), (-1, -1), criteria))
                right_points.append(cv2.cornerSubPix(gray_right, corners_right, (11, 11), (-1, -1), criteria))
    finally:
        left_camera.release()
        right_camera.release()
        cv2.destroyAllWindows()
    return left_points, right_points, image_size


def calibrate_and_save(
    left_points: list[np.ndarray],
    right_points: list[np.ndarray],
    image_size: tuple[int, int],
    board_cols: int,
    board_rows: int,
    square_size_m: float,
    output: Path,
) -> float:
    object_template = np.zeros((board_rows * board_cols, 3), np.float32)
    object_template[:, :2] = np.mgrid[0:board_cols, 0:board_rows].T.reshape(-1, 2)
    object_template *= square_size_m
    object_points = [object_template.copy() for _ in left_points]
    _, left_k, left_d, _, _ = cv2.calibrateCamera(object_points, left_points, image_size, None, None)
    _, right_k, right_d, _, _ = cv2.calibrateCamera(object_points, right_points, image_size, None, None)
    flags = cv2.CALIB_FIX_INTRINSIC
    rms, left_k, left_d, right_k, right_d, rotation, translation, _, _ = cv2.stereoCalibrate(
        object_points, left_points, right_points, left_k, left_d, right_k, right_d, image_size, flags=flags
    )
    left_r, right_r, left_p, right_p, q, _, _ = cv2.stereoRectify(
        left_k, left_d, right_k, right_d, image_size, rotation, translation, alpha=0
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        image_size=np.asarray(image_size),
        rms=np.asarray(rms),
        left_k=left_k,
        left_d=left_d,
        right_k=right_k,
        right_d=right_d,
        rotation=rotation,
        translation=translation,
        left_r=left_r,
        right_r=right_r,
        left_p=left_p,
        right_p=right_p,
        q=q,
    )
    return float(rms)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate two fixed Logitech BRIO 100 cameras.")
    parser.add_argument("--left-camera", type=int, default=0)
    parser.add_argument("--right-camera", type=int, default=1)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--board-cols", type=int, default=9, help="Chessboard inner corners across")
    parser.add_argument("--board-rows", type=int, default=6, help="Chessboard inner corners down")
    parser.add_argument("--square-size-m", type=float, required=True)
    parser.add_argument("--pairs", type=int, default=25)
    parser.add_argument("--output", default="configs/stereo_calibration.npz")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    points_left, points_right, size = capture_points(
        args.left_camera, args.right_camera, args.board_cols, args.board_rows, args.pairs, args.width, args.height
    )
    error = calibrate_and_save(
        points_left,
        points_right,
        size,
        args.board_cols,
        args.board_rows,
        args.square_size_m,
        Path(args.output),
    )
    print(f"saved={args.output} stereo_rms_px={error:.4f}")

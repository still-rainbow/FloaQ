"""두 원본 카메라의 사람 중심점으로 빠른 데모용 조준 해를 계산한다."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StereoPointing:
    yaw_deg: float
    pitch_deg: float
    range_m: float


def solve_pointing(point_launcher) -> StereoPointing:
    x, y_down, z = (float(value) for value in point_launcher)
    horizontal = math.hypot(x, z)
    if horizontal <= 0 or z <= 0:
        raise ValueError("target is not in front of launcher")
    return StereoPointing(
        yaw_deg=math.degrees(math.atan2(x, z)),
        pitch_deg=math.degrees(math.atan2(-y_down, horizontal)),
        range_m=horizontal,
    )


GRAVITY_MPS2 = 9.81


def landing_range(pitch_deg, speed_mps, height_m):
    """발사각 `pitch_deg` 로 쏜 부표가 떨어지는 수평거리(m). 공기 저항은 뺀다."""
    theta = math.radians(pitch_deg)
    up = speed_mps * math.sin(theta)
    forward = speed_mps * math.cos(theta)
    return forward * (up + math.sqrt(up * up + 2.0 * GRAVITY_MPS2 * height_m)) / GRAVITY_MPS2


def ballistic_pitch(range_m, speed_mps, height_m, min_deg, max_deg):
    """`range_m` 에 떨어지는 발사각(°). 포물선을 그대로 푼다 — 직선 근사가 없다.

    🔴 부표는 고정 스프링으로 나가므로 **떨어지는 거리는 발사각이 정한다.** 목표를
       보는 시선각으로 쏘면 가까운 목표가 모두 아래 끝에 붙어 같은 거리로 떨어진다
       (2026-09-23 — 가까우면 넘어가고 멀면 짧았다).

    - 가까우면 숙이고 멀면 든다. 두 해 중 **낮은 각**(빨리 닿는 쪽)을 쓴다.
    - `min_deg` 로도 넘어가는 가까운 목표는 `min_deg`.
    - 가장 멀리 가는 각도로도 못 닿는 목표는 그 각도(`max_deg` 로 자름).
    """
    height_m = max(float(height_m), 0.0)
    # 가장 멀리 가는 각도. 높이가 있으면 45° 보다 낮다.
    peak = math.degrees(math.atan2(
        speed_mps, math.sqrt(speed_mps * speed_mps + 2.0 * GRAVITY_MPS2 * height_m)))
    low, high = float(min_deg), min(float(max_deg), peak)
    if range_m <= landing_range(low, speed_mps, height_m):
        return low
    if range_m >= landing_range(high, speed_mps, height_m):
        return high
    for _ in range(60):
        middle = (low + high) / 2.0
        if landing_range(middle, speed_mps, height_m) < range_m:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def fit_ballistics(shot_a, shot_b):
    """서로 다른 각도로 두 번 쏜 `(발사각 °, 떨어진 거리 m)` 로 (속도, 높이) 를 푼다.

        python -c "from floaq_jetson._stereo_aiming import fit_ballistics; \
                   print(fit_ballistics((-10, 0.55), (10, 0.85)))"
    """
    (angle_a, range_a), (angle_b, range_b) = shot_a, shot_b
    if angle_a == angle_b:
        raise ValueError("two shots need different angles")

    def speed_for(height):
        low, high = 0.01, 50.0
        for _ in range(80):
            middle = (low + high) / 2.0
            if landing_range(angle_a, middle, height) < range_a:
                low = middle
            else:
                high = middle
        return (low + high) / 2.0

    def miss(height):
        return landing_range(angle_b, speed_for(height), height) - range_b

    heights = [0.001 * 1.1 ** k for k in range(80)]          # 1mm ~ 약 2m
    for low, high in zip(heights, heights[1:]):
        if miss(low) * miss(high) <= 0:
            for _ in range(60):
                middle = (low + high) / 2.0
                if miss(low) * miss(middle) <= 0:
                    high = middle
                else:
                    low = middle
            height = (low + high) / 2.0
            return round(speed_for(height), 3), round(height, 3)
    raise ValueError("no speed/height fits both shots — check the numbers")


def _bbox_ray(bbox, image_size, horizontal_fov_deg, yaw_deg):
    x, y, width, height = bbox
    frame_width, frame_height = image_size
    focal_px = frame_width / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))
    nx = (x + width / 2.0 - frame_width / 2.0) / focal_px
    ny = (y + height / 2.0 - frame_height / 2.0) / focal_px
    theta = math.radians(yaw_deg) + math.atan(nx)
    vertical_slope = ny / math.sqrt(1.0 + nx * nx)
    return (math.sin(theta), math.cos(theta)), vertical_slope


def triangulate_raw_bboxes(
    left_bbox, right_bbox, image_size, *, horizontal_fov_deg,
    left_position_m, right_position_m, left_yaw_deg, right_yaw_deg,
):
    """Intersect two raw-image bbox-centre rays in boat coordinates."""
    import numpy as np

    left_ray, left_vertical = _bbox_ray(
        left_bbox, image_size, horizontal_fov_deg, left_yaw_deg)
    right_ray, right_vertical = _bbox_ray(
        right_bbox, image_size, horizontal_fov_deg, right_yaw_deg)
    left_position = np.asarray(left_position_m, dtype=float)
    right_position = np.asarray(right_position_m, dtype=float)
    matrix = np.asarray([
        [left_ray[0], -right_ray[0]],
        [left_ray[1], -right_ray[1]],
    ])
    if abs(float(np.linalg.det(matrix))) < 1e-4:
        return None
    travel_left, travel_right = np.linalg.solve(
        matrix,
        np.asarray([
            right_position[0] - left_position[0],
            right_position[2] - left_position[2],
        ]),
    )
    if travel_left <= 0 or travel_right <= 0:
        return None
    left_point = np.asarray([
        left_position[0] + travel_left * left_ray[0],
        left_position[1] + travel_left * left_vertical,
        left_position[2] + travel_left * left_ray[1],
    ])
    right_point = np.asarray([
        right_position[0] + travel_right * right_ray[0],
        right_position[1] + travel_right * right_vertical,
        right_position[2] + travel_right * right_ray[1],
    ])
    return (left_point + right_point) / 2.0


class StereoAimStream:
    """Pair raw L/R frames, detect a person in each, and publish rough aim."""

    def __init__(self, on_frame, *, on_aim, weights: str, config_path: str,
                 imgsz: int = 640, conf: float = 0.25, device=None,
                 quality: int = 80, cls: int = 0, on_detect=None) -> None:
        """`on_detect` 만 더했다. 조준 계산은 건드리지 않는다.

        🔴 이게 없으면 `--aim-only` 가 `jetson/aim` 만 쏘고 `detected()` 를 한 번도
           안 불러서 사고·사진·신고가 통째로 없다 — 조준 시연과 신고 시연을 두 번
           나눠 돌려야 했다. 여기는 이미 좌우 YOLO 결과를 갖고 있다.
        """
        import cv2
        import numpy as np
        import yaml
        from ultralytics import YOLO

        with Path(config_path).open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        cameras = config["cameras"]
        launcher = config["launcher"]
        stereo = config["stereo"]
        self._cv2, self._np = cv2, np
        self._horizontal_fov = float(cameras["horizontal_fov_deg"])
        self._left_position = cameras["left_position_m"]
        self._right_position = cameras["right_position_m"]
        self._left_yaw = float(cameras["left_yaw_deg"])
        self._right_yaw = float(cameras["right_yaw_deg"])
        self._launcher_position = np.asarray(launcher["position_m"], dtype=float)
        self._min_pitch = float(launcher["min_pitch_deg"])
        self._max_pitch = float(launcher["max_pitch_deg"])
        #: 없으면 시선각으로 쏜다 (yaml `ballistics` 주석). 사람이 보는 두 거리
        #: (아래 끝·위 끝으로 쐈을 때 떨어지는 곳)로 속도·높이를 기동 때 푼다.
        ballistics = launcher.get("ballistics")
        self._ballistics = None if not ballistics else fit_ballistics(
            (self._min_pitch, float(ballistics["near_m"])),
            (self._max_pitch, float(ballistics["far_m"])))
        self._max_range = float(stereo["max_range_m"])
        self._max_skew_s = float(stereo["max_pair_skew_ms"]) / 1000.0
        stability = config["stability"]
        self._history = deque(maxlen=int(stability["sample_count"]))
        self._max_std = (
            float(stability["max_yaw_std_deg"]),
            float(stability["max_pitch_std_deg"]),
            float(stability["max_range_std_m"]),
        )
        self._interval = float(stability["publish_interval_s"])
        self._deadband = float(stability["deadband_deg"])
        self._last_at = 0.0
        self._last = None
        self._model = YOLO(weights)
        self._options = {"imgsz": imgsz, "conf": conf, "verbose": False}
        if device is not None:
            self._options["device"] = device
        self._cls = cls
        self._encode = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        self._on_frame, self._on_aim = on_frame, on_aim
        self._on_detect = on_detect
        #: 추론을 돌린 쌍의 수. 차이로 fps 를 낸다 (`jetson/status`)
        self.processed = 0
        self.last_seen = {}
        self._pending = {}
        self._cv = threading.Condition()
        self._stopping = False
        self._thread = None

    @property
    def names(self) -> dict:
        """모델의 클래스 번호 -> 이름. `InferenceStream.names` 와 같은 규약."""
        return dict(getattr(self._model, "names", {}) or {})

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="stereo-aim", daemon=True)
        self._thread.start()

    def submit(self, jpeg: bytes, camera: str, size=None) -> None:
        if camera not in ("L", "R"):
            return
        with self._cv:
            self._pending[camera] = (jpeg, time.monotonic())
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._stopping = True
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            pair = self._next_pair()
            if pair is None:
                return
            try:
                self._process(*pair)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("stereo aim frame failed")

    def _next_pair(self):
        with self._cv:
            while not self._stopping:
                if "L" in self._pending and "R" in self._pending:
                    left = self._pending.pop("L")
                    right = self._pending.pop("R")
                    if abs(left[1] - right[1]) <= self._max_skew_s:
                        return left[0], right[0]
                self._cv.wait()
            return None

    def _process(self, left_jpeg: bytes, right_jpeg: bytes) -> None:
        cv2, np = self._cv2, self._np
        left_raw = cv2.imdecode(np.frombuffer(left_jpeg, np.uint8), cv2.IMREAD_COLOR)
        right_raw = cv2.imdecode(np.frombuffer(right_jpeg, np.uint8), cv2.IMREAD_COLOR)
        if left_raw is None or right_raw is None:
            raise ValueError("JPEG decode failed")
        if left_raw.shape[:2] != right_raw.shape[:2]:
            raise ValueError("left and right camera sizes differ")

        left_result = self._model.predict(left_raw, **self._options)[0]
        right_result = self._model.predict(right_raw, **self._options)[0]
        self.processed += 1
        from ._inference import _best_person, seen_classes
        left_conf, left_bbox = _best_person(left_result, self._cls)
        right_conf, right_bbox = _best_person(right_result, self._cls)
        self.last_seen = {
            "L": seen_classes(left_result), "R": seen_classes(right_result),
        }
        left_preview, right_preview = left_result.plot(), right_result.plot()
        width, height = left_raw.shape[1], left_raw.shape[0]
        mode = "stereo"

        if left_bbox is None:
            self._history.clear()
            cv2.putText(left_preview, "person missing in L", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            target = None
            confidence = float(left_conf)
            if right_bbox is not None:
                target = triangulate_raw_bboxes(
                    left_bbox, right_bbox, (width, height),
                    horizontal_fov_deg=self._horizontal_fov,
                    left_position_m=self._left_position,
                    right_position_m=self._right_position,
                    left_yaw_deg=self._left_yaw,
                    right_yaw_deg=self._right_yaw,
                )
                confidence = min(confidence, float(right_conf))
            if target is None:
                # 좌우 둘 다 사람을 잡아 광선이 교차할 때만 조준한다.
                # 한쪽만 보이면 거리를 모르므로 조준을 보내지 않는다.
                self._history.clear()
                why = ("person missing in R" if right_bbox is None
                       else "no stereo intersection")
                cv2.putText(left_preview, why, (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                relative = target - self._launcher_position
                geometric = solve_pointing(relative)
                if geometric.range_m > self._max_range:
                    self._history.clear()
                    cv2.putText(left_preview, "range rejected", (20, 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                else:
                    # 포물선 값이 있으면 거리로 발사각을 풀고, 없으면 시선각이다.
                    # 범위를 벗어나면 버리지 않고 끝값에 붙인다 — 버리면 조준 전체가
                    # 안 나가서 좌우까지 멈춘다.
                    wanted = (ballistic_pitch(geometric.range_m, *self._ballistics,
                                              self._min_pitch, self._max_pitch)
                              if self._ballistics else geometric.pitch_deg)
                    pitch = min(max(wanted, self._min_pitch), self._max_pitch)
                    pointing = StereoPointing(
                        geometric.yaw_deg - 8, pitch, geometric.range_m)
                    self._publish_if_stable(pointing, confidence, left_preview, mode)

        for image, camera in ((left_preview, "L"), (right_preview, "R")):
            ok, encoded = cv2.imencode(".jpg", image, self._encode)
            if ok:
                self._on_frame(encoded.tobytes(), camera, (width, height))

        # 🔴 조준과 **같은 프레임**으로 판정을 먹인다. 판정·쿨다운은 `_detect.Judge`
        #    가 한다 — 여기서는 본 것을 넘기기만 한다 (`InferenceStream` 과 같은 규약).
        # ⚠ 미리보기를 내보낸 **뒤에** 부른다. `_feed` 가 프레임 크기를 먼저 채워야
        #   조준 해가 비지 않고, 이 프레임이 링버퍼에 먼저 들어가야 판정한 장면이
        #   업로드에 포함된다.
        if self._on_detect is not None:
            # jpeg 는 **원본**이라야 한다 — 스냅샷에 상자를 그리면 안 된다
            aim = self._last if (
                self._last is not None
                and time.monotonic() - self._last_at <= 3.0) else None
            for camera, raw, conf_v, bbox_v in (
                ("L", left_jpeg, left_conf, left_bbox),
                ("R", right_jpeg, right_conf, right_bbox),
            ):
                self._on_detect(camera, raw, conf_v, bbox_v, pointing=aim)

    def _publish_if_stable(self, pointing, confidence, preview, mode) -> None:
        cv2, np = self._cv2, self._np
        self._history.append(np.asarray(
            [pointing.yaw_deg, pointing.pitch_deg, pointing.range_m]))
        stable = False
        if len(self._history) == self._history.maxlen:
            deviation = np.std(np.stack(self._history), axis=0)
            stable = bool(np.all(deviation <= np.asarray(self._max_std)))
        now = time.monotonic()
        sent = False
        in_pitch = self._min_pitch <= pointing.pitch_deg <= self._max_pitch
        if stable and in_pitch and now - self._last_at >= self._interval:
            self._on_aim(pointing, confidence)
            self._last, self._last_at, sent = pointing, now, True
        text = (f"{mode} range~{pointing.range_m:.2f}m yaw={pointing.yaw_deg:+.1f} "
                f"pitch={pointing.pitch_deg:+.1f} stable={stable} sent={sent}")
        cv2.putText(preview, text, (20, 35), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 255, 255), 2)

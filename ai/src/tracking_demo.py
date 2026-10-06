from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2

from .detector import YoloDetector
from .target_policy import LaunchDecision, PolicySettings, TargetPolicy
from .tracker import MultiObjectTracker
from .tracking_types import TrackedDetection
from .utils import ensure_parent, load_config

STATE_COLOURS = {
    "CANDIDATE": (0, 215, 255),
    "CONFIRMED_TARGET": (0, 255, 0),
    "BLOCKED_ON_BOAT": (0, 0, 255),
    "LOST": (128, 128, 128),
}


def _resolve_source(value: str) -> str | int:
    return int(value) if value.isdecimal() else value


def _draw(
    frame: Any,
    detections: list[TrackedDetection],
    decisions: list[LaunchDecision],
    fps: float,
) -> Any:
    annotated = frame.copy()
    by_track = {decision.track_id: decision for decision in decisions}
    for item in detections:
        decision = by_track.get(item.track_id)
        if decision is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in item.detection.xyxy)
        colour = STATE_COLOURS[decision.state]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), colour, 2)
        lines = [
            f"ID {item.track_id} {item.detection.class_name} {item.detection.confidence:.2f}",
            f"{decision.state}: {decision.reason_code}",
            f"person={decision.target_confidence:.2f} boat={decision.on_boat_confidence:.2f}",
        ]
        for offset, text in enumerate(lines):
            cv2.putText(
                annotated,
                text,
                (x1, max(20, y1 - 42 + offset * 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                colour,
                1,
                cv2.LINE_AA,
            )
    cv2.putText(
        annotated,
        f"FPS {fps:.1f}",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return annotated


def run(
    config_path: str | Path,
    *,
    source: str,
    weights_override: str | None = None,
    headless: bool = False,
    output_video: str | None = None,
) -> None:
    config = load_config(config_path)
    settings = PolicySettings.from_mapping(config)
    weights = Path(weights_override or config["weights"])
    detector = YoloDetector(
        weights,
        candidate_confidence=settings.candidate_confidence,
        iou=float(config.get("iou", 0.70)),
        imgsz=int(config.get("imgsz", 640)),
        device=config.get("device", "cpu"),
        target_class_name=settings.target_class_name,
        on_boat_class_name=settings.on_boat_class_name,
    )
    tracker = MultiObjectTracker(detector, config["tracker_config"])
    policy = TargetPolicy(settings, model_sha256=detector.model_sha256)
    capture = cv2.VideoCapture(_resolve_source(source))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video source: {source}")

    log_path = ensure_parent(config.get("log_path", "outputs/tracking_decisions.jsonl"))
    writer = None
    frame_id = 0
    started = time.monotonic()
    previous = started
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(
                    {
                        "type": "run_metadata",
                        "model_path": str(weights),
                        "model_sha256": detector.model_sha256,
                        "model_classes": detector.class_names,
                        "config": config,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                timestamp_s = time.monotonic() - started
                detections = tracker.update(frame, frame_id, timestamp_s)
                decisions = policy.update(frame_id, timestamp_s, detections)
                now = time.monotonic()
                fps = 1.0 / max(now - previous, 1e-6)
                previous = now
                annotated = _draw(frame, detections, decisions, fps)

                log_file.write(
                    json.dumps(
                        {
                            "type": "frame",
                            "frame_id": frame_id,
                            "timestamp_s": timestamp_s,
                            "detections": [
                                {"track_id": item.track_id, **asdict(item.detection)}
                                for item in detections
                            ],
                            "decisions": [asdict(decision) for decision in decisions],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                log_file.flush()
                for decision in decisions:
                    print(
                        f"frame={frame_id} track={decision.track_id} state={decision.state} "
                        f"reason={decision.reason_code} person={decision.target_confidence:.3f} "
                        f"on_boat={decision.on_boat_confidence:.3f}"
                    )

                if output_video:
                    if writer is None:
                        destination = ensure_parent(output_video)
                        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
                        writer = cv2.VideoWriter(
                            str(destination),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            source_fps,
                            (width, height),
                        )
                    writer.write(annotated)

                if not headless:
                    cv2.imshow("Rescue Tracking Policy", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                frame_id += 1
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if not headless:
            cv2.destroyAllWindows()
    print(f"Decision log: {log_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track rescue targets and display multi-frame state/reason decisions."
    )
    parser.add_argument("--config", default="configs/tracking_policy.yaml")
    parser.add_argument("--source", default="0", help="Video path or webcam index")
    parser.add_argument("--weights", help="Override the model path in the config")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output-video", help="Optional annotated MP4 path")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        args.config,
        source=args.source,
        weights_override=args.weights,
        headless=args.headless,
        output_video=args.output_video,
    )

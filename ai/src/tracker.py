from __future__ import annotations

from pathlib import Path
from typing import Any

from .detector import YoloDetector
from .tracking_types import TrackedDetection


class MultiObjectTracker:
    """Keep Ultralytics ByteTrack/BoT-SORT state across successive frames."""

    def __init__(self, detector: YoloDetector, tracker_config: str | Path) -> None:
        self.detector = detector
        self.tracker_config = Path(tracker_config)
        if not self.tracker_config.is_file():
            raise FileNotFoundError(f"Tracker config not found: {self.tracker_config}")
        self._last_frame_id = -1
        self._last_timestamp_s = -1.0

    def update(
        self, frame: Any, frame_id: int, timestamp_s: float
    ) -> list[TrackedDetection]:
        if frame_id <= self._last_frame_id:
            raise ValueError(
                f"frame_id must increase: {frame_id} <= {self._last_frame_id}"
            )
        if timestamp_s < self._last_timestamp_s:
            raise ValueError(
                f"timestamp_s must not decrease: {timestamp_s} < {self._last_timestamp_s}"
            )
        self._last_frame_id = frame_id
        self._last_timestamp_s = timestamp_s
        return [
            TrackedDetection(track_id=item.track_id, detection=item.detection)
            for item in self.detector.track_frame(
                frame,
                frame_id=frame_id,
                timestamp_s=timestamp_s,
                tracker_config=self.tracker_config,
            )
        ]

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    frame_id: int
    timestamp_s: float
    xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str


@dataclass(frozen=True)
class TrackedDetection:
    track_id: int
    detection: Detection

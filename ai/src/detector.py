from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from .tracking_types import Detection


@dataclass(frozen=True)
class ModelTrack:
    track_id: int
    detection: Detection


class YoloDetector:
    """Load YOLO once and expose class-name based tracking results."""

    def __init__(
        self,
        weights: str | Path,
        *,
        candidate_confidence: float,
        iou: float,
        imgsz: int,
        device: str | int,
        target_class_name: str = "person",
        on_boat_class_name: str = "person_with_float",
    ) -> None:
        self.weights = Path(weights)
        if not self.weights.is_file():
            raise FileNotFoundError(f"YOLO weights not found: {self.weights}")
        self.model = YOLO(str(self.weights))
        self.candidate_confidence = candidate_confidence
        self.iou = iou
        self.imgsz = imgsz
        self.device = device
        self.target_class_name = target_class_name
        self.on_boat_class_name = on_boat_class_name
        self.class_names = self._normalise_names(self.model.names)
        self.relevant_class_ids = self._resolve_relevant_classes()
        self.model_sha256 = self._sha256(self.weights)

    @staticmethod
    def _normalise_names(names: Any) -> dict[int, str]:
        if isinstance(names, dict):
            return {int(class_id): str(name) for class_id, name in names.items()}
        return {class_id: str(name) for class_id, name in enumerate(names)}

    def _resolve_relevant_classes(self) -> list[int]:
        by_name = {name: class_id for class_id, name in self.class_names.items()}
        if self.target_class_name not in by_name:
            raise ValueError(
                f"Model has no '{self.target_class_name}' class. Classes: {self.class_names}"
            )
        relevant = [by_name[self.target_class_name]]
        if self.on_boat_class_name in by_name:
            relevant.append(by_name[self.on_boat_class_name])
        else:
            warnings.warn(
                f"Model has no '{self.on_boat_class_name}' class; on-boat blocking is unavailable. "
                f"Classes: {self.class_names}",
                stacklevel=2,
            )
        return relevant

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def track_frame(
        self,
        frame: Any,
        *,
        frame_id: int,
        timestamp_s: float,
        tracker_config: str | Path,
    ) -> list[ModelTrack]:
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=str(tracker_config),
            conf=self.candidate_confidence,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            classes=self.relevant_class_ids,
            verbose=False,
        )
        if not results or results[0].boxes is None or results[0].boxes.id is None:
            return []

        boxes = results[0].boxes
        track_ids = boxes.id.int().cpu().tolist()
        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        class_ids = boxes.cls.int().cpu().tolist()
        tracks: list[ModelTrack] = []
        for track_id, xyxy, confidence, class_id in zip(
            track_ids, coordinates, confidences, class_ids, strict=True
        ):
            if confidence < self.candidate_confidence:
                continue
            tracks.append(
                ModelTrack(
                    track_id=int(track_id),
                    detection=Detection(
                        frame_id=frame_id,
                        timestamp_s=timestamp_s,
                        xyxy=tuple(float(value) for value in xyxy),
                        confidence=float(confidence),
                        class_id=int(class_id),
                        class_name=self.class_names[int(class_id)],
                    ),
                )
            )
        return tracks

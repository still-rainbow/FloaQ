from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .tracking_types import TrackedDetection


class TargetState(StrEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED_TARGET = "CONFIRMED_TARGET"
    BLOCKED_ON_BOAT = "BLOCKED_ON_BOAT"
    LOST = "LOST"


@dataclass(frozen=True)
class PolicySettings:
    candidate_confidence: float = 0.05
    strong_confidence: float = 0.22
    confirmation_window_frames: int = 5
    minimum_hits_in_window: int = 2
    maximum_missed_frames: int = 10
    minimum_track_age_frames: int = 3
    class_evidence_decay: float = 0.85
    strong_evidence_multiplier: float = 1.5
    target_evidence_threshold: float = 0.08
    on_boat_evidence_threshold: float = 0.08
    class_evidence_margin: float = 0.0
    target_class_name: str = "person"
    on_boat_class_name: str = "person_with_float"

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> PolicySettings:
        known = {field_.name for field_ in cls.__dataclass_fields__.values()}
        settings = cls(**{key: value for key, value in values.items() if key in known})
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.0 <= self.candidate_confidence <= self.strong_confidence <= 1.0:
            raise ValueError(
                "confidence values must satisfy 0 <= candidate <= strong <= 1"
            )
        if self.confirmation_window_frames < 1:
            raise ValueError("confirmation_window_frames must be positive")
        if not 1 <= self.minimum_hits_in_window <= self.confirmation_window_frames:
            raise ValueError(
                "minimum_hits_in_window must fit inside the confirmation window"
            )
        if self.maximum_missed_frames < 0 or self.minimum_track_age_frames < 1:
            raise ValueError("frame counts must be non-negative")
        if not 0.0 <= self.class_evidence_decay <= 1.0:
            raise ValueError("class_evidence_decay must be in [0, 1]")


@dataclass
class TargetTrack:
    track_id: int
    first_seen_s: float
    last_seen_s: float
    age_frames: int = 0
    detected_frames: int = 0
    missed_frames: int = 0
    recent_hits: deque[bool] = field(default_factory=deque)
    class_evidence: dict[str, float] = field(default_factory=dict)
    confidence_history: deque[float] = field(default_factory=deque)
    center_history: deque[tuple[float, float]] = field(default_factory=deque)
    latest_xyxy: tuple[float, float, float, float] | None = None
    state: TargetState = TargetState.CANDIDATE
    launch_requested: bool = False


@dataclass(frozen=True)
class LaunchDecision:
    frame_id: int
    timestamp_s: float
    track_id: int
    state: str
    launch_ready: bool
    reason_code: str
    target_xy: tuple[float, float] | None
    predicted_xy: tuple[float, float] | None
    target_confidence: float
    on_boat_confidence: float
    evidence_frames: int
    model_sha256: str
    missed_frames: int


class TargetPolicy:
    """Accumulate per-track evidence and emit auditable target decisions."""

    def __init__(
        self, settings: PolicySettings, *, model_sha256: str = "unknown"
    ) -> None:
        settings.validate()
        self.settings = settings
        self.model_sha256 = model_sha256
        self.tracks: dict[int, TargetTrack] = {}

    def update(
        self,
        frame_id: int,
        timestamp_s: float,
        detections: Iterable[TrackedDetection],
    ) -> list[LaunchDecision]:
        observed: dict[int, TrackedDetection] = {}
        for item in detections:
            previous = observed.get(item.track_id)
            if (
                previous is None
                or item.detection.confidence > previous.detection.confidence
            ):
                observed[item.track_id] = item

        decisions: list[LaunchDecision] = []
        for track_id, track in list(self.tracks.items()):
            self._decay_evidence(track)
            item = observed.pop(track_id, None)
            if item is None:
                self._mark_missed(track)
            else:
                self._mark_detected(track, item, timestamp_s)
            decisions.append(self._decide(track, frame_id, timestamp_s))

        for track_id, item in observed.items():
            track = TargetTrack(
                track_id=track_id,
                first_seen_s=timestamp_s,
                last_seen_s=timestamp_s,
                recent_hits=deque(maxlen=self.settings.confirmation_window_frames),
                confidence_history=deque(
                    maxlen=self.settings.confirmation_window_frames
                ),
                center_history=deque(maxlen=self.settings.confirmation_window_frames),
            )
            self.tracks[track_id] = track
            self._mark_detected(track, item, timestamp_s)
            decisions.append(self._decide(track, frame_id, timestamp_s))

        for decision in decisions:
            if decision.state == TargetState.LOST:
                self.tracks.pop(decision.track_id, None)
        return sorted(decisions, key=lambda decision: decision.track_id)

    def _decay_evidence(self, track: TargetTrack) -> None:
        for class_name in list(track.class_evidence):
            track.class_evidence[class_name] *= self.settings.class_evidence_decay

    def _mark_detected(
        self, track: TargetTrack, item: TrackedDetection, timestamp_s: float
    ) -> None:
        detection = item.detection
        track.age_frames += 1
        track.detected_frames += 1
        track.missed_frames = 0
        track.last_seen_s = timestamp_s
        track.latest_xyxy = detection.xyxy
        is_target = detection.class_name == self.settings.target_class_name
        track.recent_hits.append(is_target)
        track.confidence_history.append(detection.confidence)
        x1, y1, x2, y2 = detection.xyxy
        track.center_history.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
        multiplier = (
            self.settings.strong_evidence_multiplier
            if detection.confidence >= self.settings.strong_confidence
            else 1.0
        )
        track.class_evidence[detection.class_name] = min(
            1.0,
            track.class_evidence.get(detection.class_name, 0.0)
            + detection.confidence * multiplier,
        )

    def _mark_missed(self, track: TargetTrack) -> None:
        track.age_frames += 1
        track.missed_frames += 1
        track.recent_hits.append(False)

    def _decide(
        self, track: TargetTrack, frame_id: int, timestamp_s: float
    ) -> LaunchDecision:
        target = track.class_evidence.get(self.settings.target_class_name, 0.0)
        on_boat = track.class_evidence.get(self.settings.on_boat_class_name, 0.0)
        target_xy = track.center_history[-1] if track.center_history else None

        if track.missed_frames > self.settings.maximum_missed_frames:
            track.state = TargetState.LOST
            reason = "TARGET_LOST"
        elif (
            on_boat >= self.settings.on_boat_evidence_threshold
            and on_boat >= target + self.settings.class_evidence_margin
        ):
            track.state = TargetState.BLOCKED_ON_BOAT
            reason = "BLOCKED_ON_BOAT"
        elif (
            track.age_frames >= self.settings.minimum_track_age_frames
            and sum(track.recent_hits) >= self.settings.minimum_hits_in_window
            and target >= self.settings.target_evidence_threshold
            and target > on_boat + self.settings.class_evidence_margin
        ):
            track.state = TargetState.CONFIRMED_TARGET
            reason = "TARGET_CONFIRMED"
        else:
            track.state = TargetState.CANDIDATE
            reason = "INSUFFICIENT_HISTORY"

        # Stereo, IMU, range validation and launcher readiness are deliberately out of scope.
        return LaunchDecision(
            frame_id=frame_id,
            timestamp_s=timestamp_s,
            track_id=track.track_id,
            state=track.state.value,
            launch_ready=False,
            reason_code=reason,
            target_xy=target_xy,
            predicted_xy=None,
            target_confidence=target,
            on_boat_confidence=on_boat,
            evidence_frames=sum(track.recent_hits),
            model_sha256=self.model_sha256,
            missed_frames=track.missed_frames,
        )

import unittest

from src.target_policy import PolicySettings, TargetPolicy, TargetState
from src.tracking_types import Detection, TrackedDetection


def tracked(
    frame_id: int,
    *,
    track_id: int = 7,
    class_name: str = "person",
    confidence: float = 0.05,
) -> TrackedDetection:
    class_id = 2 if class_name == "person" else 3
    return TrackedDetection(
        track_id=track_id,
        detection=Detection(
            frame_id=frame_id,
            timestamp_s=frame_id / 10,
            xyxy=(10.0, 20.0, 30.0, 60.0),
            confidence=confidence,
            class_id=class_id,
            class_name=class_name,
        ),
    )


class TargetPolicyTest(unittest.TestCase):
    def test_two_hits_in_five_frames_confirm_target_after_minimum_age(self) -> None:
        policy = TargetPolicy(PolicySettings(), model_sha256="abc")

        first = policy.update(0, 0.0, [tracked(0)])[0]
        missed = policy.update(1, 0.1, [])[0]
        confirmed = policy.update(2, 0.2, [tracked(2)])[0]

        self.assertEqual(first.state, TargetState.CANDIDATE)
        self.assertEqual(missed.state, TargetState.CANDIDATE)
        self.assertEqual(confirmed.state, TargetState.CONFIRMED_TARGET)
        self.assertEqual(confirmed.reason_code, "TARGET_CONFIRMED")
        self.assertFalse(confirmed.launch_ready)
        self.assertEqual(confirmed.evidence_frames, 2)

    def test_person_with_float_evidence_blocks_track(self) -> None:
        policy = TargetPolicy(PolicySettings())

        policy.update(0, 0.0, [tracked(0, class_name="person_with_float")])
        blocked = policy.update(1, 0.1, [tracked(1, class_name="person_with_float")])[0]

        self.assertEqual(blocked.state, TargetState.BLOCKED_ON_BOAT)
        self.assertEqual(blocked.reason_code, "BLOCKED_ON_BOAT")
        self.assertGreaterEqual(blocked.on_boat_confidence, 0.08)

    def test_track_survives_temporary_misses_then_becomes_lost(self) -> None:
        settings = PolicySettings(maximum_missed_frames=2)
        policy = TargetPolicy(settings)
        policy.update(0, 0.0, [tracked(0)])

        self.assertNotEqual(policy.update(1, 0.1, [])[0].state, TargetState.LOST)
        self.assertNotEqual(policy.update(2, 0.2, [])[0].state, TargetState.LOST)
        lost = policy.update(3, 0.3, [])[0]

        self.assertEqual(lost.state, TargetState.LOST)
        self.assertEqual(lost.reason_code, "TARGET_LOST")
        self.assertNotIn(7, policy.tracks)

    def test_default_thresholds_match_tracking_design(self) -> None:
        settings = PolicySettings()
        self.assertEqual(settings.candidate_confidence, 0.05)
        self.assertEqual(settings.strong_confidence, 0.22)
        self.assertEqual(settings.confirmation_window_frames, 5)
        self.assertEqual(settings.minimum_hits_in_window, 2)


if __name__ == "__main__":
    unittest.main()

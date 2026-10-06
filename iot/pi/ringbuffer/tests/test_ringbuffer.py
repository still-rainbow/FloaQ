import json
import tempfile
import unittest
from pathlib import Path

from imu_ringbuffer import (
    NS,
    CaptureWindow,
    ComplementaryOrientation,
    ImuRingBuffer,
    ImuSample,
    RawImuReading,
    write_capture,
)


def sample(index, hz=50, wall_base=1_800_000_000 * NS):
    step = NS // hz
    return ImuSample(
        index * step, wall_base + index * step,
        0.0, 0.0, 9.80665, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
    )


class RingBufferTests(unittest.TestCase):
    def test_old_samples_are_evicted(self):
        ring = ImuRingBuffer(hz=10, seconds=1)
        for index in range(20):
            ring.append(sample(index, hz=10))
        self.assertEqual(len(ring), 11)
        self.assertEqual(ring.snapshot()[0].monotonic_ns, sample(9, hz=10).monotonic_ns)

    def test_event_cut(self):
        ring = ImuRingBuffer(hz=50, seconds=40)
        for index in range(40 * 50 + 1):
            ring.append(sample(index))
        event = ring.snapshot()[-1].wall_ns
        cut = ring.cut_event(event, before_s=30, after_s=0)
        self.assertAlmostEqual(cut.actual_span_s, 30.0, places=2)
        self.assertEqual(len(cut.samples), 1501)
        self.assertFalse(cut.truncated)

    def test_orientation_units_are_separate(self):
        estimator = ComplementaryOrientation()
        level = RawImuReading(0.0, 0.0, 9.80665, 0.0, 0.0, 10.0)
        estimator.update(level, NS)
        roll, pitch, yaw = estimator.update(level, NS + NS // 10)
        self.assertAlmostEqual(roll, 0.0, places=3)
        self.assertAlmostEqual(pitch, 0.0, places=3)
        self.assertAlmostEqual(yaw, 1.0, places=3)

    def test_export_writes_units(self):
        window = CaptureWindow([sample(1)], sample(1).wall_ns, 1.0, 0.0, 0.0, 0.0, True)
        with tempfile.TemporaryDirectory() as directory:
            data, meta = write_capture(window, Path(directory) / "capture.jsonl")
            self.assertTrue(data.exists())
            metadata = json.loads(meta.read_text(encoding="utf-8"))
            self.assertEqual(metadata["units"]["gyro_x/y/z"], "deg/s")
            self.assertEqual(metadata["units"]["roll/pitch/yaw"], "deg")


if __name__ == "__main__":
    unittest.main()

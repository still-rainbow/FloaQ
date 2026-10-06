import json
import io
import threading
from unittest import mock
import tempfile
import unittest
from pathlib import Path

from imu_ringbuffer import ImuRingBuffer, ImuSample, NS
from fastapi_mjpeg import read_mjpeg_frame, receive_camera
from video_ringbuffer import (
    VideoRingBuffer,
    parse_multipart,
    write_video_capture,
)


WALL_BASE = 1_800_000_000 * NS
JPEG = b"\xff\xd8frame\xff\xd9"


def frame(index, hz=5, wall_ns=None):
    mono_ns = index * NS // hz
    wall_ns = WALL_BASE + mono_ns if wall_ns is None else wall_ns
    header = {"pair_id": index, "pub_seq": index,
              "mono_ns": mono_ns, "wall_ns": wall_ns,
              "stereo": True, "width": 640, "height": 480}
    return parse_multipart([b"frame", json.dumps(header).encode(), JPEG, JPEG])


def imu_sample(index, hz=50, wall_ns=None):
    mono_ns = index * NS // hz
    wall_ns = WALL_BASE + mono_ns if wall_ns is None else wall_ns
    return ImuSample(mono_ns, wall_ns, 0, 0, 9.80665, 0, 0, 0, 0, 0, 0)


class VideoBufferTests(unittest.TestCase):
    def test_fastapi_mjpeg_frame(self):
        payload = (b"--floaqframe\r\nContent-Type: image/jpeg\r\n"
                   + b"Content-Length: " + str(len(JPEG)).encode()
                   + b"\r\n\r\n" + JPEG + b"\r\n")
        self.assertEqual(read_mjpeg_frame(io.BytesIO(payload)), JPEG)

    def test_fastapi_receiver_records_right_camera(self):
        payload = (b"--floaqframe\r\nContent-Type: image/jpeg\r\n"
                   + b"Content-Length: " + str(len(JPEG)).encode()
                   + b"\r\n\r\n" + JPEG + b"\r\n")
        stop = threading.Event()

        class OneFrameRing:
            def __init__(self):
                self.frames = []

            def append(self, value):
                self.frames.append(value)
                stop.set()

        ring = OneFrameRing()
        state = {"seq": 0, "received": 0, "invalid": 0,
                 "error": None, "camera_counts": {"L": 0, "R": 0}}
        with mock.patch("fastapi_mjpeg.urllib.request.urlopen", return_value=io.BytesIO(payload)):
            receive_camera("http://localhost/stream.mjpg?camera=R", "R", ring,
                           stop, state, threading.Lock())
        self.assertEqual(state["camera_counts"]["R"], 1)
        self.assertIsNone(ring.frames[0].left_jpeg)
        self.assertEqual(ring.frames[0].right_jpeg, JPEG)

    def test_parse_stereo_and_mono(self):
        stereo = frame(1)
        self.assertEqual(stereo.header["pair_id"], 1)
        self.assertEqual(stereo.right_jpeg, JPEG)
        mono = parse_multipart([b"frame", json.dumps(stereo.header).encode(), JPEG])
        self.assertIsNone(mono.right_jpeg)
        with self.assertRaises(ValueError):
            parse_multipart([b"frame", b"{}", JPEG])

    def test_time_and_memory_eviction(self):
        ring = VideoRingBuffer(seconds=1, max_bytes=1000, expected_fps=5)
        for index in range(11):
            ring.append(frame(index))
        self.assertEqual(len(ring.snapshot()), 6)
        self.assertGreater(ring.stats()["evicted"], 0)
        small = VideoRingBuffer(seconds=10, max_bytes=4 * len(JPEG), expected_fps=5)
        for index in range(5):
            small.append(frame(index))
        self.assertEqual(len(small.snapshot()), 2)

    def test_shared_30_second_window_with_imu(self):
        video = VideoRingBuffer(seconds=40, max_bytes=100000, expected_fps=5)
        imu = ImuRingBuffer(hz=50, seconds=40)
        for index in range(40 * 5 + 1):
            video.append(frame(index))
        for index in range(40 * 50 + 1):
            imu.append(imu_sample(index))
        event_ns = WALL_BASE + 35 * NS
        v = video.cut_event(event_ns, before_s=30, after_s=5)
        i = imu.cut_event(event_ns, before_s=30, after_s=5)
        self.assertFalse(v.truncated)
        self.assertFalse(i.truncated)
        self.assertEqual(len(v.frames), 176)
        self.assertEqual(len(i.samples), 1751)
        self.assertAlmostEqual(v.actual_span_s, 35.0)
        self.assertAlmostEqual(i.actual_span_s, 35.0)
        self.assertEqual(v.frames[0].wall_ns, i.samples[0].wall_ns)

    def test_wall_clock_jump_keeps_interval(self):
        video = VideoRingBuffer(seconds=40, max_bytes=100000, expected_fps=5)
        imu = ImuRingBuffer(hz=50, seconds=40)
        for index in range(40 * 5 + 1):
            wall = WALL_BASE + index * NS // 5 + (7 * NS if index >= 100 else 0)
            video.append(frame(index, wall_ns=wall))
        for index in range(40 * 50 + 1):
            wall = WALL_BASE + index * NS // 50 + (7 * NS if index >= 1000 else 0)
            imu.append(imu_sample(index, wall_ns=wall))
        event_ns = WALL_BASE + 42 * NS
        self.assertAlmostEqual(video.cut_event(event_ns, 30, 5).actual_span_s, 35.0)
        self.assertAlmostEqual(imu.cut_event(event_ns, 30, 5).actual_span_s, 35.0)

    def test_export_jpeg_and_index(self):
        ring = VideoRingBuffer(seconds=40)
        ring.append(frame(0))
        window = ring.cut_event(WALL_BASE, before_s=0, after_s=0)
        with tempfile.TemporaryDirectory() as directory:
            index = write_video_capture(window, Path(directory) / "video")
            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(len(data["frames"]), 1)
            self.assertEqual((index.parent / "0000_left.jpg").read_bytes(), JPEG)
            self.assertEqual((index.parent / "0000_right.jpg").read_bytes(), JPEG)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""촬영 파이프라인 시험 — IOT-01 / Jira floaq-18

표준 라이브러리 unittest 만 쓴다. cv2 · zmq · numpy 가 없는 개발 PC 에서도
페어링·솎아내기·직렬화 같은 판단 로직은 전부 검증되어야 한다.
실물이 필요한 부분만 skip 한다.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.config import CameraConfig, ServiceConfig, default_config
from camera.frame import Frame, StereoPair
from camera.publisher import FramePublisher
from camera.stereo import StereoPairer
from camera.subscriber import parse_multipart

NS = 1_000_000_000

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ─────────────────────────────────────────────────────────────
# 보조
# ─────────────────────────────────────────────────────────────

class FakeImage:
    """numpy 없이 Frame 을 만들기 위한 최소 대역품."""

    def __init__(self, w: int = 64, h: int = 48) -> None:
        self.shape = (h, w, 3)


def make_frame(cam_id: str, seq: int, mono_ns: int) -> Frame:
    return Frame(cam_id, seq, mono_ns, mono_ns + 1_000_000_000, FakeImage())


class FakeCapture:
    """CameraCapture 대역품. 미리 정한 프레임을 순서대로 내준다."""

    def __init__(self, cam_id: str, frames: list) -> None:
        self.cam_id = cam_id
        self._frames = list(frames)
        self._i = 0
        self._last = None

    def wait_for_frame(self, timeout_s: float):
        if self._i >= len(self._frames):
            return None
        self._last = self._frames[self._i]
        self._i += 1
        return self._last

    def latest(self):
        return self._last


# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):

    def test_synthetic_감지(self):
        self.assertTrue(CameraConfig("left", "synthetic").is_synthetic)
        self.assertFalse(CameraConfig("left", "/dev/video0").is_synthetic)

    def test_장치_인덱스_변환(self):
        # 숫자는 int 로, 경로는 문자열 그대로 넘어가야 한다
        self.assertEqual(CameraConfig("left", "0").v4l2_index, 0)
        self.assertEqual(CameraConfig("left", "/dev/video2").v4l2_index, "/dev/video2")

    def test_기본값은_스테레오(self):
        cfg = default_config()
        self.assertTrue(cfg.is_stereo)
        self.assertEqual(len(cfg.cameras), 2)
        # 저장 요구가 5 fps 로 확정돼 있다 (DES-31 C-8)
        self.assertEqual(cfg.publish_fps, 5.0)

    def test_mono_구성(self):
        cfg = ServiceConfig(left=CameraConfig("left", "synthetic"))
        self.assertFalse(cfg.is_stereo)
        self.assertEqual(len(cfg.cameras), 1)


# ─────────────────────────────────────────────────────────────
# 프레임·헤더
# ─────────────────────────────────────────────────────────────

class TestFrame(unittest.TestCase):

    def test_헤더에_두_시계가_모두_들어간다(self):
        left = make_frame("left", 10, 1_000_000_000)
        right = make_frame("right", 11, 1_012_000_000)
        pair = StereoPair(1, left, right, right.mono_ns - left.mono_ns)
        h = pair.header()

        self.assertEqual(h["pair_id"], 1)
        self.assertEqual(h["mono_ns"], left.mono_ns)     # 기준은 왼쪽
        self.assertEqual(h["wall_ns"], left.wall_ns)
        self.assertTrue(h["stereo"])
        self.assertAlmostEqual(h["skew_ms"], 12.0, places=3)
        # ERD 는 초 단위 int unixtime 이다
        self.assertEqual(h["created_at"], left.wall_ns // NS)

    def test_mono_폴백_헤더(self):
        pair = StereoPair(2, make_frame("left", 1, 500), None, 0)
        h = pair.header()
        self.assertFalse(h["stereo"])
        self.assertIsNone(h["right_seq"])
        self.assertEqual(h["skew_ms"], 0.0)


# ─────────────────────────────────────────────────────────────
# 페어링
# ─────────────────────────────────────────────────────────────

class TestStereoPairing(unittest.TestCase):

    def test_허용오차_안이면_쌍으로_묶는다(self):
        base = 1_000_000_000
        left = FakeCapture("left", [make_frame("left", 1, base)])
        right = FakeCapture("right", [make_frame("right", 1, base + 10_000_000)])  # 10 ms
        pairer = StereoPairer(left, right, max_skew_ms=33.0)

        pair = pairer.next_pair(timeout_s=0.1)
        self.assertIsNotNone(pair)
        self.assertTrue(pair.is_stereo)
        self.assertAlmostEqual(pair.skew_ms, 10.0, places=3)
        self.assertEqual(pairer.stats.paired, 1)

    def test_허용오차를_넘으면_붙이지_않는다(self):
        # 억지로 맞춘 쌍은 스테레오 거리에서 조용히 틀린 값을 만든다
        base = 1_000_000_000
        left = FakeCapture("left", [make_frame("left", 1, base)])
        right = FakeCapture("right", [make_frame("right", 1, base + 200_000_000)])  # 200 ms
        pairer = StereoPairer(left, right, max_skew_ms=33.0)

        pair = pairer.next_pair(timeout_s=0.1)
        self.assertIsNotNone(pair)
        self.assertFalse(pair.is_stereo)
        self.assertIsNone(pair.right)
        self.assertEqual(pairer.stats.mono_fallback, 1)
        self.assertEqual(pairer.stats.paired, 0)

    def test_오른쪽이_없으면_mono(self):
        left = FakeCapture("left", [make_frame("left", 1, 1000)])
        pairer = StereoPairer(left, None, max_skew_ms=33.0)
        pair = pairer.next_pair(timeout_s=0.1)
        self.assertFalse(pair.is_stereo)

    def test_pair_id는_단조증가한다(self):
        base = 1_000_000_000
        frames = [make_frame("left", i, base + i * 66_000_000) for i in range(5)]
        pairer = StereoPairer(FakeCapture("left", frames), None, max_skew_ms=33.0)

        ids = []
        while True:
            p = pairer.next_pair(timeout_s=0.01)
            if p is None:
                break
            ids.append(p.pair_id)
        self.assertEqual(ids, [1, 2, 3, 4, 5])

    def test_쌍_비율_저하_판정(self):
        pairer = StereoPairer(FakeCapture("left", []), None)
        # 표본이 적으면 판정하지 않는다
        pairer.stats.paired, pairer.stats.mono_fallback = 5, 5
        self.assertFalse(pairer.stats.pair_rate_low())
        pairer.stats.paired, pairer.stats.mono_fallback = 50, 50
        self.assertTrue(pairer.stats.pair_rate_low())
        pairer.stats.paired, pairer.stats.mono_fallback = 100, 1
        self.assertFalse(pairer.stats.pair_rate_low())


# ─────────────────────────────────────────────────────────────
# 송신 솎아내기
# ─────────────────────────────────────────────────────────────

class TestPublishRate(unittest.TestCase):

    @staticmethod
    def _run_gate(pub: FramePublisher, fps: float, seconds: float) -> list:
        """송신 게이트만 돌린다. 인코딩·ZMQ 없이 솎아내기 결과만 본다."""
        base = 1_000_000_000
        period = NS / fps
        passed = []
        for i in range(int(fps * seconds)):
            mono = base + int(i * period)
            pair = StereoPair(i, make_frame("left", i, mono), None, 0)
            pub._observe_interval(mono)
            if pub.should_publish(pair):
                passed.append(mono)
                pub._advance_deadline(mono)       # publish() 가 하는 갱신
        return passed

    def test_publish_fps로_솎아낸다(self):
        # 수집 15 fps → 송신 5 fps
        pub = FramePublisher("inproc://test", publish_fps=5.0)
        passed = self._run_gate(pub, fps=15.0, seconds=10.0)
        span_s = (passed[-1] - passed[0]) / NS
        rate = (len(passed) - 1) / span_s
        # 마감 누적 방식이므로 목표 5 fps 에서 5% 안에 들어와야 한다.
        # 마지막 송신 시각 기준으로 재던 구현은 여기서 4.3 fps 로 떨어졌다.
        self.assertAlmostEqual(rate, 5.0, delta=0.25)

    def test_수집주기가_배수가_아니어도_목표에_맞는다(self):
        # 24 fps 수집 → 5 fps 송신. 24 는 5 의 배수가 아니다
        pub = FramePublisher("inproc://test", publish_fps=5.0)
        passed = self._run_gate(pub, fps=24.0, seconds=10.0)
        rate = (len(passed) - 1) / ((passed[-1] - passed[0]) / NS)
        self.assertAlmostEqual(rate, 5.0, delta=0.25)

    def test_마감이_밀려도_버스트가_없다(self):
        # 3초 끊겼다 재개해도 밀린 마감이 한꺼번에 쏟아지면 안 된다
        pub = FramePublisher("inproc://test", publish_fps=5.0)
        base = 1_000_000_000
        pub._observe_interval(base)
        pub._advance_deadline(base)

        resumed = base + 3 * NS
        pair = StereoPair(1, make_frame("left", 1, resumed), None, 0)
        self.assertTrue(pub.should_publish(pair))
        pub._advance_deadline(resumed)
        # 재개 직후 다음 프레임(+66 ms)은 통과하면 안 된다
        nxt = StereoPair(2, make_frame("left", 2, resumed + 66_000_000), None, 0)
        self.assertFalse(pub.should_publish(nxt))

    def test_publish_fps가_0이면_전부_통과(self):
        pub = FramePublisher("inproc://test", publish_fps=0)
        pair = StereoPair(1, make_frame("left", 1, 1000), None, 0)
        self.assertTrue(pub.should_publish(pair))


# ─────────────────────────────────────────────────────────────
# 직렬화
# ─────────────────────────────────────────────────────────────

class TestSerialization(unittest.TestCase):

    def test_멀티파트_왕복(self):
        header = {"pair_id": 7, "mono_ns": 123, "wall_ns": 456, "stereo": True}
        parts = [b"frame", json.dumps(header).encode(), b"LEFTJPEG", b"RIGHTJPEG"]

        pair = parse_multipart(parts)
        self.assertEqual(pair.pair_id, 7)
        self.assertEqual(pair.mono_ns, 123)
        self.assertTrue(pair.is_stereo)
        self.assertEqual(pair.left_jpeg, b"LEFTJPEG")
        self.assertEqual(pair.nbytes, len(b"LEFTJPEG") + len(b"RIGHTJPEG"))

    def test_mono_메시지는_3파트(self):
        header = {"pair_id": 1, "mono_ns": 1, "wall_ns": 2, "stereo": False}
        pair = parse_multipart([b"frame", json.dumps(header).encode(), b"L"])
        self.assertIsNone(pair.right_jpeg)
        self.assertFalse(pair.is_stereo)

    def test_파트가_모자라면_거부(self):
        with self.assertRaises(ValueError):
            parse_multipart([b"frame", b"{}"])


# ─────────────────────────────────────────────────────────────
# 합성 소스 (numpy 필요)
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# 시작 전 확인
# ─────────────────────────────────────────────────────────────

class TestPreflight(unittest.TestCase):
    """cv2 가 없으면 조용히 도는 게 아니라 시작 시점에 죽어야 한다.

    지연 임포트라 없어도 서비스가 뜨고, 인코딩에서 프레임마다 실패하면서
    통계를 뜯어보기 전에는 원인을 알 수 없는 상태가 된다.
    """

    def test_cv2가_없으면_시작을_거부한다(self):
        import builtins
        from camera.service import CaptureService

        real_import = builtins.__import__

        def no_cv2(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("No module named 'cv2'")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = no_cv2
        try:
            with self.assertRaises(RuntimeError) as ctx:
                CaptureService._preflight()
        finally:
            builtins.__import__ = real_import

        # 원인만 알리는 게 아니라 고치는 방법까지 메시지에 있어야 한다
        self.assertIn("--system-site-packages", str(ctx.exception))

    def test_cv2가_있으면_통과한다(self):
        from camera.service import CaptureService

        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("cv2 없음")
        CaptureService._preflight()


class TestEncodeErrorLogging(unittest.TestCase):

    def test_첫_인코딩_실패만_로그로_남긴다(self):
        import logging as _logging
        from camera.publisher import FramePublisher

        pub = FramePublisher("inproc://test", publish_fps=0)
        pair = StereoPair(1, make_frame("left", 1, 1000), None, 0)

        with self.assertLogs("floaq.camera", level=_logging.ERROR) as cm:
            # FakeImage 는 ndarray 가 아니라 imencode 가 반드시 터진다
            self.assertFalse(pub.publish(pair))
        self.assertEqual(len(cm.records), 1)
        self.assertEqual(pub.stats.encode_errors, 1)

        # 두 번째부터는 세기만 한다. 매 프레임 찍으면 로그가 잠긴다
        pub.publish(StereoPair(2, make_frame("left", 2, 2000), None, 0))
        self.assertEqual(pub.stats.encode_errors, 2)


# ─────────────────────────────────────────────────────────────
# 장치 장애와 재연결
# ─────────────────────────────────────────────────────────────

class FlakySource:
    """N 번 grab 한 뒤 장치가 빠진 것처럼 예외를 던진다."""

    opened = 0

    def __init__(self, cam_id: str, fail_after: int) -> None:
        self.cam_id = cam_id
        self._fail_after = fail_after
        self._n = 0
        self._open = False

    def open(self) -> None:
        FlakySource.opened += 1
        self._n = 0
        self._open = True

    def grab(self) -> bool:
        self._n += 1
        if self._n > self._fail_after:
            raise OSError("장치가 빠졌다")
        time.sleep(0.005)
        return True

    def retrieve(self):
        return FakeImage()

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open


class TestReconnect(unittest.TestCase):

    def test_장치가_빠지면_다시_연다(self):
        import camera.capture as capture_mod
        from camera.capture import CameraCapture

        FlakySource.opened = 0
        original = capture_mod.make_source
        capture_mod.make_source = lambda cfg: FlakySource(cfg.cam_id, fail_after=3)
        try:
            cap = CameraCapture(
                CameraConfig("left", "synthetic"), stale_after_s=0.2,
            )
            cap._backoff = 0.05     # 시험에서 기다릴 이유가 없다
            cap.start()
            time.sleep(0.8)
            cap.stop()
        finally:
            capture_mod.make_source = original

        # 여러 번 다시 열렸어야 한다. 스레드는 살아서 계속 재시도한다.
        self.assertGreater(FlakySource.opened, 1)
        self.assertGreater(cap.stats.reopens, 0)
        self.assertGreater(cap.stats.grab_errors, 0)
        self.assertGreater(cap.stats.grabbed, 0)

    def test_열지_못해도_스레드가_죽지_않는다(self):
        import camera.capture as capture_mod
        from camera.capture import CameraCapture

        def always_fail(cfg):
            raise RuntimeError("카메라를 열지 못했다")

        original = capture_mod.make_source
        capture_mod.make_source = always_fail
        try:
            cap = CameraCapture(CameraConfig("left", "/dev/video9"))
            cap._backoff = 0.05
            cap.start()
            time.sleep(0.3)
            # 프로세스가 죽으면 상태를 보고할 주체도 같이 사라진다
            self.assertTrue(cap.is_running)
            self.assertIsNotNone(cap.open_error)
            self.assertIsNone(cap.wait_for_frame(timeout_s=0.1))
            cap.stop()
        finally:
            capture_mod.make_source = original


@unittest.skipUnless(HAS_NUMPY, "numpy 없음")
class TestSyntheticCapture(unittest.TestCase):

    def test_설정한_해상도로_프레임을_만든다(self):
        from camera.source import SyntheticSource

        cfg = CameraConfig("left", "synthetic", width=320, height=240, capture_fps=60)
        src = SyntheticSource(cfg)
        src.open()
        self.assertTrue(src.grab())
        img = src.retrieve()
        src.close()
        self.assertEqual(img.shape, (240, 320, 3))

    def test_캡처_스레드가_프레임을_쌓는다(self):
        from camera.capture import CameraCapture

        cfg = CameraConfig("left", "synthetic", width=160, height=120, capture_fps=50)
        cap = CameraCapture(cfg)
        cap.start()
        try:
            f = cap.wait_for_frame(timeout_s=2.0)
            self.assertIsNotNone(f)
            self.assertEqual(f.cam_id, "left")
            self.assertGreater(f.seq, 0)
            time.sleep(0.3)
            self.assertGreater(cap.stats.grabbed, 1)
            # 아무도 안 가져간 프레임이 덮어써지면 드롭으로 잡혀야 한다
            self.assertGreater(cap.stats.dropped, 0)
        finally:
            cap.stop()

    def test_스테레오_페어링_실동작(self):
        from camera.capture import CameraCapture

        left = CameraCapture(CameraConfig("left", "synthetic", width=160, height=120, capture_fps=30))
        right = CameraCapture(CameraConfig("right", "synthetic", width=160, height=120, capture_fps=30))
        left.start()
        right.start()
        pairer = StereoPairer(left, right, max_skew_ms=50.0)
        try:
            pairs = [pairer.next_pair(timeout_s=1.0) for _ in range(10)]
            got = [p for p in pairs if p is not None]
            self.assertGreaterEqual(len(got), 5)
            stereo = [p for p in got if p.is_stereo]
            # 독립 스레드라 전부 맞지는 않지만 대부분은 맞아야 한다
            self.assertGreaterEqual(len(stereo), len(got) // 2)
        finally:
            left.stop()
            right.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Jetson ZMQ JPEG 스트림을 디코드 없이 RAM에 보관하는 독립 링버퍼."""

import json
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path


NS = 1_000_000_000


@dataclass(frozen=True)
class VideoFrame:
    header: dict
    left_jpeg: bytes = None
    right_jpeg: bytes = None

    @property
    def mono_ns(self):
        return int(self.header["mono_ns"])

    @property
    def wall_ns(self):
        return int(self.header["wall_ns"])

    @property
    def size(self):
        return (len(self.left_jpeg) if self.left_jpeg else 0) + (
            len(self.right_jpeg) if self.right_jpeg else 0)


@dataclass
class VideoWindow:
    frames: list
    event_wall_ns: int
    before_s: float
    after_s: float
    anchor_error_ms: float
    actual_span_s: float
    truncated: bool


def parse_multipart(parts):
    """jetson_camera의 [topic, JSON, left JPEG, right JPEG?] 형식을 검사한다."""
    if len(parts) not in (3, 4) or parts[0] != b"frame":
        raise ValueError("ZMQ 프레임 형식 오류")
    header = json.loads(parts[1].decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("헤더가 JSON 객체가 아닙니다")
    for key in ("mono_ns", "wall_ns", "pair_id"):
        if key not in header:
            raise ValueError("헤더에 {}가 없습니다".format(key))
    if not parts[2].startswith(b"\xff\xd8"):
        raise ValueError("왼쪽 JPEG 시작 마커가 없습니다")
    right = parts[3] if len(parts) == 4 else None
    if right is not None and not right.startswith(b"\xff\xd8"):
        raise ValueError("오른쪽 JPEG 시작 마커가 없습니다")
    return VideoFrame(header, bytes(parts[2]), bytes(right) if right is not None else None)


class VideoRingBuffer:
    """시간과 메모리 상한을 동시에 적용한다. 초과 시 가장 오래된 쌍을 버린다."""

    def __init__(self, seconds=40.0, max_bytes=128 * 1024 * 1024, expected_fps=5.0):
        if seconds <= 0 or max_bytes <= 0 or expected_fps <= 0:
            raise ValueError("seconds, max_bytes, expected_fps는 양수여야 합니다")
        self.seconds = seconds
        self.max_bytes = max_bytes
        self.expected_fps = expected_fps
        self._frames = deque()
        self._bytes = 0
        self._evicted = 0
        self._lock = threading.Lock()

    def append(self, frame):
        with self._lock:
            if self._frames and frame.mono_ns <= self._frames[-1].mono_ns:
                raise ValueError("mono_ns는 증가해야 합니다")
            self._frames.append(frame)
            self._bytes += frame.size
            cutoff = frame.mono_ns - int(self.seconds * NS)
            while self._frames and (
                self._frames[0].mono_ns < cutoff or self._bytes > self.max_bytes
            ):
                old = self._frames.popleft()
                self._bytes -= old.size
                self._evicted += 1

    def snapshot(self):
        with self._lock:
            return list(self._frames)

    def stats(self):
        with self._lock:
            span = 0.0
            if len(self._frames) > 1:
                span = (self._frames[-1].mono_ns - self._frames[0].mono_ns) / NS
            return {"frames": len(self._frames), "span_s": round(span, 2),
                    "bytes": self._bytes, "evicted": self._evicted}

    def cut_event(self, event_wall_ns, before_s=30.0, after_s=5.0):
        frames = self.snapshot()
        if not frames:
            return VideoWindow([], event_wall_ns, before_s, after_s, 0.0, 0.0, True)
        anchor = min(frames, key=lambda frame: abs(frame.wall_ns - event_wall_ns))
        lo = anchor.mono_ns - int(before_s * NS)
        hi = anchor.mono_ns + int(after_s * NS)
        selected = [frame for frame in frames if lo <= frame.mono_ns <= hi]
        span = ((selected[-1].mono_ns - selected[0].mono_ns) / NS
                if len(selected) > 1 else 0.0)
        tolerance_ns = int(NS / self.expected_fps)
        truncated = (frames[0].mono_ns > lo + tolerance_ns or
                     frames[-1].mono_ns < hi - tolerance_ns or
                     abs(anchor.wall_ns - event_wall_ns) > tolerance_ns)
        return VideoWindow(selected, event_wall_ns, before_s, after_s,
                           (anchor.wall_ns - event_wall_ns) / 1e6, span, truncated)


def write_video_capture(window, output_dir):
    """사고 때만 JPEG와 인덱스를 기록한다. 평상시에는 디스크를 쓰지 않는다."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    index = []
    for number, frame in enumerate(window.frames):
        left_name = None
        if frame.left_jpeg is not None:
            left_name = "{:04d}_left.jpg".format(number)
            (directory / left_name).write_bytes(frame.left_jpeg)
        right_name = None
        if frame.right_jpeg is not None:
            right_name = "{:04d}_right.jpg".format(number)
            (directory / right_name).write_bytes(frame.right_jpeg)
        index.append({"left": left_name, "right": right_name, "header": frame.header})
    (directory / "index.json").write_text(
        json.dumps({"event_wall_ns": window.event_wall_ns,
                    "before_s": window.before_s, "after_s": window.after_s,
                    "anchor_error_ms": window.anchor_error_ms,
                    "actual_span_s": window.actual_span_s,
                    "truncated": window.truncated,
                    "frames": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory / "index.json"

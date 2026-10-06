#!/usr/bin/env python3
"""프레임 구독자 — IOT-01 / Jira floaq-18

퍼블리셔의 상대편이다. AI 탐지 모듈과 링버퍼(floaq-146)가 같은 스트림을
구독하므로, 각자 파싱 코드를 쓰지 않도록 여기에 한 벌만 둔다.
메시지 구조가 바뀌면 이 파일과 publisher.py 만 같이 고치면 된다.

설계 원칙
  헤더만 먼저 읽고 이미지 디코드는 필요할 때만 한다.
  링버퍼는 JPEG 바이트를 그대로 보관하는 쪽이 메모리에 유리하고
  (사고 전 30초 × 5 fps = 150장), 탐지는 디코드가 필요하다.
  둘의 요구가 다르므로 디코드를 강제하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

NS = 1_000_000_000


@dataclass(slots=True)
class ReceivedPair:
    """수신한 스테레오 쌍. 이미지는 아직 JPEG 바이트 상태다."""

    header: dict
    left_jpeg: bytes
    right_jpeg: Optional[bytes]

    @property
    def pair_id(self) -> int:
        """수집 쪽 쌍 번호. 솎아내기 때문에 연속하지 않는다."""
        return int(self.header["pair_id"])

    @property
    def pub_seq(self) -> int:
        """송신 번호. 연속해야 정상이고, 끊기면 전송 중 유실이다."""
        return int(self.header.get("pub_seq", 0))

    @property
    def mono_ns(self) -> int:
        return int(self.header["mono_ns"])

    @property
    def wall_ns(self) -> int:
        return int(self.header["wall_ns"])

    @property
    def is_stereo(self) -> bool:
        return bool(self.header.get("stereo")) and self.right_jpeg is not None

    @property
    def nbytes(self) -> int:
        return len(self.left_jpeg) + (len(self.right_jpeg) if self.right_jpeg else 0)

    def decode_left(self) -> Any:
        return _decode(self.left_jpeg)

    def decode_right(self) -> Optional[Any]:
        return _decode(self.right_jpeg) if self.right_jpeg else None


def _decode(buf: bytes) -> Any:
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(buf, dtype=np.uint8), cv2.IMREAD_COLOR)


def parse_multipart(parts: list) -> ReceivedPair:
    """ZMQ 멀티파트를 ReceivedPair 로. zmq 없이도 테스트할 수 있게 분리했다."""
    if len(parts) < 3:
        raise ValueError(f"프레임 수가 부족하다: {len(parts)}")
    header = json.loads(parts[1].decode("utf-8"))
    left = parts[2]
    right = parts[3] if len(parts) > 3 else None
    return ReceivedPair(header=header, left_jpeg=left, right_jpeg=right)


class FrameSubscriber:
    """ZMQ SUB. 느리게 소비하면 퍼블리셔가 버린다 — 그게 의도된 동작이다."""

    def __init__(self, endpoint: str, topic: str = "frame", rcvhwm: int = 2) -> None:
        self._endpoint = endpoint
        self._topic = topic.encode()
        self._rcvhwm = rcvhwm
        self._sock: Any = None
        self.received = 0
        # pub_seq 가 건너뛴 개수 = 전송 중 유실. pair_id 로 세면
        # 의도적 솎아내기까지 유실로 잡혀 항상 큰 값이 나온다.
        self.lost = 0
        self._last_pub_seq = -1

    def open(self) -> None:
        import zmq

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.RCVHWM, self._rcvhwm)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SUBSCRIBE, self._topic)
        sock.connect(self._endpoint)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def recv(self, timeout_ms: int = 1000) -> Optional[ReceivedPair]:
        import zmq

        if self._sock is None:
            return None
        if not self._sock.poll(timeout_ms, zmq.POLLIN):
            return None

        pair = parse_multipart(self._sock.recv_multipart())
        self.received += 1
        seq = pair.pub_seq
        if seq and self._last_pub_seq >= 0 and seq > self._last_pub_seq + 1:
            self.lost += seq - self._last_pub_seq - 1
        self._last_pub_seq = seq
        return pair


def main() -> int:
    """수신 확인용. `python -m camera.subscriber` 로 돌린다."""
    import argparse
    import time

    p = argparse.ArgumentParser(description="프레임 수신 확인")
    p.add_argument("--endpoint", default="ipc:///tmp/floaq_frames")
    p.add_argument("--seconds", type=float, default=10.0)
    args = p.parse_args()

    sub = FrameSubscriber(args.endpoint)
    sub.open()
    t_end = time.monotonic() + args.seconds
    first_ns = None
    try:
        while time.monotonic() < t_end:
            pair = sub.recv(timeout_ms=1000)
            if pair is None:
                print("수신 없음 (퍼블리셔가 떠 있는지 확인)")
                continue
            if first_ns is None:
                first_ns = pair.mono_ns
            print(
                f"pair {pair.pair_id:>6} | "
                f"stereo={pair.is_stereo} | "
                f"skew={pair.header.get('skew_ms')} ms | "
                f"{pair.nbytes / 1024:.0f} KB | "
                f"t={(pair.mono_ns - first_ns) / NS:.2f}s"
            )
    finally:
        sub.close()
        print(f"수신 {sub.received} 쌍 · 전송 유실 {sub.lost} 쌍")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

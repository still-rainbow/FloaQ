#!/usr/bin/env python3
"""프레임 퍼블리셔 — IOT-01 / Jira floaq-18

설계 원칙
  ZMQ PUB/SUB 을 쓴다. PUB 은 구독자가 없거나 느려도 송신을 막지 않고
  버린다. 수집이 소비자 사정에 끌려가면 '실시간 촬영'이 성립하지 않으므로
  이 동작이 정확히 필요한 것이다. 버린 개수는 세어서 노출한다.

  같은 보드 안이면 ipc://, 보드를 넘기면 tcp:// — 엔드포인트 문자열만 바뀐다.
  현재 탐지는 Jetson 단독 배치이므로 ipc 가 기본값이다(DES-31 §1).

  ZMQ_CONFLATE 는 쓰지 않는다. 멀티파트 메시지에서 동작하지 않는다.
  대신 SNDHWM 을 작게 잡아 PUB 의 기본 드롭 동작에 맡긴다.

  메시지 구조 (멀티파트 4~5 프레임)
    [0] topic      : b"frame"           — SUB 구독 필터
    [1] header     : JSON utf-8         — frame.StereoPair.header() + 인코딩 정보
    [2] left JPEG  : bytes
    [3] right JPEG : bytes              — stereo 일 때만
  헤더를 따로 둬서 구독자가 이미지를 디코드하지 않고도 시각·pair_id 로
  버릴지 말지 먼저 정할 수 있게 한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .frame import StereoPair

log = logging.getLogger("floaq.camera")

NS = 1_000_000_000


@dataclass
class PublishStats:
    published: int = 0
    skipped_rate: int = 0       # publish_fps 솎아내기로 건너뛴 쌍
    dropped_hwm: int = 0        # HWM 에 걸려 ZMQ 가 버린 메시지
    encode_errors: int = 0
    bytes_sent: int = 0
    encode_ms_sum: float = 0.0

    def snapshot(self) -> dict:
        n = self.published
        return {
            "published": n,
            "skipped_rate": self.skipped_rate,
            "dropped_hwm": self.dropped_hwm,
            "encode_errors": self.encode_errors,
            "mb_sent": round(self.bytes_sent / 1e6, 2),
            "encode_ms_avg": round(self.encode_ms_sum / n, 2) if n else 0.0,
            "kb_per_frame": round(self.bytes_sent / n / 1024, 1) if n else 0.0,
        }


class FramePublisher:
    """스테레오 쌍을 JPEG 로 인코딩해 ZMQ PUB 으로 내보낸다."""

    def __init__(
        self,
        endpoint: str,
        topic: str = "frame",
        publish_fps: float = 5.0,
        jpeg_quality: int = 85,
        sndhwm: int = 2,
    ) -> None:
        self._endpoint = endpoint
        self._topic = topic.encode()
        self._min_interval_ns = int(NS / publish_fps) if publish_fps > 0 else 0
        self._quality = jpeg_quality
        self._sndhwm = sndhwm

        self._ctx: Any = None
        self._sock: Any = None
        # 마지막 송신 시각이 아니라 '다음 마감 시각'을 들고 간다.
        # 마지막 송신 기준으로 간격을 재면 프레임이 마감에 정확히 안 떨어질 때마다
        # 한 프레임씩 밀려서 목표 fps 에 계속 못 미친다
        # (15 fps 수집 → 5 fps 송신 요청이 실측 4.3 fps 로 나왔다).
        self._next_pub_ns = 0
        self._frame_interval_ns = 0     # 실측 수집 주기 (EMA)
        self._last_seen_ns = 0
        # 실제로 내보낸 메시지에만 붙는 번호.
        # pair_id 는 솎아내기 때문에 구독자 쪽에서 띄엄띄엄 보이므로
        # 그걸로는 '일부러 안 보낸 것'과 '전송 중 유실'을 구분할 수 없다.
        self._pub_seq = 0
        self.stats = PublishStats()

    def open(self) -> None:
        import zmq       # 지연 임포트 — 테스트에서 zmq 없이 인코딩만 검증한다

        self._ctx = zmq.Context.instance()
        sock = self._ctx.socket(zmq.PUB)
        sock.setsockopt(zmq.SNDHWM, self._sndhwm)
        # 종료 시 큐에 남은 메시지를 붙들지 않는다. 정지가 느려지면
        # systemd 가 SIGKILL 로 끊어 통계 로그를 못 남긴다.
        sock.setsockopt(zmq.LINGER, 0)
        sock.bind(self._endpoint)
        self._sock = sock
        # PUB 은 bind 직후 구독자 연결이 붙기 전까지 보낸 메시지를 버린다
        # (slow joiner). 첫 프레임이 통째로 사라지는 걸 줄이려 잠깐 쉰다.
        time.sleep(0.2)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    # ── 송신 ────────────────────────────────────────────────

    def should_publish(self, pair: StereoPair) -> bool:
        """publish_fps 로 솎아낸다. 수집 fps 보다 낮게 내보낼 때 쓴다.

        수집 주기가 송신 주기의 약수가 아니면 마감에 정확히 떨어지는 프레임이
        없다. 그때는 마감을 조금 넘긴 프레임이 아니라 마감에 가장 가까운
        프레임을 택해야 평균 fps 가 목표에 맞는다. 그래서 마감 직전
        반 프레임까지는 통과시킨다.
        """
        if self._min_interval_ns <= 0:
            return True
        if self._next_pub_ns == 0:
            return True
        return pair.mono_ns >= self._next_pub_ns - self._half_frame_ns()

    def _half_frame_ns(self) -> int:
        """관측한 수집 주기의 절반. 초반에는 0 이므로 마감을 그대로 쓴다."""
        return self._frame_interval_ns // 2

    def _advance_deadline(self, mono_ns: int) -> None:
        """다음 마감을 한 칸 민다.

        마감에 간격을 더해 나간다. 실제 송신 시각으로 리셋하면 오차가 누적돼
        목표 fps 에 계속 못 미친다. 다만 오래 멈췄다 재개할 때 밀린 마감이
        쌓여 한꺼번에 쏟아지면 안 되므로, 지나간 마감은 건너뛴다.
        """
        if self._next_pub_ns == 0:
            self._next_pub_ns = mono_ns + self._min_interval_ns
            return
        self._next_pub_ns += self._min_interval_ns
        if self._next_pub_ns <= mono_ns:
            missed = (mono_ns - self._next_pub_ns) // self._min_interval_ns + 1
            self._next_pub_ns += missed * self._min_interval_ns

    def _observe_interval(self, mono_ns: int) -> None:
        """수집 주기를 지수이동평균으로 추정한다. 설정값이 아니라 실측이다."""
        if self._last_seen_ns:
            gap = mono_ns - self._last_seen_ns
            if 0 < gap < NS:      # 1초를 넘는 간격은 끊김이므로 평균에 넣지 않는다
                self._frame_interval_ns = (
                    gap if self._frame_interval_ns == 0
                    else int(0.8 * self._frame_interval_ns + 0.2 * gap)
                )
        self._last_seen_ns = mono_ns

    def publish(self, pair: StereoPair) -> bool:
        """쌍 하나를 내보낸다. 솎아내기로 건너뛰면 False."""
        self._observe_interval(pair.mono_ns)
        if not self.should_publish(pair):
            self.stats.skipped_rate += 1
            return False

        t0 = time.monotonic()
        try:
            left_buf = self._encode(pair.left.image)
            right_buf = self._encode(pair.right.image) if pair.right is not None else None
        except Exception:
            self.stats.encode_errors += 1
            if self.stats.encode_errors == 1:
                # 첫 번째만 스택트레이스를 남긴다. 매 프레임 찍으면 로그가 잠긴다.
                # 이걸 안 남기면 서비스가 멀쩡히 뜬 채로 아무것도 못 보내는
                # 상태가 되고, 10초마다 나오는 통계를 뜯어봐야만 알 수 있다.
                log.exception("JPEG 인코딩 실패 — 이후 같은 오류는 세기만 한다")
            return False
        encode_ms = (time.monotonic() - t0) * 1000

        header = pair.header()
        header.update({
            "pub_seq": self._pub_seq + 1,
            "encoding": "jpeg",
            "quality": self._quality,
            "left_bytes": len(left_buf),
            "right_bytes": len(right_buf) if right_buf is not None else 0,
            "encode_ms": round(encode_ms, 2),
            "capture_age_ms": round(pair.left.age_ms, 2),
        })

        parts = [self._topic, json.dumps(header, separators=(",", ":")).encode()]
        parts.append(left_buf)
        if right_buf is not None:
            parts.append(right_buf)

        if not self._send(parts):
            # HWM 드롭도 그 슬롯을 쓴 것으로 친다. 마감을 안 밀면
            # 다음 프레임이 곧바로 또 통과해 버스트가 된다.
            self._advance_deadline(pair.mono_ns)
            return False

        self._advance_deadline(pair.mono_ns)
        self._pub_seq += 1
        self.stats.published += 1
        self.stats.encode_ms_sum += encode_ms
        self.stats.bytes_sent += sum(len(p) for p in parts)
        return True

    def _send(self, parts: list) -> bool:
        import zmq

        if self._sock is None:
            return False
        try:
            self._sock.send_multipart(parts, flags=zmq.NOBLOCK)
            return True
        except zmq.Again:
            # HWM 도달. 소비자가 못 따라오고 있다 — 버리는 게 맞다.
            self.stats.dropped_hwm += 1
            return False

    def _encode(self, image: Any) -> bytes:
        """JPEG 인코딩.

        지금은 CPU 인코딩이다. Jetson 의 NVJPG 가 유휴 상태이므로
        (DES-31 C-1, §5 #6) 여기를 하드웨어로 내리면 GPU/CPU 를 추론에
        돌려줄 수 있다. encode_ms 통계가 그 판단 근거가 된다.
        """
        import cv2

        ok, buf = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality],
        )
        if not ok:
            raise RuntimeError("JPEG 인코딩 실패")
        return buf.tobytes()

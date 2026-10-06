#!/usr/bin/env python3
"""스테레오 페어링 — IOT-01 / Jira floaq-18

설계 원칙
  좌우가 독립 스레드로 돌기 때문에 같은 순간의 프레임이 저절로 맞물리지는
  않는다. 왼쪽을 기준으로 삼고, 오른쪽에서 시각이 가장 가까운 프레임을 찾는다.
  허용 오차를 넘으면 쌍으로 인정하지 않는다 — 억지로 맞춘 쌍은
  스테레오 거리 계산에서 조용히 틀린 값을 만든다. 차라리 mono 로 떨어뜨린다.

  왼쪽을 고정 기준으로 두는 이유는 페어링이 결정적이어야 하기 때문이다.
  매번 더 최근 쪽을 기준으로 잡으면 같은 입력에서 다른 쌍이 나온다.

  skew 는 버리지 않고 그대로 실어 보낸다. 파도로 흔들리는 중이면
  skew 가 곧 시차 오차이므로 AI 쪽에서 신뢰도 판단에 써야 한다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from .capture import CameraCapture
from .frame import Frame, StereoPair

NS = 1_000_000_000


@dataclass
class PairStats:
    paired: int = 0
    mono_fallback: int = 0      # 오른쪽을 못 찾아 단안으로 내보낸 횟수
    skew_sum_ns: int = 0
    skew_max_ns: int = 0

    def record(self, skew_ns: int) -> None:
        self.paired += 1
        a = abs(skew_ns)
        self.skew_sum_ns += a
        self.skew_max_ns = max(self.skew_max_ns, a)

    def pair_rate_low(self, threshold: float = 0.9, min_samples: int = 30) -> bool:
        """쌍이 안 맞는 비율이 높은가. 표본이 적을 때는 판정하지 않는다."""
        total = self.paired + self.mono_fallback
        return total >= min_samples and (self.paired / total) < threshold

    def snapshot(self) -> dict:
        mean = self.skew_sum_ns / self.paired if self.paired else 0.0
        total = self.paired + self.mono_fallback
        return {
            "paired": self.paired,
            "mono_fallback": self.mono_fallback,
            "pair_rate": round(self.paired / total, 3) if total else 0.0,
            "skew_mean_ms": round(mean / 1e6, 2),
            "skew_max_ms": round(self.skew_max_ns / 1e6, 2),
        }


class StereoPairer:
    """왼쪽 새 프레임마다 오른쪽에서 짝을 찾아 쌍을 만든다."""

    def __init__(
        self,
        left: CameraCapture,
        right: Optional[CameraCapture],
        max_skew_ms: float = 33.0,
    ) -> None:
        self._left = left
        self._right = right
        self._max_skew_ns = int(max_skew_ms * 1e6)
        self._pair_id = 0
        self._lock = threading.Lock()
        self.stats = PairStats()

    def next_pair(self, timeout_s: float = 1.0) -> Optional[StereoPair]:
        """다음 쌍. 왼쪽에 새 프레임이 없으면 None."""
        left = self._left.wait_for_frame(timeout_s)
        if left is None:
            return None

        with self._lock:
            self._pair_id += 1
            pair_id = self._pair_id

        if self._right is None:
            return StereoPair(pair_id, left, None, 0)

        right = self._closest_right(left, timeout_s)
        if right is None:
            self.stats.mono_fallback += 1
            return StereoPair(pair_id, left, None, 0)

        skew = right.mono_ns - left.mono_ns
        if abs(skew) > self._max_skew_ns:
            # 맞물리지 않은 쌍이다. 붙여서 내보내면 안 된다.
            self.stats.mono_fallback += 1
            return StereoPair(pair_id, left, None, 0)

        self.stats.record(skew)
        return StereoPair(pair_id, left, right, skew)

    def _closest_right(self, left: Frame, timeout_s: float) -> Optional[Frame]:
        """왼쪽 시각에 가장 가까운 오른쪽 프레임.

        오른쪽 최신 프레임이 왼쪽보다 과거라면, 더 가까운 프레임이 곧 들어올
        수 있으므로 허용 오차만큼만 기다려 본다. 무한정 기다리지는 않는다 —
        오른쪽이 죽었을 때 왼쪽까지 멈추면 독립 스레드로 나눈 의미가 없다.
        """
        assert self._right is not None
        cand = self._right.latest()

        if cand is not None and cand.mono_ns >= left.mono_ns:
            return cand

        wait_s = min(self._max_skew_ns / NS, timeout_s)
        nxt = self._right.wait_for_frame(wait_s)
        if nxt is None:
            return cand
        if cand is None:
            return nxt
        # 앞뒤 두 후보 중 왼쪽에 더 가까운 쪽
        return nxt if abs(nxt.mono_ns - left.mono_ns) < abs(cand.mono_ns - left.mono_ns) else cand

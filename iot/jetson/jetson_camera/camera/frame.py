#!/usr/bin/env python3
"""프레임 데이터 모델 — IOT-01 / Jira floaq-18 (Jetson Orin Nano)

설계 원칙
  시계 규칙은 IMU 링버퍼(floaq-146)와 동일하게 맞춘다.
    mono_ns : 순서·스테레오 페어링·구간 길이 계산 기준. NTP 영향 없음
    wall_ns : 기록·조회용. 사고 시각으로 구간을 자를 때만 쓴다
  두 시계를 섞으면 NTP 점프가 난 순간 30초 창과 페어링이 같이 틀어진다.
  Jetson 은 makestep 이 켜져 있어 점프가 실제로 일어난다(Jira floaq-178).

  타임스탬프는 grab() 직후에 찍는다. retrieve()·디코드 시간이 섞이면
  스테레오 skew 가 실제보다 커 보여 DES-31 §5 #5 측정값을 못 믿게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

NS = 1_000_000_000


# ─────────────────────────────────────────────────────────────
# 단일 프레임
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Frame:
    """카메라 한 대에서 나온 프레임 한 장.

    image 는 BGR ndarray 다. 복사하지 않고 그대로 넘기므로
    받은 쪽에서 내용을 바꾸면 안 된다. 바꿔야 하면 copy() 한다.
    """

    cam_id: str
    seq: int            # 카메라별 0부터 증가. 드롭 판정에 쓴다
    mono_ns: int        # grab() 직후 time.monotonic_ns()
    wall_ns: int        # grab() 직후 time.time_ns()
    image: Any          # numpy.ndarray (H, W, 3) BGR

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def age_ms(self) -> float:
        """지금 기준 이 프레임이 몇 ms 전 것인가."""
        import time
        return (time.monotonic_ns() - self.mono_ns) / 1e6


# ─────────────────────────────────────────────────────────────
# 스테레오 쌍
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class StereoPair:
    """좌우 프레임 한 쌍.

    skew_ns 는 좌우 grab 시각 차이다. 스테레오 거리 계산의 오차 예산에
    직접 들어가므로 버리지 않고 헤더에 실어 보낸다.
    선박이 파도로 흔들리는 중이면 skew 가 곧 시차 오차가 된다.
    """

    pair_id: int
    left: Frame
    right: Optional[Frame]      # 한쪽만 살아있을 때 None (mono 폴백)
    skew_ns: int                # right 가 None 이면 0

    @property
    def mono_ns(self) -> int:
        """쌍의 기준 시각. 왼쪽을 기준으로 삼는다."""
        return self.left.mono_ns

    @property
    def wall_ns(self) -> int:
        return self.left.wall_ns

    @property
    def skew_ms(self) -> float:
        return self.skew_ns / 1e6

    @property
    def is_stereo(self) -> bool:
        return self.right is not None

    def header(self) -> dict:
        """AI 탐지 모듈로 보내는 메타데이터.

        ai/docs/interface.md 의 detection contract 가 frame identifier 와
        timestamp 를 요구하므로 pair_id 와 두 시계를 모두 넣는다.
        탐지 결과가 돌아왔을 때 이 pair_id 로 원본 프레임을 다시 찾는다.
        """
        return {
            "pair_id": self.pair_id,
            "mono_ns": self.mono_ns,
            "wall_ns": self.wall_ns,
            "created_at": self.wall_ns // NS,   # ERD: int unixtime
            "width": self.left.width,
            "height": self.left.height,
            "stereo": self.is_stereo,
            "skew_ms": round(self.skew_ms, 3),
            "left_seq": self.left.seq,
            "right_seq": self.right.seq if self.right is not None else None,
        }

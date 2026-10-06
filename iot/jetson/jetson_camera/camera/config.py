#!/usr/bin/env python3
"""촬영 설정 — IOT-01 / Jira floaq-18

설계 원칙
  카메라 모델이 아직 확정 전이다(DES-31 §4 — 랩실 웹캠 불출).
  해상도·fps·FOURCC 를 코드에 박지 않고 전부 설정으로 뺀다.
  모델이 바뀌어도 소스 코드가 아니라 실행 인자만 바뀌어야 한다.

  capture_fps 와 publish_fps 를 분리한다.
  탐지는 높은 fps 가 유리하지만 저장(IOT-19)은 5 fps 로 확정돼 있다
  (DES-31 C-8). 카메라를 5 fps 로 낮춰버리면 탐지 쪽 여지가 사라지므로
  수집은 높게 두고 내보낼 때 솎아낸다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# UVC 웹캠에서 MJPG 를 지정하지 않으면 YUYV 로 떨어져
# 1280x720 에서 5~10 fps 밖에 안 나온다. 기본값을 MJPG 로 둔다.
DEFAULT_FOURCC = "MJPG"


@dataclass(slots=True)
class CameraConfig:
    """카메라 한 대 설정."""

    cam_id: str
    device: str                       # "/dev/video0" 또는 "0" 또는 "synthetic"
    width: int = 1280
    height: int = 720
    fourcc: str = DEFAULT_FOURCC
    capture_fps: float = 15.0

    # V4L2 버퍼를 1로 두면 오래된 프레임이 쌓이지 않는다.
    # 큐가 길면 지연이 누적돼 '실시간'이 아니게 된다.
    buffer_size: int = 1

    @property
    def is_synthetic(self) -> bool:
        return self.device.strip().lower() == "synthetic"

    @property
    def resolved_node(self) -> str:
        """로그에 찍을 실제 장치 노드.

        🔴 이 속성이 없으면 카메라를 못 열었을 때 그 사실을 남기는 로그 줄에서
           AttributeError 가 난다. 그 예외는 `_open_source` 밖으로 나가
           **캡처 스레드를 죽인다** — 재연결이 영영 안 된다. 카메라가 늦게
           올라오는 시연에서 제일 먼저 터지는 자리다.

        ⚠ `/dev/v4l/by-id/...` 같은 링크를 주면 무엇이 열렸는지 로그로 알 수 없다.
          링크를 풀어 둔다. 링크가 아니면 준 값 그대로다.
        """
        d = self.device.strip()
        if d.isdigit() or self.is_synthetic:
            return d
        try:
            return os.path.realpath(d)
        except OSError:
            return d

    @property
    def v4l2_index(self) -> object:
        """cv2.VideoCapture 에 넘길 값. 숫자면 int, 아니면 경로 문자열."""
        d = self.device.strip()
        return int(d) if d.isdigit() else d


@dataclass(slots=True)
class ServiceConfig:
    """촬영 서비스 전체 설정."""

    left: CameraConfig
    right: CameraConfig | None = None       # None 이면 mono 운용

    # 페어링 허용 오차. 이보다 벌어진 좌우 조합은 쌍으로 인정하지 않는다.
    # 15 fps 면 프레임 간격이 66 ms 다. 그 절반을 기본값으로 둔다.
    max_skew_ms: float = 33.0

    # 이 시간 동안 새 프레임이 없으면 장치가 죽은 것으로 보고 재연결한다.
    stale_after_s: float = 2.0

    publish_fps: float = 5.0
    jpeg_quality: int = 85

    endpoint: str = "ipc:///tmp/floaq_frames"   # 같은 보드 안이면 ipc 가 빠르다
    topic: str = "frame"

    stats_interval_s: float = 10.0

    @property
    def cameras(self) -> list[CameraConfig]:
        return [c for c in (self.left, self.right) if c is not None]

    @property
    def is_stereo(self) -> bool:
        return self.right is not None


def default_config() -> ServiceConfig:
    """동일 모델 웹캠 2대를 /dev/video0, /dev/video2 에 꽂은 기본 구성.

    UVC 웹캠은 장치당 video 노드를 2개(영상 + 메타데이터) 잡는 경우가 많아
    두 번째 카메라가 video1 이 아니라 video2 로 올라온다.
    실제 번호는 `v4l2-ctl --list-devices` 로 확인한다.
    """
    return ServiceConfig(
        left=CameraConfig(cam_id="left", device="/dev/video0"),
        right=CameraConfig(cam_id="right", device="/dev/video2"),
    )


def config_from_env() -> ServiceConfig:
    """환경변수 오버라이드. systemd 유닛에서 쓴다."""
    cfg = default_config()
    env = os.environ.get

    if env("FLOAQ_CAM_LEFT"):
        cfg.left.device = env("FLOAQ_CAM_LEFT", cfg.left.device)
    right_dev = env("FLOAQ_CAM_RIGHT")
    if right_dev is not None:
        cfg.right = None if right_dev.lower() in ("", "none") else CameraConfig(
            cam_id="right", device=right_dev,
        )
    if env("FLOAQ_FRAME_ENDPOINT"):
        cfg.endpoint = env("FLOAQ_FRAME_ENDPOINT", cfg.endpoint)
    if env("FLOAQ_PUBLISH_FPS"):
        cfg.publish_fps = float(env("FLOAQ_PUBLISH_FPS", cfg.publish_fps))

    for cam in cfg.cameras:
        if env("FLOAQ_CAM_WIDTH"):
            cam.width = int(env("FLOAQ_CAM_WIDTH", cam.width))
        if env("FLOAQ_CAM_HEIGHT"):
            cam.height = int(env("FLOAQ_CAM_HEIGHT", cam.height))
        if env("FLOAQ_CAPTURE_FPS"):
            cam.capture_fps = float(env("FLOAQ_CAPTURE_FPS", cam.capture_fps))
    return cfg

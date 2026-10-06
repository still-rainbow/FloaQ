"""실시간 영상 촬영 — IOT-01 / Jira floaq-18 (Jetson Orin Nano)

선박 후방 스테레오 카메라에서 프레임을 수집해 AI 탐지 모듈로 넘긴다.
보드 배치는 DES-31 §1 을 따른다 — 영상 수집·추론은 Jetson, Pi 5 는 제어 전담.
"""

from .config import CameraConfig, ServiceConfig, config_from_env, default_config
from .frame import Frame, StereoPair
from .capture import CameraCapture, CaptureStats
from .stereo import PairStats, StereoPairer
from .publisher import FramePublisher, PublishStats
from .service import CaptureService, install_signal_handlers

__all__ = [
    "CameraConfig", "ServiceConfig", "config_from_env", "default_config",
    "Frame", "StereoPair",
    "CameraCapture", "CaptureStats",
    "StereoPairer", "PairStats",
    "FramePublisher", "PublishStats",
    "CaptureService", "install_signal_handlers",
]

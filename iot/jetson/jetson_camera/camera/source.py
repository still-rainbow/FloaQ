#!/usr/bin/env python3
"""카메라 소스 — IOT-01 / Jira floaq-18

설계 원칙
  grab() 과 retrieve() 를 분리해 노출한다.
  OpenCV 의 read() 는 grab+retrieve 를 묶어버려서 디코드 시간이 타임스탬프에
  섞인다. 스테레오에서는 이 차이가 그대로 skew 오차가 되므로,
  시각은 grab() 직후에 찍고 디코드는 그 뒤에 한다.

  cv2 는 지연 임포트한다. JetPack 시스템 패키지라 uv 의존성에 없고
  (iot/jetson/pyproject.toml 이 opencv-python 계열을 명시적으로 제외한다),
  합성 소스만 쓰는 개발 PC·CI 에서는 없어도 돌아야 한다.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional, Protocol

from .config import CameraConfig


class CameraSource(Protocol):
    """카메라 한 대의 최소 인터페이스."""

    cam_id: str

    def open(self) -> None: ...

    def grab(self) -> bool:
        """센서에서 프레임 한 장을 잡아둔다. 디코드는 하지 않는다."""
        ...

    def retrieve(self) -> Optional[Any]:
        """직전 grab() 한 프레임을 디코드해 BGR ndarray 로 돌려준다."""
        ...

    def close(self) -> None: ...

    @property
    def is_open(self) -> bool: ...


# ─────────────────────────────────────────────────────────────
# V4L2 (실물 USB 웹캠)
# ─────────────────────────────────────────────────────────────

class V4l2Source:
    """UVC USB 웹캠.

    ⚠ 카메라 모델 미확정 상태에서 작성했다(DES-31 §4).
    실물 연결 후 확인할 것:
      - MJPG 지원 여부와 해당 해상도의 실효 fps (`v4l2-ctl --list-formats-ext`)
      - 자동 노출·화이트밸런스가 좌우에서 따로 놀지 않는지.
        스테레오 캘리브레이션은 두 카메라의 노출이 같다고 가정한다.
      - USB 대역. 같은 허브에 MJPG 2스트림이면 보통 버티지만
        YUYV 로 떨어지면 한 대도 못 버틴다 (DES-31 §5 #5).
    """

    def __init__(self, config: CameraConfig) -> None:
        self.cam_id = config.cam_id
        self._cfg = config
        self._cap: Any = None

    def open(self) -> None:
        import cv2       # 지연 임포트 — JetPack 시스템 cv2

        cap = cv2.VideoCapture(self._cfg.v4l2_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"카메라를 열지 못했다: {self._cfg.device}")

        # 순서가 중요하다. FOURCC 를 해상도보다 먼저 지정해야
        # 드라이버가 MJPG 프로파일에서 해상도를 고른다.
        # 거꾸로 하면 YUYV 로 잡힌 뒤 FOURCC 변경이 무시되는 드라이버가 있다.
        fourcc = cv2.VideoWriter_fourcc(*self._cfg.fourcc)
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self._cfg.capture_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, self._cfg.buffer_size)

        self._cap = cap

    def actual_settings(self) -> dict:
        """드라이버가 실제로 받아들인 값. 요청값과 다를 수 있다.

        요청 1280x720@30 을 넣어도 드라이버가 조용히 640x480@15 로
        떨어뜨리는 경우가 흔하다. 로그에 남겨 두지 않으면
        나중에 fps 가 왜 안 나오는지 추적이 안 된다.
        """
        import cv2
        if self._cap is None:
            return {}
        raw = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        fourcc = "".join(chr((raw >> (8 * i)) & 0xFF) for i in range(4))
        return {
            "width": int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": self._cap.get(cv2.CAP_PROP_FPS),
            "fourcc": fourcc,
        }

    def grab(self) -> bool:
        return False if self._cap is None else bool(self._cap.grab())

    def retrieve(self) -> Optional[Any]:
        if self._cap is None:
            return None
        ok, img = self._cap.retrieve()
        return img if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and bool(self._cap.isOpened())


# ─────────────────────────────────────────────────────────────
# 합성 소스 (실물 없이 파이프라인 검증)
# ─────────────────────────────────────────────────────────────

class SyntheticSource:
    """실물 카메라 없이 아래 단계를 전부 돌리기 위한 소스.

    수평선과 그 위를 움직이는 표적을 그린다. 좌우 카메라에 시차를 주어
    스테레오 페어링과 시차 계산이 말이 되는지까지 확인할 수 있다.
    프레임마다 seq 를 그려 넣으므로 드롭이 눈으로 보인다.
    """

    def __init__(
        self,
        config: CameraConfig,
        disparity_px: int = 24,
        jitter_ms: float = 0.0,
    ) -> None:
        self.cam_id = config.cam_id
        self._cfg = config
        self._disparity = disparity_px if config.cam_id == "right" else 0
        self._jitter_s = jitter_ms / 1000.0
        self._open = False
        self._n = 0
        self._t0 = time.monotonic()
        self._period = 1.0 / max(config.capture_fps, 1e-6)
        self._next_t = 0.0

    def open(self) -> None:
        self._open = True
        self._t0 = time.monotonic()
        self._next_t = self._t0 + self._period

    def grab(self) -> bool:
        if not self._open:
            return False
        # 실제 카메라처럼 fps 만큼만 프레임을 내준다.
        # 안 그러면 아래 단계가 CPU 최대 속도로 돌아 측정값이 의미를 잃는다.
        delay = self._next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_t += self._period
        if self._jitter_s:
            time.sleep(self._jitter_s)
        self._n += 1
        return True

    def retrieve(self) -> Optional[Any]:
        if not self._open:
            return None
        import numpy as np

        w, h = self._cfg.width, self._cfg.height
        img = np.zeros((h, w, 3), dtype=np.uint8)

        horizon = h // 2
        img[:horizon, :] = (150, 120, 80)     # 하늘 (BGR)
        img[horizon:, :] = (90, 70, 40)       # 바다

        t = time.monotonic() - self._t0
        # 표적이 화면을 4초에 한 번 왕복한다
        x = int((0.5 + 0.4 * math.sin(2 * math.pi * t / 4.0)) * w) - self._disparity
        y = horizon + int(0.15 * h * math.sin(2 * math.pi * t / 1.7))
        r = max(6, w // 60)
        x0, x1 = max(0, x - r), min(w, x + r)
        y0, y1 = max(0, y - r), min(h, y + r)
        img[y0:y1, x0:x1] = (60, 60, 230)     # 표적

        # seq 를 픽셀로 찍어 둔다. 드롭이 나면 건너뛴 숫자가 보인다.
        self._draw_seq(img)
        return img

    def _draw_seq(self, img: Any) -> None:
        """cv2 없이 숫자를 찍는다. 개발 PC 에 cv2 가 없어도 돌아야 한다."""
        s = str(self._n % 100000)
        cell = 6
        for i, ch in enumerate(s):
            v = int(ch)
            # 자릿수만큼 막대를 세운다. 정밀할 필요 없다, 육안 확인용이다.
            x0 = 8 + i * (cell + 3)
            y1 = 8 + cell
            img[8:y1, x0:x0 + cell] = (255, 255, 255)
            if v:
                img[y1:y1 + v * 2, x0:x0 + cell] = (255, 255, 255)

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open


def make_source(config: CameraConfig) -> CameraSource:
    """설정을 보고 소스를 고른다."""
    return SyntheticSource(config) if config.is_synthetic else V4l2Source(config)

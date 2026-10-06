"""카메라 프레임을 YOLO에 통과시켜 라이브 스트림으로 보낸다.

촬영 스레드는 최신 JPEG만 넘기고 바로 돌아간다. 추론이 느려도 오래된
프레임을 쌓지 않으므로 키오스크에 지연된 장면을 보여주지 않는다.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class InferenceStream:
    def __init__(self, on_frame, *, weights: str, imgsz: int = 640,
                 conf: float = 0.25, device: str | None = None,
                 quality: int = 80, on_detect=None, cls: int = 0) -> None:
        """`on_detect(camera, raw_jpeg, best_conf, bbox)` 를 매 프레임 부른다.

        🔴 **판정은 여기서 하지 않는다.** 여기는 "이 프레임에서 제일 그럴듯한
           사람 하나" 까지만 말하고, 사고로 올릴지는 `_detect.Judge` 가 정한다.
           둘을 섞으면 임계값을 바꿀 때마다 추론 코드를 건드리게 된다.

        ⚠ `on_detect` 에 넘기는 jpeg 은 **상자를 안 그린 원본**이다. 기록으로
          남는 프레임에 우리가 그린 상자가 찍혀 있으면 나중에 오탐 분석을 못 한다.
        """
        import cv2
        import numpy as np
        from ultralytics import YOLO

        self._cv2 = cv2
        self._np = np
        self._model = YOLO(weights)
        self._on_frame = on_frame
        self._on_detect = on_detect
        #: COCO 의 person 은 0 이다. 자체 학습 모델이면 다를 수 있다
        self._cls = cls
        self._options = {"imgsz": imgsz, "conf": conf, "verbose": False}
        if device is not None:
            self._options["device"] = device
        self._encode_options = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        #: 마지막 프레임에서 본 클래스별 개수. --cls 진단용
        self.last_seen: dict = {}
        self._pending: dict[str, bytes] = {}
        self._cv = threading.Condition()
        self._stopping = False
        self._thread: threading.Thread | None = None
        #: 추론을 돌린 프레임 수. 차이로 fps 를 낸다 (`jetson/status`)
        self.processed = 0

    @property
    def names(self) -> dict:
        """모델의 클래스 번호 -> 이름.

        🔴 `--cls` 가 틀리면 **아무것도 안 잡히는데 화면에는 상자가 그려진다.**
           COCO 는 person 이 0 이지만 자체 학습 모델은 다르다. 부팅 때 찍어서
           눈으로 대조할 수 있게 한다.
        """
        return dict(getattr(self._model, "names", {}) or {})

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera-inference",
                                        daemon=True)
        self._thread.start()

    def submit(self, jpeg: bytes, camera: str,
               size: tuple[int, int] | None = None) -> None:
        """Capture 콜백의 세 인자를 받는다. 오래된 프레임은 교체한다.

        입력 size 대신 추론 결과의 실제 해상도를 스트림에 전달한다.
        """
        with self._cv:
            self._pending[camera] = jpeg
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._stopping = True
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stopping:
                    self._cv.wait()
                if self._stopping:
                    return
                # 먼저 기다린 카메라부터 처리한다. 한쪽이 빠르게 계속 들어와도
                # 다른 쪽 프레임이 영영 밀리지 않게 한다.
                camera = next(iter(self._pending))
                jpeg = self._pending.pop(camera)

            try:
                image = self._cv2.imdecode(
                    self._np.frombuffer(jpeg, dtype=self._np.uint8),
                    self._cv2.IMREAD_COLOR,
                )
                if image is None:
                    raise ValueError("JPEG 디코드 실패")
                result = self._model.predict(image, **self._options)[0]
                self.processed += 1
                if self._on_detect is not None:
                    best, box = _best_person(result, self._cls)
                    self.last_seen = seen_classes(result)
                    # ⚠ 사람이 없어도 부른다. Judge 가 연속을 끊으려면 "이번엔
                    #   없었다"는 것도 알아야 한다
                    self._on_detect(camera, jpeg, best, box)
                annotated = result.plot()
                ok, encoded = self._cv2.imencode(
                    ".jpg", annotated, self._encode_options)
                if not ok:
                    raise ValueError("JPEG 인코드 실패")
                height, width = annotated.shape[:2]
                self._on_frame(encoded.tobytes(), camera, (width, height))
            except Exception:
                log.exception("카메라 %s 추론 실패", camera)


def seen_classes(result) -> dict:
    """이 프레임에서 본 클래스별 개수. `--cls` 가 맞는지 보려고 센다."""
    boxes = getattr(result, "boxes", None)
    out: dict[int, int] = {}
    if boxes is None:
        return out
    for b in boxes:
        try:
            k = int(b.cls[0])
        except (IndexError, TypeError, ValueError):
            continue
        out[k] = out.get(k, 0) + 1
    return out


def _best_person(result, cls: int) -> tuple[float | None, tuple | None]:
    """한 프레임에서 신뢰도가 제일 높은 사람 하나. 없으면 `(None, None)`.

    ⚠ ultralytics 의 박스는 `xyxy` 인데 우리 규격(`JetsonDetection.bbox`)은
      `(x, y, w, h)` 다. 그대로 넘기면 폭·높이 자리에 좌표가 들어가서
      화면에 엉뚱한 상자가 그려진다. 여기서 바꾼다.
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return None, None

    best_conf = -1.0
    best_box = None
    for b in boxes:
        try:
            if int(b.cls[0]) != cls:
                continue
            c = float(b.conf[0])
        except (IndexError, TypeError, ValueError):
            continue
        if c > best_conf:
            best_conf = c
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            best_box = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
    return (best_conf, best_box) if best_box is not None else (None, None)

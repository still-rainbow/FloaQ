"""카메라에서 프레임을 읽어 JPEG 으로 넘긴다.

**SDK 의 본업이 아니다.** 추론 루프는 AI 팀이 돌리고, 거기서 `frame()` 을 부르면 된다.
이건 두 경우를 위한 것이다.

    ① 카메라를 붙이기 전후에 경로가 사는지 눈으로 보는 것 (`--stream-only --camera`)
    ② 추론을 아직 안 붙였을 때 화면만 먼저 띄우는 것

🔴 **카메라마다 스레드 하나다.** `VideoCapture.read()` 는 블로킹이고, 한 루프에서
   둘을 번갈아 읽으면 느린 쪽이 빠른 쪽을 끌어내린다. 좌우 프레임률이 달라지면
   스테레오 거리가 조용히 나빠진다.

🔴 **한 대만 열려도 계속 간다.** 카메라 하나가 안 붙었다고 나머지까지 멈추면 시연
   중에 아무것도 못 본다. 못 연 카메라는 경고만 남기고 넘어간다.

⚠ `cv2` 는 JetPack 시스템 패키지다. `pyproject.toml` 이 pip OpenCV 를 전이까지
  막아 둔 이유가 그것이다 — 두 벌이 되면 CUDA 가속이 없는 쪽이 잡힌다.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

#: JPEG 품질. 200KB 근처를 노린다 — 그 값이 프레임 예산의 기준이다.
QUALITY = 80


def parse_sources(spec: str) -> dict[str, str | int]:
    """`"L=0,R=1"` 또는 `"0,1"` -> `{"L": 0, "R": 1}`.

    GStreamer 파이프라인도 받는다: `"L=nvarguscamerasrc ! ..."`.
    CSI 카메라는 인덱스로 안 열리는 경우가 있어서 그 자리가 필요하다.
    """
    out: dict[str, str | int] = {}
    for i, part in enumerate(s.strip() for s in spec.split(",") if s.strip()):
        if "=" in part:
            name, src = part.split("=", 1)
        else:
            # 이름을 안 주면 순서대로 L, R
            name, src = ("L", "R")[i] if i < 2 else f"C{i}", part
        out[name.strip()] = int(src) if src.strip().isdigit() else src.strip()
    return out


class Capture:
    """카메라들을 열고 프레임을 콜백으로 넘긴다."""

    def __init__(self, sources: dict[str, str | int], *, fps: int = 5,
                 quality: int = QUALITY, width: int = 0, height: int = 0) -> None:
        self.sources = sources
        self.fps = fps
        self.quality = quality
        self.size = (width, height)
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        self.opened: list[str] = []
        #: 카메라별 마지막 프레임 시각(`time.monotonic`).
        #:
        #: 🔴 `opened` 만으로는 부족하다. 장치를 연 뒤 케이블이 빠져도 목록에는
        #:    계속 남는다 — 그러면 키오스크가 죽은 카메라를 정상으로 그린다.
        self.last_frame_at: dict[str, float] = {}

    def start(self, on_frame) -> int:
        """연 카메라 수를 돌려준다. 0 이면 하나도 못 열었다.

        `on_frame(jpeg: bytes, camera: str)` 이 프레임마다 불린다.
        """
        try:
            import cv2
        except ImportError:
            log.error("cv2 가 없다. JetPack 시스템 패키지를 상속하는지 확인할 것 "
                      "(uv venv --system-site-packages)")
            return 0

        for name, src in self.sources.items():
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                # 한 대가 없어도 나머지는 간다
                log.warning("카메라 %s 를 못 열었다 (%r) - 건너뛴다", name, src)
                cap.release()
                continue
            if self.size[0] and self.size[1]:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
            # ⚠ 버퍼를 1로 줄인다. 기본값이면 읽는 쪽이 느릴 때 옛 프레임이 쌓이고
            #   라이브 화면이 몇 초 뒤처진다
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            self.opened.append(name)
            t = threading.Thread(target=self._loop, args=(cv2, cap, name, on_frame),
                                 name=f"capture-{name}", daemon=True)
            t.start()
            self._threads.append(t)
            log.info("카메라 %s 열림 (%r)", name, src)

        if not self.opened:
            log.error("카메라를 하나도 못 열었다. `ls /dev/video*` 로 확인할 것")
        return len(self.opened)

    def stop(self) -> None:
        self._stopping.set()
        for t in self._threads:
            t.join(timeout=2.0)

    def _loop(self, cv2, cap, name: str, on_frame) -> None:
        period = 1.0 / self.fps
        params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]
        misses = 0
        try:
            while not self._stopping.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    misses += 1
                    # 🔴 한 번 실패했다고 끝내지 않는다. USB 카메라는 가끔 빈 프레임을
                    #   준다. 다만 계속 실패하면 케이블이 빠진 것이므로 알린다
                    if misses in (1, 10, 100):
                        log.warning("카메라 %s 프레임 없음 (%d회)", name, misses)
                    time.sleep(period)
                    continue
                misses = 0

                ok, buf = cv2.imencode(".jpg", frame, params)
                if ok:
                    h, w = frame.shape[:2]
                    self.last_frame_at[name] = time.monotonic()
                    on_frame(buf.tobytes(), name, (w, h))

                # 인코딩에 쓴 시간을 빼고 잔다. 안 그러면 실제 fps 가 목표보다 낮다
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
        except Exception:
            log.exception("카메라 %s 루프 중단", name)
        finally:
            cap.release()

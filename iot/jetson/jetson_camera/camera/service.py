#!/usr/bin/env python3
"""촬영 서비스 — IOT-01 / Jira floaq-18

설계 원칙
  수집·페어링·송신을 조립하고 상태를 주기적으로 남긴다.
  수집이 멈춰도 프로세스는 살려 둔다. 프로세스가 죽으면 상태를 보고할
  주체가 같이 사라져서 -20(카메라 상태 모니터링)이 아무것도 못 한다.

  통계는 누적값과 구간값을 같이 남긴다. 누적만 남기면 '지금' 문제가 있는지
  알 수 없다. fps 가 떨어진 순간을 찾으려면 구간값이 필요하다.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from typing import Optional

from .capture import CameraCapture
from .config import ServiceConfig
from .publisher import FramePublisher
from .stereo import StereoPairer

log = logging.getLogger("floaq.camera")

NS = 1_000_000_000


class CaptureService:
    """실시간 영상 촬영 서비스 본체."""

    def __init__(self, config: ServiceConfig) -> None:
        self._cfg = config
        self._left = CameraCapture(config.left, stale_after_s=config.stale_after_s)
        self._right = (
            CameraCapture(config.right, stale_after_s=config.stale_after_s)
            if config.right is not None else None
        )
        self._pairer = StereoPairer(self._left, self._right, config.max_skew_ms)
        self._pub = FramePublisher(
            endpoint=config.endpoint,
            topic=config.topic,
            publish_fps=config.publish_fps,
            jpeg_quality=config.jpeg_quality,
        )
        self._stop = threading.Event()
        self._started_ns = 0
        self._last_stats_ns = 0
        self._last_published = 0

    # ── 수명 주기 ────────────────────────────────────────────

    @staticmethod
    def _preflight() -> None:
        """필수 의존성을 시작 전에 확인한다.

        cv2 는 JetPack 시스템 패키지라 venv 구성에 따라 안 보일 수 있다
        (uv 는 기본적으로 시스템 패키지를 못 보는 venv 를 만들고, `uv sync` 가
        venv 를 다시 만들면서 --system-site-packages 를 날린다).
        지연 임포트라 없어도 서비스는 멀쩡히 뜨고 인코딩에서 프레임마다
        조용히 실패한다. 여기서 못 박아 즉시 죽인다.
        """
        try:
            import cv2  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "cv2 를 불러올 수 없다. JetPack 시스템 패키지이므로 venv 를 "
                "--system-site-packages 로 만들어야 한다: "
                "uv venv --python /usr/bin/python3.10 --system-site-packages"
            ) from exc

    def start(self) -> None:
        self._preflight()
        self._pub.open()
        self._left.start()
        if self._right is not None:
            self._right.start()
        self._started_ns = time.monotonic_ns()
        self._last_stats_ns = self._started_ns
        log.info(
            "촬영 시작 | %s | %s | publish %.1f fps → %s",
            self._cfg.left.device,
            self._cfg.right.device if self._cfg.right else "(mono)",
            self._cfg.publish_fps,
            self._cfg.endpoint,
        )

    def stop(self) -> None:
        self._stop.set()
        self._left.stop()
        if self._right is not None:
            self._right.stop()
        self._pub.close()
        log.info("촬영 종료 | %s", json.dumps(self.stats(), ensure_ascii=False))

    def request_stop(self, *_args) -> None:
        self._stop.set()

    # ── 메인 루프 ───────────────────────────────────────────

    def run(self, max_pairs: Optional[int] = None) -> None:
        """중지 신호가 올 때까지 돈다. max_pairs 는 시험용이다."""
        self.start()
        n = 0
        try:
            while not self._stop.is_set():
                pair = self._pairer.next_pair(timeout_s=1.0)
                if pair is None:
                    self._log_stats(force=False)
                    continue

                self._pub.publish(pair)
                n += 1
                self._log_stats(force=False)

                if max_pairs is not None and n >= max_pairs:
                    break
        finally:
            self.stop()

    # ── 상태 ────────────────────────────────────────────────

    def stats(self) -> dict:
        now = time.monotonic_ns()
        out = {
            "uptime_s": round((now - self._started_ns) / NS, 1) if self._started_ns else 0.0,
            "left": self._left.stats.snapshot(now),
            "pairing": self._pairer.stats.snapshot(),
            "publish": self._pub.stats.snapshot(),
        }
        if self._right is not None:
            out["right"] = self._right.stats.snapshot(now)
        return out

    def health(self) -> dict:
        """-20(카메라 상태 모니터링)이 쓸 요약.

        여기서는 '장애인지 아닌지'만 판정한다. 렌즈 오염·초점 이상 같은
        영상 내용 기반 판정은 -20 의 범위다. 이 모듈은 장치·수집 계층만 본다.
        """
        now = time.monotonic_ns()
        left = self._left.stats.snapshot(now)
        problems = []
        if not self._left.is_open:
            problems.append("left_down")
        if self._right is not None and not self._right.is_open:
            problems.append("right_down")
        if self._right is not None and self._pairer.stats.pair_rate_low():
            problems.append("pairing_degraded")
        return {
            "ok": not problems,
            "problems": problems,
            "left_fps": left["fps"],
            "created_at": time.time_ns() // NS,
        }

    def _log_stats(self, force: bool) -> None:
        now = time.monotonic_ns()
        interval_ns = int(self._cfg.stats_interval_s * NS)
        if not force and (now - self._last_stats_ns) < interval_ns:
            return

        elapsed_s = (now - self._last_stats_ns) / NS
        published = self._pub.stats.published
        window_fps = (published - self._last_published) / elapsed_s if elapsed_s > 0 else 0.0

        s = self.stats()
        s["window_publish_fps"] = round(window_fps, 2)
        log.info("상태 | %s", json.dumps(s, ensure_ascii=False))

        self._last_stats_ns = now
        self._last_published = published


def install_signal_handlers(service: CaptureService) -> None:
    """SIGTERM·SIGINT 에서 통계를 남기고 정상 종료한다."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, service.request_stop)

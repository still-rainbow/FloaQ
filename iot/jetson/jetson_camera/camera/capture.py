#!/usr/bin/env python3
"""캡처 스레드 — IOT-01 / Jira floaq-18

설계 원칙
  카메라마다 스레드를 하나씩 둔다.
  좌우를 한 스레드에서 grab-grab-retrieve-retrieve 로 묶으면 skew 는
  더 작아지지만, 한쪽이 멈추는 순간 다른 쪽도 같이 멈춘다. 해상 환경에서
  USB 한 대가 빠지는 일을 정상 동작으로 봐야 하므로 독립 스레드로 간다.
  대신 skew 를 측정해 헤더에 실어 보낸다(frame.StereoPair.skew_ms).

  버퍼를 쌓지 않고 '최신 한 장'만 들고 있는다.
  큐를 두면 소비자가 느릴 때 지연이 누적된다. 오래된 프레임을 늦게 주느니
  버리는 게 낫다. 버린 개수는 세어서 노출한다 — DES-31 §5 #5 의 측정값이다.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import CameraConfig
from .frame import Frame
from .source import CameraSource, make_source

log = logging.getLogger("floaq.camera")

NS = 1_000_000_000


@dataclass
class CaptureStats:
    """카메라 한 대의 수집 상태. -20(카메라 상태 모니터링)의 입력이 된다."""

    grabbed: int = 0          # 센서에서 받은 총 프레임
    delivered: int = 0        # 소비자가 실제로 가져간 프레임
    dropped: int = 0          # 새 프레임이 덮어써서 버려진 프레임
    grab_errors: int = 0
    reopens: int = 0          # 장치 재연결 횟수
    last_mono_ns: int = 0
    opened_mono_ns: int = 0

    def snapshot(self, now_ns: int) -> dict:
        elapsed = (now_ns - self.opened_mono_ns) / NS if self.opened_mono_ns else 0.0
        return {
            "grabbed": self.grabbed,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "grab_errors": self.grab_errors,
            "reopens": self.reopens,
            "fps": round(self.grabbed / elapsed, 2) if elapsed > 0.5 else 0.0,
            "idle_ms": round((now_ns - self.last_mono_ns) / 1e6, 1) if self.last_mono_ns else None,
        }


class CameraCapture:
    """한 대를 계속 읽어 최신 프레임 한 장을 들고 있는다.

    장치가 죽으면 스스로 다시 연다. 재연결은 실패해도 스레드를 죽이지 않는다.
    수집이 멈추는 것과 프로세스가 죽는 것은 다르게 다뤄야 한다 —
    프로세스가 죽으면 -20 이 상태를 보고할 방법도 같이 사라진다.
    """

    def __init__(
        self,
        config: CameraConfig,
        stale_after_s: float = 2.0,
        reopen_backoff_s: float = 1.0,
    ) -> None:
        self.cam_id = config.cam_id
        self.stats = CaptureStats()
        self._cfg = config
        self._stale_ns = int(stale_after_s * NS)
        self._backoff = reopen_backoff_s

        self._src: Optional[CameraSource] = None
        self._latest: Optional[Frame] = None
        # 최신 프레임을 아무도 안 가져갔는지. 드롭 판정의 기준이다.
        # 이 플래그가 없으면 이미 소비된 프레임을 덮어쓴 것까지 드롭으로 세어
        # 드롭률이 항상 100% 로 나온다.
        self._consumed = True
        self._lock = threading.Lock()
        self._new_frame = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seq = 0
        self.open_error: Optional[str] = None

    # ── 수명 주기 ────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError(f"{self.cam_id}: 이미 실행 중")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"cap-{self.cam_id}", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._new_frame:
            self._new_frame.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._close_source()

    # ── 소비자 쪽 ────────────────────────────────────────────

    def latest(self) -> Optional[Frame]:
        """최신 프레임을 즉시 돌려준다. 없으면 None.

        이미 가져간 프레임을 다시 요청하면 같은 것을 준다. 페어링에서
        오른쪽 후보를 볼 때 이 동작이 필요하다 — 새 프레임을 기다리지 않고
        지금 있는 것 중 가장 가까운 것을 먼저 보려는 것이다.
        """
        with self._lock:
            return self._take_locked()

    def wait_for_frame(self, timeout_s: float) -> Optional[Frame]:
        """아직 아무도 안 가져간 프레임이 생길 때까지 기다린다."""
        deadline = time.monotonic() + timeout_s
        with self._new_frame:
            while not self._stop.is_set():
                if not self._consumed:
                    return self._take_locked()
                remain = deadline - time.monotonic()
                if remain <= 0:
                    return None
                self._new_frame.wait(remain)
        return None

    def _take_locked(self) -> Optional[Frame]:
        """락을 쥔 상태에서 최신 프레임을 소비 표시하고 돌려준다."""
        f = self._latest
        if f is not None and not self._consumed:
            self._consumed = True
            self.stats.delivered += 1
        return f

    # ── 수집 루프 ────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._src is None and not self._open_source():
                self._stop.wait(self._backoff)
                continue

            try:
                ok = self._src.grab()          # type: ignore[union-attr]
            except Exception as exc:           # 장치가 빠지면 여기서 터진다
                self.stats.grab_errors += 1
                self.open_error = f"grab 실패: {exc}"
                self._close_source()
                continue

            if not ok:
                self.stats.grab_errors += 1
                if self._is_stale():
                    self._close_source()       # 조용히 멈춘 장치는 재연결로만 산다
                continue

            # 시각은 여기서 찍는다. 아래 retrieve() 의 디코드 시간은 빼야 한다.
            mono_ns, wall_ns = time.monotonic_ns(), time.time_ns()

            try:
                img = self._src.retrieve()     # type: ignore[union-attr]
            except Exception as exc:
                self.stats.grab_errors += 1
                self.open_error = f"retrieve 실패: {exc}"
                self._close_source()
                continue

            if img is None:
                self.stats.grab_errors += 1
                continue

            self.stats.grabbed += 1
            self.stats.last_mono_ns = mono_ns
            self._seq += 1
            frame = Frame(self.cam_id, self._seq, mono_ns, wall_ns, img)

            with self._new_frame:
                if self._latest is not None and not self._consumed:
                    # 아직 아무도 안 가져간 프레임을 덮어쓴다 = 드롭
                    self.stats.dropped += 1
                self._latest = frame
                self._consumed = False
                self._new_frame.notify_all()

    def _is_stale(self) -> bool:
        last = self.stats.last_mono_ns
        return bool(last) and (time.monotonic_ns() - last) > self._stale_ns

    def _open_source(self) -> bool:
        try:
            src = make_source(self._cfg)
            src.open()
        except Exception as exc:
            msg = str(exc)
            # 같은 실패를 매 재시도마다 찍으면 로그가 잠긴다. 바뀔 때만 남긴다.
            # 그래도 한 번은 반드시 남긴다 — 안 남기면 조용히 재시도만 도는
            # 상태가 되어 밖에서는 원인을 알 방법이 없다.
            if msg != self.open_error:
                log.error("%s: 카메라를 열지 못했다 (%s → %s): %s",
                          self.cam_id, self._cfg.device, self._cfg.resolved_node, msg)
            self.open_error = msg
            return False

        self._src = src
        if self.open_error is not None:
            log.info("%s: 카메라 복구됨", self.cam_id)
        self.open_error = None
        # 드라이버가 실제로 받아들인 값. 요청값을 조용히 낮추는 경우가 흔해서
        # 남겨두지 않으면 나중에 fps 가 왜 안 나오는지 추적이 안 된다.
        actual = getattr(src, "actual_settings", None)
        if callable(actual):
            try:
                log.info("%s: %s 열림 | 요청 %dx%d@%.0f %s → 실제 %s",
                         self.cam_id, self._cfg.resolved_node,
                         self._cfg.width, self._cfg.height,
                         self._cfg.capture_fps, self._cfg.fourcc, actual())
            except Exception:
                pass
        now = time.monotonic_ns()
        if self.stats.opened_mono_ns == 0:
            self.stats.opened_mono_ns = now
        else:
            self.stats.reopens += 1
        self.stats.last_mono_ns = now
        return True

    def _close_source(self) -> None:
        if self._src is not None:
            try:
                self._src.close()
            except Exception:
                pass
            self._src = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_open(self) -> bool:
        return self._src is not None and self._src.is_open

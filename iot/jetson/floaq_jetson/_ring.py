"""사고 전 프레임 링 버퍼.

탐지가 나기 **전** 장면은 다시 만들 수 없다. 그래서 상시로 최근 몇 초를 들고 있다가
탐지 순간에 쏟아낸다.

🔴 **상한이 있어야 한다.** 리스트로 두면 Jetson 메모리가 조용히 찬다 — 하루 종일
   도는 프로그램이라 며칠 뒤에 OOM 으로 죽고, 원인이 카메라 쪽으로 보인다.
   `deque(maxlen=...)` 은 넘치면 가장 오래된 것부터 자동으로 버린다.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Frame:
    """JPEG 한 장. 인코딩은 호출자가 한다 — 우리는 바이트만 다룬다."""

    jpeg: bytes
    camera: str          #: "L" · "R"
    captured_at: float   #: time.time()


class RingBuffer:
    """최근 `seconds` 초치를 들고 있는다. 스레드 안전하다.

    추론 루프와 업로드 워커가 동시에 건드리므로 락이 필요하다. `deque` 자체는
    append/popleft 가 원자적이지만, "전부 꺼내고 비우기"는 그렇지 않다.
    """

    def __init__(self, seconds: int, fps: int) -> None:
        self.seconds = seconds
        self.fps = fps
        #: 카메라가 둘이라 초당 프레임이 fps 의 2배로 들어올 수 있다.
        #: 좌우를 한 벌로 세지 않고 장수로 세므로 여유를 둔다.
        self.capacity = max(1, seconds * fps * 2)
        self._q: deque[Frame] = deque(maxlen=self.capacity)
        self._lock = threading.Lock()

    def push(self, jpeg: bytes, camera: str, captured_at: float) -> None:
        with self._lock:
            self._q.append(Frame(jpeg, camera, captured_at))

    def drain(self) -> list[Frame]:
        """전부 꺼내고 비운다. 시간순으로 돌려준다.

        ⚠ 비우는 이유: 탐지 직후의 프레임은 AFTER 로 따로 올라간다. 비우지 않으면
          같은 장면이 BEFORE 와 AFTER 양쪽에 들어가고 순번이 겹친다.
        """
        with self._lock:
            out = list(self._q)
            self._q.clear()
        return out

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)

    @property
    def bytes_held(self) -> int:
        with self._lock:
            return sum(len(f.jpeg) for f in self._q)

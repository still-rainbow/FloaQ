"""프레임 업로드 워커. HTTP PUT 을 백그라운드 스레드에서 한다.

🔴 **추론 루프를 막으면 안 된다.** 5fps 로 도는 루프에서 HTTP 를 기다리면 그만큼
   프레임이 밀리고, Pi 가 잠깐 느려진 것이 탐지 지연으로 번진다. 호출부는 큐에
   넣기만 하고 즉시 돌아온다.

🔴 **네트워크 오류를 호출부로 올리지 않는다.** 어선은 선내 랜도 끊겼다 붙었다 한다.
   예외가 추론 루프까지 올라가면 사람을 보고 있던 프로그램이 죽는다. 삼키고 센다.

큐가 차면 **AFTER 부터 버린다.** 셋의 가치가 다르다.

    DETECT_SNAPSHOT  사고당 1장. 화면 대표 이미지     -> 절대 안 버린다
    BEFORE           탐지 전 장면. 다시 못 만든다      -> 안 버린다
    AFTER            계속 생기고 뒤쪽이 더 유용하다     -> 오래된 것부터 버린다
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

#: 큐 상한(장). 앞 15초 + 뒤 10초가 125장이라 사고 두 건치 여유다.
#: ⚠ 무제한으로 두면 Pi 가 죽어 있는 동안 Jetson 메모리가 찬다.
QUEUE_MAX = 400

#: 연결·읽기 타임아웃(초). `requests` 기본이 무한 대기라 반드시 준다.
#:
#: 🔴 연결 3초는 너무 빡빡했다. Jetson 이 YOLO 로 CPU 를 다 쓰는 동안 업로드
#:   스레드가 GIL 을 못 잡으면, 망이 멀쩡해도 `ConnectTimeout` 이 난다. 그 상태로
#:   MAX_TRIES 를 넘기면 **사고 스냅샷이 사라진다** — 실제로 그랬다:
#:   `업로드 포기 DETECT_SNAPSHOT None (ConnectTimeout, 3회)`
#:
#: ⚠ 늘리면 링크가 진짜 끊겼을 때 알아채는 것도 그만큼 늦어진다. 대신
#:   `avg_ms` 가 커지므로 상태 줄을 보면 느린 줄은 안다.
TIMEOUT: tuple[float, float] = (10.0, 30.0)

#: 한 장당 재시도 횟수. 이 뒤로는 버리고 센다 — 쌓아두면 뒤 프레임이 밀린다.
#:
#: ⚠ 느린 것과 안 되는 것은 다르다. 3회는 느린 링크에서 멀쩡한 프레임을 버렸다.
MAX_TRIES = 5


@dataclass(order=True)
class _Item:
    #: 작을수록 먼저 나간다. 스냅샷 -> BEFORE -> AFTER
    priority: int
    seq_key: int
    detection_id: str = field(compare=False)
    file_type: str = field(compare=False)
    sequence_no: int | None = field(compare=False)
    jpeg: bytes = field(compare=False)
    camera: str | None = field(compare=False)
    tries: int = field(compare=False, default=0)


_PRIORITY = {"DETECT_SNAPSHOT": 0, "BEFORE": 1, "AFTER": 2}


class Uploader:
    """`PUT /api/detections/{id}/files/{type}/{seq}` 를 백그라운드로 민다."""

    def __init__(self, base_url: str, *, timeout=TIMEOUT, max_items=QUEUE_MAX) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_items = max_items
        self._q: queue.PriorityQueue[_Item] = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        #: 409 로 통째로 버린 탐지. 뒤늦게 들어오는 프레임도 여기서 막는다
        self._abandoned: set[str] = set()
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        #: 요청 하나에 걸린 시간(ms). 큐가 안 빠질 때 **어디서 쓰는지**를 본다.
        #: 단일 스레드 순차 PUT 이라 이 값이 곧 처리율의 역수다 —
        #: 200ms 면 초당 5장, 800ms 면 초당 1.2장이다.
        self.last_ms = 0.0
        self.total_ms = 0.0
        self.bytes_sent = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="upload", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """남은 것을 잠깐 기다렸다가 멈춘다. 다 못 보내도 프로그램은 끝나야 한다."""
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # ── 넣기 ─────────────────────────────────────────────────────────
    def submit(self, detection_id: str, file_type: str, sequence_no: int | None,
               jpeg: bytes, camera: str | None = None) -> bool:
        """큐에 넣는다. **즉시 돌아온다.** 넣었으면 True.

        ⚠ 큐가 차면 AFTER 를 오래된 것부터 버린다. 버릴 게 없으면 이번 것을 버린다 —
          BEFORE·스냅샷이 큐를 채운 상태에서 AFTER 가 들어온 경우다.
        """
        with self._lock:
            if detection_id in self._abandoned:
                # 이미 409 로 버린 탐지다. 큐에 넣어봐야 같은 답이 온다
                self.dropped += 1
                return False
            if self._q.qsize() >= self.max_items and not self._make_room(file_type):
                self.dropped += 1
                return False
            self._seq += 1
            self._q.put(_Item(_PRIORITY.get(file_type, 2), self._seq, detection_id,
                              file_type, sequence_no, jpeg, camera))
        return True

    def _make_room(self, incoming: str) -> bool:
        """AFTER 를 하나 버려 자리를 만든다. 락을 쥔 채 부른다."""
        keep: list[_Item] = []
        victim = None
        while True:
            try:
                it = self._q.get_nowait()
            except queue.Empty:
                break
            if victim is None and it.file_type == "AFTER":
                victim = it          # 우선순위 큐라 AFTER 중 가장 오래된 것이 먼저 나온다
            else:
                keep.append(it)
        for it in keep:
            self._q.put(it)
        if victim is not None:
            self.dropped += 1
            return True
        # 버릴 AFTER 가 없다. 들어오는 게 AFTER 면 그것을 버린다
        return incoming != "AFTER"

    # ── 보내기 ───────────────────────────────────────────────────────
    def _run(self) -> None:
        with requests.Session() as s:
            while not (self._stopping.is_set() and self._q.empty()):
                try:
                    item = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._send(s, item)

    def _send(self, s: requests.Session, item: _Item) -> None:
        seq = 0 if item.sequence_no is None else item.sequence_no
        url = (f"{self.base_url}/api/detections/{item.detection_id}"
               f"/files/{item.file_type}/{seq}")
        headers = {"Content-Type": "image/jpeg"}
        if item.camera:
            headers["X-Camera"] = item.camera
        t0 = time.monotonic()
        try:
            r = s.put(url, data=item.jpeg, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            self._retry(item, type(e).__name__)
            return
        finally:
            self.last_ms = (time.monotonic() - t0) * 1000.0
            self.total_ms += self.last_ms
            self.bytes_sent += len(item.jpeg)

        if r.status_code in (200, 201):
            self.sent += 1
            return
        if r.status_code == 409:
            # 🔴 진행 중 사고가 있어 이 탐지가 **통째로** 거부됐다. 그 detection_id 는
            #   영영 사고에 안 붙으므로 **남은 프레임도 전부 버린다.**
            #   장당 한 줄씩 로그를 내면 126줄이 쏟아지는데, 새로 알려주는 것이 없다.
            self._abandon(item.detection_id)
            return
        if r.status_code == 404:
            # 아직 사고에 안 붙었다. Jetson 이 Pi 보다 빨랐던 것이라 재시도하면 붙는다
            self._retry(item, "404")
            return
        # 400·413·415 는 우리가 보낸 것이 틀린 것이다. 다시 보내도 같다
        self.failed += 1
        log.warning("업로드 실패 %s %s -> HTTP %d", item.file_type, seq, r.status_code)

    def _abandon(self, detection_id: str) -> int:
        """이 탐지의 큐를 통째로 비운다. 버린 장수를 돌려준다.

        🔴 409 는 장당 판정이 아니라 **탐지 단위**다. 하나가 거부되면 나머지 125장도
          같은 이유로 거부된다. 큐에 두면 그만큼 요청과 로그를 태우고, 그 사이 다음
          탐지의 프레임이 뒤로 밀린다.
        """
        with self._lock:
            if detection_id in self._abandoned:
                return 0
            self._abandoned.add(detection_id)
            keep = []
            dropped = 0
            while True:
                try:
                    it = self._q.get_nowait()
                except queue.Empty:
                    break
                if it.detection_id == detection_id:
                    dropped += 1
                else:
                    keep.append(it)
            for it in keep:
                self._q.put(it)
            self.failed += dropped + 1
        log.warning("업로드 거부(409) %s - 진행 중 사고가 있다. 남은 %d장을 버린다",
                    detection_id, dropped)
        return dropped

    def _retry(self, item: _Item, why: str) -> None:
        item.tries += 1
        if item.tries >= MAX_TRIES:
            self.failed += 1
            log.warning("업로드 포기 %s %s (%s, %d회)",
                        item.file_type, item.sequence_no, why, item.tries)
            return
        with self._lock:
            self._q.put(item)

    # ── 상태 ─────────────────────────────────────────────────────────
    @property
    def queued(self) -> int:
        return self._q.qsize()

    @property
    def avg_ms(self) -> float:
        """요청 하나 평균(ms). 0 이면 아직 하나도 안 보냈다."""
        n = self.sent + self.failed
        return round(self.total_ms / n, 1) if n else 0.0

    @property
    def mbps(self) -> float:
        """실효 처리율(MB/s). 대역 문제인지 지연 문제인지 가른다.

        지연이 문제면 이 값이 낮은데 CPU 도 망도 한가하다. 대역이 문제면
        이 값이 망 상한에 붙어 있다.
        """
        return round(self.bytes_sent / 1048576 / (self.total_ms / 1000), 2)             if self.total_ms > 0 else 0.0

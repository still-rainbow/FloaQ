"""카메라 라이브 스트림. Jetson `:8080` 에서 MJPEG 로 내보낸다.

Pi 와 같은 FastAPI 를 쓴다. 기기는 다르지만 프레임워크가 하나여야 읽는 사람이
둘을 따로 배우지 않는다. 버린 Flask 카메라 서버가 있던 자리다.

    http://<jetson>:8080/            좌우 카메라 확인 페이지
    http://<jetson>:8080/stream.mjpg?camera=L   <img src> 에 그대로 넣는다
    http://<jetson>:8080/snapshot.jpg?camera=R  가장 최근 한 장
    http://<jetson>:8080/health      배선 확인

**기록이 아니라 보기용이다.** 기록은 `frame()` 이 링 버퍼·업로드 큐로 보낸다.

**왜 MJPEG 인가.** 이미 JPEG 로 인코딩된 프레임을 그대로 흘리면 되고, 브라우저가
`<img>` 하나로 받는다. WebRTC·HLS 는 지연이 낮거나 압축률이 좋지만 시그널링·세그먼트
관리가 붙고, 선내 랜에서 몇 명이 보는 용도에는 과하다.

🔴 **추론 루프를 막지 않는다.** 보는 사람이 느려도 최신 프레임만 주고 넘어간다 —
   프레임을 큐에 쌓아 두면 느린 클라이언트 하나가 메모리를 채우고, 화면은 점점
   과거를 보여준다. 라이브에서 과거를 보여주는 건 틀린 것보다 나쁘다.

🔴 **스트림이 죽어도 탐지는 돌아야 한다.** 기동 실패는 예외가 아니라 False 다.
   보는 화면이 없다고 사람을 못 건지면 안 된다.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response, StreamingResponse

log = logging.getLogger(__name__)

PORT = 8080
BOUNDARY = "floaqframe"

#: 카메라 둘. 스테레오 거리(AI-03)가 둘 다 있어야 나온다.
CAMERAS = ("L", "R")

#: 이 시간 안에 프레임이 없으면 그 카메라를 죽은 것으로 본다.
#: 5fps 기준 15프레임치라 잠깐 끊긴 것과 고장을 가른다.
STALE_SEC = 3.0

_PAGE = """<!doctype html><meta charset=utf-8><title>FloaQ Jetson</title>
<style>body{background:#111;color:#ddd;font:14px system-ui;margin:0;padding:16px}
h1{font-size:15px;font-weight:600;margin:0 0 12px}
.row{display:flex;gap:12px;flex-wrap:wrap}
figure{margin:0}figcaption{padding:6px 0;color:#888}
img{width:min(46vw,640px);background:#000;border-radius:6px;display:block}</style>
<h1>FloaQ Jetson &mdash; 라이브 (기록 아님)</h1>
<div class=row>
<figure><img src="/stream.mjpg?camera=L"><figcaption>camera L</figcaption></figure>
<figure><img src="/stream.mjpg?camera=R"><figcaption>camera R</figcaption></figure>
</div>
"""


class _Latest:
    """카메라별 최신 프레임 한 장. **쌓지 않는다.**

    느린 클라이언트를 위해 큐를 두면 그 클라이언트가 메모리를 채우고 화면은 과거를
    보여준다. 최신 한 장만 들고, 새 프레임이 오면 기다리던 쪽을 전부 깨운다.

    ⚠ 추론 루프(동기 스레드)가 넣고 uvicorn(비동기)이 꺼낸다. 락은 스레드용이고
      대기는 폴링이다 — `asyncio.Event` 를 쓰면 루프에 소속돼서 다른 스레드에서
      set 할 때 `call_soon_threadsafe` 가 필요해지고, 그 배선이 더 비싸다.
    """

    def __init__(self) -> None:
        self._jpeg: dict[str, bytes] = {}
        self._count: dict[str, int] = {}
        self._at: dict[str, float] = {}
        self._size: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def put(self, jpeg: bytes, camera: str, size: tuple[int, int] | None = None) -> None:
        with self._lock:
            self._jpeg[camera] = jpeg
            self._count[camera] = self._count.get(camera, 0) + 1
            self._at[camera] = time.monotonic()
            if size is not None:
                self._size[camera] = size
            self._seq += 1

    def health(self) -> dict:
        """카메라별 상태. **둘 다 항상 나온다.**

        🔴 프레임이 온 것만 나열하면 R 이 고장난 것과 카메라가 하나인 것을 구분할 수
          없다. 스테레오 거리가 둘 다 필요한데 조용히 한쪽만 도는 상태가 된다.
        """
        now = time.monotonic()
        with self._lock:
            out = {}
            for cam in CAMERAS:
                at = self._at.get(cam)
                w, h = self._size.get(cam, (0, 0))
                out[cam] = {
                    "frames": self._count.get(cam, 0),
                    "age_sec": None if at is None else round(now - at, 2),
                    "live": at is not None and now - at < STALE_SEC,
                    # 🔴 좌우 해상도가 다르면 스테레오 거리가 조용히 틀린다.
                    #   예외가 안 나므로 여기 숫자로 드러낸다
                    "size": f"{w}x{h}" if w else None,
                }
        return out

    def get(self, camera: str) -> bytes | None:
        with self._lock:
            return self._jpeg.get(camera)

    def peek(self, camera: str) -> tuple[bytes | None, int]:
        with self._lock:
            return self._jpeg.get(camera), self._seq


def create_app(latest: _Latest) -> FastAPI:
    app = FastAPI(title="FloaQ Jetson 카메라", version="1",
                  docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict:
        """카메라 둘이 다 살아 있어야 ok 다. 한쪽만 돌면 조준 해가 조용히 나빠진다."""
        cams = latest.health()
        sizes = {c["size"] for c in cams.values() if c["size"]}
        return {
            "ok": all(c["live"] for c in cams.values()) and len(sizes) <= 1,
            # 좌우 해상도가 다르면 스테레오 거리를 못 믿는다
            "size_mismatch": len(sizes) > 1,
            "cameras": cams,
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE

    @app.get("/snapshot.jpg")
    def snapshot(camera: str = Query("L", pattern="^[LR]$")) -> Response:
        jpeg = latest.get(camera)
        if jpeg is None:
            return Response(f"camera {camera} 프레임이 아직 없다".encode(),
                            status_code=503, media_type="text/plain; charset=utf-8")
        # 캐시되면 화면이 옛 장면에 멈춘다
        return Response(jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/stream.mjpg")
    def stream(camera: str = Query("L", pattern="^[LR]$")) -> StreamingResponse:
        return StreamingResponse(
            _frames(latest, camera),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"})

    return app


async def _frames(latest: _Latest, camera: str):
    """새 프레임이 생길 때만 보낸다. 없으면 잠깐 자고 다시 본다.

    ⚠ 보던 사람이 탭을 닫으면 `asyncio.CancelledError` 가 여기로 온다. 그건 정상이라
      uvicorn 이 처리하게 그대로 둔다.
    """
    seen = 0
    while True:
        jpeg, seq = latest.peek(camera)
        if jpeg is None or seq == seen:
            # 🔴 바쁜 대기를 하지 않는다. 5fps 면 200ms 간격이라 20ms 면 충분히 촘촘하다
            await asyncio.sleep(0.02)
            continue
        seen = seq
        yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
               f"Content-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"


class StreamServer:
    """`:8080` MJPEG 서버. `Floaq.frame()` 이 프레임을 밀어 넣는다."""

    def __init__(self, port: int = PORT, host: str = "0.0.0.0") -> None:
        self.port, self.host = port, host
        self.latest = _Latest()
        self._server = None
        self._sock: socket.socket | None = None

    def start(self) -> bool:
        """uvicorn 을 데몬 스레드로 띄운다. 실패해도 예외를 내지 않는다.

        ⚠ `uvicorn.run()` 을 쓰지 않는다. 그건 블로킹이라 추론 루프가 멈춘다.

        🔴 소켓을 **여기서 먼저 바인드**해 uvicorn 에 넘긴다. 스레드 안에서 바인드하게
          두면 포트가 막혀 있어도 `start()` 가 True 를 돌려주고, 실패는 uvicorn 로그에만
          남아 아무도 못 본다. 스트림이 안 뜬 걸 화면을 열어보기 전까지 모르게 된다.
        """
        try:
            import uvicorn
        except ImportError:
            log.warning("uvicorn 이 없다 - 카메라 스트림을 띄우지 않는다. "
                        "`uv add fastapi uvicorn` 후 다시 시작할 것")
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
            sock.listen(16)
        except OSError as e:
            sock.close()
            log.warning("카메라 스트림 기동 실패 :%d (%s) - 탐지는 계속한다",
                        self.port, e)
            return False

        config = uvicorn.Config(create_app(self.latest), log_level="warning",
                                access_log=False)
        self._server = uvicorn.Server(config)
        self._sock = sock
        threading.Thread(target=self._server.run, kwargs={"sockets": [sock]},
                         name="stream", daemon=True).start()
        log.info("카메라 스트림  http://%s:%d/", self.host, self.port)
        return True

    def put(self, jpeg: bytes, camera: str,
            size: tuple[int, int] | None = None) -> None:
        self.latest.put(jpeg, camera, size)

    def stop(self, timeout: float = 0.5) -> None:
        """멈춘다.

        🔴 **소켓을 우리가 닫지 않는다.** uvicorn 에게 넘긴 소켓이라 종료할 때
          uvicorn 이 닫는다. 우리가 먼저 닫으면 uvicorn 이 이미 -1 이 된 fd 를
          또 닫으려다 `ValueError: Invalid file descriptor: -1` 을 스택트레이스로
          쏟는다. 기능엔 문제가 없지만 종료 로그가 그걸로 덮여 진짜 오류를 못 본다 —
          시연 리허설에서 실제로 그랬다.

        ⚠ 기동에 **실패한** 경우에는 uvicorn 이 소켓을 받지 못했으므로 우리가 닫는다.
          그 구분이 `self._server` 가 있느냐다.
        """
        if self._server is not None:
            self._server.should_exit = True
            time.sleep(timeout)          # uvicorn 이 소켓을 닫을 틈
            self._server = None
            self._sock = None            # 소유권은 uvicorn 에 있다. 손대지 않는다
            return
        if self._sock is not None:
            self._sock.close()
            self._sock = None

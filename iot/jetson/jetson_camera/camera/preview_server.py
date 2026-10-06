#!/usr/bin/env python3
"""미리보기 HTTP 서버 — IOT-01 / Jira floaq-18

퍼블리셔가 내보내는 JPEG 바이트를 그대로 브라우저로 흘린다.

설계 원칙
  디코드도 인코드도 하지 않는다. Orin Nano 에는 하드웨어 인코더(NVENC)가
  없어서 H.264 로 바꾸려면 CPU 를 써야 하는데, 그 CPU 는 추론 몫이다.
  카메라가 MJPEG 로 주고 퍼블리셔가 JPEG 로 보내니 그대로 통과시키면
  변환 비용이 0 이다.

  multipart/x-mixed-replace 는 브라우저가 기본으로 이해하는 형식이다.
  보는 쪽에 아무것도 설치할 필요가 없다 — 크롬 주소창이면 된다.

  구독은 한 번만 하고 최신 쌍을 공유한다. 접속자마다 SUB 소켓을 열면
  퍼블리셔의 HWM 을 접속자 수만큼 소모한다.

  이 서버는 촬영 경로에 끼어들지 않는다. 죽어도 수집·송신은 계속된다.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from typing import Optional

from .subscriber import FrameSubscriber, ReceivedPair

log = logging.getLogger("floaq.camera.preview")

BOUNDARY = "floaqframe"


# ─────────────────────────────────────────────────────────────
# 최신 쌍 보관
# ─────────────────────────────────────────────────────────────

class LatestPair:
    """수신 스레드가 넣고, HTTP 스트림들이 꺼내 간다."""

    def __init__(self, fps_window_s: float = 3.0) -> None:
        self._cv = threading.Condition()
        self._pair: Optional[ReceivedPair] = None
        self._seq = 0
        self.received = 0
        self.lost = 0
        self.last_rx_mono = 0.0
        # fps 는 도착 간격의 역수가 아니라 창 구간의 개수로 센다.
        # 역수로 재면 프레임 하나의 지터가 그대로 표시값이 된다.
        self._win = fps_window_s
        self._marks: list = []

    def put(self, pair: ReceivedPair) -> None:
        now = time.monotonic()
        with self._cv:
            self._pair = pair
            self._seq += 1
            self.last_rx_mono = now
            self._marks.append(now)
            cut = now - self._win
            while self._marks and self._marks[0] < cut:
                self._marks.pop(0)
            self._cv.notify_all()

    @property
    def fps(self) -> float:
        with self._cv:
            if len(self._marks) < 2:
                return 0.0
            span = self._marks[-1] - self._marks[0]
            return (len(self._marks) - 1) / span if span > 0 else 0.0

    @property
    def pair(self) -> Optional[ReceivedPair]:
        with self._cv:
            return self._pair

    def take(self, last_seq: int, timeout: float = 2.0):
        """last_seq 이후의 새 쌍을 기다린다. 없으면 (None, last_seq)."""
        with self._cv:
            if self._seq == last_seq:
                self._cv.wait(timeout)
            return self._pair, self._seq

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.last_rx_mono if self.last_rx_mono else -1.0


def pump(endpoint: str, latest: LatestPair, stop: threading.Event) -> None:
    """ZMQ 구독 → 최신 쌍 갱신. 퍼블리셔가 죽어도 계속 재시도한다."""
    sub = FrameSubscriber(endpoint)
    sub.open()
    try:
        while not stop.is_set():
            pair = sub.recv(timeout_ms=500)
            if pair is None:
                continue
            latest.put(pair)
            latest.received = sub.received
            latest.lost = sub.lost
    finally:
        sub.close()


# ─────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────

PAGE = """<!doctype html><meta charset=utf-8><title>FloaQ 카메라</title>
<style>
 body{margin:0;background:#11151a;color:#dfe5ec;font:14px system-ui,sans-serif}
 header{padding:10px 16px;display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
 h1{font-size:15px;margin:0;font-weight:600}
 #s{color:#8fa3b8;font-variant-numeric:tabular-nums}
 .wrap{display:flex;gap:2px;flex-wrap:wrap;padding:0 2px}
 figure{margin:0;flex:1 1 400px;min-width:280px}
 img{width:100%;display:block;background:#000}
 figcaption{padding:4px 8px;color:#8fa3b8;font-size:12px}
</style>
<header><h1>FloaQ 스테레오 카메라</h1><span id=s>연결 중…</span></header>
<div class=wrap>
 <figure><img src="/left.mjpg"><figcaption>LEFT</figcaption></figure>
 <figure><img src="/right.mjpg"><figcaption>RIGHT</figcaption></figure>
</div>
<script>
setInterval(async()=>{
 try{
  const r=await fetch('/stats.json'); const d=await r.json();
  document.getElementById('s').textContent =
    `${d.width}x${d.height} · ${d.fps} fps · skew ${d.skew_ms} ms · `
    + `${d.kb} KB/쌍 · 수신 ${d.received} · 유실 ${d.lost}`
    + (d.stereo?'':' · ⚠ mono');
 }catch(e){ document.getElementById('s').textContent='서버 응답 없음'; }
},1000);
</script>
"""


def build_app(latest: LatestPair):
    from flask import Flask, Response, jsonify   # 지연 임포트

    app = Flask(__name__)

    def stream(side: str):
        last_seq, t0, n = 0, time.monotonic(), 0
        while True:
            pair, last_seq = latest.take(last_seq)
            if pair is None:
                time.sleep(0.2)
                continue
            buf = pair.left_jpeg if side == "left" else pair.right_jpeg
            if buf is None:                      # mono 폴백이면 오른쪽이 없다
                time.sleep(0.2)
                continue
            n += 1
            yield (b"--" + BOUNDARY.encode() + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(buf)).encode() + b"\r\n\r\n"
                   + buf + b"\r\n")

    @app.route("/")
    def index():
        return Response(PAGE, mimetype="text/html; charset=utf-8")

    @app.route("/<any(left,right):side>.mjpg")
    def mjpg(side):
        return Response(
            stream(side),
            mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store", "Connection": "close"},
        )

    @app.route("/stats.json")
    def stats():
        p = latest.pair
        if p is None:
            return jsonify(width=0, height=0, fps=0, skew_ms=0, kb=0,
                           received=0, lost=0, stereo=False, age_s=-1)
        h = p.header
        return jsonify(
            width=h.get("width"), height=h.get("height"),
            skew_ms=h.get("skew_ms"), stereo=bool(h.get("stereo")),
            kb=round(p.nbytes / 1024, 1),
            received=latest.received, lost=latest.lost,
            fps=round(latest.fps, 1),
            age_s=round(latest.age_s, 2),
        )

    return app


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="camera.preview_server",
                                description="브라우저로 카메라 보기")
    p.add_argument("--endpoint", default="ipc:///tmp/floaq_frames",
                   help="퍼블리셔 주소. 다른 보드면 tcp://<ip>:5555")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s")

    latest = LatestPair()
    stop = threading.Event()
    t = threading.Thread(target=pump, args=(a.endpoint, latest, stop),
                         name="preview-sub", daemon=True)
    t.start()

    log.info("미리보기 → http://<이 보드의 IP>:%d/  (구독 %s)", a.port, a.endpoint)
    app = build_app(latest)
    try:
        app.run(host=a.host, port=a.port, threaded=True, debug=False)
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

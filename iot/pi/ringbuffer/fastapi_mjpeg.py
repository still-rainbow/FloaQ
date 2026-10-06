#!/usr/bin/env python3
"""운영 FastAPI /stream.mjpg?camera=L|R 소비자.

서버가 원래 촬영 시각을 헤더로 보내지 않으므로 여기서는 수신 시각을 찍는다.
영상과 IMU를 엄밀히 동기화하려면 추후 촬영 시각 메타데이터가 필요하다.
"""

import threading
import time
import urllib.request

from video_ringbuffer import VideoFrame


NS = 1_000_000_000


def read_mjpeg_frame(stream, max_jpeg_bytes=5 * 1024 * 1024):
    """FastAPI 스트림의 boundary + Content-Length + JPEG 한 장을 읽는다."""
    while True:
        line = stream.readline(512)
        if not line:
            raise EOFError("MJPEG 연결 종료")
        if line.startswith(b"--"):
            break

    headers = {}
    for _ in range(16):
        line = stream.readline(512)
        if not line:
            raise EOFError("MJPEG 헤더 중 연결 종료")
        if line in (b"\r\n", b"\n"):
            break
        if b":" not in line:
            raise ValueError("MJPEG 헤더 형식 오류")
        key, value = line.split(b":", 1)
        headers[key.strip().lower()] = value.strip()
    else:
        raise ValueError("MJPEG 헤더가 너무 깁니다")

    try:
        length = int(headers[b"content-length"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Content-Length가 없습니다") from exc
    if length <= 0 or length > max_jpeg_bytes:
        raise ValueError("JPEG 길이 제한 초과: {}".format(length))
    jpeg = stream.read(length)
    if len(jpeg) != length:
        raise EOFError("JPEG 수신 중 연결 종료")
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("JPEG 시작/끝 마커 오류")
    return jpeg


def receive_camera(url, camera, ring, stop, state, append_lock):
    """한 카메라 연결이 끊겨도 재접속한다."""
    while not stop.is_set():
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
            with urllib.request.urlopen(request, timeout=5) as stream:
                while not stop.is_set():
                    jpeg = read_mjpeg_frame(stream)
                    with append_lock:
                        mono_ns = time.monotonic_ns()
                        wall_ns = time.time_ns()
                        state["seq"] += 1
                        header = {"pair_id": state["seq"],
                                  "mono_ns": mono_ns, "wall_ns": wall_ns,
                                  "camera": camera, "source": "fastapi_mjpeg",
                                  "timestamp_origin": "receiver"}
                        frame = VideoFrame(header,
                                           jpeg if camera == "L" else None,
                                           jpeg if camera == "R" else None)
                        ring.append(frame)
                        state["received"] += 1
                        state["camera_counts"][camera] += 1
                        state["error"] = None
        except Exception as exc:
            state["error"] = "{}: {}".format(camera, exc)
            state["invalid"] += 1
            stop.wait(1.0)

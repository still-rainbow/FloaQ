#!/usr/bin/env python3
"""Jetson 카메라 ZMQ 스트림용 영상 링버퍼 실험 CLI."""

import argparse
import datetime
import queue
import sys
import threading
import time
from pathlib import Path

from fastapi_mjpeg import receive_camera
from video_ringbuffer import VideoRingBuffer, parse_multipart, write_video_capture


def receive_loop(endpoint, ring, stop, state):
    try:
        import zmq
    except ImportError:
        state["error"] = "pyzmq가 없습니다: pip install pyzmq"
        return
    ctx = zmq.Context.instance()
    socket = ctx.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"frame")
    socket.setsockopt(zmq.RCVHWM, 2)
    socket.setsockopt(zmq.LINGER, 0)
    socket.connect(endpoint)
    try:
        while not stop.is_set():
            if not socket.poll(200, zmq.POLLIN):
                continue
            try:
                frame = parse_multipart(socket.recv_multipart())
                ring.append(frame)
                state["received"] += 1
            except (ValueError, KeyError) as exc:
                state["invalid"] += 1
                state["error"] = str(exc)
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        socket.close()


def command_loop(commands):
    while True:
        try:
            command = input().strip()
        except EOFError:
            return
        commands.put(command)
        if command.lower() == "q":
            return


def main():
    parser = argparse.ArgumentParser(description="Jetson ZMQ 영상 링버퍼 실험")
    parser.add_argument("--source", choices=("fastapi", "zmq"), default="fastapi")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080",
                        help="운영 FastAPI 카메라 서버 URL")
    parser.add_argument("--endpoint", default="ipc:///tmp/floaq_frames")
    parser.add_argument("--before", type=float, default=30.0)
    parser.add_argument("--after", type=float, default=5.0)
    parser.add_argument("--buffer-seconds", type=float, default=40.0)
    parser.add_argument("--max-mb", type=float, default=128.0)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--output", default="captures")
    args = parser.parse_args()

    ring = VideoRingBuffer(
        seconds=max(args.buffer_seconds, args.before + args.after + 2.0),
        max_bytes=int(args.max_mb * 1024 * 1024), expected_fps=args.fps,
    )
    stop = threading.Event()
    state = {"received": 0, "invalid": 0, "error": None,
             "seq": 0, "camera_counts": {"L": 0, "R": 0}}
    commands = queue.Queue()
    receivers = []
    if args.source == "fastapi":
        append_lock = threading.Lock()
        for camera in ("L", "R"):
            url = args.base_url.rstrip("/") + "/stream.mjpg?camera=" + camera
            receiver = threading.Thread(target=receive_camera,
                                        args=(url, camera, ring, stop, state, append_lock),
                                        daemon=True)
            receiver.start()
            receivers.append(receiver)
        print("FastAPI MJPEG 수신: {} (L, R)".format(args.base_url))
    else:
        receiver = threading.Thread(target=receive_loop,
                                    args=(args.endpoint, ring, stop, state), daemon=True)
        receiver.start()
        receivers.append(receiver)
        print("ZMQ 수신: {}".format(args.endpoint))
    threading.Thread(target=command_loop, args=(commands,), daemon=True).start()
    pending = []
    print("Enter: 현재 시각으로 저장 / event <Unix ns>: 지정 시각으로 저장 / q: 종료")
    next_status = 0.0
    try:
        running = True
        while running:
            try:
                command = commands.get(timeout=0.05)
            except queue.Empty:
                command = None
            if command is not None:
                if command.lower() == "q":
                    running = False
                elif not command:
                    event_ns = time.time_ns()
                    pending.append((event_ns, time.monotonic() + args.after))
                    print("이벤트 Unix ns: {}".format(event_ns))
                elif command.startswith("event "):
                    try:
                        event_ns = int(command.split()[1])
                    except (IndexError, ValueError):
                        print("형식: event <Unix nanoseconds>")
                        continue
                    remaining = max(0.0, args.after - (time.time_ns() - event_ns) / 1e9)
                    pending.append((event_ns, time.monotonic() + remaining))
                else:
                    print("Enter, event <Unix ns>, q 중 하나를 입력하세요")

            now = time.monotonic()
            if now >= next_status:
                stats = ring.stats()
                print("영상: {frames}프레임 (L={left}, R={right}) {span_s:.1f}초 "
                      "{bytes:.1f}MB 오류={invalid} (최근 오류: {error})".format(
                          frames=stats["frames"], span_s=stats["span_s"],
                          bytes=stats["bytes"] / 1048576,
                          left=state["camera_counts"]["L"],
                          right=state["camera_counts"]["R"],
                          invalid=state["invalid"], error=state["error"]))
                next_status = now + 1.0

            for event_ns, ready_at in list(pending):
                if now < ready_at:
                    continue
                window = ring.cut_event(event_ns, args.before, args.after)
                stamp = datetime.datetime.fromtimestamp(event_ns / 1e9).strftime(
                    "%Y%m%d_%H%M%S_%f")
                path = Path(args.output) / ("event_" + stamp) / "video"
                index = write_video_capture(window, path)
                print("저장: {} ({}프레임, {:.2f}초, truncated={}, anchor={:.0f}ms)".format(
                    index, len(window.frames), window.actual_span_s,
                    window.truncated, window.anchor_error_ms))
                pending.remove((event_ns, ready_at))
    except KeyboardInterrupt:
        print("종료 요청")
    finally:
        stop.set()
        for receiver in receivers:
            receiver.join(2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())

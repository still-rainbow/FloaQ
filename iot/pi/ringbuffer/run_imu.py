#!/usr/bin/env python3
"""MPU6050 링버퍼 하드웨어 실험 CLI."""

import argparse
import datetime
import queue
import sys
import threading
import time
from pathlib import Path

from imu_ringbuffer import (
    ImuCollector,
    ImuRingBuffer,
    Mpu6050Source,
    SyntheticSource,
    summarize,
    write_capture,
)


def parse_int(value):
    return int(value, 0)


def command_reader(commands):
    while True:
        try:
            command = input().strip().lower()
        except EOFError:
            return
        commands.put(command)
        if command == "q":
            return


def check_hardware(args):
    source = Mpu6050Source(args.bus, args.addr, args.hz)
    try:
        print("MPU6050 확인 성공")
        print("  I2C bus : {}".format(args.bus))
        print("  address : 0x{:02X}".format(args.addr))
        print("  WHO_AM_I: 0x{:02X}".format(source.who_am_i))
        print("  원시값 10회:")
        for _ in range(10):
            reading = source.read()
            print(
                "  accel=({:7.3f}, {:7.3f}, {:7.3f}) m/s²  "
                "gyro=({:7.3f}, {:7.3f}, {:7.3f}) deg/s".format(
                    reading.accel_x, reading.accel_y, reading.accel_z,
                    reading.gyro_x, reading.gyro_y, reading.gyro_z,
                )
            )
            time.sleep(0.1)
    finally:
        source.close()


def build_parser():
    parser = argparse.ArgumentParser(description="MPU6050 최근 구간 링버퍼 실험")
    parser.add_argument("--source", choices=("mpu6050", "synthetic"), default="mpu6050")
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--addr", type=parse_int, default=0x68)
    parser.add_argument("--hz", type=int, default=50)
    parser.add_argument("--buffer-seconds", type=float, default=40.0)
    parser.add_argument("--before", type=float, default=30.0, help="이벤트 전 저장 구간")
    parser.add_argument("--after", type=float, default=5.0, help="이벤트 후 저장 구간")
    parser.add_argument("--calibrate", type=float, default=3.0, help="정지 상태 자이로 보정 시간")
    parser.add_argument("--output", default="captures")
    parser.add_argument("--check", action="store_true", help="연결과 원시값만 확인")
    return parser


def main():
    args = build_parser().parse_args()
    if args.check:
        check_hardware(args)
        return 0

    minimum_buffer = args.before + args.after + 2.0
    buffer_seconds = max(args.buffer_seconds, minimum_buffer)

    if args.source == "mpu6050":
        source = Mpu6050Source(args.bus, args.addr, args.hz)
        print("MPU6050 연결됨: bus={} addr=0x{:02X} WHO_AM_I=0x{:02X}".format(
            args.bus, args.addr, source.who_am_i
        ))
        if args.calibrate > 0:
            print("센서를 움직이지 마세요. 자이로를 {:.1f}초 보정합니다...".format(args.calibrate))
            bias = source.calibrate_gyro(args.calibrate)
            print("자이로 보정값: x={:.4f}, y={:.4f}, z={:.4f} deg/s".format(*bias))
    else:
        source = SyntheticSource()
        print("합성 IMU 소스를 사용합니다")

    ring = ImuRingBuffer(args.hz, buffer_seconds)
    collector = ImuCollector(source, ring, args.hz)
    commands = queue.Queue()
    reader = threading.Thread(target=command_reader, args=(commands,), daemon=True)
    pending_events = []
    output_dir = Path(args.output)

    collector.start()
    reader.start()
    print("\n수집 시작: {}Hz, 버퍼 {:.1f}초".format(args.hz, buffer_seconds))
    print("Enter: 현재 시각으로 저장 / event <Unix ns>: 지정 시각으로 저장 / q: 종료")

    try:
        next_status = time.monotonic()
        running = True
        while running:
            try:
                command = commands.get(timeout=0.05)
                if command == "q":
                    running = False
                elif command == "":
                    event_wall_ns = time.time_ns()
                    ready_at = time.monotonic() + args.after
                    pending_events.append((event_wall_ns, ready_at))
                    print("이벤트 Unix ns: {} / 후속 {:.1f}초 수집".format(event_wall_ns, args.after))
                elif command.startswith("event "):
                    try:
                        event_wall_ns = int(command.split()[1])
                    except (IndexError, ValueError):
                        print("형식: event <Unix nanoseconds>")
                        continue
                    remaining = max(0.0, args.after - (time.time_ns() - event_wall_ns) / 1e9)
                    pending_events.append((event_wall_ns, time.monotonic() + remaining))
                else:
                    print("Enter, event <Unix ns>, q 중 하나를 입력하세요")
            except queue.Empty:
                pass

            now = time.monotonic()
            if now >= next_status:
                samples = ring.snapshot()
                recent = samples[-args.hz:] if samples else []
                info = summarize(recent)
                if info:
                    print(
                        "buffer={:5.1f}s/{:4d}  roll={:7.2f}° pitch={:7.2f}° "
                        "yaw(rel)={:7.2f}° gyro_max={:6.2f}°/s stable={} errors={}".format(
                            ring.span_s(), len(ring), info["roll_deg"], info["pitch_deg"],
                            info["yaw_relative_deg"], info["gyro_max_dps"],
                            info["stable"], collector.read_errors,
                        )
                    )
                elif collector.last_error:
                    print("IMU 읽기 오류: {}".format(collector.last_error))
                next_status = now + 1.0

            ready = [event for event in pending_events if now >= event[1]]
            for event_wall_ns, ready_at in ready:
                window = ring.cut_event(event_wall_ns, args.before, args.after)
                stamp = datetime.datetime.fromtimestamp(event_wall_ns / 1e9).strftime("%Y%m%d_%H%M%S_%f")
                jsonl = output_dir / ("imu_{}.jsonl".format(stamp))
                data_path, meta_path = write_capture(window, jsonl)
                print(
                    "저장 완료: {} ({}개, {:.2f}초, truncated={})".format(
                        data_path, len(window.samples), window.actual_span_s, window.truncated
                    )
                )
                print("메타데이터: {}".format(meta_path))
                pending_events.remove((event_wall_ns, ready_at))
    except KeyboardInterrupt:
        print("\n종료 요청")
    finally:
        collector.stop()
        print("수집 종료: read_errors={}, late_ticks={}".format(
            collector.read_errors, collector.late_ticks
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

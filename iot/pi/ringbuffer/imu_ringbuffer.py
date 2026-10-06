#!/usr/bin/env python3
"""MPU6050 수집, 자세 추정, 최근 구간 보관을 위한 독립 모듈."""

import json
import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path


NS = 1_000_000_000


@dataclass
class RawImuReading:
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float


@dataclass
class ImuSample:
    monotonic_ns: int
    wall_ns: int
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    roll: float
    pitch: float
    yaw: float


@dataclass
class CaptureWindow:
    samples: list
    event_wall_ns: int
    before_s: float
    after_s: float
    anchor_error_ms: float
    actual_span_s: float
    truncated: bool


class Mpu6050Source:
    """MPU6050 I2C 소스. 가속도는 m/s², 자이로는 deg/s를 반환한다."""

    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B
    WHO_AM_I = 0x75

    ACCEL_SCALE = 9.80665 / 16384.0
    GYRO_SCALE = 1.0 / 131.0

    def __init__(self, bus=1, addr=0x68, sample_hz=50):
        try:
            from smbus2 import SMBus
        except ImportError as exc:
            raise RuntimeError("smbus2가 없습니다: pip install smbus2") from exc

        self.bus_no = bus
        self.addr = addr
        self._bus = SMBus(bus)
        self._gyro_bias = (0.0, 0.0, 0.0)

        who = self._bus.read_byte_data(addr, self.WHO_AM_I)
        if who not in (0x68, 0x69):
            self._bus.close()
            raise RuntimeError(
                "MPU6050 WHO_AM_I 불일치: 주소 0x{:02X}, 응답 0x{:02X}".format(addr, who)
            )
        self.who_am_i = who

        self._bus.write_byte_data(addr, self.PWR_MGMT_1, 0x01)
        time.sleep(0.1)
        self._bus.write_byte_data(addr, self.CONFIG, 0x03)       # DLPF 약 44 Hz
        self._bus.write_byte_data(addr, self.GYRO_CONFIG, 0x00) # ±250 deg/s
        self._bus.write_byte_data(addr, self.ACCEL_CONFIG, 0x00)# ±2 g
        divider = max(0, min(255, int(round(1000.0 / sample_hz)) - 1))
        self._bus.write_byte_data(addr, self.SMPLRT_DIV, divider)

    @staticmethod
    def _i16(hi, lo):
        value = (hi << 8) | lo
        return value - 65536 if value >= 32768 else value

    def read(self):
        data = self._bus.read_i2c_block_data(self.addr, self.ACCEL_XOUT_H, 14)
        ax = self._i16(data[0], data[1]) * self.ACCEL_SCALE
        ay = self._i16(data[2], data[3]) * self.ACCEL_SCALE
        az = self._i16(data[4], data[5]) * self.ACCEL_SCALE
        gx = self._i16(data[8], data[9]) * self.GYRO_SCALE - self._gyro_bias[0]
        gy = self._i16(data[10], data[11]) * self.GYRO_SCALE - self._gyro_bias[1]
        gz = self._i16(data[12], data[13]) * self.GYRO_SCALE - self._gyro_bias[2]
        return RawImuReading(ax, ay, az, gx, gy, gz)

    def calibrate_gyro(self, seconds=3.0, sample_hz=100):
        """센서를 움직이지 않은 상태에서 자이로 영점 오차를 측정한다."""
        count = max(1, int(seconds * sample_hz))
        sums = [0.0, 0.0, 0.0]
        old_bias = self._gyro_bias
        self._gyro_bias = (0.0, 0.0, 0.0)
        try:
            for _ in range(count):
                reading = self.read()
                sums[0] += reading.gyro_x
                sums[1] += reading.gyro_y
                sums[2] += reading.gyro_z
                time.sleep(1.0 / sample_hz)
        except Exception:
            self._gyro_bias = old_bias
            raise
        self._gyro_bias = tuple(value / count for value in sums)
        return self._gyro_bias

    def close(self):
        self._bus.close()


class SyntheticSource:
    """하드웨어 없이 CLI와 저장 흐름을 확인하는 합성 소스."""

    def __init__(self):
        self._start = time.monotonic()

    def read(self):
        t = time.monotonic() - self._start
        roll = math.radians(6.0 * math.sin(2.0 * math.pi * t / 4.0))
        pitch = math.radians(3.0 * math.sin(2.0 * math.pi * t / 6.0))
        gx = 6.0 * (2.0 * math.pi / 4.0) * math.cos(2.0 * math.pi * t / 4.0)
        gy = 3.0 * (2.0 * math.pi / 6.0) * math.cos(2.0 * math.pi * t / 6.0)
        g = 9.80665
        return RawImuReading(
            -g * math.sin(pitch),
            g * math.sin(roll),
            g * math.cos(roll) * math.cos(pitch),
            gx, gy, 0.0,
        )

    def close(self):
        pass


class ComplementaryOrientation:
    """가속도와 자이로를 결합해 roll/pitch 각도를 계산한다.

    MPU6050에는 지자기 센서가 없어서 yaw는 gyro_z 적분값이며 시간이 지나면
    드리프트한다. 절대 방위로 사용하면 안 된다.
    """

    def __init__(self, time_constant_s=0.5):
        self.time_constant_s = time_constant_s
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self._last_ns = None

    def update(self, reading, now_ns):
        roll_acc = math.degrees(math.atan2(reading.accel_y, reading.accel_z))
        pitch_acc = math.degrees(math.atan2(
            -reading.accel_x,
            math.sqrt(reading.accel_y ** 2 + reading.accel_z ** 2),
        ))

        if self._last_ns is None:
            self.roll = roll_acc
            self.pitch = pitch_acc
            self._last_ns = now_ns
            return self.roll, self.pitch, self.yaw

        dt = (now_ns - self._last_ns) / NS
        self._last_ns = now_ns
        if dt <= 0.0 or dt > 0.2:
            return self.roll, self.pitch, self.yaw

        alpha = self.time_constant_s / (self.time_constant_s + dt)
        self.roll = alpha * (self.roll + reading.gyro_x * dt) + (1.0 - alpha) * roll_acc
        self.pitch = alpha * (self.pitch + reading.gyro_y * dt) + (1.0 - alpha) * pitch_acc
        self.yaw += reading.gyro_z * dt
        return self.roll, self.pitch, self.yaw


class ImuRingBuffer:
    """가장 최근 ``seconds`` 구간만 유지하는 고정 크기 버퍼."""

    def __init__(self, hz=50, seconds=40.0):
        if hz <= 0 or seconds <= 0:
            raise ValueError("hz와 seconds는 0보다 커야 합니다")
        self.hz = hz
        self.seconds = seconds
        self.capacity = int(math.ceil(hz * seconds)) + 1
        self._samples = deque(maxlen=self.capacity)
        self._lock = threading.Lock()

    def append(self, sample):
        with self._lock:
            if self._samples and sample.monotonic_ns <= self._samples[-1].monotonic_ns:
                raise ValueError("monotonic_ns는 증가해야 합니다")
            self._samples.append(sample)
            cutoff = sample.monotonic_ns - int(self.seconds * NS)
            while self._samples and self._samples[0].monotonic_ns < cutoff:
                self._samples.popleft()

    def snapshot(self):
        with self._lock:
            return list(self._samples)

    def __len__(self):
        with self._lock:
            return len(self._samples)

    def span_s(self):
        samples = self.snapshot()
        if len(samples) < 2:
            return 0.0
        return (samples[-1].monotonic_ns - samples[0].monotonic_ns) / NS

    def cut_event(self, event_wall_ns, before_s=30.0, after_s=0.0):
        samples = self.snapshot()
        if not samples:
            return CaptureWindow([], event_wall_ns, before_s, after_s, 0.0, 0.0, True)

        anchor = min(samples, key=lambda item: abs(item.wall_ns - event_wall_ns))
        start_ns = anchor.monotonic_ns - int(before_s * NS)
        end_ns = anchor.monotonic_ns + int(after_s * NS)
        selected = [item for item in samples if start_ns <= item.monotonic_ns <= end_ns]
        actual_span = 0.0
        if len(selected) >= 2:
            actual_span = (selected[-1].monotonic_ns - selected[0].monotonic_ns) / NS
        tolerance_ns = int(NS / self.hz)
        truncated = (samples[0].monotonic_ns > start_ns + tolerance_ns or
                     samples[-1].monotonic_ns < end_ns - tolerance_ns or
                     abs(anchor.wall_ns - event_wall_ns) > tolerance_ns)
        return CaptureWindow(
            selected,
            event_wall_ns,
            before_s,
            after_s,
            (anchor.wall_ns - event_wall_ns) / 1e6,
            actual_span,
            truncated,
        )


class ImuCollector:
    """정해진 주기로 IMU를 읽어 링버퍼에 추가한다."""

    def __init__(self, source, ring, hz=50, orientation=None):
        self.source = source
        self.ring = ring
        self.hz = hz
        self.orientation = orientation or ComplementaryOrientation()
        self.read_errors = 0
        self.late_ticks = 0
        self.last_error = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("이미 실행 중입니다")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="imu-collector", daemon=True)
        self._thread.start()

    def stop(self, timeout=2.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self.source.close()

    def _run(self):
        period = 1.0 / self.hz
        deadline = time.monotonic()
        while not self._stop.is_set():
            deadline += period
            try:
                raw = self.source.read()
                mono_ns = time.monotonic_ns()
                wall_ns = time.time_ns()
                roll, pitch, yaw = self.orientation.update(raw, mono_ns)
                self.ring.append(ImuSample(
                    mono_ns, wall_ns,
                    raw.accel_x, raw.accel_y, raw.accel_z,
                    raw.gyro_x, raw.gyro_y, raw.gyro_z,
                    roll, pitch, yaw,
                ))
                self.last_error = None
            except Exception as exc:
                self.read_errors += 1
                self.last_error = str(exc)

            delay = deadline - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                self.late_ticks += 1
                deadline = time.monotonic()


def summarize(samples, stable_threshold_dps=3.0):
    if not samples:
        return {}
    latest = samples[-1]
    gyro_max = max(math.sqrt(s.gyro_x ** 2 + s.gyro_y ** 2 + s.gyro_z ** 2) for s in samples)
    accel_mag = math.sqrt(latest.accel_x ** 2 + latest.accel_y ** 2 + latest.accel_z ** 2)
    return {
        "sample_count": len(samples),
        "roll_deg": round(latest.roll, 2),
        "pitch_deg": round(latest.pitch, 2),
        "yaw_relative_deg": round(latest.yaw, 2),
        "gyro_max_dps": round(gyro_max, 2),
        "accel_magnitude": round(accel_mag, 3),
        "stable": gyro_max < stable_threshold_dps,
        "created_at": latest.wall_ns // NS,
    }


def write_capture(window, jsonl_path):
    path = Path(jsonl_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for sample in window.samples:
            stream.write(json.dumps(asdict(sample), separators=(",", ":")) + "\n")

    meta_path = path.with_suffix(".meta.json")
    metadata = {
        "event_wall_ns": window.event_wall_ns,
        "before_s": window.before_s,
        "after_s": window.after_s,
        "sample_count": len(window.samples),
        "actual_span_s": window.actual_span_s,
        "anchor_error_ms": window.anchor_error_ms,
        "truncated": window.truncated,
        "units": {
            "accel_x/y/z": "m/s^2",
            "gyro_x/y/z": "deg/s",
            "roll/pitch/yaw": "deg",
        },
        "yaw_note": "MPU6050 자이로 적분 상대각. 절대 방위가 아니며 드리프트함",
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, meta_path

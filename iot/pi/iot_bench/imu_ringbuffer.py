#!/usr/bin/env python3
"""IMU 링버퍼 — IOT-09 / Jira floaq-146 (Raspberry Pi)

설계 원칙
  버퍼 순서와 구간 길이는 monotonic 시계로 잡는다.
  wall clock 은 기록·조회용이며 NTP 보정으로 점프할 수 있다
  (Jira 178에서 Jetson makestep 1.0 -1 로 두었으므로 점프는 실제로 일어난다).
  두 시계를 섞으면 점프가 난 순간 30초 창 계산이 틀린다.

단위 — ERD 확정값을 따른다
  accel_x/y/z     : m/s^2
  roll/pitch/yaw  : deg/s  ← 각속도다. 각도가 아니다
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

NS = 1_000_000_000


# ─────────────────────────────────────────────────────────────
# 샘플
# ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ImuSample:
    mono_ns: int      # 순서·구간 계산 기준. 단조 증가, NTP 영향 없음
    wall_ns: int      # 기록·조회용. NTP 보정으로 점프 가능
    accel_x: float    # m/s^2
    accel_y: float
    accel_z: float
    roll: float       # deg/s
    pitch: float
    yaw: float

    @property
    def gyro_mag(self) -> float:
        """각속도 크기 (deg/s). 안정 구간 판정에 쓴다."""
        return math.sqrt(self.roll ** 2 + self.pitch ** 2 + self.yaw ** 2)


@dataclass(slots=True)
class Cut:
    """절단 결과와 진단값."""
    samples: list[ImuSample]
    anchor: ImuSample | None
    anchor_error_ms: float      # 요청 시각과 실제 기준 샘플의 차이
    span_s: float               # 실제로 잘린 구간 길이
    requested_span_s: float
    truncated: bool             # 버퍼가 요청 구간을 다 담고 있지 않았다

    def __len__(self) -> int:
        return len(self.samples)


# ─────────────────────────────────────────────────────────────
# 데이터 소스
# ─────────────────────────────────────────────────────────────

class ImuSource(Protocol):
    def read(self) -> tuple[float, float, float, float, float, float]:
        """(accel_x, accel_y, accel_z, roll, pitch, yaw)"""
        ...

    def close(self) -> None:
        ...


class SyntheticImuSource:
    """실물 IMU가 붙기 전 사용. 선박 롤링을 모사한다.

    각도가 A·sin(2πt/T) 라면 각속도는 A·(2π/T)·cos(2πt/T) 이므로
    물리적으로 일관된 각속도를 만든다.
    """

    def __init__(
        self,
        roll_period_s: float = 4.0,
        roll_amp_deg: float = 6.0,
        pitch_period_s: float = 6.5,
        pitch_amp_deg: float = 3.0,
        noise_dps: float = 0.08,
        seed: int = 42,
    ) -> None:
        import random
        self._rng = random.Random(seed)
        self._t0 = time.monotonic()
        self._rw = 2 * math.pi / roll_period_s
        self._pw = 2 * math.pi / pitch_period_s
        self._ra = roll_amp_deg * self._rw     # deg/s 진폭
        self._pa = pitch_amp_deg * self._pw
        self._noise = noise_dps

    def read(self) -> tuple[float, float, float, float, float, float]:
        t = time.monotonic() - self._t0
        n = lambda: self._rng.gauss(0.0, self._noise)
        roll = self._ra * math.cos(self._rw * t) + n()
        pitch = self._pa * math.cos(self._pw * t) + n()
        yaw = n()
        # 중력이 z 에 실린 상태에서 기울기만큼 x·y 로 분해
        roll_deg = (self._ra / self._rw) * math.sin(self._rw * t)
        pitch_deg = (self._pa / self._pw) * math.sin(self._pw * t)
        g = 9.80665
        ax = -g * math.sin(math.radians(pitch_deg))
        ay = g * math.sin(math.radians(roll_deg))
        az = g * math.cos(math.radians(roll_deg)) * math.cos(math.radians(pitch_deg))
        return ax, ay, az, roll, pitch, yaw

    def close(self) -> None:
        pass


class Mpu6050Source:
    """MPU6050 (I2C 0x68 / 0x69).

    ⚠ 미검증 — 작성 시점에 센서가 I2C 에 연결되지 않았다(i2cdetect 에 0x68 없음).
    배선 후 read() 부호·축 방향을 실물로 확인해야 한다.
    """

    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B

    ACCEL_SCALE = 9.80665 / 16384.0   # ±2g,      16384 LSB/g
    GYRO_SCALE = 1.0 / 131.0          # ±250 dps, 131 LSB/(deg/s)

    def __init__(self, bus: int = 1, addr: int = 0x68) -> None:
        from smbus2 import SMBus       # 지연 임포트 — 합성 소스만 쓸 때 불필요
        self._bus = SMBus(bus)
        self._addr = addr
        self._bus.write_byte_data(addr, self.PWR_MGMT_1, 0x00)   # 슬립 해제
        time.sleep(0.05)
        self._bus.write_byte_data(addr, self.CONFIG, 0x03)       # DLPF 44Hz
        self._bus.write_byte_data(addr, self.GYRO_CONFIG, 0x00)  # ±250 dps
        self._bus.write_byte_data(addr, self.ACCEL_CONFIG, 0x00) # ±2g

    @staticmethod
    def _i16(hi: int, lo: int) -> int:
        v = (hi << 8) | lo
        return v - 65536 if v >= 32768 else v

    def read(self) -> tuple[float, float, float, float, float, float]:
        d = self._bus.read_i2c_block_data(self._addr, self.ACCEL_XOUT_H, 14)
        ax = self._i16(d[0], d[1]) * self.ACCEL_SCALE
        ay = self._i16(d[2], d[3]) * self.ACCEL_SCALE
        az = self._i16(d[4], d[5]) * self.ACCEL_SCALE
        # d[6:8] = 온도, 사용하지 않음
        gx = self._i16(d[8], d[9]) * self.GYRO_SCALE
        gy = self._i16(d[10], d[11]) * self.GYRO_SCALE
        gz = self._i16(d[12], d[13]) * self.GYRO_SCALE
        return ax, ay, az, gx, gy, gz

    def close(self) -> None:
        self._bus.close()


# ─────────────────────────────────────────────────────────────
# 링버퍼
# ─────────────────────────────────────────────────────────────

class ImuRingBuffer:
    """30초 창을 확보하기 위해 여유를 두고 보관한다."""

    def __init__(self, hz: int = 50, seconds: float = 35.0) -> None:
        self.hz = hz
        self.seconds = seconds
        self.capacity = int(hz * seconds)
        self._buf: deque[ImuSample] = deque(maxlen=self.capacity)
        self._lock = threading.Lock()

    def append(self, s: ImuSample) -> None:
        with self._lock:
            self._buf.append(s)

    def snapshot(self) -> list[ImuSample]:
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    @property
    def bytes_estimate(self) -> int:
        return self.capacity * 96      # 8 필드 × 8바이트 + 객체 오버헤드

    def span_s(self) -> float:
        b = self.snapshot()
        return 0.0 if len(b) < 2 else (b[-1].mono_ns - b[0].mono_ns) / NS

    def cut_by_wall(self, t0_wall_ns: int, pre_s: float = 30.0, post_s: float = 0.0) -> Cut:
        """사고 시각(wall clock)을 받아 구간을 잘라낸다.

        Jetson 이 사고 시각을 wall clock 으로 보내오므로 입구는 wall clock 이다.
        그 시각에 가장 가까운 샘플을 기준점으로 잡고, 구간 계산은 monotonic 으로 한다.
        wall clock 이 점프해도 잘린 길이가 정확히 pre+post 로 유지된다.
        """
        buf = self.snapshot()
        req = pre_s + post_s
        if not buf:
            return Cut([], None, 0.0, 0.0, req, True)

        anchor = min(buf, key=lambda s: abs(s.wall_ns - t0_wall_ns))
        lo = anchor.mono_ns - int(pre_s * NS)
        hi = anchor.mono_ns + int(post_s * NS)
        picked = [s for s in buf if lo <= s.mono_ns <= hi]

        span = 0.0 if len(picked) < 2 else (picked[-1].mono_ns - picked[0].mono_ns) / NS
        # 버퍼 시작이 요청 구간보다 늦으면 잘린 것이다
        truncated = buf[0].mono_ns > lo or buf[-1].mono_ns < hi
        return Cut(
            samples=picked,
            anchor=anchor,
            anchor_error_ms=(anchor.wall_ns - t0_wall_ns) / 1e6,
            span_s=span,
            requested_span_s=req,
            truncated=truncated,
        )


# ─────────────────────────────────────────────────────────────
# 수집 스레드
# ─────────────────────────────────────────────────────────────

class ImuCollector:
    """고정 주기로 소스를 읽어 링버퍼에 넣는다.

    sleep(period) 를 반복하면 읽기 시간이 누적돼 실제 주기가 늘어진다.
    다음 마감 시각을 더해가며 그 차이만큼 대기해 드리프트를 없앤다.
    """

    def __init__(self, source: ImuSource, buffer: ImuRingBuffer, hz: int = 50) -> None:
        self._src = source
        self._buf = buffer
        self._hz = hz
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.read_errors = 0
        self.late_ticks = 0          # 주기를 못 지킨 횟수

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("이미 실행 중")
        self._thread = threading.Thread(target=self._loop, name="imu", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._src.close()

    def _loop(self) -> None:
        period = 1.0 / self._hz
        next_t = time.monotonic()
        while not self._stop.is_set():
            next_t += period
            try:
                a = self._src.read()
            except Exception:
                self.read_errors += 1
            else:
                self._buf.append(ImuSample(time.monotonic_ns(), time.time_ns(), *a))
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                # 밀렸으면 따라잡지 않는다. 몰아서 읽으면 주기가 더 깨진다
                self.late_ticks += 1
                next_t = time.monotonic()


# ─────────────────────────────────────────────────────────────
# 요약과 내보내기
# ─────────────────────────────────────────────────────────────

def summarize(samples: Sequence[ImuSample], stable_threshold_dps: float = 3.0) -> dict:
    """MQTT `sensors/imu` 용 1Hz 요약.

    원본 50Hz 를 MQTT 로 올리면 초당 50 메시지가 된다. 표시·감시용은 요약만 보낸다.
    """
    if not samples:
        return {}
    n = len(samples)
    mean = lambda f: sum(getattr(s, f) for s in samples) / n
    span_ms = int((samples[-1].mono_ns - samples[0].mono_ns) / 1e6)
    return {
        "accel_x": round(mean("accel_x"), 4),
        "accel_y": round(mean("accel_y"), 4),
        "accel_z": round(mean("accel_z"), 4),
        "roll": round(mean("roll"), 4),        # deg/s
        "pitch": round(mean("pitch"), 4),
        "yaw": round(mean("yaw"), 4),
        "gyro_mag_max": round(max(s.gyro_mag for s in samples), 4),
        "stable": max(s.gyro_mag for s in samples) < stable_threshold_dps,
        "window_ms": span_ms,
        "sample_count": n,
        "created_at": samples[-1].wall_ns // NS,   # ERD: int unixtime
    }


def write_jsonl(samples: Sequence[ImuSample], path: str | Path) -> Path:
    """IOT-20(EC2 업로드) 입력. 30초 단위로 잘라 저장한다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps({
                "mono_ns": s.mono_ns,
                "created_at_ns": s.wall_ns,
                "accel_x": s.accel_x, "accel_y": s.accel_y, "accel_z": s.accel_z,
                "roll": s.roll, "pitch": s.pitch, "yaw": s.yaw,
            }, separators=(",", ":")) + "\n")
    return p

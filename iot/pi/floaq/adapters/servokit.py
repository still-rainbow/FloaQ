from __future__ import annotations

import logging
import time
from itertools import pairwise
from typing import Any


log = logging.getLogger(__name__)

#: CH0/CH1 위치 서보의 펄스 범위(µs). `2servo.py` 와 같은 규약이다:
#: 0°=500µs, 90°=1500µs, 180°=2500µs.
#:
#: 🔴 이걸 안 걸면 adafruit 라이브러리 기본값 750~2250µs 로 돈다. 그러면 같은
#:    명령값이 2servo 의 75% 만 돌고, 이 규약으로 잰 pitch 보정표
#:    (2.5:110 / 25:90)가 잰 자세를 못 낸다 (2026-09-23 확인).
POSITION_PULSE_US = (500, 2500)
CH2_REVERSAL_PAUSE_SECONDS = 0.5
CH2_REWIND_SECONDS = 1.0


def interpolate_servo_command(
    angle_deg: float, points: list[tuple[float, float]]
) -> float:
    ordered = sorted((float(angle), float(command)) for angle, command in points)
    if len(ordered) < 2:
        raise ValueError("servo calibration requires at least two points")
    if len({angle for angle, _ in ordered}) != len(ordered):
        raise ValueError("servo calibration angles must be unique")
    if not ordered[0][0] <= angle_deg <= ordered[-1][0]:
        raise ValueError("requested angle is outside the calibrated range")
    for (angle_a, command_a), (angle_b, command_b) in pairwise(ordered):
        if angle_a <= angle_deg <= angle_b:
            ratio = (angle_deg - angle_a) / (angle_b - angle_a)
            return command_a + ratio * (command_b - command_a)
    raise RuntimeError("failed to interpolate servo command")


class ServoKitAimOnlyLauncher:
    """PCA9685 CH0/CH1 aimer with an explicitly armed one-shot CH2 mode."""

    def __init__(
        self,
        *,
        yaw_points: list[tuple[float, float]],
        pitch_points: list[tuple[float, float]],
        address: int = 0x60,
        yaw_channel: int = 0,
        pitch_channel: int = 1,
        release_channel: int = 2,
        armed: bool = False,
        fire_settle_seconds: float = 3.0,
        ch2_max_seconds: float = 1.1,
        fire_stable_count: int = 3,
        kit: Any | None = None,
    ) -> None:
        if len(yaw_points) < 2 or len(pitch_points) < 2:
            raise ValueError(
                "yaw and pitch each require at least two calibration points"
            )
        if len({yaw_channel, pitch_channel, release_channel}) != 3:
            raise ValueError("yaw, pitch, and release channels must differ")
        if not 0 <= fire_settle_seconds <= 10:
            raise ValueError("fire settle time must be between 0 and 10 seconds")
        if not 0 < ch2_max_seconds <= 5:
            raise ValueError("CH2 drive time must be over 0 and at most 5 seconds")
        if not 1 <= fire_stable_count <= 10:
            raise ValueError("fire stable count must be between 1 and 10")
        if kit is None:
            from adafruit_servokit import ServoKit

            kit = ServoKit(channels=16, address=address)
        self._kit = kit
        self._yaw_channel = yaw_channel
        self._pitch_channel = pitch_channel
        self._release_channel = release_channel
        for channel in (yaw_channel, pitch_channel):
            self._kit.servo[channel].set_pulse_width_range(*POSITION_PULSE_US)
        self._yaw_points = yaw_points
        self._pitch_points = pitch_points
        self._armed = bool(armed)
        self._fired = False
        self._fire_candidate = None
        self._fire_stable_count = 0
        self._fire_stable_needed = int(fire_stable_count)
        self._fire_settle_seconds = float(fire_settle_seconds)
        self._ch2_max_seconds = float(ch2_max_seconds)
        self._release = None
        if self._armed:
            self._release = self._kit.continuous_servo[self._release_channel]
            # Match 2servo.py: neutral=1500us, plus=1800us.
            self._release.set_pulse_width_range(1200, 1800)
            self._release.throttle = 0.0

    def is_loaded(self) -> bool:
        # Aim-only mode deliberately prevents the launch state machine from
        # considering the device loaded.
        return False

    @property
    def armed(self) -> bool:
        return self._armed

    def _move(self, label: str, yaw_deg: float, pitch_deg: float) -> None:
        yaw_command = interpolate_servo_command(yaw_deg, self._yaw_points)
        pitch_command = interpolate_servo_command(pitch_deg, self._pitch_points)
        log.info(
            "%s yaw=%+.2f°→CH%d %.1f, pitch=%+.2f°→CH%d %.1f",
            label,
            yaw_deg,
            self._yaw_channel,
            yaw_command,
            pitch_deg,
            self._pitch_channel,
            pitch_command,
        )
        self._kit.servo[self._yaw_channel].angle = yaw_command
        self._kit.servo[self._pitch_channel].angle = pitch_command

    def point(self, yaw_command: float, pitch_command: float) -> None:
        """Start pose in raw servo commands (0~180, same numbers as 2servo.py).

        Moves CH0/CH1 only and never counts toward auto fire.
        """
        for command in (yaw_command, pitch_command):
            if not 0 <= command <= 180:
                raise ValueError("servo command must be between 0 and 180")
        log.info(
            "start pose CH%d %.1f, CH%d %.1f",
            self._yaw_channel,
            yaw_command,
            self._pitch_channel,
            pitch_command,
        )
        self._kit.servo[self._yaw_channel].angle = yaw_command
        self._kit.servo[self._pitch_channel].angle = pitch_command

    def aim(self, yaw_deg: float, pitch_deg: float) -> str:
        self._move("aim", yaw_deg, pitch_deg)
        if self._armed and not self._fired:
            current = (float(yaw_deg), float(pitch_deg))
            if self._fire_candidate is not None and (
                abs(current[0] - self._fire_candidate[0]) <= 2.0
                and abs(current[1] - self._fire_candidate[1]) <= 1.0
            ):
                self._fire_stable_count += 1
            else:
                self._fire_stable_count = 1
            self._fire_candidate = current
            log.warning("AUTO FIRE CHECK: stable aim %d/%d",
                        self._fire_stable_count, self._fire_stable_needed)
        if (self._armed and not self._fired
                and self._fire_stable_count >= self._fire_stable_needed):
            # Latch before waiting: a second MQTT command can never release twice.
            self._fired = True
            log.warning(
                "AUTO FIRE ARMED: settle %.1fs, CH%d forward %.1fs, "
                "pause %.1fs, rewind %.1fs",
                self._fire_settle_seconds,
                self._release_channel,
                self._ch2_max_seconds,
                CH2_REVERSAL_PAUSE_SECONDS,
                CH2_REWIND_SECONDS,
            )
            time.sleep(self._fire_settle_seconds)
            try:
                self._release.throttle = 1.0
                time.sleep(self._ch2_max_seconds)
                self._release.throttle = 0.0
                time.sleep(CH2_REVERSAL_PAUSE_SECONDS)
                self._release.throttle = -1.0
                time.sleep(CH2_REWIND_SECONDS)
            finally:
                self._release.throttle = 0.0
            log.warning("AUTO FIRE COMPLETE: CH%d returned to neutral", self._release_channel)
        return "SUCCESS"

    def aim_and_release(self, yaw_deg: float, pitch_deg: float, profile: str) -> str:
        # Manual release only. Do not even move CH0/CH1 through this method,
        # because callers must use the separate jetson/aim path.
        return "DEVICE_ERROR"

    def safe(self) -> None:
        self._kit.servo[self._yaw_channel].angle = None
        self._kit.servo[self._pitch_channel].angle = None
        if self._release is not None:
            self._release.throttle = 0.0

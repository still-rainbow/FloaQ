from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters.servokit import (
    ServoKitAimOnlyLauncher,
    interpolate_servo_command,
)


class Servo:
    angle = None
    pulse_range = None

    def set_pulse_width_range(self, minimum, maximum) -> None:
        self.pulse_range = (minimum, maximum)


class ContinuousServo:
    def __init__(self) -> None:
        self.history = []
        self.pulse_range = None
        self._throttle = None

    def set_pulse_width_range(self, minimum, maximum) -> None:
        self.pulse_range = (minimum, maximum)

    @property
    def throttle(self):
        return self._throttle

    @throttle.setter
    def throttle(self, value) -> None:
        self._throttle = value
        self.history.append(value)


class Kit:
    def __init__(self) -> None:
        self.servo = [Servo() for _ in range(16)]
        self.continuous_servo = [ContinuousServo() for _ in range(16)]


def test_position_servos_use_the_2servo_pulse_range() -> None:
    """🔴 `2servo.py` 와 같은 0°=500µs … 180°=2500µs.

    안 걸면 라이브러리 기본 750~2250µs 라 같은 명령값이 75% 만 돈다.
    """
    kit = Kit()
    ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        kit=kit,
    )
    assert kit.servo[0].pulse_range == (500, 2500)
    assert kit.servo[1].pulse_range == (500, 2500)
    # CH2 는 연속 서보라 따로 건다 (발사할 때만 — --no-fire 면 안 만든다)
    assert kit.continuous_servo[2].pulse_range is None


def test_interpolates_calibrated_commands() -> None:
    assert interpolate_servo_command(13.75, [(2.5, 110), (25, 90)]) == 100


def test_refuses_extrapolation() -> None:
    with pytest.raises(ValueError, match="outside"):
        interpolate_servo_command(30, [(2.5, 110), (25, 90)])


def test_aim_only_moves_ch0_and_ch1_but_never_ch2() -> None:
    kit = Kit()
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        kit=kit,
    )
    assert launcher.aim(0, 13.75) == "SUCCESS"
    assert kit.servo[0].angle == 90
    assert kit.servo[1].angle == 100
    assert kit.servo[2].angle is None
    assert launcher.aim_and_release(0, 10, "demo-low-v1") == "DEVICE_ERROR"
    assert kit.servo[2].angle is None


def test_safe_disables_only_aiming_channels() -> None:
    kit = Kit()
    kit.servo[2].angle = 77
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        kit=kit,
    )
    launcher.aim(0, 13.75)
    launcher.safe()
    assert kit.servo[0].angle is None
    assert kit.servo[1].angle is None
    assert kit.servo[2].angle == 77


def test_armed_mode_fires_then_rewinds_ch2_once(monkeypatch) -> None:
    sleep_calls = []
    monkeypatch.setattr("floaq.adapters.servokit.time.sleep", sleep_calls.append)
    kit = Kit()
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        armed=True,
        fire_settle_seconds=3,
        ch2_max_seconds=1.3,
        kit=kit,
    )

    launcher.aim(0, 13.75)
    launcher.aim(1, 13.75)
    launcher.aim(1.5, 13.75)
    launcher.aim(1.5, 13.75)

    release = kit.continuous_servo[2]
    assert release.pulse_range == (1200, 1800)
    assert release.history == [0.0, 1.0, 0.0, -1.0, 0.0]
    assert sleep_calls == [3, 1.3, 0.5, 1.0]
    launcher.safe()
    assert release.history[-1] == 0.0


def test_stable_count_one_fires_on_the_first_aim(monkeypatch) -> None:
    """시연 기본값: Jetson 이 이미 2쌍 안정 뒤에 보내므로 첫 조준에 쏜다."""
    monkeypatch.setattr("floaq.adapters.servokit.time.sleep", lambda _seconds: None)
    kit = Kit()
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        armed=True,
        fire_stable_count=1,
        kit=kit,
    )

    launcher.aim(0, 13.75)

    assert kit.continuous_servo[2].history == [0.0, 1.0, 0.0, -1.0, 0.0]


def test_ch2_returns_to_neutral_if_rewind_is_interrupted(monkeypatch) -> None:
    def interrupt_rewind(seconds):
        if seconds == 1.0:
            raise KeyboardInterrupt

    monkeypatch.setattr("floaq.adapters.servokit.time.sleep", interrupt_rewind)
    kit = Kit()
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-10, 80), (10, 100)],
        pitch_points=[(2.5, 110), (25, 90)],
        armed=True,
        fire_stable_count=1,
        kit=kit,
    )

    with pytest.raises(KeyboardInterrupt):
        launcher.aim(0, 13.75)

    assert kit.continuous_servo[2].history == [0.0, 1.0, 0.0, -1.0, 0.0]


def test_start_pose_never_fires(monkeypatch) -> None:
    """🔴 시작 자세는 aim() 이 아니다. 안정 1회로도 켜자마자 쏘면 안 된다."""
    monkeypatch.setattr("floaq.adapters.servokit.time.sleep", lambda _seconds: None)
    kit = Kit()
    launcher = ServoKitAimOnlyLauncher(
        yaw_points=[(-45, 123.75), (0, 90), (45, 56.25)],
        pitch_points=[(-10, 121.1), (2.5, 110), (25, 90)],
        armed=True,
        fire_stable_count=1,
        kit=kit,
    )

    # 보정표 밖의 명령값이어도 간다 — 시작 자세는 각도가 아니라 명령값이다
    launcher.point(135, 130)

    assert kit.servo[0].angle == 135              # 90 초과가 왼쪽 (09-23 실측)
    assert kit.servo[1].angle == 130              # 기본 자세 110 보다 아래
    assert kit.continuous_servo[2].history == [0.0]
    with pytest.raises(ValueError):
        launcher.point(181, 110)

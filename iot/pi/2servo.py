#!/usr/bin/env python3
"""PCA9685 CH0/1 위치제어와 CH2 연속회전 서보를 무부하 시험.

실측 보정: 0°=500 us, 90°=1500 us, 180°=2500 us.
스프링과 발사 하중을 제거한 상태에서만 시험한다.
CH2의 끝 위치는 서보 자체로 알 수 없다. 리미트 스위치가 없으면 시간 제한으로만 멈춘다.
"""

import argparse
import math
import sys
import time


ADDRESS = 0x60
FREQUENCY = 50
HOLD_SECONDS = 3.0
CHANNELS = ((0, "좌우(yaw)"), (1, "상하(pitch)"))
CH2_NEUTRAL_US = 1500
CH2_DRIVE_OFFSET_US = 300  # 첫 무부하 시험용 저속 시작값. 실제 방향·정지는 실측한다.
CH2_DEFAULT_MAX_SECONDS = 5.0
CH2_ABSOLUTE_MAX_SECONDS = 5.0


def parse_args():
    parser = argparse.ArgumentParser(description="PCA9685 서보 3채널 무부하 시험")
    parser.add_argument("--ch2", choices=("skip", "plus", "minus"), default=None,
                        help="CH2 방향. plus/minus는 펄스 방향이며 실제 회전 방향은 장착에 따라 다름")
    parser.add_argument("--ch2-max-seconds", type=float,
                        default=CH2_DEFAULT_MAX_SECONDS,
                        help="CH2 강제 정지 시간 (기본 1초, 최대 5초)")
    parser.add_argument("--ch2-limit-gpio", type=int, default=None,
                        help="끝 감지 스위치 BCM GPIO. 누르면 GND로 연결되는 방식")
    parser.add_argument("--ch2-neutral-us", type=int, default=CH2_NEUTRAL_US,
                        help="CH2 정지 펄스. 1500us에서 움직이면 무부하로 보정")
    args = parser.parse_args()
    if not math.isfinite(args.ch2_max_seconds) or not 0 < args.ch2_max_seconds <= CH2_ABSOLUTE_MAX_SECONDS:
        parser.error("--ch2-max-seconds는 0초 초과, 5초 이하여야 합니다")
    if not 1400 <= args.ch2_neutral_us <= 1600:
        parser.error("--ch2-neutral-us는 1400~1600us 범위에서 보정하세요")
    if args.ch2_limit_gpio is not None and not 0 <= args.ch2_limit_gpio <= 27:
        parser.error("--ch2-limit-gpio는 BCM 0~27이어야 합니다")
    return args


def read_angle(label):
    value = float(input(f"{label} 각도 입력 (0~180): ").strip())
    if not math.isfinite(value) or not 0 <= value <= 180:
        raise ValueError(f"{label} 각도는 0~180 사이의 숫자여야 합니다.")
    return value


def angle_to_pulse_us(angle):
    return 500 + angle * (2000 / 180)


def set_pulse_us(channel, actual_hz, pulse_us):
    channel.duty_cycle = round(0xFFFF * pulse_us * actual_hz / 1_000_000)


def read_ch2_direction(value):
    if value is None:
        value = input("CH2 방향 [plus/minus/skip] (기본 skip): ").strip().lower() or "skip"
    if value not in ("plus", "minus", "skip"):
        raise ValueError("CH2 방향은 plus, minus, skip 중 하나여야 합니다")
    return value


def rotate_ch2(channel, actual_hz, direction, *, max_seconds, neutral_us,
               limit_pressed=None):
    """끝 스위치 또는 제한 시간까지 회전한 뒤 정지 펄스를 준다.

    리미트 스위치가 없으면 '끝에 도달'은 판정하지 않는다.
    """
    if direction == "skip":
        return "skipped"
    if limit_pressed is not None and limit_pressed():
        print("CH2 리미트 스위치가 이미 눌려 있어 구동하지 않습니다.")
        return "limit"

    sign = 1 if direction == "plus" else -1
    drive_us = neutral_us + sign * CH2_DRIVE_OFFSET_US
    deadline = time.monotonic() + max_seconds
    print(f"CH2 {direction}: {drive_us}us, 최대 {max_seconds:g}초")
    try:
        set_pulse_us(channel, actual_hz, drive_us)
        while time.monotonic() < deadline:
            if limit_pressed is not None and limit_pressed():
                print("CH2 리미트 스위치 감지 - 정지")
                return "limit"
            time.sleep(0.02)
        print("CH2 제한 시간 도달 - 정지 (끝 위치 확인 아님)")
        return "timeout"
    finally:
        set_pulse_us(channel, actual_hz, neutral_us)
        time.sleep(0.1)


def disable_channel(channel, label):
    for attempt in range(3):
        try:
            channel.duty_cycle = 0
            if channel.duty_cycle == 0:
                return True
        except OSError as exc:
            print(f"{label} PWM 차단 오류 ({attempt + 1}/3): {exc}", file=sys.stderr)
        if attempt < 2:
            time.sleep(0.2)
    return False


def main():
    args = parse_args()
    try:
        angles = [read_angle(label) for _, label in CHANNELS]
        ch2_direction = read_ch2_direction(args.ch2)
    except (ValueError, EOFError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소했습니다.")
        return 1


    try:
        import board
        from adafruit_pca9685 import PCA9685
    except ImportError as exc:
        print(f"필요한 패키지가 없습니다: {exc}. IoT/PI에서 uv sync를 확인하세요.",
              file=sys.stderr)
        return 2

    controller = None
    channels = []
    gpio = None
    status = 0
    try:
        limit_pressed = None
        if ch2_direction != "skip" and args.ch2_limit_gpio is not None:
            import RPi.GPIO as gpio
            gpio.setmode(gpio.BCM)
            gpio.setup(args.ch2_limit_gpio, gpio.IN, pull_up_down=gpio.PUD_UP)
            limit_pressed = lambda: gpio.input(args.ch2_limit_gpio) == gpio.LOW

        controller = PCA9685(board.I2C(), address=ADDRESS)
        controller.frequency = FREQUENCY
        channels = [controller.channels[index] for index, _ in CHANNELS]
        if ch2_direction != "skip":
            channels.append(controller.channels[2])
        actual_hz = controller.frequency

        for channel, (index, label), angle in zip(channels[:2], CHANNELS, angles):
            pulse_us = angle_to_pulse_us(angle)
            set_pulse_us(channel, actual_hz, pulse_us)
            print(f"CH{index} {label}: {angle:g}° → {pulse_us:.0f} us")

        print(f"{HOLD_SECONDS:g}초 동안 유지합니다.")
        time.sleep(HOLD_SECONDS)
        if ch2_direction != "skip":
            result = rotate_ch2(
                channels[2], actual_hz, ch2_direction,
                max_seconds=args.ch2_max_seconds,
                neutral_us=args.ch2_neutral_us,
                limit_pressed=limit_pressed,
            )
            if result == "timeout" and limit_pressed is not None:
                status = 4  # 끝 스위치를 달았는데 시간 안에 도달하지 못함
    except KeyboardInterrupt:
        print("\n사용자 중단")
    except (OSError, ImportError) as exc:
        print(f"PCA9685 또는 리미트 스위치 오류: {exc}", file=sys.stderr)
        status = 2
    finally:
        if controller is not None:
            for index, channel in enumerate(channels):
                label = CHANNELS[index][1] if index < 2 else "해제(CH2)"
                if not disable_channel(channel, label):
                    print(f"위험: {label} PWM 차단을 확인하지 못했습니다. 서보 V+ 전원을 차단하세요.",
                          file=sys.stderr)
                    status = 3
            try:
                controller.deinit()
            except OSError as exc:
                print(f"PCA9685 종료 중 I2C 오류: {exc}", file=sys.stderr)
                if status == 0:
                    status = 2
        if gpio is not None:
            gpio.cleanup(args.ch2_limit_gpio)
    if status == 0:
        print("사용한 채널 PWM 차단 완료 (유지 토크 없음).")
    return status


if __name__ == "__main__":
    sys.exit(main())

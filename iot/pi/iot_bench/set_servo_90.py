#!/usr/bin/env python3
"""Center one unloaded, positional servo through the project's PCA9685.

The 1500 us command is a nominal center, not a measured 90-degree position.
Run on the Raspberry Pi only after removing the spring and detaching the horn.

Examples:
    python set_servo_90.py --ch 0                 # yaw
    python set_servo_90.py --ch 1                 # pitch
    python set_servo_90.py --ch 2 --addr 0x60     # release, unloaded only
"""

import argparse
import sys
import time


CHANNEL_NAMES = {0: "yaw", 1: "pitch", 2: "release"}


def main():
    parser = argparse.ArgumentParser(
        description="PCA9685의 한 채널에 50 Hz / 1500 us를 보내 서보를 중앙으로 이동"
    )
    parser.add_argument("--ch", type=int, choices=CHANNEL_NAMES, required=True,
                        help="0=yaw, 1=pitch, 2=release")
    parser.add_argument("--addr", type=lambda value: int(value, 0), default=0x60,
                        help="I2C 주소 (현장 시험값 0x60; 다른 보드는 스캔 후 지정)")
    parser.add_argument("--bus", type=int, default=1, help="I2C 버스 번호 (기본 1)")
    parser.add_argument("--hold", type=float, default=5.0,
                        help="중앙 명령 유지 시간(초, 기본 5; 이후 PWM 차단)")
    args = parser.parse_args()

    if not 0x03 <= args.addr <= 0x77:
        parser.error("I2C 주소는 0x03~0x77이어야 합니다")
    if args.bus < 0 or not 0.1 <= args.hold <= 60:
        parser.error("버스는 0 이상, 유지 시간은 0.1~60초여야 합니다")

    print(f"채널 CH{args.ch} ({CHANNEL_NAMES[args.ch]}), I2C 0x{args.addr:02X}")
    print("스프링 제거·혼 분리·180° 위치제어형 서보 확인이 필요합니다.")
    print("360° 연속회전형에서는 1500 us가 '90°'가 아니라 정지/중립일 수 있습니다.")
    if args.ch == 2:
        print("주의: CH2는 잠금핀 해제용입니다. 발사장치에 하중이 걸려 있으면 실행하지 마세요.")
    try:
        if input("위 조건을 확인했다면 YES 입력: ").strip() != "YES":
            print("취소: 모터에 명령을 보내지 않았습니다.")
            return 1
    except EOFError:
        print("취소: 대화형 확인 입력이 없습니다.", file=sys.stderr)
        return 1

    from pca9685_servo_test import PCA9685

    controller = None
    try:
        controller = PCA9685(args.bus, args.addr)
        _, actual_hz = controller.set_freq(50)
        counts = controller.set_pulse_us(args.ch, 1500)
        print(f"1500 us 출력 중 ({actual_hz:.2f} Hz, {counts} counts) — {args.hold:g}초")
        time.sleep(args.hold)
    except KeyboardInterrupt:
        print("\n사용자 중단")
    finally:
        if controller is not None:
            controller.close()  # Existing driver disables all PWM channels.
            print("PWM 전 채널 차단. 이 상태에서는 서보 유지 토크가 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Test only the continuous-rotation release servo on PCA9685 CH2.

Uses the same 1200-1800 us range and +1.0 throttle as floaq/adapters/servokit.py,
then runs at -1.0 throttle for the same duration. Each direction has the same
speed magnitude; a short neutral pause separates the direction changes.
Remove the spring and release load before running; CH2 can actuate the launcher.
Do not run this alongside main.py, which uses the same PCA9685.

From IoT/PI on the Raspberry Pi:
    uv run python iot_bench/ch2_continuous_servo_test.py --seconds 2
"""

import argparse
import math
import sys
import time


REVERSAL_PAUSE_SECONDS = 0.5


def main() -> int:
    parser = argparse.ArgumentParser(description="CH2 연속회전 서보 정방향·역방향 시험")
    parser.add_argument("--seconds", type=float, required=True,
                        help="방향별 회전 시간(초, 0초 초과~5초 이하)")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 5:
        parser.error("--seconds는 0초 초과, 5초 이하의 숫자여야 합니다")

    print("CH2 발사 장치의 스프링과 하중을 제거하고 main.py를 종료했는지 확인하세요.")


    try:
        from adafruit_servokit import ServoKit
        kit = ServoKit(channels=16, address=0x60)
        release = kit.continuous_servo[2]
        release.set_pulse_width_range(1200, 1800)
        release.throttle = 0.0
        try:
            print(f"CH2 정방향: throttle=+1.0, {args.seconds:g}초")
            release.throttle = 1.0
            time.sleep(1.3)
            release.throttle = 0.0
            time.sleep(REVERSAL_PAUSE_SECONDS)
            print(f"CH2 역방향: throttle=-1.0, {args.seconds:g}초")
            release.throttle = -1.0
            time.sleep(1.0)
        finally:
            release.throttle = 0.0
            print("CH2 중립 신호 출력: throttle=0.0")
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다.")
        return 130
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"CH2 시험 오류: {exc}", file=sys.stderr)
        print("정지 신호를 확인할 수 없으면 서보 전원을 차단하세요.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

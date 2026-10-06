"""서보 제어만 추출 — PCA9685 + MG996R 180°

원본 hardware.py에서 서보에 해당하는 부분만 남겼다.
제거: 홀센서(GPIO), 디바운스, 점유 판정, evidence, 대여/반납 상태머신
"""

import threading
import time

from adafruit_servokit import ServoKit

# ── 설정 (원본의 config 상수를 리터럴로) ──────────────────────
PCA9685_ADDRESS  = 0x60      # i2cdetect -y 1 결과
PCA9685_CHANNELS = 16
SERVO_CHANNEL    = 0

SERVO_PULSE_MIN  = 1000      # us. 데이터시트 기준. 실측 후 넓힌다
SERVO_PULSE_MAX  = 2000

OPEN_ANGLE   = 90            # 실물 확인 후 조정
CLOSE_ANGLE  = 0

# ── 초기화 ──────────────────────────────────────────────────
_kit = ServoKit(channels=PCA9685_CHANNELS, address=PCA9685_ADDRESS)
_servo = _kit.servo[SERVO_CHANNEL]
_servo.set_pulse_width_range(SERVO_PULSE_MIN, SERVO_PULSE_MAX)

servo_lock = threading.Lock()
current_lock_state = "UNKNOWN"      # OPEN / CLOSED / UNKNOWN


def open_servo(reason: str = ""):
    global current_lock_state
    with servo_lock:
        print(f"[Pi] 서보 OPEN (angle={OPEN_ANGLE}, 원인={reason})")
        _servo.angle = OPEN_ANGLE
        current_lock_state = "OPEN"


def close_servo(reason: str = ""):
    global current_lock_state
    with servo_lock:
        print(f"[Pi] 서보 CLOSE (angle={CLOSE_ANGLE}, 원인={reason})")
        _servo.angle = CLOSE_ANGLE
        current_lock_state = "CLOSED"


def set_angle(deg: float, reason: str = ""):
    """임의 각도. 원본에는 없지만 시험용으로 추가."""
    global current_lock_state
    with servo_lock:
        print(f"[Pi] 서보 {deg}° (원인={reason})")
        _servo.angle = max(0, min(180, deg))
        current_lock_state = "UNKNOWN"


def release_servo(reason: str = ""):
    """PWM 중단 — 토크가 걸리지 않는다. 부팅·종료 시 안전 상태."""
    global current_lock_state
    with servo_lock:
        print(f"[Pi] 서보 해제 (원인={reason})")
        _servo.angle = None
        current_lock_state = "UNKNOWN"


if __name__ == "__main__":
    try:
        for deg in (90, 60, 90, 120, 90):
            set_angle(deg, "시험")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n중단")
    finally:
        release_servo("시험 종료")

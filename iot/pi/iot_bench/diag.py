#!/usr/bin/env python3
"""PCA9685 진단 — 쓴 값이 칩에 실제로 들어가는지 읽어서 확인"""

import sys, time

try:
    from smbus2 import SMBus
except ImportError:
    sys.exit("[X] smbus2 없음 →  uv add smbus2   (또는 pip install smbus2 --break-system-packages)")

ADDR = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x60
CH   = int(sys.argv[2]) if len(sys.argv) > 2 else 0
BUS  = 1

MODE1, MODE2, PRESCALE, LED0 = 0x00, 0x01, 0xFE, 0x06

print(f"버스 /dev/i2c-{BUS} · 주소 0x{ADDR:02X} · 채널 {CH}\n")

try:
    bus = SMBus(BUS)
except Exception as e:
    sys.exit(f"[X] 버스 열기 실패: {e}\n    I2C 활성화(raspi-config)와 i2c 그룹 권한 확인")

def r(reg):
    return bus.read_byte_data(ADDR, reg)

def w(reg, *v):
    bus.write_i2c_block_data(ADDR, reg, list(v))

# 1) 응답 확인
try:
    m1 = r(MODE1)
except Exception as e:
    sys.exit(f"[X] 0x{ADDR:02X} 응답 없음: {e}\n    i2cdetect -y 1 로 주소 재확인")
print(f"[OK] 응답함 · MODE1 = 0x{m1:02X}")

# 2) PCA9685 인지 확인 — PRESCALE 왕복 시험
before = r(PRESCALE)
w(MODE1, (m1 & ~0x80) | 0x10)          # SLEEP
w(PRESCALE, 0x79)                       # 121 = 50Hz
time.sleep(0.005)
back = r(PRESCALE)
if back != 0x79:
    print(f"[X] PRESCALE 왕복 실패 (쓴 값 0x79, 읽은 값 0x{back:02X})")
    print("    → 이 주소의 장치는 PCA9685가 아닐 가능성이 큽니다")
    sys.exit(1)
print(f"[OK] PRESCALE 왕복 성공 (reset 기본값 0x{before:02X} → 0x{back:02X}) — PCA9685 확인")

# 3) 깨우기 + auto-increment
w(MODE1, 0x20)                          # AI=1, SLEEP=0
time.sleep(0.005)
w(MODE1, 0xA0)                          # RESTART | AI
m1 = r(MODE1)
print(f"[{'OK' if not (m1 & 0x10) else 'X '}] MODE1 = 0x{m1:02X} · SLEEP={'해제' if not (m1 & 0x10) else '걸림!'} · AI={'on' if m1 & 0x20 else 'off!'}")
w(MODE2, 0x04)
print(f"[OK] MODE2 = 0x{r(MODE2):02X} (0x04 = totem-pole)")

# 4) 채널 레지스터 왕복 — 1500us = 307 counts
base = LED0 + 4 * CH
w(base, 0, 0, 307 & 0xFF, 307 >> 8)
time.sleep(0.005)
vals = [r(base + i) for i in range(4)]
on  = vals[0] | ((vals[1] & 0x0F) << 8)
off = vals[2] | ((vals[3] & 0x0F) << 8)
print(f"[{'OK' if off == 307 else 'X '}] CH{CH} 레지스터 = {[hex(v) for v in vals]} → ON={on}, OFF={off} (기대 OFF=307)")

if off == 307:
    print("\n>>> I2C 경로는 정상입니다. 지금 CH{}에 1500us(50Hz)가 출력 중입니다.".format(CH))
    print(">>> 서보가 안 움직이면 원인은 통신이 아니라 배선/전원/보드종류입니다.")
    print(">>> 아래를 확인하세요.")
    print("    1. V+ (서보 전원) 5~6V 별도 인가 여부 — 로직 전원만으로는 안 돕니다")
    print("    2. 서보 GND와 PCA9685 GND, Pi GND가 공통인지")
    print("    3. 서보 신호선이 CH{} 헤더의 PWM 핀에 맞게 꽂혔는지 (V+/GND/PWM 순서)".format(CH))
    print("    4. 보드에 3핀 헤더 16줄이 있는지 — 나사 단자만 있으면 서보 드라이버가 아닙니다")
    print("\n>>> 10초간 유지합니다. 서보를 손으로 살짝 돌려보세요.")
    print("    힘으로 버티면 신호가 살아있는 것이고, 힘없이 돌아가면 V+가 없는 것입니다.")
    try:
        time.sleep(10)
    except KeyboardInterrupt:
        pass

w(base, 0, 0, 0, 0x10)
bus.close()
print("\n채널 차단 후 종료")

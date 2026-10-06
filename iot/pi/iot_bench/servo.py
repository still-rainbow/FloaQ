#!/usr/bin/env python3
"""PCA9685(0x60) + MG996R 180° 구동 — Raspberry Pi 5"""

import time
from smbus2 import SMBus

ADDR = 0x60          # i2cdetect 결과
BUS  = 1             # GPIO2/GPIO3
CH   = 0             # PWM 채널

MODE1, MODE2, PRESCALE, LED0 = 0x00, 0x01, 0xFE, 0x06
ALL_LED = 0xFA
AI, SLEEP, RESTART, OUTDRV = 0x20, 0x10, 0x80, 0x04

bus = SMBus(BUS)


def w(reg, *vals):
    bus.write_i2c_block_data(ADDR, reg, list(vals))


def init(freq=50):
    w(ALL_LED, 0, 0, 0, 0x10)                    # 깨우기 전에 전 채널 차단
    w(MODE2, OUTDRV)
    w(MODE1, AI)
    time.sleep(0.005)
    pre = round(25_000_000 / (4096 * freq)) - 1  # 50Hz → 121
    old = bus.read_byte_data(ADDR, MODE1)
    w(MODE1, (old & ~RESTART) | SLEEP)           # PRESCALE은 SLEEP에서만 쓸 수 있다
    w(PRESCALE, pre)
    w(MODE1, old)
    time.sleep(0.005)
    w(MODE1, old | RESTART | AI)


def pulse(ch, us):
    """50Hz·12비트 기준 counts = us × 0.2048"""
    c = max(0, min(4095, round(us * 0.2048)))
    w(LED0 + 4 * ch, 0, 0, c & 0xFF, c >> 8)


def angle(ch, deg):
    """0~180° → 1000~2000us. 실물 가동 범위는 실측해서 조정한다."""
    deg = max(0, min(180, deg))
    pulse(ch, 1000 + deg * 1000 / 180)


def off(ch):
    """채널 완전 차단 — 토크가 걸리지 않는다"""
    w(LED0 + 4 * ch, 0, 0, 0, 0x10)


if __name__ == "__main__":
    init()
    try:
        for deg in (90, 60, 90, 120, 90):
            print(f"{deg}°")
            angle(CH, deg)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n중단")
    finally:
        off(CH)
        bus.close()
        print("차단")

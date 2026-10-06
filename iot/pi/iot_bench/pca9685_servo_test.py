#!/usr/bin/env python3
"""PCA9685 + MG996R(180°) 단독 구동 시험 — Raspberry Pi 5

전제
  - PCA9685 VCC(로직) ← Pi 3.3V, SDA/SCL ← GPIO2/GPIO3, GND 공통
  - PCA9685 V+(서보 전원) ← 별도 5~6V 전원. Pi의 5V/3.3V 핀에서 뽑지 않는다.
  - 서보 혼(팔)은 기구에서 분리한 상태로 시작한다.

사용법
  uv add smbus2
  uv run python pca9685_servo_test.py --scan
  uv run python pca9685_servo_test.py --ch 0 --center
  uv run python pca9685_servo_test.py --ch 0 --sweep --min 1200 --max 1800
  uv run python pca9685_servo_test.py --ch 0 --us 1500
  uv run python pca9685_servo_test.py --ch 0 --off
"""

import argparse
import sys
import time

try:
    from smbus2 import SMBus
except ImportError:
    sys.exit("smbus2 가 없습니다:  uv add smbus2   (또는 pip install smbus2)")

# ── PCA9685 레지스터 ────────────────────────────────────────────
MODE1, MODE2, PRESCALE = 0x00, 0x01, 0xFE
LED0_ON_L = 0x06
ALL_LED_ON_L = 0xFA

RESTART, EXTCLK, AI, SLEEP = 0x80, 0x40, 0x20, 0x10
OUTDRV = 0x04                 # totem-pole 출력
FULL_OFF = 0x1000             # OFF 레지스터 bit12 = 채널 완전 차단

OSC_HZ = 25_000_000           # 내장 오실레이터 공칭값
STEPS = 4096                  # 12비트


class PCA9685:
    def __init__(self, bus: int = 1, addr: int = 0x60):
        self.addr = addr
        self.freq = None
        try:
            self.bus = SMBus(bus)
        except (FileNotFoundError, PermissionError) as e:
            sys.exit(f"/dev/i2c-{bus} 를 열 수 없습니다 ({e}). I2C 활성화와 i2c 그룹 권한을 확인하세요.")

        # 전원 인가 직후 PCA9685는 SLEEP 상태다. 잠든 동안 전 채널을 먼저 끈 뒤 깨운다.
        # 순서를 뒤집으면 이전 세션의 잔여 듀티로 서보가 튈 수 있다.
        self._w(ALL_LED_ON_L, [0x00, 0x00, 0x00, FULL_OFF >> 8])
        self._w8(MODE2, OUTDRV)
        self._w8(MODE1, AI)              # 자동 증가 on, SLEEP 해제
        time.sleep(0.005)

    def _w8(self, reg, val):
        self.bus.write_byte_data(self.addr, reg, val & 0xFF)

    def _w(self, reg, data):
        self.bus.write_i2c_block_data(self.addr, reg, data)

    def _r8(self, reg):
        return self.bus.read_byte_data(self.addr, reg)

    def set_freq(self, hz: float) -> int:
        """PWM 주파수 설정. PRESCALE 변경은 SLEEP 상태에서만 가능하다."""
        prescale = max(3, min(255, round(OSC_HZ / (STEPS * hz)) - 1))
        old = self._r8(MODE1)
        self._w8(MODE1, (old & ~RESTART) | SLEEP)   # 재우기
        self._w8(PRESCALE, prescale)
        self._w8(MODE1, old)                        # 깨우기
        time.sleep(0.005)
        self._w8(MODE1, old | RESTART | AI)
        self.freq = hz
        actual = OSC_HZ / (STEPS * (prescale + 1))
        return prescale, actual

    def set_counts(self, ch: int, on: int, off: int):
        self._w(LED0_ON_L + 4 * ch,
                [on & 0xFF, (on >> 8) & 0x1F, off & 0xFF, (off >> 8) & 0x1F])

    def set_pulse_us(self, ch: int, us: float):
        if self.freq is None:
            raise RuntimeError("set_freq() 를 먼저 호출하세요")
        counts = round(us * STEPS * self.freq / 1_000_000)
        counts = max(0, min(STEPS - 1, counts))
        self.set_counts(ch, 0, counts)
        return counts

    def off(self, ch: int):
        """채널 완전 차단. 서보에 토크가 걸리지 않는다."""
        self.set_counts(ch, 0, FULL_OFF)

    def all_off(self):
        self._w(ALL_LED_ON_L, [0x00, 0x00, 0x00, FULL_OFF >> 8])

    def close(self):
        self.all_off()
        self.bus.close()


def scan(bus_no: int = 1):
    """i2cdetect 없이 파이썬으로 주소 스캔."""
    found = []
    with SMBus(bus_no) as bus:
        for addr in range(0x03, 0x78):
            try:
                bus.read_byte(addr)
                found.append(addr)
            except OSError:
                pass
    print(f"/dev/i2c-{bus_no} 응답 주소: " +
          (", ".join(f"0x{a:02X}" for a in found) if found else "없음"))
    for a in found:
        note = {0x60: "PCA9685 (프로젝트 설정)", 0x70: "PCA9685 All-Call (정상)",
                0x68: "MPU6050 (AD0=L)", 0x69: "MPU6050 (AD0=H)"}.get(a)
        if note:
            print(f"  0x{a:02X}  {note}")
    if 0x60 not in found:
        print("\n0x60 이 없습니다. SDA/SCL 교차, PCA9685 로직 전원, 주소 점퍼를 확인하세요.")
    return found


def main():
    ap = argparse.ArgumentParser(description="PCA9685 + MG996R 시험")
    ap.add_argument("--bus", type=int, default=1, help="I2C 버스 (Pi 5 GPIO2/3 = 1)")
    ap.add_argument("--addr", type=lambda x: int(x, 0), default=0x60,
                    help="PCA9685 I2C 주소 (프로젝트 배선 기본값 0x60)")
    ap.add_argument("--ch", type=int, default=0, help="PWM 채널 0~15")
    ap.add_argument("--freq", type=float, default=50.0, help="PWM 주파수 Hz")
    ap.add_argument("--scan", action="store_true", help="I2C 주소 스캔만")
    ap.add_argument("--center", action="store_true", help="중립(1500us) 유지")
    ap.add_argument("--us", type=float, help="지정 펄스폭(us) 1회 출력")
    ap.add_argument("--sweep", action="store_true", help="min~max 왕복")
    ap.add_argument("--min", type=float, default=1200, help="최소 펄스폭 us")
    ap.add_argument("--max", type=float, default=1800, help="최대 펄스폭 us")
    ap.add_argument("--step", type=float, default=10, help="스텝 us")
    ap.add_argument("--dwell", type=float, default=0.02, help="스텝 간 대기 s")
    ap.add_argument("--off", action="store_true", help="채널 차단 후 종료")
    a = ap.parse_args()

    if a.scan:
        scan(a.bus)
        return

    if not (0 <= a.ch <= 15):
        sys.exit("채널은 0~15")
    if a.min < 500 or a.max > 2500:
        sys.exit("펄스폭은 500~2500us 안에서만. 끝단은 기계적 스톨 구간입니다.")

    pca = PCA9685(a.bus, a.addr)
    prescale, actual = pca.set_freq(a.freq)
    print(f"PCA9685 0x{a.addr:02X} · PRESCALE={prescale} · 실제 약 {actual:.2f} Hz")
    print(f"채널 {a.ch}\n")

    try:
        if a.off:
            pca.off(a.ch)
            print("채널 차단")
            return

        if a.us is not None:
            c = pca.set_pulse_us(a.ch, a.us)
            print(f"{a.us:.0f} us  (counts={c})  — Ctrl+C 로 종료")
            while True:
                time.sleep(1)

        if a.center or not a.sweep:
            c = pca.set_pulse_us(a.ch, 1500)
            print(f"중립 1500 us (counts={c}) 유지 — Ctrl+C 로 종료")
            print("여기서 서보가 떨거나 윙윙거리면 전원 부족입니다. 진행하지 마세요.")
            while True:
                time.sleep(1)

        if a.sweep:
            print(f"왕복 {a.min:.0f} ↔ {a.max:.0f} us, {a.step:.0f} us 스텝")
            print("소리나 발열이 생기면 즉시 Ctrl+C\n")
            pca.set_pulse_us(a.ch, (a.min + a.max) / 2)
            time.sleep(0.5)
            while True:
                for us in list(_frange(a.min, a.max, a.step)) + \
                          list(_frange(a.max, a.min, -a.step)):
                    pca.set_pulse_us(a.ch, us)
                    time.sleep(a.dwell)

    except KeyboardInterrupt:
        print("\n중단")
    finally:
        pca.close()
        print("전 채널 차단 후 종료")


def _frange(start, stop, step):
    v = start
    while (step > 0 and v <= stop) or (step < 0 and v >= stop):
        yield v
        v += step


if __name__ == "__main__":
    main()

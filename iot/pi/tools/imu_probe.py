"""I2C 에 붙은 IMU 가 실제로 대답하는지 본다. **의존성 없다.**

    uv run python tools/imu_probe.py
    uv run python tools/imu_probe.py --addr 0x69 --bus 1 --watch

🔴 `i2cdetect` 에 주소가 보이는 것과 **칩이 살아 있는 것은 다르다.** 주소만 보이고
   WHO_AM_I 가 안 나오는 경우가 있다 — 배선은 닿았는데 전원이 모자라거나, AD0 이
   떠 있어 주소가 흔들리거나, 같은 버스의 다른 칩과 부딪히는 경우다.
   그래서 여기서는 **레지스터를 읽어** 무슨 칩인지까지 말한다.

⚠ 이 도구는 진단만 한다. Pi 운영 경로에는 **IMU 어댑터가 아직 없다** —
  `contracts/pi.py SensorImu` 와 토픽표·sync 는 있는데 발행하는 코드가 없다
  (2026-09-22 전수검사, floaq-229). 여기서 값이 나온다고 화면에 뜨지 않는다.

⚠ MPU6050 은 기본이 **잠자기(sleep)** 다. 깨우지 않으면 가속도가 0 으로만 나온다.
  `--watch` 는 깨운 뒤 읽는다 — 0 이 "안 움직인다" 가 아니라 "안 깨웠다" 인 경우를
  가른다.
"""

from __future__ import annotations

import argparse
import fcntl
import struct
import time

#: `linux/i2c-dev.h`. 이 ioctl 로 이번 파일 핸들이 말 걸 주소를 정한다
I2C_SLAVE = 0x0703

#: WHO_AM_I 가 돌려주는 값 -> 칩 이름. 셋 다 주소가 0x68 이라 눈으로는 구분이 안 된다
WHO_AM_I = 0x75
CHIPS = {
    0x68: "MPU6050",
    0x70: "MPU6500",
    0x71: "MPU9250",
    0x73: "MPU9255",
    0x98: "ICM20600",
    0xAC: "ICM20948",
}

PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B


class I2C:
    """`/dev/i2c-N` 을 그냥 파일로 연다. smbus2 같은 패키지가 없어도 된다."""

    def __init__(self, bus: int, addr: int) -> None:
        self.f = open(f"/dev/i2c-{bus}", "r+b", buffering=0)
        fcntl.ioctl(self.f, I2C_SLAVE, addr)

    def read(self, reg: int, n: int = 1) -> bytes:
        self.f.write(bytes([reg]))
        return self.f.read(n)

    def write(self, reg: int, val: int) -> None:
        self.f.write(bytes([reg, val]))

    def close(self) -> None:
        self.f.close()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bus", type=int, default=1)
    p.add_argument("--addr", default="0x68", help="0x68 또는 0x69 (AD0 이 HIGH 면 0x69)")
    p.add_argument("--watch", action="store_true", help="깨운 뒤 가속도를 계속 읽는다")
    args = p.parse_args()

    addr = int(args.addr, 0)
    try:
        dev = I2C(args.bus, addr)
    except FileNotFoundError:
        print(f"/dev/i2c-{args.bus} 가 없다. raspi-config 에서 I2C 를 켤 것")
        return 1
    except PermissionError:
        print(f"/dev/i2c-{args.bus} 권한 없음.  sudo usermod -aG i2c $USER  후 다시 로그인")
        return 1
    except OSError as e:
        print(f"버스를 못 열었다: {e}")
        return 1

    try:
        who = dev.read(WHO_AM_I)[0]
    except OSError as e:
        # 🔴 i2cdetect 에 보였는데 여기서 죽으면 배선은 닿았고 칩이 대답을 안 하는 것이다
        print(f"0x{addr:02X} 가 대답하지 않는다: {e}")
        print("  전원(3.3V)·SDA·SCL·GND 와 AD0 핀을 볼 것")
        dev.close()
        return 1

    name = CHIPS.get(who, "모르는 칩")
    print(f"i2c-{args.bus} 0x{addr:02X}  WHO_AM_I=0x{who:02X}  {name}")
    if who not in CHIPS:
        print("  ⚠ 아는 값이 아니다. 주소는 맞는데 다른 칩이거나 배선 잡음이다")

    if not args.watch:
        print("\n움직임까지 보려면 --watch")
        dev.close()
        return 0

    # 🔴 MPU 계열은 기본이 잠자기다. 안 깨우면 전부 0 이 나오고, 그게 "고정돼 있다"
    #    처럼 보인다 — 실제로는 칩이 자고 있는 것이다
    dev.write(PWR_MGMT_1, 0x00)
    time.sleep(0.1)
    print("\n깨웠다. Ctrl+C 로 종료")
    try:
        while True:
            raw = dev.read(ACCEL_XOUT_H, 6)
            ax, ay, az = struct.unpack(">hhh", raw)     # 빅엔디안 16비트 셋
            # ±2g 기본 설정에서 16384 LSB/g
            print(f"  accel  x={ax / 16384:+.2f}g  y={ay / 16384:+.2f}g  z={az / 16384:+.2f}g")
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

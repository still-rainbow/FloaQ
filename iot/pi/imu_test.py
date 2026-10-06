import time
from smbus2 import SMBus

BUS_NUMBER = 1
ADDRESS = 0x68

PWR_MGMT_1 = 0x6B
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_XOUT_H = 0x3B
WHO_AM_I = 0x75

GRAVITY = 9.80665


def signed_16(msb: int, lsb: int) -> int:
    value = (msb << 8) | lsb
    return value - 65536 if value & 0x8000 else value


with SMBus(BUS_NUMBER) as bus:
    who_am_i = bus.read_byte_data(ADDRESS, WHO_AM_I)
    print(f"WHO_AM_I: 0x{who_am_i:02X}")

    if who_am_i != 0x68:
        raise RuntimeError(
            f"MPU6050 확인 실패: WHO_AM_I=0x{who_am_i:02X}"
        )

    # 절전 모드 해제
    bus.write_byte_data(ADDRESS, PWR_MGMT_1, 0x00)
    time.sleep(0.1)

    # 약 100Hz 샘플링, 저역통과 필터 활성화
    bus.write_byte_data(ADDRESS, SMPLRT_DIV, 9)
    bus.write_byte_data(ADDRESS, CONFIG, 0x03)

    # 자이로 ±250 deg/s, 가속도 ±2g
    bus.write_byte_data(ADDRESS, GYRO_CONFIG, 0x00)
    bus.write_byte_data(ADDRESS, ACCEL_CONFIG, 0x00)

    print("MPU6050 데이터 수신 시작 — 종료: Ctrl+C")

    try:
        while True:
            data = bus.read_i2c_block_data(
                ADDRESS, ACCEL_XOUT_H, 14
            )

            ax_raw = signed_16(data[0], data[1])
            ay_raw = signed_16(data[2], data[3])
            az_raw = signed_16(data[4], data[5])
            temp_raw = signed_16(data[6], data[7])
            gx_raw = signed_16(data[8], data[9])
            gy_raw = signed_16(data[10], data[11])
            gz_raw = signed_16(data[12], data[13])

            ax = ax_raw / 16384.0 * GRAVITY
            ay = ay_raw / 16384.0 * GRAVITY
            az = az_raw / 16384.0 * GRAVITY

            gx = gx_raw / 131.0
            gy = gy_raw / 131.0
            gz = gz_raw / 131.0

            temperature = temp_raw / 340.0 + 36.53

            print(
                f"t={time.monotonic_ns()} "
                f"acc=({ax:7.3f}, {ay:7.3f}, {az:7.3f}) m/s² "
                f"gyro=({gx:7.3f}, {gy:7.3f}, {gz:7.3f}) deg/s "
                f"temp={temperature:5.1f}°C"
            )

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n종료")

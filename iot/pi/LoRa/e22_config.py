import serial
import time

COMMAND = bytes.fromhex(
    "C0 00 09 00 00 00 62 03 48 13 00 00"
)
EXPECTED = bytes.fromhex(
    "C1 00 09 00 00 00 62 03 48 13 00 00"
)

with serial.Serial("/dev/ttyAMA2", 9600, timeout=2) as port:
    time.sleep(0.5)
    port.reset_input_buffer()
    port.write(COMMAND)
    port.flush()

    response = port.read(12)
    print("응답:", response.hex(" "))

    if response != EXPECTED:
        raise RuntimeError("E22 설정 실패")

print("Pi 측 E22 설정 성공")

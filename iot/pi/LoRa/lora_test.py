import time

import serial


PORT = "/dev/ttyAMA2"
BAUD_RATE = 9600
TEST_COUNT = 20
RESPONSE_TIMEOUT = 6.0


def wait_for_ack(
    lora: serial.Serial,
    expected: bytes,
    timeout: float,
) -> bytes | None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        response = lora.readline().strip()

        if not response:
            continue

        print(f"    RX {response!r}")

        if response == expected:
            return response

        print("    예상하지 않은 패킷이므로 무시")

    return None


def main() -> None:
    success = 0

    with serial.Serial(
        port=PORT,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.2,
        write_timeout=2,
    ) as lora:
        time.sleep(1)
        lora.reset_input_buffer()

        for sequence in range(TEST_COUNT):
            packet = f"PING,{sequence}\n".encode()
            expected = f"ACK,PING,{sequence}".encode()

            print(f"{sequence:03d}: TX {packet!r}")

            started = time.monotonic()

            lora.write(packet)
            lora.flush()

            response = wait_for_ack(
                lora,
                expected,
                RESPONSE_TIMEOUT,
            )

            if response is None:
                print(f"{sequence:03d}: TIMEOUT")
            else:
                rtt_ms = (time.monotonic() - started) * 1000
                success += 1
                print(f"{sequence:03d}: ACK, RTT={rtt_ms:.1f}ms")

            time.sleep(1)

    failed = TEST_COUNT - success
    loss_rate = failed / TEST_COUNT * 100

    print()
    print("===== 시험 결과 =====")
    print(f"송신: {TEST_COUNT}")
    print(f"성공: {success}")
    print(f"실패: {failed}")
    print(f"손실률: {loss_rate:.1f}%")


if __name__ == "__main__":
    main()

"""어느 시리얼 포트로 바이트가 들어오는지 훑는다. **코덱을 안 거친다.**

LoRa 가 조용할 때 제일 먼저 갈라야 하는 것은 "전파가 안 오나" 와 "포트가 틀렸나"
다. 이 도구는 프레임·CRC·ship_tag 를 전부 무시하고 **날바이트만** 센다.

    uv run python tools/uart_scan.py
    uv run python tools/uart_scan.py --seconds 10 --baud 9600

🔴 **Pi 5 는 포트 이름이 함정이다.** `ttyAMA0` 은 GPIO14/15(헤더 8·10번)이고,
   `ttyAMA2` 는 `dtoverlay=uart2` 를 켜야 생기며 **GPIO4/5(헤더 7·29번)** 이다.
   8·10번에 꽂고 ttyAMA2 를 열면 영원히 0 바이트다 — 전파 문제로 오해하기 딱 좋다.
   그래서 하나를 고르는 대신 **전부 훑는다.**

⚠ 이미 다른 프로그램이 포트를 잡고 있으면 못 연다. `main.py` 나 `lora_ab.py` 를
  먼저 끌 것. 콘솔(getty)이 물고 있는 경우도 여기서 드러난다.
"""

from __future__ import annotations

import argparse
import glob
import time

import serial


def candidates() -> list[str]:
    """있을 법한 포트 전부. 없는 이름은 아래에서 걸러진다."""
    found = glob.glob("/dev/ttyAMA*") + glob.glob("/dev/ttyS*") + glob.glob("/dev/ttyUSB*")
    # serial0 은 보통 심볼릭 링크다. 같은 장치를 두 번 읽어도 해가 없다
    return sorted(set(found + ["/dev/serial0"]))


def sniff(port: str, baud: int, seconds: float) -> None:
    try:
        s = serial.Serial(port, baud, timeout=0.3)
    except Exception as e:                      # noqa: BLE001 - 종류가 많고 전부 같은 뜻이다
        print(f"  {port:16} 못 엶: {type(e).__name__}: {e}")
        return

    buf = bytearray()
    end = time.time() + seconds
    try:
        while time.time() < end:
            buf += s.read(256)
    finally:
        s.close()

    if not buf:
        print(f"  {port:16}    0B")
        return

    head = bytes(buf[:24]).hex()
    # ⚠ 프레임 첫 바이트는 0x10 이다(버전 1 << 4 | 종류 0). 그게 보이면 우리 부표다 —
    #   보레이트가 틀리면 바이트는 오는데 이 값이 아니다. 둘을 갈라 준다
    ours = " <- 우리 프레임 같다 (0x10 로 시작)" if buf[0] == 0x10 else ""
    print(f"  {port:16} {len(buf):4d}B  {head}{ours}")


def loopback(port: str, baud: int) -> None:
    """TX 와 RX 를 점퍼로 이은 뒤 부른다. **라디오를 경로에서 뺀다.**

    🔴 "전파가 안 온다" 와 "포트·핀이 틀렸다" 는 증상이 똑같다. 이 시험이 그 둘을
       가른다 — 되돌아오면 포트와 핀은 맞고 문제는 라디오 쪽이다. 안 되돌아오면
       여는 포트가 그 핀이 아니다.

    ⚠ E22 를 뽑고 **Pi 의 TXD 핀과 RXD 핀을 점퍼선으로 직접** 이을 것.
    """
    # 0xAA·0x55 는 비트가 번갈아 서는 값이라 보레이트가 틀리면 바로 깨진다
    probe = bytes([0xAA]) + b"FLOAQ-LOOPBACK" + bytes([0x55])
    try:
        s = serial.Serial(port, baud, timeout=1.0)
    except Exception as e:                      # noqa: BLE001
        print(f"  {port:16} 못 엶: {type(e).__name__}: {e}")
        return
    try:
        s.reset_input_buffer()
        s.write(probe)
        s.flush()
        got = s.read(len(probe))
    finally:
        s.close()
    if got == probe:
        print(f"  {port:16} 되돌아왔다 — 포트·핀 정상. 문제는 라디오 쪽이다")
    elif got:
        print(f"  {port:16} 일부만: {got.hex()} — 보레이트나 접촉 문제")
    else:
        print(f"  {port:16} 안 돌아왔다 — 이 포트는 그 핀이 아니다")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--seconds", type=float, default=4.0, help="포트당 듣는 시간")
    p.add_argument("--port", help="이것만 본다")
    p.add_argument("--loopback", action="store_true",
                   help="TX-RX 를 점퍼로 잇고 실행. 라디오를 빼고 포트·핀만 시험한다")
    args = p.parse_args()

    ports = [args.port] if args.port else candidates()

    if args.loopback:
        print(f"{args.baud} baud 되돌림 시험 — E22 를 뽑고 TXD-RXD 를 점퍼로 이을 것")
        for port in ports:
            loopback(port, args.baud)
        return 0

    print(f"{args.baud} baud, 포트당 {args.seconds:.0f}초")
    for port in ports:
        sniff(port, args.baud, args.seconds)

    print("\n바이트가 나온 포트가 있으면 그걸로:")
    print("  uv run python tools/lora_ab.py b --link serial --port <그 포트> --baud 9600")
    print("전부 0 이면 전파·E22 설정이다 (M0/M1 이 양쪽 다 GND 인지, 채널이 같은지).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

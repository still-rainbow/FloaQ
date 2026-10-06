"""Ebyte E22-900T22D 설정 읽기/쓰기.

아두이노에 `iot/buoy/lora_uart_bridge` 를 올린 상태에서 그 다리를 통해 말한다.
모듈을 USB-UART 로 PC 에 직접 꽂았다면 그것도 그대로 된다.

    python tools\\e22_config.py --port COM9 --read
    python tools\\e22_config.py --port COM9 --channel 71
    python tools\\e22_config.py --port COM9 --power 13

🔴 **설정 모드로 두고 실행해야 한다: M0 = 1, M1 = 1.**
   M0/M1 을 GND 에서 떼어 **3.3V 핀**에 물린다. 5V 가 아니다 — E22 입력은 3.3V 다.
   (M0/M1 은 로직 입력이라 전류가 거의 0 이다. 3.3V 핀의 50mA 상한과 무관하다.)
   전송 모드(M0=0, M1=0)에서는 이 명령들이 무선으로 나가버리고 응답이 없다.

⚠ 설정 모드의 UART 는 모듈 설정과 무관하게 **항상 9600 8N1** 이다.
  평소 통신 속도를 바꿔놨더라도 여기서는 9600 으로 붙는다.

⚠ 아래 디코드 표는 E22-900T22D(SX1262) 기준이다.
  다른 모델은 송신 출력·공기속도 표가 다르다. 손에 있는 모듈 데이터시트와 대조할 것.
"""

from __future__ import annotations

import argparse
import sys
import time

import serial

#: 설정 모드 고정 속도. 모듈 설정값과 무관하다.
CONFIG_BAUD = 9600

#: 850.125 MHz + 채널 = 실제 주파수 (900 시리즈)
FREQ_BASE_MHZ = 850.125
CH_MIN, CH_MAX = 0, 80

# ── 레지스터 디코드 표 ───────────────────────────────────────────────
UART_BAUD = {0: 1200, 1: 2400, 2: 4800, 3: 9600, 4: 19200, 5: 38400, 6: 57600, 7: 115200}
PARITY = {0: "8N1", 1: "8O1", 2: "8E1", 3: "8N1"}
AIR_RATE = {0: "2.4k", 1: "2.4k", 2: "2.4k", 3: "4.8k",
            4: "9.6k", 5: "19.2k", 6: "38.4k", 7: "62.5k"}
SUB_PACKET = {0: 240, 1: 128, 2: 64, 3: 32}
TX_POWER = {0: 22, 1: 17, 2: 13, 3: 10}          # dBm, 22D 기준
POWER_TO_BITS = {v: k for k, v in TX_POWER.items()}


def talk(ser: serial.Serial, frame: bytes, *, expect: int) -> bytes:
    """프레임 하나 보내고 응답을 받는다. AUX 를 안 쓰므로 시간으로 기다린다."""
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()
    time.sleep(0.4)                 # 모듈이 플래시를 건드리므로 넉넉히 준다
    return ser.read(expect)


def read_params(ser: serial.Serial) -> bytes:
    """레지스터 0x00~0x08 을 읽는다. 응답은 `C1 00 09` + 9바이트."""
    resp = talk(ser, bytes([0xC1, 0x00, 0x09]), expect=12)
    if len(resp) < 12:
        raise SystemExit(
            f"응답 없음 또는 짧음 ({len(resp)}바이트: {resp.hex(' ') or '없음'}).\n"
            "  확인할 것:\n"
            "   1) M0 = 3.3V, M1 = 3.3V 인가 (설정 모드). GND 면 응답이 없다\n"
            "   2) E22 TXD -> D10, E22 RXD -> D11 크로스가 맞는가\n"
            "   3) 브리지 스케치가 올라가 있는가 (iot/buoy/lora_uart_bridge)\n"
            "   4) VCC 가 5V 핀인가 (3.3V 핀이면 전류 부족)"
        )
    if resp[0] != 0xC1:
        raise SystemExit(f"머리가 C1 이 아니다: {resp.hex(' ')}")
    return resp[3:12]


def show(p: bytes) -> None:
    addh, addl, netid, reg0, reg1, reg2, reg3 = p[0], p[1], p[2], p[3], p[4], p[5], p[6]
    ch = reg2 & 0x7F
    freq = FREQ_BASE_MHZ + ch

    print(f"  원본        {p.hex(' ')}")
    print(f"  주소        0x{addh:02X}{addl:02X}")
    print(f"  NETID       0x{netid:02X}")
    print(f"  UART        {UART_BAUD[(reg0 >> 5) & 0x07]} {PARITY[(reg0 >> 3) & 0x03]}")
    print(f"  공기속도    {AIR_RATE[reg0 & 0x07]}")
    print(f"  서브패킷    {SUB_PACKET[(reg1 >> 6) & 0x03]} 바이트")
    print(f"  송신출력    {TX_POWER[reg1 & 0x03]} dBm")
    print(f"  채널        {ch}  ->  {freq:.3f} MHz")
    print(f"  RSSI 바이트 {'켬' if reg3 & 0x80 else '끔'}")
    print(f"  전송모드    {'고정' if reg3 & 0x40 else '투명'}")
    print(f"  LBT         {'켬' if reg3 & 0x10 else '끔'}")

    # 한국 920MHz 대역 밖이면 알려준다. 공장 기본값은 대개 밖이다.
    if not (920.0 <= freq <= 923.5):
        print(f"\n  ⚠ {freq:.3f} MHz 는 한국 920MHz 대역 밖이다.")
        print("    링크 시험은 되지만 실제 운용 전에 채널을 바꿔야 한다.")
        print("    예:  --channel 71   ->  921.125 MHz")


def write_reg(ser: serial.Serial, addr: int, value: int) -> None:
    """레지스터 1바이트를 영구 기록(C0). 전원을 꺼도 남는다."""
    resp = talk(ser, bytes([0xC0, addr, 0x01, value]), expect=4)
    if len(resp) < 4 or resp[0] != 0xC1:
        raise SystemExit(f"쓰기 응답 이상: {resp.hex(' ') or '없음'}")
    if resp[3] != value:
        raise SystemExit(f"쓴 값이 안 맞다: 넣은 0x{value:02X}, 돌아온 0x{resp[3]:02X}")


def main() -> int:
    p = argparse.ArgumentParser(description="E22-900T22D 설정 (M0=1, M1=1 설정 모드에서)")
    p.add_argument("--port", required=True, help="COM9, /dev/ttyUSB0")
    p.add_argument("--read", action="store_true", help="현재 설정 읽기")
    p.add_argument("--channel", type=int, help=f"채널 {CH_MIN}~{CH_MAX}. 한국 920MHz 는 71 근처")
    p.add_argument("--power", type=int, choices=sorted(POWER_TO_BITS), help="송신 출력 dBm")
    args = p.parse_args()

    with serial.Serial(args.port, CONFIG_BAUD, timeout=1.0) as ser:
        time.sleep(2)               # Uno 는 포트를 열면 자동 리셋된다. 부트로더 대기

        print("현재 설정")
        before = read_params(ser)
        show(before)

        changed = False
        if args.channel is not None:
            if not CH_MIN <= args.channel <= CH_MAX:
                sys.exit(f"채널은 {CH_MIN}~{CH_MAX}: {args.channel}")
            write_reg(ser, 0x05, args.channel)
            changed = True
        if args.power is not None:
            reg1 = (before[4] & 0xFC) | POWER_TO_BITS[args.power]
            write_reg(ser, 0x04, reg1)
            changed = True

        if changed:
            print("\n바꾼 뒤")
            show(read_params(ser))
            print("\n⚠ 두 모듈 모두 같은 값이어야 한다. 반대쪽에도 같은 명령을 돌릴 것.")
            print("⚠ 끝나면 M0 = GND, M1 = GND 로 되돌려야 통신 모드가 된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

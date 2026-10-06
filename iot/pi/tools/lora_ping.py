"""LoRa 링크 A/B 핑. **모듈 두 개가 서로 닿는지만 본다.**

프레임 규격도, ship_tag 도, CRC 도 없다. 줄 단위 텍스트다.
"전파가 가느냐"와 "얼마나 빠뜨리느냐"만 잰다.

    # 모듈 두 개를 USB-UART 로 꽂고 (투명 전송 모드)
    python tools/lora_ping.py rx --port COM4
    python tools/lora_ping.py tx --port COM3

    # 라디오 없이 배선만 먼저 확인할 때
    python tools/lora_ping.py rx --link udp
    python tools/lora_ping.py tx --link udp

거리 시험
    rx 를 고정해 두고 tx 를 들고 멀어진다. 수신률이 떨어지는 지점이 실효 거리다.
    부표는 배에서 수십~수백 m 떨어진 물 위에 있다 — 지상 시험 거리보다 짧게 나온다.

⚠ 규격 검증이 아니다. 19바이트 프레임 포맷은 `floaq/contracts/lora.py` 와
  `tools/lora_ab.py` 가 따로 본다.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

PORT_UDP = 9311


def open_link(args, *, receiving: bool):
    """줄 단위로 읽고 쓰는 것이면 무엇이든 된다."""
    if args.link == "serial":
        if not args.port:
            sys.exit("--link serial 은 --port 가 필요하다")
        import serial  # noqa: PLC0415

        return serial.Serial(args.port, args.baud, timeout=1.0)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if receiving:
        sock.bind(("0.0.0.0", args.udp_port))
        sock.settimeout(1.0)
    return _UdpAsSerial(sock, ("127.0.0.1", args.udp_port))


class _UdpAsSerial:
    """UDP 를 시리얼처럼. 라디오 없이 도구 자체를 확인할 때만 쓴다."""

    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer

    def write(self, data: bytes) -> None:
        self.sock.sendto(data, self.peer)

    def readline(self) -> bytes:
        try:
            return self.sock.recvfrom(256)[0]
        except socket.timeout:
            return b""

    def close(self) -> None:
        self.sock.close()


def run_tx(args) -> int:
    link = open_link(args, receiving=False)
    print(f"TX  {args.link}  {args.period}s 주기.  Ctrl+C 로 종료\n")
    n = 0
    try:
        while args.count == 0 or n < args.count:
            line = f"PING {n:06d} {time.time():.3f}\n".encode()
            link.write(line)
            print(f"  -> {line.decode().strip()}")
            n += 1
            time.sleep(args.period)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


def run_rx(args) -> int:
    link = open_link(args, receiving=True)
    print(f"RX  {args.link}  Ctrl+C 로 종료\n")
    got = lost = junk = 0
    prev: int | None = None
    try:
        while True:
            raw = link.readline()
            if not raw:
                continue
            text = raw.decode("utf-8", "replace").strip()
            parts = text.split()
            # 깨진 줄은 세기만 한다. 전파가 약하면 이게 늘어난다.
            # 4번째 칸은 RSSI — 아두이노 수신 스케치가 붙여 보낸다. 없어도 된다.
            if len(parts) not in (3, 4) or parts[0] != "PING":
                junk += 1
                print(f"  ?? {text!r}")
                continue

            n = int(parts[1])
            rssi = parts[3] if len(parts) == 4 else None
            if prev is not None and n > prev + 1:
                lost += n - prev - 1
                print(f"  ** 유실 {n - prev - 1}개 ({prev} -> {n})")
            prev = n
            got += 1

            # ⚠ 송신이 아두이노면 시계 기준이 달라 지연이 의미 없다 (millis() 는 부팅 후 ms).
            #   말이 되는 값일 때만 보여준다.
            delay_ms = (time.time() - float(parts[2])) * 1000
            shown = f"지연 {delay_ms:6.1f}ms" if abs(delay_ms) < 60_000 else "지연   -   "
            print(f"  <- {n:06d}  {shown}" + (f"  RSSI {rssi}dBm" if rssi else ""))

            if got % args.stats_every == 0:
                _stats(got, lost, junk)
    except KeyboardInterrupt:
        pass
    finally:
        _stats(got, lost, junk)
        link.close()
    return 0


def _stats(got, lost, junk):
    total = got + lost
    print(f"\n  수신 {got}  유실 {lost}  깨짐 {junk}  "
          f"수신률 {(got / total * 100) if total else 0:.1f}%\n")


def main() -> int:
    p = argparse.ArgumentParser(description="LoRa 링크 A/B 핑")
    p.add_argument("role", choices=["tx", "rx"])
    p.add_argument("--link", choices=["serial", "udp"], default="serial")
    p.add_argument("--port", help="COM3, /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--udp-port", type=int, default=PORT_UDP)
    p.add_argument("--period", type=float, default=1.0)
    p.add_argument("--count", type=int, default=0, help="tx: 이만큼 보내고 종료. 0 이면 무한")
    p.add_argument("--stats-every", type=int, default=20)
    args = p.parse_args()
    return run_tx(args) if args.role == "tx" else run_rx(args)


if __name__ == "__main__":
    sys.exit(main())

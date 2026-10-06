"""해안국 역할. 조난 확인응답(Distress acknowledgement)을 UDP 로 보낸다.

실제로는 해경·RCC 의 해안국이 VHF Ch70 에서 보낸다. 우리 쪽에 무전기가 없으니
그 자리를 이 도구가 대신한다. 받은 Pi 는 **DSC 채널만** 멈추고 AIS 두 채널은
계속 쏜다 — 구조가 끝난 게 아니라 신고가 접수된 것뿐이기 때문이다.

    # 들어오는 조난 경보를 지켜보다 자동으로 응답
    python tools\\coastguard_ack.py --watch

    # 특정 배에 바로 응답
    python tools\\coastguard_ack.py --distress-mmsi 440123456 --once

Table 4.2 (VHF RT) 배치:
    116(전선박) · 112(조난) · 해안국 MMSI · 110(확인응답) · 조난선 MMSI
    · 조난성격 · 좌표 · UTC · 100 · EOS 127 · ECC

🔴 **실제 조난 통신이 아니다.** 해안국을 사칭하는 신호를 실제 무선으로 내보내면
   불법이다. 사내망 UDP 확인용까지만 쓴다.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters import nmea, report
from floaq.protocols import dsc

#: 해안국 MMSI 는 00 으로 시작한다 (00MIDxxxx). 440 = 대한민국 MID.
DEFAULT_COAST_MMSI = "004401001"


def build_ack(args, *, distress_mmsi: str, nature: int,
              lat: float | None, lon: float | None) -> str:
    utc = time.gmtime()
    return nmea.coastguard_acknowledgement(
        coast_mmsi=args.coast_mmsi, distress_mmsi=distress_mmsi,
        nature=nature, lat=lat, lon=lon,
        hour=utc.tm_hour, minute=utc.tm_min)


def send(sock, args, line: str) -> None:
    sock.sendto(line.encode("ascii"), (args.host, args.port))
    print(f"  -> {line.strip()}")


def watch(sock, args) -> int:
    """조난 경보를 기다렸다가 자동으로 응답한다. 해안국 자동 접수를 흉내낸다."""
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("0.0.0.0", args.listen_port))
    rx.settimeout(1.0)
    print(f"조난 경보 대기  0.0.0.0:{args.listen_port}")
    print(f"해안국 MMSI  {args.coast_mmsi}")
    print(f"응답 지연    {args.delay}초 뒤\n")

    answered: set[str] = set()
    try:
        while True:
            try:
                data, _ = rx.recvfrom(4096)
            except socket.timeout:
                continue
            for line in data.decode("ascii", "replace").splitlines():
                p = nmea.parse_dsc(line)
                if p is None:
                    continue
                # 조난 경보(112)만 응답한다. 확인응답에 또 응답하면 무한히 돈다.
                if p.format_specifier != dsc.Format.DISTRESS:
                    continue
                if p.sender_mmsi in answered:
                    continue
                answered.add(p.sender_mmsi)
                nature = p.nature if p.nature is not None else int(dsc.Nature.UNDESIGNATED)
                known = {int(n) for n in dsc.Nature}
                label = dsc.Nature(nature).name if nature in known else "?"
                print(f"조난 경보 수신: MMSI {p.sender_mmsi}  성격 {nature} ({label})")
                time.sleep(args.delay)
                send(sock, args, build_ack(args, distress_mmsi=p.sender_mmsi,
                                           nature=nature, lat=args.lat, lon=args.lon))
    except KeyboardInterrupt:
        pass
    finally:
        rx.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="해안국 조난 확인응답 (시뮬레이션)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=report.NMEA_UDP_PORT)
    p.add_argument("--listen-port", type=int, default=report.NMEA_UDP_PORT)
    p.add_argument("--coast-mmsi", default=DEFAULT_COAST_MMSI,
                   help="해안국 MMSI. 00 으로 시작한다")
    p.add_argument("--distress-mmsi", default="440123456", help="조난선 MMSI")
    p.add_argument("--nature", type=int, default=int(dsc.Nature.MAN_OVERBOARD))
    p.add_argument("--lat", type=float, default=35.1234567)
    p.add_argument("--lon", type=float, default=129.7654321)
    p.add_argument("--watch", action="store_true", help="조난 경보를 기다렸다 자동 응답")
    p.add_argument("--delay", type=float, default=2.0, help="--watch 에서 응답까지 지연")
    p.add_argument("--once", action="store_true", help="한 번 보내고 끝")
    p.add_argument("--print-only", action="store_true")
    args = p.parse_args()

    line = build_ack(args, distress_mmsi=args.distress_mmsi, nature=args.nature,
                     lat=args.lat, lon=args.lon)
    if args.print_only:
        print(line.strip())
        return 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        if args.watch:
            return watch(sock, args)
        print(f"해안국 {args.coast_mmsi} -> 조난선 {args.distress_mmsi}")
        send(sock, args, line)
        if not args.once:
            while True:
                time.sleep(10)
                send(sock, args, line)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

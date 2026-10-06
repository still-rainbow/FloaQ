"""조난 신고를 UDP 로 내보낸다. OpenCPN 등 항해 소프트웨어 확인용.

    python tools\\distress_send.py --host 127.0.0.1 --once
    python tools\\distress_send.py --host 192.168.0.50 --lat 35.1 --lon 129.0
    python tools\\distress_send.py --print-only          전송 없이 문장만 본다

OpenCPN 설정
    Options > Connections > Add Connection > Network
    Protocol  UDP
    Address   0.0.0.0        (모든 인터페이스에서 수신)
    DataPort  10110          (NMEA 0183 over TCP/UDP 의 IETF 할당 포트)

    표적은 AIS 표적 목록에 뜬다. DSC 조난은 목록 맨 위에 고정된다.

🔴 **실제 조난 신고가 아니다.** 전파가 나가지 않으며 형식 승인된 GMDSS 장비를
   대신할 수 없다. 목적지를 반드시 확인할 것 — 사내망 밖으로 보내면 남의 해도에
   허위 조난 표적이 뜬다. 기본값을 브로드캐스트가 아니라 루프백으로 둔 이유다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters import nmea, report
from floaq.protocols import ais, dsc


def build(args) -> list[tuple[str, tuple[str, ...]]]:
    utc = time.gmtime()
    mob = report.device_mmsi(args.mmsi, ais.MMSI_PREFIX_MOB)
    sart = report.device_mmsi(args.mmsi, ais.MMSI_PREFIX_SART)
    return [
        ("DSC 조난경보", nmea.dsc_distress_sentences(
            mmsi=args.mmsi, nature=args.nature, lat=args.lat, lon=args.lon,
            hour=utc.tm_hour, minute=utc.tm_min)),
        ("AIS-MOB", nmea.ais_mob_sentences(
            mmsi=mob, lat=args.lat, lon=args.lon,
            second=utc.tm_sec, with_text=True)),
        ("AIS-SART", nmea.ais_sart_sentences(
            mmsi=sart, lat=args.lat, lon=args.lon,
            second=utc.tm_sec, with_text=True)),
    ]


def show_symbols(args) -> None:
    """무선에 실릴 M.493 심볼도 같이 보여준다. NMEA 는 그 위의 형식일 뿐이다."""
    utc = time.gmtime()
    call = dsc.distress_alert(mmsi=args.mmsi, nature=args.nature,
                              lat=args.lat, lon=args.lon,
                              hour=utc.tm_hour, minute=utc.tm_min)
    print("── ITU-R M.493 심볼 ──")
    print(f"  정보문자 {list(call.information)}")
    print(f"  ECC      {call.ecc}")
    syms = call.symbols()
    print(f"  전체     {len(syms)} 심볼 = {len(syms) * 10} 비트 (점패턴 제외)")
    print(f"  {syms}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="조난 신고 UDP 송출 (시뮬레이션)")
    p.add_argument("--host", default="127.0.0.1",
                   help="목적지. 기본은 루프백. 다른 PC 면 그 주소, 전체는 255.255.255.255")
    p.add_argument("--port", type=int, default=report.NMEA_UDP_PORT)
    p.add_argument("--mmsi", default="440123456", help="선박 MMSI 9자리")
    p.add_argument("--lat", type=float, default=35.1234567)
    p.add_argument("--lon", type=float, default=129.7654321)
    p.add_argument("--nature", type=int, default=int(dsc.Nature.MAN_OVERBOARD),
                   help="ITU-R M.493 조난성격 (110=익수자, 101=침수, 100=화재)")
    p.add_argument("--once", action="store_true", help="한 번만 보내고 끝낸다")
    p.add_argument("--period", type=float, default=8.0, help="반복 주기(초)")
    p.add_argument("--print-only", action="store_true", help="전송하지 않고 문장만 출력")
    p.add_argument("--symbols", action="store_true", help="M.493 심볼도 출력")
    args = p.parse_args()

    if args.nature not in {int(n) for n in dsc.Nature}:
        sys.exit(f"모르는 조난성격 {args.nature}. Table 3 값이어야 한다")

    if args.symbols:
        show_symbols(args)

    groups = build(args)
    for label, lines in groups:
        print(f"── {label} ──")
        for ln in lines:
            print(" ", ln.strip())
    print()

    if args.print_only:
        return 0

    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    payload = "".join(ln for _, lines in groups for ln in lines).encode("ascii")

    print(f"송신 -> {args.host}:{args.port}  ({len(payload)} bytes)")
    if not args.once:
        print(f"{args.period}초마다 반복. Ctrl+C 로 종료")
    n = 0
    try:
        while True:
            # 좌표를 조금씩 흘려 표류를 흉내낸다. 해도에서 표적이 움직인다
            args.lat -= 0.00002 * n
            args.lon += 0.00002 * n
            payload = "".join(
                ln for _, lines in build(args) for ln in lines).encode("ascii")
            sock.sendto(payload, (args.host, args.port))
            n += 1
            print(f"  {n:4d} 회  {args.lat:.6f}, {args.lon:.6f}")
            if args.once:
                break
            time.sleep(args.period)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

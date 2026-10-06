"""LoRa A/B 링크 검증 도구. **간섭·다중 부표는 범위 밖이다. 링크만 본다.**

A = 부표 역할(송신), B = Pi 역할(수신). 같은 코덱(`floaq.contracts.lora`)을 양쪽이 쓴다.

    # 라디오 없이 (같은 PC 에서 두 창)
    python tools/lora_ab.py b --link udp
    python tools/lora_ab.py a --link udp --ship-id demo-ship

    # 실물 라디오가 오면 링크만 바꾼다. 코덱·통계는 그대로다
    python tools/lora_ab.py b --link serial --port /dev/ttyUSB0 --baud 9600
    python tools/lora_ab.py a --link serial --port COM3

검증하는 것
    프레임이 19바이트로 정확히 오가는가
    CRC 가 실제 오류를 잡는가
    seq 구멍으로 유실률이 측정되는가
    ship_tag 로 남의 배 부표가 걸러지는가

⚠ 이건 **검증 도구**다. 운영 경로가 아니다.
  실제 수신은 `adapters/lora.py` 가 `ports.BuoyLink` 구현으로 한다.
"""

from __future__ import annotations

import argparse
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.contracts.lora import (
    FRAME_LEN, BuoyFrame, LoraFrameError, seq_gap, ship_tag, unpack,
)
# 🔴 경계 판정은 운영 경로와 **같은 함수**를 쓴다. 도구가 따로 판정하면
#    도구에서만 나는 버그가 생긴다 — 실제로 그랬다 (아래 SerialLink.recv 참고)
from floaq.adapters.lora import _looks_like_frame

#: 시리얼 링크 전용 동기 워드. UDP 는 데이터그램 자체가 프레임 경계라 필요 없다.
#:
#: ⚠ 실제 라디오 모듈은 자기 프레이밍을 갖는다 — SX127x explicit header 에 길이와 CRC 가
#:   들어 있고, AT 모듈은 모듈 프로토콜이 감싼다. 이 동기 워드는 **테스트 하네스가
#:   생 UART 로 붙었을 때**만 쓴다. 규격의 일부가 아니다.
#:
#: 🔴 **A 가 보낼 때만 붙인다. 받을 때는 기대하지 않는다.** 실물 부표
#:    (`buoy_tx.ino`)는 19바이트를 그대로 쏜다 — 받는 쪽이 이걸 찾으면 전부 버린다.
SYNC = b"\xaa\x55"

#: 송신 주기와 지터. 정확히 1.000초면 두 부표가 한 번 겹친 뒤 계속 겹친다.
TX_PERIOD_SEC = 1.0
TX_JITTER_SEC = 0.05


# ── 링크 ─────────────────────────────────────────────────────────────
class UdpLink:
    """라디오 없이 도는 링크. 코덱과 통계 로직을 먼저 굳히려고 둔다."""

    def __init__(self, *, bind: int | None = None, peer: tuple[str, int] | None = None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer = peer
        if bind is not None:
            self.sock.bind(("0.0.0.0", bind))
            self.sock.settimeout(1.0)

    def send(self, raw: bytes) -> None:
        self.sock.sendto(raw, self.peer)

    def recv(self) -> tuple[bytes, float | None] | None:
        """(프레임, rssi). UDP 는 RSSI 가 없어 None 이다."""
        try:
            data, _ = self.sock.recvfrom(256)
        except socket.timeout:
            return None
        return data, None

    def close(self) -> None:
        self.sock.close()


class SerialLink:
    """생 UART 링크. **보낼 때만** 동기 워드를 붙이고, 받을 때는 CRC 로 경계를 잡는다.

    ⚠ pyserial 을 여기서만 import 한다. UDP 로만 쓸 때 설치를 강요하지 않는다.
    """

    def __init__(self, port: str, baud: int):
        import serial  # noqa: PLC0415

        self.ser = serial.Serial(port, baud, timeout=1.0)
        self._buf = bytearray()

    def send(self, raw: bytes) -> None:
        self.ser.write(SYNC + raw)

    def recv(self) -> tuple[bytes, float | None] | None:
        """CRC 로 경계를 잡는다. **동기 워드를 기대하지 않는다.**

        🔴 전에는 `find(SYNC)` 로 0xAA55 를 찾았다. 이 도구의 A 역할끼리는 맞지만
           **실물 부표는 동기 워드를 안 붙인다** — 19바이트를 그대로 쏜다
           (`buoy_tx.ino`). 그래서 전파가 멀쩡히 들어오는데 전부 버려졌고,
           `!! 버림` 조차 안 찍혀 "수신 0" 으로만 보였다. `uart_scan.py` 는
           바이트를 보는데 여기만 조용한 상태였다 (2026-09-22 실기에서 확인).

        운영 경로와 **같은 함수**(`adapters.lora._looks_like_frame`)를 쓴다 —
        창을 한 바이트씩 밀며 CRC 와 버전 니블이 맞는 자리를 찾는다.
        """
        self._buf.extend(self.ser.read(64) or b"")
        # ⚠ 상한. 잡음만 들어오면 버퍼가 무한히 자란다
        if len(self._buf) > 1024:
            del self._buf[:-FRAME_LEN]

        while len(self._buf) >= FRAME_LEN:
            if _looks_like_frame(self._buf):
                raw = bytes(self._buf[:FRAME_LEN])
                del self._buf[:FRAME_LEN]
                return raw, None
            del self._buf[:1]          # 경계가 아니다. 한 바이트 버리고 다시
        return None

    def close(self) -> None:
        self.ser.close()


def build_link(args, *, receiving: bool):
    if args.link == "serial":
        if not args.port:
            sys.exit("--link serial 은 --port 가 필요하다")
        return SerialLink(args.port, args.baud)
    if receiving:
        return UdpLink(bind=args.udp_port)
    return UdpLink(peer=(args.udp_host, args.udp_port))


# ── A: 부표 역할 ─────────────────────────────────────────────────────
def run_sender(args) -> int:
    link = build_link(args, receiving=False)
    tag = ship_tag(args.ship_id)
    lat, lon = args.lat, args.lon
    seq = 0                     # 전원 인가 시 0 부터. 실물 부표도 같다

    print(f"A(부표)  ship_tag=0x{tag:02X}  {args.link}  {TX_PERIOD_SEC}s +- {TX_JITTER_SEC}s")
    print("Ctrl+C 로 종료\n")
    try:
        while args.count == 0 or seq < args.count:
            # 표류를 흉내낸다. 초당 약 0.5m 남동쪽
            lat -= 0.0000045
            lon += 0.0000055
            f = BuoyFrame(
                ship_tag=tag,
                seq=seq,
                lat=lat,
                lon=lon,
                measured_at=int(time.time()),
                # 익수자가 부표를 잡았나. 🔴 이 한 비트가 프레임에서 제일 중요하다 —
                # 좌표는 부표 위치만 말하고, 사람이 거기 있는지는 이 값만 말한다
                is_pressed=args.pressed,
                gps_fix=True,
                battery=3,
            )
            raw = f.pack()
            # --drop 으로 유실을 흉내낸다. B 의 seq 구멍 집계가 맞는지 확인용이다
            if random.random() >= args.drop:
                link.send(raw)
            print(f"  TX seq={seq:5d}  {lat:.7f},{lon:.7f}  {len(raw)}B  {raw.hex()}")
            seq = (seq + 1) & 0xFFFF
            time.sleep(TX_PERIOD_SEC + random.uniform(-TX_JITTER_SEC, TX_JITTER_SEC))
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


# ── B: Pi 역할 ───────────────────────────────────────────────────────
def run_receiver(args) -> int:
    link = build_link(args, receiving=True)
    want = ship_tag(args.ship_id) if args.ship_id else None

    got = lost = bad_crc = bad_other = foreign = 0
    prev_seq: int | None = None
    started = time.time()

    filt = f"ship_tag=0x{want:02X} 만 수용" if want is not None else "ship_tag 필터 없음"
    print(f"B(Pi)  {args.link}  {filt}")
    print("Ctrl+C 로 종료\n")
    try:
        while True:
            item = link.recv()
            if item is None:
                continue
            raw, rssi = item
            try:
                f = unpack(raw)
            except LoraFrameError as e:
                # 실패해도 죽지 않는다. 운영 경로(adapters/lora.py)도 같은 규칙이다
                if "CRC" in str(e):
                    bad_crc += 1
                else:
                    bad_other += 1
                print(f"  !! 버림: {e}")
                continue

            # 남의 배 부표. 깨끗하게 수신되고 CRC 도 통과하므로 여기서만 걸러진다.
            # 이걸 안 하면 남의 익수자 위치가 우리 사고에 기록된다.
            if want is not None and f.ship_tag != want:
                foreign += 1
                print(f"  -- 남의 배: ship_tag=0x{f.ship_tag:02X}")
                continue

            if prev_seq is not None:
                gap = seq_gap(prev_seq, f.seq)
                if gap:
                    lost += gap
                    print(f"  ** 유실 {gap}개 (seq {prev_seq} -> {f.seq})")
            prev_seq = f.seq
            got += 1

            age = int(time.time()) - f.measured_at
            rssi_s = f"{rssi:.0f}dBm" if rssi is not None else "  -   "
            # 🔴 `is_pressed` 를 반드시 찍는다. 익수자가 부표를 **잡았는가**가 이
            #    프레임에서 제일 중요한 한 비트다 — 좌표는 부표가 어디 있는지만
            #    말하고, 사람이 거기 있는지는 이 값만 말한다.
            #    ⚠ 0 이 "사람 없음" 은 아니다 (E9). 잡지 못한 채 떠 있을 수 있다.
            grab = "잡음" if f.is_pressed else "  - "
            print(f"  RX seq={f.seq:5d}  {f.lat:.7f},{f.lon:.7f}  [{grab}] "
                  f"bat={f.battery} fix={int(f.gps_fix)} 지연={age}s  {rssi_s}")

            if got % args.stats_every == 0:
                _print_stats(got, lost, bad_crc, bad_other, foreign, started)
    except KeyboardInterrupt:
        pass
    finally:
        _print_stats(got, lost, bad_crc, bad_other, foreign, started)
        link.close()
    return 0


def _print_stats(got, lost, bad_crc, bad_other, foreign, started):
    total = got + lost
    rate = (got / total * 100) if total else 0.0
    print(f"\n  -- 누적 {time.time() - started:.0f}s --")
    print(f"  수신 {got}  유실 {lost}  수신률 {rate:.1f}%")
    print(f"  CRC 오류 {bad_crc}  기타 거부 {bad_other}  남의 배 {foreign}\n")


# ── 진입점 ───────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="LoRa A/B 링크 검증")
    p.add_argument("role", choices=["a", "b"], help="a=부표(송신), b=Pi(수신)")
    p.add_argument("--link", choices=["udp", "serial"], default="udp")
    # 🔴 B(수신)의 기본값을 빈 문자열로 둔다. 전에는 "demo-ship" 이라, 실물 부표를
    #    붙이면 그 배의 ship_tag 와 안 맞아 **모든 프레임이 "남의 배" 로 걸러졌다.**
    #    전파는 멀쩡히 오는데 화면에 아무것도 안 떠서 배선·안테나를 의심하게 된다.
    #    A(송신)는 태그를 만들어야 하므로 아래에서 기본값을 채운다.
    p.add_argument("--ship-id", default="",
                   help="ship_tag. A 는 필수(기본 demo-ship), B 는 비우면 필터 없음")
    p.add_argument("--port", help="시리얼 포트 (COM3, /dev/ttyUSB0)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--udp-host", default="127.0.0.1")
    p.add_argument("--udp-port", type=int, default=9310)
    p.add_argument("--lat", type=float, default=35.1234567)
    p.add_argument("--lon", type=float, default=129.7654321)
    p.add_argument("--count", type=int, default=0, help="A: 이만큼 보내고 종료. 0 이면 무한")
    p.add_argument("--drop", type=float, default=0.0,
                   help="A: 이 확률로 송신을 건너뛴다. B 의 유실 집계 확인용")
    p.add_argument("--pressed", action="store_true",
                   help="A: is_pressed=1 로 보낸다. 실물 부표 없이 버튼 경로를 본다")
    p.add_argument("--stats-every", type=int, default=20)
    args = p.parse_args()

    # A 는 ship_tag 를 만들어야 한다. 비었으면 예전 기본값을 그대로 쓴다 —
    # B 만 "필터 없음" 이 기본이고, A 는 태그 없이 프레임을 만들 수 없다
    if args.role == "a" and not args.ship_id:
        args.ship_id = "demo-ship"
    return run_sender(args) if args.role == "a" else run_receiver(args)


if __name__ == "__main__":
    sys.exit(main())

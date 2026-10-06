"""LoRa 프레임 코덱 테스트. **라디오 없이 돈다.**

실물 모듈이 오기 전에 확정할 수 있는 건 전부 여기서 확정한다.
포맷이 틀린 채로 부표 펌웨어를 구우면 되돌리는 비용이 크다.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.contracts.lora import (
    COORD_SCALE, FRAME_LEN, LORA_VERSION, BadCrc, BadLength, BadValue, BuoyFrame,
    UnknownVersion, crc16_ccitt, seq_gap, ship_tag, unpack,
)

T0 = 1_757_000_000


def frame(**kw) -> BuoyFrame:
    base = dict(ship_tag=0xAB, seq=1, lat=35.1234567, lon=129.7654321, measured_at=T0)
    return BuoyFrame(**{**base, **kw})


# ── 크기 ─────────────────────────────────────────────────────────────
def test_frame_is_exactly_19_bytes():
    """16~19바이트가 SF7 에서 같은 38심볼이다. 20바이트로 넘어가면 airtime 이 10% 는다."""
    assert len(frame().pack()) == FRAME_LEN == 19


def test_no_alignment_padding():
    """빅엔디안 명시(`>`)라 패딩이 없다. 네이티브 `@` 였으면 MCU 와 어긋난다."""
    assert struct.calcsize(">BBHiiIBH") == 19


# ── 왕복 ─────────────────────────────────────────────────────────────
def test_roundtrip_preserves_everything():
    f = frame(is_pressed=True, gps_fix=False, battery=1, seq=40000)
    assert unpack(f.pack()) == f


def test_coordinate_precision_is_centimeter():
    """int32 * 1e-7. float32 였으면 경도 129도대에서 약 1m 오차가 난다."""
    f = frame(lat=35.1234567, lon=129.7654321)
    got = unpack(f.pack())
    assert abs(got.lat - 35.1234567) < 1e-7
    assert abs(got.lon - 129.7654321) < 1e-7


@pytest.mark.parametrize("lat,lon", [(90, 180), (-90, -180), (0, 0)])
def test_coordinate_extremes_fit_in_int32(lat, lon):
    """lat 90 -> 900_000_000, lon 180 -> 1_800_000_000. int32 상한 2_147_483_647 안이다."""
    assert unpack(frame(lat=lat, lon=lon).pack()) == frame(lat=lat, lon=lon)
    assert abs(lon * COORD_SCALE) <= 2_147_483_647


# ── 거부 ─────────────────────────────────────────────────────────────
def test_short_frame_rejected():
    with pytest.raises(BadLength):
        unpack(frame().pack()[:-1])


def test_single_bit_flip_caught_by_crc():
    raw = bytearray(frame().pack())
    raw[5] ^= 0x01
    with pytest.raises(BadCrc):
        unpack(bytes(raw))


def test_unknown_version_rejected_not_crashed():
    """부표만 먼저 업데이트된 경우. 죽지 않고 예외로 알린다."""
    f = frame()
    body = bytearray(f.pack()[:17])
    body[0] = ((LORA_VERSION + 1) << 4) | 0
    raw = bytes(body) + struct.pack(">H", crc16_ccitt(bytes(body)))
    with pytest.raises(UnknownVersion):
        unpack(raw)


def test_out_of_range_coordinate_rejected_even_with_valid_crc():
    """CRC 가 통과해도 값이 틀릴 수 있다. 송신 GPS 가 이상한 값을 낸 경우다."""
    body = struct.pack(">BBHiiIB", (LORA_VERSION << 4), 0xAB, 1,
                       91 * COORD_SCALE, 0, T0, 0)
    raw = body + struct.pack(">H", crc16_ccitt(body))
    with pytest.raises(BadValue):
        unpack(raw)


def test_pack_rejects_bad_battery():
    with pytest.raises(BadValue):
        frame(battery=4).pack()


# ── ship_tag ─────────────────────────────────────────────────────────
def test_ship_tag_is_stable_across_processes():
    """🔴 내장 hash() 를 쓰면 PYTHONHASHSEED 때문에 재시작마다 값이 바뀐다.

    부표 펌웨어에 박아야 하는 값이라 안정성이 필수다. sha256 첫 바이트를 쓴다.
    """
    import subprocess
    code = ("import sys; sys.path.insert(0,'.');"
            "from floaq.contracts.lora import ship_tag; print(ship_tag('ship-xyz'))")
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parents[1])).stdout.strip()
            for _ in range(3)}
    assert len(outs) == 1
    assert outs.pop() == str(ship_tag("ship-xyz"))


def test_ship_tag_is_one_byte():
    assert all(0 <= ship_tag(f"ship-{i}") <= 0xFF for i in range(50))


# ── seq ──────────────────────────────────────────────────────────────
def test_seq_gap_counts_losses():
    assert seq_gap(10, 11) == 0
    assert seq_gap(10, 14) == 3


def test_seq_gap_handles_uint16_wrap():
    """18.2시간마다 순환한다. 순환을 못 다루면 유실률이 65535 로 튄다."""
    assert seq_gap(65535, 0) == 0
    assert seq_gap(65534, 2) == 3


def test_seq_wraps_on_pack():
    assert unpack(frame(seq=65536).pack()).seq == 0


# ── 부표 펌웨어와의 대조 ─────────────────────────────────────────────
#: `iot/buoy/buoy_tx/buoy_tx.ino` 의 selftest 가 쓰는 것과 **같은 벡터**다.
#: 부표는 아두이노(AVR)라 같은 코드를 공유할 수 없다 — 벡터로만 묶인다.
FIRMWARE_VECTOR = bytes.fromhex(
    "10 c9 0007 14e434a0 4cf318c0 6aa1f940 0f d721".replace(" ", ""))


def test_matches_the_arduino_firmware_vector():
    """🔴 이게 깨지면 `buoy_tx.ino` 도 같이 고쳐야 한다.

    부표 펌웨어는 C 로 바이트를 직접 채운다. 코덱이 조용히 바뀌면 부표만 옛 포맷으로
    쏘게 되고, Pi 는 CRC 나 버전에서 **전부 버린다** — 로그에는 카운터만 오른다.
    같은 벡터를 양쪽에 박아 그 갈라짐을 여기서 잡는다.

    갈라졌을 때 고칠 곳:
        iot/buoy/buoy_tx/buoy_tx.ino  의 build_frame() 과 selftest() 상수
    """
    got = BuoyFrame(ship_tag=0xC9, seq=7, lat=35.05, lon=129.10,
                    measured_at=1_789_000_000, is_pressed=True,
                    gps_fix=True, battery=3).pack()
    assert got == FIRMWARE_VECTOR, (
        f"코덱이 바뀌었다. buoy_tx.ino 의 selftest 벡터도 {got.hex(' ')} 로 고칠 것")


def test_firmware_vector_round_trips():
    f = unpack(FIRMWARE_VECTOR)
    assert (f.ship_tag, f.seq, f.battery) == (0xC9, 7, 3)
    assert f.is_pressed and f.gps_fix
    assert f.lat == pytest.approx(35.05) and f.lon == pytest.approx(129.10)


def test_ccitt_false_standard_check_value():
    """표준 검사값. 펌웨어 selftest 가 같은 값을 확인한다 — 다른 언어로 다시 구현하는
    쪽이 CRC 변종(CCITT-TRUE, XMODEM)을 잡기 쉬워서 못 박는다."""
    assert crc16_ccitt(b"123456789") == 0x29B1

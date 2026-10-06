"""LoRa 수신 어댑터 시험. **여기서 보는 건 코덱이 아니라 프레이밍이다.**

코덱은 `test_lora_codec.py` 가 본다. 이쪽은 "UART 바이트 흐름에서 19바이트 경계를
어떻게 찾는가" — 실물에서만 드러나고 UDP·가짜로는 절대 안 드러나는 부분이다.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.adapters import lora
from floaq.contracts.lora import FRAME_LEN, BuoyFrame, unpack

TAG = 0xC9
T0 = 1_757_000_000


def frame(seq: int = 0, tag: int = TAG, **kw) -> bytes:
    base = dict(ship_tag=tag, seq=seq, lat=35.05, lon=129.10,
                measured_at=T0 + seq, is_pressed=True)
    return BuoyFrame(**{**base, **kw}).pack()


def cut(link: lora.SerialLoRa, data: bytes) -> list:
    """`_cut` 을 직접 돌린다. 시리얼 포트 없이 프레이밍만 본다."""
    buf = bytearray(data)
    return list(link._cut(buf))


# ── 프레이밍 ─────────────────────────────────────────────────────────
def test_cuts_back_to_back_frames():
    link = lora.SerialLoRa(TAG)
    got = cut(link, frame(0) + frame(1) + frame(2))
    assert len(got) == 3
    assert [r[1] for r in got] == [None, None, None]     # RSSI 바이트 꺼짐


def test_resyncs_after_leading_garbage():
    """🔴 UART 에는 프레임 경계가 없다. 한 바이트만 밀려도 그 뒤가 전부 깨진다.

    전원 인가 직후나 케이블을 다시 꽂은 직후가 정확히 이 상태다.
    """
    link = lora.SerialLoRa(TAG)
    got = cut(link, b"\x00\xff\x13\x7e" + frame(7))
    assert len(got) == 1
    assert link.stats.resync_bytes == 4


def test_newline_inside_payload_is_not_a_boundary():
    """🔴 `readline()` 을 쓰면 안 되는 이유. 좌표 안에 0x0A 가 들어간다.

    실험용 `LoRa/lora_test.py` 가 줄 단위였던 건 그게 텍스트 PING/ACK 이라서다.
    같은 방식으로 이진 프레임을 읽으면 여기서 잘린다.
    """
    raw = None
    for seq in range(4096):
        cand = frame(seq)
        if b"\n" in cand[:FRAME_LEN - 2]:      # CRC 자리 말고 본문에 들어간 것
            raw = cand
            break
    assert raw is not None, "0x0A 를 포함하는 프레임을 못 만들었다"

    assert len(raw.split(b"\n")) > 1           # readline 이라면 잘렸을 것이다
    assert len(cut(lora.SerialLoRa(TAG), raw)) == 1


def test_partial_frame_waits_for_rest():
    """반쪽이 온 상태에서 버리지 않는다. 다음 read 에 나머지가 온다."""
    link = lora.SerialLoRa(TAG)
    raw = frame(3)
    buf = bytearray(raw[:10])
    assert list(link._cut(buf)) == []
    assert len(buf) == 10                      # 그대로 들고 있다

    buf.extend(raw[10:])
    assert len(list(link._cut(buf))) == 1


def test_version_nibble_guards_against_false_crc_sync():
    """CRC 만 보면 무작위 바이트가 65536분의 1 로 통과한다. 버전을 같이 본다."""
    raw = bytearray(frame(1))
    raw[0] = 0x90          # 버전 9. CRC 는 여전히 안 맞지만 첫 관문에서 걸린다
    assert lora._looks_like_frame(raw) is False


# ── RSSI 바이트 ──────────────────────────────────────────────────────
def test_rssi_byte_changes_the_unit_length():
    """🔴 E22 REG3 bit7 을 켜면 단위가 19 가 아니라 20바이트가 된다.

    설정과 코드가 어긋나면 매 프레임 1바이트씩 밀려 **전부** 버려진다.
    """
    link = lora.SerialLoRa(TAG, rssi=True)
    assert link.unit == 20

    got = cut(link, frame(0) + b"\xb4" + frame(1) + b"\xa0")
    assert [r[1] for r in got] == [-76.0, -96.0]        # rssi_byte - 256


def test_rssi_off_by_default_matches_current_module_config():
    """2026-09-18 Pi 에 써넣은 REG3 은 0x13 — RSSI 바이트가 꺼져 있다."""
    assert lora.SerialLoRa(TAG).unit == FRAME_LEN


# ── 걸러내기 ─────────────────────────────────────────────────────────
def test_foreign_ship_frames_are_dropped():
    """🔴 남의 배 부표는 **깨끗하게 수신되고 CRC 도 통과한다.**

    걸러낼 곳이 여기뿐이다. 빠뜨리면 남의 익수자 좌표가 우리 사고에 기록된다.
    """
    link = lora.SerialLoRa(TAG)
    link._accept(frame(0, tag=TAG), None)
    link._accept(frame(1, tag=0x42), None)

    assert link.stats.ok == 1
    assert link.stats.foreign == 1
    assert len(link.drain()) == 1
    assert link.last_foreign_tag == 0x42        # 어떤 태그가 왔는지 로그에 찍는다


# ── 5초 요약 로그 ────────────────────────────────────────────────────
def test_summary_says_nothing_arrived():
    """🔴 받은 게 없어도 한 줄은 찍는다. 조용하면 안 오는 건지 버리는 건지 모른다."""
    line = lora.link_summary({"ok": 0, "foreign": 0, "bad_crc": 0, "bad_frame": 0, "lost": 0}, {})
    assert "받은 쪽지 없음" in line


def test_summary_counts_and_explains_why_dropped():
    link = lora.SerialLoRa(TAG)
    link._accept(frame(0, tag=TAG), None)
    last = link.drain()[-1]
    line = lora.link_summary({"ok": 1, "foreign": 0, "bad_crc": 0, "bad_frame": 0, "lost": 0},
                             {"no_accident": 1}, last, our_tag=TAG)
    assert "받음 1" in line and "사고없음 1" in line
    assert "진행 중 사고가 없어 기록하지 않는다" in line
    assert f"seq {last.frame.seq}" in line


def test_summary_names_the_foreign_tag():
    """태그가 안 맞으면 **무슨 태그가 왔는지** 보여야 부표를 다시 구울 수 있다."""
    line = lora.link_summary({"ok": 0, "foreign": 3, "bad_crc": 0, "bad_frame": 0, "lost": 0},
                             {}, our_tag=0x64, foreign_tag=0xC9)
    assert "태그다름 3" in line and "0xC9" in line and "0x64" in line


def test_no_tag_accepts_everything():
    """벤치 시험용. 운영에서는 절대 이 상태로 두지 않는다."""
    link = lora.SerialLoRa(None)
    link._accept(frame(0, tag=0x42), None)
    assert len(link.drain()) == 1


def test_broken_frame_does_not_kill_the_link():
    link = lora.SerialLoRa(TAG)
    link._accept(b"\x10" * FRAME_LEN, None)
    link._accept(frame(5), None)
    assert link.stats.bad_frame == 1
    assert link.stats.ok == 1


# ── 큐 ───────────────────────────────────────────────────────────────
def test_drain_returns_every_frame_not_just_the_latest():
    """🔴 GPS 와 다르다. 한 프레임이 `pi_buoy` 한 행이라 사이를 버리면 궤적에 구멍이 난다."""
    link = lora.SerialLoRa(TAG)
    for i in range(5):
        link._accept(frame(i), None)
    assert [r.frame.seq for r in link.drain()] == [0, 1, 2, 3, 4]
    assert link.drain() == []          # 비워진다


def test_queue_overflow_drops_oldest():
    """넘치면 오래된 것부터 버린다. 익수자 **최신** 위치를 지키는 쪽이 옳다."""
    link = lora.SerialLoRa(TAG)
    for i in range(lora.QUEUE_MAX + 10):
        link._accept(frame(i), None)
    got = link.drain()
    assert len(got) == lora.QUEUE_MAX
    assert got[-1].frame.seq == lora.QUEUE_MAX + 9


def test_age_sec_is_elapsed_not_epoch():
    """🔴 수신 스레드는 GPS 시계를 안 본다. Pi 5 는 RTC 가 없어 fix 전 `time.time()` 이 틀리다.

    경과만 내보내고 호출자가 `clock.now()` 로 환산한다.
    """
    link = lora.SerialLoRa(TAG)
    link._accept(frame(0), None)
    time.sleep(0.02)
    rx = link.drain()[0]
    assert 0.0 < rx.age_sec < 1.0


# ── 유실 집계 ────────────────────────────────────────────────────────
def test_counts_seq_gaps():
    """`docs/lora.md` §5 가 재라고 한 숫자. RSSI 정상인데 크면 충돌, 낮으면 거리다."""
    link = lora.SerialLoRa(TAG)
    for seq in (0, 1, 5, 6):
        link._accept(frame(seq), None)
    assert link.stats.lost == 3


def test_seq_wrap_is_not_counted_as_loss():
    link = lora.SerialLoRa(TAG)
    link._accept(frame(0xFFFF), None)
    link._accept(frame(0), None)
    assert link.stats.lost == 0


# ── 가짜 부표 ────────────────────────────────────────────────────────
def test_fake_buoy_goes_through_the_real_codec():
    """코덱을 우회하면 코덱 버그가 시연 날까지 안 드러난다."""
    fake = lora.FakeLoRa(TAG)
    raw = fake.frame(T0).pack()
    assert len(raw) == FRAME_LEN
    fake._accept(raw, -70.0)
    assert fake.stats.ok == 1


def test_fake_buoy_drifts():
    fake = lora.FakeLoRa(TAG, lat=35.0, lon=129.0, cog=90.0)
    before = fake.lon
    fake._advance(60.0)
    assert fake.lon > before           # 동쪽으로 간다
    assert fake.lat == pytest.approx(35.0, abs=1e-9)


# ── 실물 부표가 보낸 바이트 ──────────────────────────────────────────
#
# 🔴 2026-09-22 Pi 가 `/dev/ttyAMA0` 에서 실제로 받은 것이다. 손으로 만든 벡터가
#    아니라 전파를 타고 온 바이트다 — 동기 워드가 **없다.**
REAL_CAPTURE = bytes.fromhex("10c9003014e434a04cf31e7e6ab21e7702ce40")


def test_production_adapter_accepts_the_real_capture():
    """운영 경로가 실물 프레임을 잡는가. 여기가 깨지면 시연에서 부표가 안 뜬다."""
    from floaq.adapters.lora import _looks_like_frame

    assert _looks_like_frame(bytearray(REAL_CAPTURE))
    f = unpack(REAL_CAPTURE[:FRAME_LEN])
    assert (f.ship_tag, f.seq) == (0xC9, 48)
    assert f.lat == pytest.approx(35.05)


def test_resync_finds_the_frame_after_noise():
    """⚠ 앞에 잡음이 붙어도 잡아야 한다. UART 에는 프레임 경계가 없다."""
    from floaq.adapters.lora import _looks_like_frame

    buf = bytearray(b"\xff\x00\x7f" + REAL_CAPTURE)
    dropped = 0
    while len(buf) >= FRAME_LEN and not _looks_like_frame(buf):
        del buf[:1]
        dropped += 1
    assert dropped == 3
    assert unpack(bytes(buf[:FRAME_LEN])).seq == 48


def test_the_ab_tool_does_not_require_a_sync_word():
    """🔴 진단 도구가 `find(SYNC)` 로 되돌아가면 실물이 전부 버려진다.

    실제로 그랬다 — 전파는 멀쩡히 들어오는데 `lora_ab.py b` 가 "수신 0" 만
    찍었고, `!! 버림` 조차 안 나와 전파 문제로 한참 의심했다. 운영 경로는
    CRC 재동기라 멀쩡했는데 도구만 달랐다.
    """
    src = (Path(__file__).resolve().parents[1] / "tools" / "lora_ab.py").read_text(
        encoding="utf-8")
    # ⚠ `recv` 가 둘이다 (UdpLink·SerialLink). SerialLink 것만 본다
    body = src[src.index("class SerialLink"):]
    recv = body[body.index("def recv("):body.index("def close(")]
    # ⚠ 실제 호출만 본다. docstring 이 그 버그를 설명하느라 같은 글자를 담고 있다
    assert "_buf.find(SYNC)" not in recv, "도구가 동기 워드를 다시 찾고 있다"
    assert "_looks_like_frame" in recv, "운영 경로와 같은 판정을 써야 한다"

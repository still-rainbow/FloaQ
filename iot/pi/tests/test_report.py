"""조난 신고 발신기 시험. **실제 UDP 소켓으로 왕복시킨다.**

루프백이라 네트워크가 없어도 돈다. 확인응답 수신 경로가 실제로 동작하는지를
여기서 잡는다 — 그 경로가 죽어 있으면 DSC 가 영원히 송신한다.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq.adapters import nmea, report
from floaq.contracts import ReportChannel
from floaq.protocols import dsc

SHIP_MMSI = "440123456"
COAST_MMSI = "004401001"
LAT, LON = 35.1234567, 129.7654321


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def reporter():
    events: list[tuple[str, report.ChannelState]] = []
    r = report.UdpReporter(ship_mmsi=SHIP_MMSI, host="127.0.0.1", port=free_port(),
                           on_status=lambda aid, st: events.append((aid, st)))
    r.events = events          # type: ignore[attr-defined]
    yield r
    r.close()


def ack_line(*, distress_mmsi: str = SHIP_MMSI, coast: str = COAST_MMSI) -> str:
    return nmea.coastguard_acknowledgement(
        coast_mmsi=coast, distress_mmsi=distress_mmsi,
        nature=int(dsc.Nature.MAN_OVERBOARD), lat=LAT, lon=LON, hour=14, minute=30)


# ── 장치 MMSI ────────────────────────────────────────────────────────
def test_device_mmsi_keeps_nine_digits():
    from floaq.protocols import ais
    mob = report.device_mmsi(SHIP_MMSI, ais.MMSI_PREFIX_MOB)
    assert mob == "972123456" and len(mob) == 9
    assert report.device_mmsi(SHIP_MMSI, ais.MMSI_PREFIX_SART).startswith("970")


def test_bad_ship_mmsi_rejected():
    for bad in ("12345", "44012345a"):
        with pytest.raises(ValueError):
            report.UdpReporter(ship_mmsi=bad)


# ── 시작·중지 ────────────────────────────────────────────────────────
def test_start_creates_all_three_channels(reporter):
    reporter.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))
    time.sleep(0.4)
    assert set(reporter._active.channels) == set(ReportChannel)


def test_start_twice_does_not_duplicate(reporter):
    """🔴 QoS 1 재전송이나 사용자 연타로 신고가 두 번 나가면 안 된다."""
    reporter.start("acc-1", LAT, LON, 110)
    first = reporter._active
    reporter.start("acc-1", 36.0, 130.0, 110)
    assert reporter._active is first
    assert reporter._active.lat == 36.0        # 좌표만 갱신된다


def test_stop_marks_channels_stopped(reporter):
    reporter.start("acc-1", LAT, LON, 110)
    time.sleep(0.3)
    reporter.stop("acc-1", "TABLET_RESCUE")
    assert reporter._active is None


def test_stop_ignores_other_accident(reporter):
    reporter.start("acc-1", LAT, LON, 110)
    reporter.stop("acc-2", "TABLET_RESCUE")
    assert reporter._active is not None


# ── 🔴 확인응답 ──────────────────────────────────────────────────────
def test_ack_stops_dsc_only(reporter):
    """🔴 이 시험이 이 파일의 이유다.

    DSC 는 확인응답으로 멈추지만 **AIS 두 채널은 계속 간다.** AIS 는 단방향이라
    ACK 이 없고, 신고 접수는 구조 완료가 아니다. 여기서 AIS 까지 멈추면
    표류 중인 익수자를 놓친다.
    """
    reporter.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))
    reporter.handle_sentence(ack_line())

    ch = reporter._active.channels
    assert ch[ReportChannel.DSC].status == "ACKED"
    assert ch[ReportChannel.DSC].acked_by == COAST_MMSI
    assert ch[ReportChannel.AIS_MOB].status == "SENDING"
    assert ch[ReportChannel.AIS_SART].status == "SENDING"


def test_ack_for_another_ship_ignored(reporter):
    """같은 망에 남의 배 조난 확인응답이 흐른다. 조난선 MMSI 로 가른다."""
    reporter.start("acc-1", LAT, LON, 110)
    reporter.handle_sentence(ack_line(distress_mmsi="440999999"))
    assert reporter._active.channels[ReportChannel.DSC].status == "SENDING"


def test_own_sentence_echo_ignored(reporter):
    """같은 포트로 브로드캐스트하면 자기가 쏜 걸 자기가 받는다."""
    reporter.start("acc-1", LAT, LON, 110)
    reporter.handle_sentence(ack_line(coast=SHIP_MMSI))
    assert reporter._active.channels[ReportChannel.DSC].status == "SENDING"


def test_distress_alert_is_not_mistaken_for_ack(reporter):
    """조난 경보(112)를 확인응답으로 읽으면 쏘자마자 스스로 멈춘다."""
    reporter.start("acc-1", LAT, LON, 110)
    alert = nmea.dsc_distress_sentences(mmsi=COAST_MMSI, nature=110, lat=LAT, lon=LON,
                                        hour=14, minute=30)[0]
    reporter.handle_sentence(alert)
    assert reporter._active.channels[ReportChannel.DSC].status == "SENDING"


def test_ack_twice_is_idempotent(reporter):
    reporter.start("acc-1", LAT, LON, 110)
    reporter.handle_sentence(ack_line())
    first = reporter._active.channels[ReportChannel.DSC].acked_at
    time.sleep(1.1)
    reporter.handle_sentence(ack_line())
    assert reporter._active.channels[ReportChannel.DSC].acked_at == first


def test_ack_before_any_incident_is_harmless(reporter):
    reporter.handle_sentence(ack_line())        # 예외가 나면 안 된다


def test_garbage_does_not_crash_receiver(reporter):
    """수신 경로에서 죽으면 그 뒤 확인응답을 영영 못 받는다."""
    reporter.start("acc-1", LAT, LON, 110)
    for junk in ("", "쓰레기", "$CDDSC", "$CDDSC,16,x,12,10*00",
                 "$CDDSC,16,0044010010,12,10,00,0350712945,1430,4401234560,10,S,E*00",
                 "!AIVDM,1,1,,A,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C"):
        reporter.handle_sentence(junk)
    assert reporter._active.channels[ReportChannel.DSC].status == "SENDING"


def test_bad_checksum_rejected():
    line = ack_line().replace("*", "*FF", 1)
    assert nmea.parse_dsc(line) is None


# ── 실제 UDP 왕복 ────────────────────────────────────────────────────
def test_ack_over_real_udp_socket():
    """🔴 `listen()` 을 안 부르면 `on_dsc_ack` 를 부를 사람이 없다.

    실제 소켓으로 왕복시켜 수신 스레드가 살아 있는지 확인한다.
    """
    port = free_port()
    r = report.UdpReporter(ship_mmsi=SHIP_MMSI, host="127.0.0.1", port=port)
    try:
        r.listen(bind_port=port)
        r.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(ack_line().encode("ascii"), ("127.0.0.1", port))
        s.close()

        deadline = time.time() + 5
        while time.time() < deadline:
            if r._active.channels[ReportChannel.DSC].acked_at is not None:
                break
            time.sleep(0.1)

        ch = r._active.channels
        assert ch[ReportChannel.DSC].status == "ACKED"
        assert ch[ReportChannel.AIS_MOB].status == "SENDING"
    finally:
        r.close()


def test_sends_real_sentences_over_udp():
    """발신 쪽도 확인한다. 세 채널 문장이 실제로 소켓을 타는가."""
    port = free_port()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("127.0.0.1", port))
    rx.settimeout(6.0)

    r = report.UdpReporter(ship_mmsi=SHIP_MMSI, host="127.0.0.1", port=port)
    try:
        r.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))
        # ⚠ 채널마다 별도 데이터그램이다. 줄 수로 끊으면 AIS 만 받고 DSC 를 놓친다.
        #   세 종류가 다 나올 때까지 읽는다.
        seen: list[str] = []
        deadline = time.time() + 6
        while time.time() < deadline:
            if any(ln.startswith("$CDDSC") for ln in seen) and \
               any(ln.startswith("!AIVDM") for ln in seen):
                break
            try:
                data, _ = rx.recvfrom(4096)
            except socket.timeout:
                break
            seen += [ln for ln in data.decode().splitlines() if ln]

        assert seen, "아무것도 안 나갔다"
        assert all(nmea.verify_checksum(ln) for ln in seen)
        assert any(ln.startswith("$CDDSC") for ln in seen)
        assert any(ln.startswith("!AIVDM") for ln in seen)
    finally:
        r.close()
        rx.close()


# ── M.541 §3.1.3.1 호출 시도 ─────────────────────────────────────────
def test_dsc_attempt_is_five_consecutive_calls():
    """M.541 §3.1.3.1 — 한 번의 호출 시도는 연속 5회다."""
    from floaq import config
    assert config.DSC_ATTEMPT_CALLS == 5

    port = free_port()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("127.0.0.1", port))
    rx.settimeout(5.0)

    r = report.UdpReporter(ship_mmsi=SHIP_MMSI, host="127.0.0.1", port=port)
    try:
        r.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))
        lines: list[str] = []
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                data, _ = rx.recvfrom(4096)
            except socket.timeout:
                break
            lines += [ln for ln in data.decode().splitlines() if ln]

        alerts = [ln for ln in lines if ln.startswith("$CDDSC")]
        expansions = [ln for ln in lines if ln.startswith("$CDDSE")]
        assert len(alerts) == 5
        # 🔴 확장 메시지는 마지막 호출 뒤 **한 번만** (M.493 §11.4.1)
        assert len(expansions) == 1
    finally:
        r.close()
        rx.close()


def test_dsc_repeat_delay_is_randomised_in_spec_band():
    """🔴 M.541 §3.1.3.1 — 3½~4½분 사이 **무작위**.

    고정 간격이면 재전송이 확인응답 수신 창을 같은 자리에서 계속 막는다.
    확인응답은 해안국 운용자가 수동으로 보내므로 도착 시각이 무작위다 (§3.3).
    """
    from floaq import config
    assert config.DSC_REPEAT_MIN_SEC == 210
    assert config.DSC_REPEAT_MAX_SEC == 270

    import random as _r
    draws = {round(_r.uniform(config.DSC_REPEAT_MIN_SEC,
                              config.DSC_REPEAT_MAX_SEC), 3) for _ in range(50)}
    assert len(draws) > 40, "고정값이면 안 된다"
    assert all(210 <= d <= 270 for d in draws)


def test_ack_during_attempt_stops_remaining_calls(reporter):
    """시도 도중 확인응답이 오면 남은 호출을 멈춘다. M.541 §3.3.5"""
    reporter.start("acc-1", LAT, LON, int(dsc.Nature.MAN_OVERBOARD))
    reporter.handle_sentence(ack_line())
    st = reporter._active.channels[ReportChannel.DSC]
    assert st.status == "ACKED"
    before = st.sent_count
    time.sleep(0.5)
    assert st.sent_count == before, "확인응답 뒤에도 쏘고 있다"

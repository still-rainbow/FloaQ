"""사고 전 과정 테스트. **브로커도 SQLite 도 서보도 없이 돈다.**

탐지 → 판정 → 투하 → 카운트다운 → 자동 신고 → 종료가 전부 여기서 검증된다.
DES-37 §4 스프링 실측이 끝나기 전까지 기구가 정지 상태여도 이건 돌아간다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq import config
from floaq.adapters.memory import FakeClock, FakeLauncher, FakeReporter, MemoryBus, MemoryRepo
from floaq.contracts import AccidentStatus as S
from floaq.contracts import AimCommand, JetsonDetection
from floaq.core.orchestrator import Orchestrator
from floaq.ids import uuid7, uuid7_timestamp_ms

SHIP = uuid7()
T0 = 1_757_000_000


def build(*, loaded=True, outcome="SUCCESS", clock_valid=True):
    clock = FakeClock(T0, valid=clock_valid)
    bus, repo = MemoryBus(), MemoryRepo()
    launcher = FakeLauncher(loaded=loaded, outcome=outcome)
    reporter = FakeReporter()
    orch = Orchestrator(ship_id=SHIP, clock=clock, bus=bus, repo=repo,
                        launcher=launcher, reporter=reporter)
    return orch, clock, bus, repo, launcher, reporter


def detection(**kw) -> JetsonDetection:
    base = dict(
        detection_id=uuid7(), ship_id=SHIP, lat=35.1, lon=129.0, distance_m=12.5,
        confidence=0.93, frame_count=5, model_version="v1", camera="L",
        bbox=(10, 20, 30, 40), detected_at=T0,
        launch=dict(target_yaw_deg=12.5, target_pitch_deg=20.0,
                    launch_profile="demo-low-v1", target_lat=35.11,
                    target_lon=129.01, solved_at=T0),
    )
    return JetsonDetection(**{**base, **kw})


def aim(**kw) -> AimCommand:
    base = dict(target_yaw_deg=12.5, target_pitch_deg=20.0,
                confidence=0.93, track_id=7, solved_at=T0)
    return AimCommand(**{**base, **kw})


def test_aim_only_never_releases():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_aim(aim())
    assert launcher.aim_calls == [(12.5, 20.0)]
    assert launcher.calls == []
    assert repo.active() is None


def test_stale_or_out_of_range_aim_is_ignored():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_aim(aim(solved_at=T0 - config.AIM_COMMAND_TTL_SEC - 1))
    orch.on_aim(aim(target_yaw_deg=90.0))
    orch.on_aim(aim(target_pitch_deg=config.PITCH_MIN_DEG - 1.0))
    assert launcher.aim_calls == []
    assert launcher.calls == []


# ── 정상 흐름 ────────────────────────────────────────────────────────
def test_full_incident():
    """탐지 → 투하 → 카운트다운 → 30초 만료 → 자동 신고 → 구조 확정."""
    orch, clock, bus, repo, launcher, reporter = build()

    orch.on_detection(detection())
    acc = repo.active()
    assert acc.status is S.WAIT
    assert acc.report_due_at == T0 + config.WAIT_SEC
    assert len(launcher.calls) == 1
    assert bus.last("pi/launch/result").result == "SUCCESS"
    # DETECT 와 WAIT 두 번 발행됐다
    assert bus.count("pi/accident/state") == 2

    # 29초 — 아직 안 쏜다
    clock.advance(29)
    orch.tick()
    assert repo.active().status is S.WAIT
    assert reporter.started == []

    # 30초 — 키오스크가 살아있든 아니든 Pi 가 혼자 쏜다
    clock.advance(1)
    orch.tick()
    acc = repo.active()
    assert acc.status is S.REPORT
    assert reporter.started == [acc.accident_id]

    # 구조 확정
    orch.on_command("rescue", {"accident_id": acc.accident_id}, uuid7())
    assert repo.get(acc.accident_id).status is S.CLOSE
    assert repo.active() is None
    assert reporter.stopped[0][1] == "TABLET_RESCUE"


def test_cancel_before_timeout():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()

    orch.on_command("cancel", {"accident_id": acc.accident_id}, uuid7())
    assert repo.get(acc.accident_id).status is S.CANCEL
    assert repo.active() is None

    # 취소했으면 만료가 지나도 신고가 나가면 안 된다
    clock.advance(999)
    orch.tick()
    assert reporter.started == []


def test_report_now_skips_wait():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()
    orch.on_command("report_now", {"accident_id": acc.accident_id}, uuid7())
    assert repo.active().status is S.REPORT
    assert reporter.started == [acc.accident_id]


def test_manual_report():
    """카운트다운 없이 바로 신고. accident_id 는 키오스크가 만든다."""
    orch, clock, bus, repo, launcher, reporter = build()
    aid = uuid7()
    orch.on_command("report_manual", {
        "accident_id": aid, "accident_type": "FLOODING", "lat": 35.1, "lon": 129.0,
    }, uuid7())
    acc = repo.get(aid)
    assert acc.status is S.REPORT
    assert acc.report_dsc == 101          # 침수
    assert acc.wait_sec == 0
    assert reporter.started == [aid]
    assert launcher.calls == []           # 수동 신고는 투하하지 않는다


# ── 발사 실패 ────────────────────────────────────────────────────────
def test_launch_failure_does_not_stop_the_incident():
    """E5 — 발사 실패해도 사고는 그대로 진행한다. 부표 없이 신고까지 간다."""
    orch, clock, bus, repo, launcher, reporter = build(loaded=False)
    orch.on_detection(detection())

    res = bus.last("pi/launch/result")
    assert res.result == "FAILED"
    assert res.fail_reason == "NOT_LOADED"
    assert launcher.calls == []           # 장치를 건드리지도 않았다
    assert repo.active().status is S.WAIT # 사고는 계속된다

    clock.advance(30)
    orch.tick()
    assert repo.active().status is S.REPORT


def test_launcher_exception_does_not_stop_the_incident():
    """🔴 I2C 가 한 번 끊겼다고 조난신고가 통째로 사라지면 안 된다.

    버스 디스패처(`adapters/mqtt`)가 예외를 삼키므로, 여기서 예외가 나가면
    발사 기록도 안 남고 **5단계 카운트다운이 시작되지 않는다** — 화면에는
    사고만 뜬 채 멈춘다. 2026-09-22 합본 시연 준비 중 찾았다.
    """
    orch, clock, bus, repo, launcher, reporter = build()

    def boom(yaw, pitch, profile):
        raise OSError("[Errno 121] Remote I/O error")

    launcher.aim_and_release = boom
    orch.on_detection(detection())

    res = bus.last("pi/launch/result")
    assert res.result == "FAILED"
    assert res.fail_reason == "DEVICE_ERROR"
    assert repo.active().status is S.WAIT      # 사고는 계속된다

    clock.advance(config.WAIT_SEC)
    orch.tick()
    assert repo.active().status is S.REPORT     # 신고까지 간다


def test_no_solution_reported():
    """Jetson 이 GPS 를 못 받아 조준 해를 못 낸 경우."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection(launch=None))
    assert bus.last("pi/launch/result").fail_reason == "NO_SOLUTION"
    assert launcher.calls == []


def test_out_of_range_not_sent_to_device():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection(launch=dict(
        target_yaw_deg=90.0, target_pitch_deg=20.0, launch_profile="demo-low-v1",
        target_lat=35.1, target_lon=129.0, solved_at=T0)))
    assert bus.last("pi/launch/result").fail_reason == "OUT_OF_RANGE"
    assert launcher.calls == []


# ── 중복·거부 ────────────────────────────────────────────────────────
def test_second_detection_ignored():
    """AI-05 / E1 — 진행 중 사고가 있으면 새로 만들지 않는다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    first = repo.active().accident_id
    orch.on_detection(detection())
    assert repo.active().accident_id == first
    assert len(repo.accidents) == 1


def test_duplicate_command_executes_once():
    """QoS 1 은 at-least-once 다. 같은 request_id 면 실행은 건너뛰고 응답만 다시 보낸다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()
    rid = uuid7()

    orch.on_command("report_now", {"accident_id": acc.accident_id}, rid)
    orch.on_command("report_now", {"accident_id": acc.accident_id}, rid)

    assert len(reporter.started) == 1           # 신고는 한 번만
    assert bus.count("pi/command/response") == 2  # 응답은 두 번


def test_invalid_command_gets_rejection_not_silence():
    """거부도 응답이다. 침묵하면 키오스크가 재시도하고 사용자가 연타한다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()

    orch.on_command("rescue", {"accident_id": acc.accident_id}, uuid7())  # WAIT 에선 무효
    ack = bus.last("pi/command/response")
    assert ack.is_success is False
    assert ack.error.code == "INVALID_STATE"
    assert ack.data.status == S.WAIT        # 현재 상태를 실어줘서 화면을 되돌릴 수 있다
    assert repo.active().status is S.WAIT


def test_manual_report_blocked_while_active():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    orch.on_command("report_manual", {
        "accident_id": uuid7(), "accident_type": "FIRE", "lat": 35.1, "lon": 129.0,
    }, uuid7())
    ack = bus.last("pi/command/response")
    assert ack.error.code == "ACCIDENT_IN_PROGRESS"
    assert len(repo.accidents) == 1


# ── 재부팅 ───────────────────────────────────────────────────────────
def test_boot_forces_launcher_safe():
    """🔴 DES-38 §9 — 전원 재인가 시 자동 발사하지 않는다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.boot()
    assert launcher.safe_calls == 1


def test_boot_republishes_state_from_db():
    """상태 원본은 브로커 retained 가 아니라 DB 다. 재부팅하면 다시 발행한다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()

    bus.sent.clear()
    orch.boot()
    assert bus.last("pi/accident/state").accident_id == acc.accident_id


def test_broken_clock_never_auto_reports():
    """🔴 RTC 없는 Pi 가 부팅 직후 시각이 1970년이어도 신고가 나가면 안 된다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())

    clock.break_clock()          # GPS fix 전 상태
    for _ in range(10):
        orch.tick()
    assert reporter.started == []
    assert repo.active().status is S.WAIT

    # GPS fix 를 받으면 정상 동작한다 — 가드가 기능을 죽이지는 않는다
    clock._now = T0 + 60
    clock.set_valid(True)
    orch.tick()
    assert repo.active().status is S.REPORT


# ── retained 정리 ────────────────────────────────────────────────────
def test_retained_cleared_on_close_state_last():
    """사고가 끝나면 딸린 retained 를 비운다. pi/accident/state 는 **맨 마지막**이다."""
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()
    clock.advance(30)
    orch.tick()

    bus.sent.clear()
    orch.on_command("close", {"accident_id": acc.accident_id}, uuid7())

    cleared = [p.subject for p in bus.sent if p.payload is None]
    assert "pi/launch/result" in cleared
    assert "pi/buoy/drift" in cleared
    assert cleared[-1] == "pi/accident/state"   # 순서가 중요하다
    # Pi 는 jetson/snapshot 을 못 지운다 — ACL 이 막는다. Jetson 이 스스로 지운다.
    assert "jetson/snapshot" not in cleared


# ── 이력 ─────────────────────────────────────────────────────────────
def test_transition_history_is_append_only():
    orch, clock, bus, repo, launcher, reporter = build()
    orch.on_detection(detection())
    acc = repo.active()
    clock.advance(30)
    orch.tick()
    orch.on_command("rescue", {"accident_id": acc.accident_id}, uuid7())

    reasons = [t.reason for t in repo.transitions]
    assert reasons == ["AI_DETECT", "COUNTDOWN_START", "TIMEOUT", "TABLET_RESCUE"]
    # 명령으로 일어난 전이만 caused_by 가 있다
    assert repo.transitions[2].caused_by is None      # TIMEOUT
    assert repo.transitions[3].caused_by is not None  # TABLET_RESCUE


def test_uuid7_is_time_ordered():
    """문자열 정렬이 곧 시간 순서여야 한다 — 동기화 커서와 인덱스가 여기 의존한다."""
    ids = [uuid7(ts_ms=T0 * 1000 + i) for i in range(50)]
    assert ids == sorted(ids)
    assert uuid7_timestamp_ms(ids[0]) == T0 * 1000


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as e:
            failed += 1
            print("  FAIL  %s  %s" % (name, e))
        except Exception as e:
            failed += 1
            print("  ERROR %s  %r" % (name, e))
    print("\n%d passed, %d failed (of %d)" % (len(fns) - failed, failed, len(fns)))
    sys.exit(1 if failed else 0)


# ── 남의 장비 시계 ───────────────────────────────────────────────────
def test_detection_with_uptime_clock_is_restamped():
    """🔴 젯슨도 RTC 가 없다. NTP 없이 부팅하면 `time.time()` 이 epoch+업타임이다.

    그 값이 `pi_accident.created_at` 에 박혀 EC2 까지 올라갔다 — 관제에서
    `1970-01-01T01:29:34Z` 로 확인했다(업타임 1:29:34). Pi 17건 중 3건.
    """
    orch, clock, *_ = build()
    repo = orch.repo
    # 부팅 1시간 29분 34초 — 실제로 DB 에 남아 있던 값이다
    orch.on_detection(detection(detected_at=5374))

    acc = repo.active()
    assert acc is not None                      # 🔴 사고는 반드시 만들어진다
    assert acc.created_at == T0                 # Pi 시계로 갈아 끼웠다
    assert config.clock_is_valid(acc.created_at)


def test_good_detection_time_is_kept():
    """정상 시각은 안 건드린다. 탐지 시각이지 수신 시각이 아니다."""
    orch, clock, *_ = build()
    clock.advance(30)                           # Pi 시계가 앞서 간다
    orch.on_detection(detection())              # detected_at = T0
    assert orch.repo.active().created_at == T0


def test_both_clocks_bad_still_creates_the_accident():
    """⚠ 둘 다 못 믿어도 사고는 만든다. 시계가 틀렸다고 익수자를 안 구할 수는 없다."""
    orch, clock, *_ = build(clock_valid=False)
    clock._now = 5000                           # Pi 도 부팅 직후다
    orch.on_detection(detection(detected_at=5374))
    acc = orch.repo.active()
    assert acc is not None
    # 바꿔 봐야 더 나을 것이 없다 — 보낸 쪽 로그와 맞는 값을 남긴다
    assert acc.created_at == 5374


def test_launch_survives_a_jetson_clock_from_1970():
    """🔴 `solved_at` 도 시계 보정을 받아야 한다.

    만료 검사가 `now - solved_at > 3초` 다. 젯슨이 NTP 없이 부팅하면 그 차이가
    수십 년이라 **발사가 OUT_OF_RANGE 로 조용히 거부된다.** 사고 시각은
    `detected_at` 보정 덕에 정상으로 보여서 각도 문제로 오해하게 된다.
    """
    orch, clock, bus, repo, launcher, _ = build()
    det = detection(detected_at=5374)
    bad = det.model_copy(update={
        "launch": det.launch.model_copy(update={"solved_at": 5374})})

    orch.on_detection(bad)

    assert launcher.calls, "발사가 아예 시도되지 않았다"
    res = bus.last("pi/launch/result")
    assert res is not None and res.result == "SUCCESS", getattr(res, "fail_reason", None)


def test_launch_profile_matches_what_pi_approves():
    """🔴 젯슨 기본 프로파일이 Pi 화이트리스트에 있어야 한다.

    `_client.detected()` 의 기본값이 `"default"` 였고 아무도 안 넘기고 있었다 —
    실제 젯슨 탐지는 전부 OUT_OF_RANGE 로 거부됐다 (2026-09-22 전수검사).
    두 저장소가 따로라 여기서 문자열로 못 박는다.
    """
    assert "demo-low-v1" in config.APPROVED_LAUNCH_PROFILES

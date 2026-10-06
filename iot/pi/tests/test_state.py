"""상태머신·거부 규칙 테스트. **하드웨어도 브로커도 DB 도 없이 돈다.**

DES-38 §9 승인 조건 중 셋이 여기서 증명된다:
  - 범위·만료·중복 명령 거부 시험
  - 비상 정지와 전원 재인가 시 자동 발사하지 않음
  - 부팅 시 구동 미허가 유지

DES-37 §4 스프링 실측이 끝나기 전까지 기구 쪽은 전부 정지 상태인데,
이 파일은 지금 돌릴 수 있다.

    python -m pytest tests/ -v          (pytest 있으면)
    python tests/test_state.py          (없으면 그냥 실행)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq import config
from floaq.contracts import AccidentStatus as S
from floaq.contracts import ACCIDENT_ROUTING, AccidentType, ErrorCode, LaunchSolution
from floaq.core import state

NOW = 1_757_000_000
BAD_CLOCK = 100  # 부팅 직후 RTC 없는 Pi 가 보고할 법한 값


def sol(**kw) -> LaunchSolution:
    base = dict(
        target_yaw_deg=12.5,
        target_pitch_deg=20.0,
        launch_profile="demo-low-v1",
        target_lat=35.1,
        target_lon=129.0,
        solved_at=NOW,
    )
    return LaunchSolution(**{**base, **kw})


# ── 상태 전이 ────────────────────────────────────────────────────────
def test_happy_path():
    """AI 감지 → 투하 → 카운트다운 → 자동 신고 → 종료."""
    assert state.next_status(None, "AI_DETECT") is S.DETECT
    assert state.next_status(S.DETECT, "COUNTDOWN_START") is S.WAIT
    assert state.next_status(S.WAIT, "TIMEOUT") is S.REPORT
    assert state.next_status(S.REPORT, "TABLET_RESCUE") is S.CLOSE


def test_manual_report_skips_countdown():
    """수동 긴급 신고는 사람이 이미 판단했으므로 대기 없이 REPORT (APP-06)."""
    assert state.next_status(None, "TABLET_MANUAL") is S.REPORT


def test_cancel_only_from_wait():
    """DETECT 중엔 취소 버튼이 뜨지 않는다 — 부표 투하가 진행 중이다."""
    assert state.next_status(S.WAIT, "TABLET_CANCEL") is S.CANCEL
    assert state.next_status(S.DETECT, "TABLET_CANCEL") is None


def test_terminal_states_accept_nothing():
    """CANCEL·CLOSE 후에는 어떤 사유로도 전이하지 않는다.

    취소 후 다시 사람이 탐지되면 **새 사고**다 (E2) — 이 상태로 돌아오지 않는다.
    """
    reasons = {r for _, r in state.TRANSITIONS}
    for terminal in state.TERMINAL:
        for reason in reasons:
            assert state.next_status(terminal, reason) is None, (terminal, reason)


def test_unknown_reason_rejected():
    """화이트리스트라 등록 안 된 사유는 통과하지 못한다."""
    assert state.next_status(S.WAIT, "SOMETHING_NEW") is None


def test_active_set_matches_db_index():
    """ACTIVE 는 DB 의 uq_pi_accident_active 부분 인덱스와 같은 집합이어야 한다.

    갈라지면 코드는 통과시키는데 INSERT 가 실패하거나(또는 그 반대) 동시 사고가 두 개 생긴다.
    """
    assert state.ACTIVE == {S.DETECT, S.WAIT, S.REPORT}
    assert state.ACTIVE.isdisjoint(state.TERMINAL)


# ── 명령 검증 ────────────────────────────────────────────────────────
def test_command_valid_states():
    assert state.validate_command("cancel", S.WAIT) is None
    assert state.validate_command("report_now", S.WAIT) is None
    assert state.validate_command("rescue", S.REPORT) is None
    assert state.validate_command("close", S.REPORT) is None
    assert state.validate_command("report_manual", None) is None


def test_command_wrong_state_rejected_not_ignored():
    """거부도 응답이다. 조용히 무시하면 키오스크가 재시도하고 사용자가 연타한다."""
    assert state.validate_command("cancel", S.REPORT) is ErrorCode.INVALID_STATE
    assert state.validate_command("rescue", S.WAIT) is ErrorCode.INVALID_STATE
    assert state.validate_command("cancel", S.CLOSE) is ErrorCode.INVALID_STATE


def test_manual_report_blocked_by_active_accident():
    """동시 사고 1건 (E1). 사유가 INVALID_STATE 가 아니라 구체적이어야 화면이 설명할 수 있다."""
    for active in state.ACTIVE:
        assert state.validate_command("report_manual", active) is ErrorCode.ACCIDENT_IN_PROGRESS


def test_command_on_missing_accident():
    assert state.validate_command("cancel", S.WAIT, target_exists=False) is ErrorCode.ACCIDENT_NOT_FOUND
    # report_manual 은 사고를 새로 만드는 명령이라 대상이 없는 게 정상이다
    assert state.validate_command("report_manual", None, target_exists=False) is None


def test_every_command_has_a_reason():
    """명령을 추가하고 전이 사유를 안 만들면 여기서 걸린다."""
    for cmd in state.COMMAND_REASON:
        assert cmd in state._COMMAND_VALID_IN
    for cmd, reason in state.COMMAND_REASON.items():
        valid = state._COMMAND_VALID_IN[cmd]
        assert any(state.can_transition(s, reason) for s in valid), (cmd, reason)


# ── 카운트다운 ───────────────────────────────────────────────────────
def test_countdown_uses_absolute_deadline():
    assert state.countdown_deadline(NOW) == NOW + config.WAIT_SEC


def test_countdown_expiry():
    due = NOW + 30
    assert state.countdown_expired(due, NOW + 29, clock_valid=True) is False
    assert state.countdown_expired(due, NOW + 30, clock_valid=True) is True
    assert state.countdown_expired(None, NOW + 999, clock_valid=True) is False


def test_bad_clock_never_fires_countdown():
    """🔴 RTC 없는 Pi 가 부팅 직후 신고를 쏘면 안 된다.

    시각이 1970년이면 report_due_at 이 '이미 지난' 것으로 보인다.
    이 가드가 없으면 전원 재인가만으로 자동 신고가 나간다 (DES-31 C-6).
    """
    due = NOW + 30
    assert state.countdown_expired(due, BAD_CLOCK, clock_valid=False) is False
    # 시계가 맞으면 정상 동작한다 — 가드가 기능 자체를 죽이지는 않는다
    assert state.countdown_expired(due, NOW + 31, clock_valid=True) is True


def test_clock_sanity():
    assert config.clock_is_valid(NOW) is True
    assert config.clock_is_valid(BAD_CLOCK) is False
    assert config.clock_is_valid(0) is False


# ── 발사 검증 (DES-38 §6) ────────────────────────────────────────────
def test_launch_accepted():
    assert state.validate_launch(sol(), now=NOW, is_loaded=True) is None


def test_no_solution():
    """탐지는 유효한데 조준을 못 한 경우. Jetson 이 GPS 를 못 받을 때가 대표적이다."""
    assert state.validate_launch(None, now=NOW, is_loaded=True) == "NO_SOLUTION"


def test_angle_out_of_range():
    assert state.validate_launch(sol(target_yaw_deg=90.0), now=NOW, is_loaded=True) == "OUT_OF_RANGE"
    assert state.validate_launch(sol(target_yaw_deg=-90.0), now=NOW, is_loaded=True) == "OUT_OF_RANGE"
    assert state.validate_launch(sol(target_pitch_deg=config.PITCH_MIN_DEG - 1.0), now=NOW, is_loaded=True) == "OUT_OF_RANGE"
    assert state.validate_launch(sol(target_pitch_deg=60.0), now=NOW, is_loaded=True) == "OUT_OF_RANGE"


def test_boundary_angles_accepted():
    """경계값은 통과해야 한다. off-by-one 으로 정상 사격을 막으면 안 된다."""
    assert state.validate_launch(sol(target_yaw_deg=config.YAW_MAX_DEG), now=NOW, is_loaded=True) is None
    assert state.validate_launch(sol(target_pitch_deg=config.PITCH_MIN_DEG), now=NOW, is_loaded=True) is None


def test_unapproved_profile():
    """AI 가 임의의 힘 값을 모터로 직접 보내지 못하게 하는 장치."""
    assert state.validate_launch(sol(launch_profile="max-power"), now=NOW, is_loaded=True) == "OUT_OF_RANGE"


def test_stale_solution():
    """10노트면 1초에 약 5m 이동한다 — 묵은 해는 목표점이 어긋나 있다."""
    old = NOW - config.LAUNCH_SOLUTION_TTL_SEC - 1
    assert state.validate_launch(sol(solved_at=old), now=NOW, is_loaded=True) == "OUT_OF_RANGE"
    fresh = NOW - config.LAUNCH_SOLUTION_TTL_SEC
    assert state.validate_launch(sol(solved_at=fresh), now=NOW, is_loaded=True) is None


def test_stale_check_skipped_when_clock_invalid():
    """시계를 못 믿으면 만료 판정도 못 한다. 여기서 거부하면 GPS fix 전엔 영영 못 쏜다."""
    assert state.validate_launch(sol(solved_at=NOW), now=BAD_CLOCK, is_loaded=True, clock_valid=False) is None


def test_not_loaded():
    """E4. 장전 스위치가 안 눌렸으면 시도조차 하지 않는다."""
    assert state.validate_launch(sol(), now=NOW, is_loaded=False) == "NOT_LOADED"


def test_rejection_order():
    """해가 없으면서 장전도 안 됐으면 NO_SOLUTION 을 먼저 보고한다.

    원인 추적 순서가 중요하다 — '장전 안 됨'을 보고하면 사람이 장전하러 가는데
    실제 문제는 GPS 였던 상황이 된다.
    """
    assert state.validate_launch(None, now=NOW, is_loaded=False) == "NO_SOLUTION"


# ── 신고 등급 라우팅 ─────────────────────────────────────────────────
def test_routing_covers_every_type():
    """사고 유형을 추가하고 라우팅을 빠뜨리면 KeyError 로 터진다 — 조용히 넘어가지 않는다."""
    for t in AccidentType:
        report_type, dsc = state.route(t)
        assert report_type is not None


def test_flooding_splits_on_roll():
    """FLOODING 만 IMU 기울기로 101(침수)/104(전복 위험)이 갈린다.

    ⚠ roll 은 **각도(deg)** 다. ERD 주석의 deg/s 로 읽으면 이 판정이 무의미해진다.
    """
    assert state.route(AccidentType.FLOODING)[1] == 101
    assert state.route(AccidentType.FLOODING, roll_deg=10.0)[1] == 101
    assert state.route(AccidentType.FLOODING, roll_deg=50.0)[1] == 104
    assert state.route(AccidentType.FLOODING, roll_deg=-50.0)[1] == 104


def test_urgency_has_no_dsc():
    """URGENCY 는 M.493 nature 표에 대응이 없다. 억지로 코드를 만들면 안 된다."""
    assert state.route(AccidentType.MEDICAL)[1] is None


def test_report_types_are_two():
    """🔴 SAFETY 를 뺐다 `확정` 2026-09-17. 항행경보 수준이라 쓸 일이 없었다."""
    from floaq.contracts import ReportType
    assert {r.value for r in ReportType} == {"DISTRESS", "URGENCY"}


def test_accident_types_match_server_enum():
    """🔴 8종. `api.md` §1.7 서버 CHECK 와 **글자까지** 같아야 한다.

    한쪽만 늘리면 Edge 전송이 400 으로 조용히 막힌다. 그래서 집합을 통째로 고정한다.
    HAZARD·ABANDON_SHIP 은 1차 범위에서 뺐다 `확정` 2026-09-17.
    """
    assert {t.value for t in AccidentType} == {
        "MOB", "FIRE", "FLOODING", "COLLISION", "GROUNDING",
        "ENGINE_FAILURE", "OTHER_DISTRESS", "MEDICAL"}


def test_every_accident_type_routes():
    """라우팅 표에 빠진 유형이 있으면 그 사고는 신고 등급을 못 정한다."""
    assert set(ACCIDENT_ROUTING) == set(AccidentType)


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

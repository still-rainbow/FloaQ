"""사고 상태머신과 거부 규칙. **순수 함수만 있다 — I/O 가 없다.**

여기 있는 것은 전부 입력 → 출력이라 하드웨어도 브로커도 DB 도 없이 테스트된다.
DES-38 §9 의 승인 조건 중 셋이 이 파일의 테스트로 증명된다:

  - 범위·만료·중복 명령 거부 시험
  - 비상 정지와 전원 재인가 시 자동 발사하지 않음
  - 부팅 시 구동 미허가 유지

⚠ 여기 있는 사고 상태머신(DETECT/WAIT/REPORT/CANCEL/CLOSE)과
  DES-38 §6 의 **발사 장치 안전 상태머신**(SAFE→AIMING→ARMED→READY→RELEASED, +FAULT)은
  다른 층이다. 후자는 adapters 의 Launcher 구현 안에 있고, 여기서는 결과만 본다.
"""

from __future__ import annotations

from typing import Final

from floaq import config
from floaq.contracts import (
    AccidentStatus,
    AccidentType,
    ErrorCode,
    LaunchSolution,
    ReportType,
    ACCIDENT_ROUTING,
)

# ── 사고 상태 전이 ───────────────────────────────────────────────────
# (현재 상태, 사유) → 다음 상태.  현재 상태가 None 이면 "진행 중 사고 없음"이다.
#
# 상세기획 §3.1 의 다이어그램을 그대로 표로 옮겼다. 표에 없는 조합은 전부 거부한다 —
# 화이트리스트라서, 새 사유를 추가하면 여기 등록하기 전까지는 동작하지 않는다.
# (블랙리스트로 짰으면 빠뜨린 조합이 조용히 통과했을 것이다.)
TRANSITIONS: Final[dict[tuple[AccidentStatus | None, str], AccidentStatus]] = {
    # AI 감지 → 사고 생성. 부표 투하가 여기서 진행된다
    (None, "AI_DETECT"): AccidentStatus.DETECT,
    # 수동 긴급 신고는 카운트다운이 없다 — 사람이 이미 판단했으므로 바로 REPORT (APP-06)
    (None, "TABLET_MANUAL"): AccidentStatus.REPORT,
    # 투하가 끝나면 30초 카운트다운 시작
    (AccidentStatus.DETECT, "COUNTDOWN_START"): AccidentStatus.WAIT,
    # 카운트다운 만료 → 자동 신고. 키오스크가 살아있든 아니든 Pi 가 혼자 판단한다
    (AccidentStatus.WAIT, "TIMEOUT"): AccidentStatus.REPORT,
    (AccidentStatus.WAIT, "TABLET_REPORT_NOW"): AccidentStatus.REPORT,
    (AccidentStatus.WAIT, "TABLET_CANCEL"): AccidentStatus.CANCEL,
    # 구조 확정(APP-10) / 사고 종료(APP-11). 둘 다 CLOSE 지만 사유가 남는다
    (AccidentStatus.REPORT, "TABLET_RESCUE"): AccidentStatus.CLOSE,
    (AccidentStatus.REPORT, "TABLET_CLOSE"): AccidentStatus.CLOSE,
}

#: 더 나갈 곳이 없는 상태. 여기서는 어떤 명령도 받지 않는다.
#: CANCEL 후 다시 사람이 탐지되면 **새 사고**로 처리한다 (E2) — 이 상태로 돌아오지 않는다.
TERMINAL: Final[frozenset[AccidentStatus]] = frozenset(
    {AccidentStatus.CANCEL, AccidentStatus.CLOSE}
)

#: 진행 중으로 보는 상태. DB 의 uq_pi_accident_active 부분 인덱스와 같은 집합이어야 한다.
ACTIVE: Final[frozenset[AccidentStatus]] = frozenset(
    {AccidentStatus.DETECT, AccidentStatus.WAIT, AccidentStatus.REPORT}
)


def next_status(current: AccidentStatus | None, reason: str) -> AccidentStatus | None:
    """전이 결과. 허용되지 않는 조합이면 None.

    None 을 돌려주는 것과 "None 상태로 간다"는 건 다르다 — 후자는 없다.
    """
    return TRANSITIONS.get((current, reason))


def can_transition(current: AccidentStatus | None, reason: str) -> bool:
    return (current, reason) in TRANSITIONS


# ── 명령 검증 ────────────────────────────────────────────────────────
#: 명령 → 그 명령이 유효한 상태. contracts.VALID_COMMAND_STATES 와 같은 내용이지만
#: 여기서는 거부 사유까지 만들어야 해서 따로 판정 함수를 둔다.
#:
#: DETECT 중에 취소·신고 버튼이 없는 이유: 부표 투하가 진행 중이라 사람이 개입할 지점이 아니다.
_COMMAND_VALID_IN: Final[dict[str, frozenset[AccidentStatus | None]]] = {
    "cancel": frozenset({AccidentStatus.WAIT}),
    "report_now": frozenset({AccidentStatus.WAIT}),
    "rescue": frozenset({AccidentStatus.REPORT}),
    "close": frozenset({AccidentStatus.REPORT}),
    "report_manual": frozenset({None}),
}

#: 전이 사유 → `pi_report.trigger_kind`. 신고 **행**이 어떻게 생겼는지를 적는다.
#:
#: ⚠ `pi_accident.report_type`(DISTRESS/URGENCY)과 **다른 것이다.** 구 ERD 가 둘 다
#:   report_type 이라 불러서 개명했다 (`api.json` IPiReportRequest 설명).
#: ⚠ RESCUE 는 발신 시작이 아니라 **구조 확정으로 중지된 것**이다. 시작 사유가 아니라
#:   중지 사유에서 온다 — 그래서 아래 표에 없고 `Reporter.stop` 이 붙인다.
REPORT_TRIGGER_KIND: Final[dict[str, str]] = {
    "TIMEOUT": "AUTO",              # 카운트다운 만료. 사람이 안 눌렀다
    "TABLET_REPORT_NOW": "MANUAL",  # 대기 중 즉시 신고
    "TABLET_MANUAL": "MANUAL",      # 수동 긴급 신고 (카운트다운 없음)
}

#: 명령 → 그 명령이 일으키는 전이 사유
COMMAND_REASON: Final[dict[str, str]] = {
    "cancel": "TABLET_CANCEL",
    "report_now": "TABLET_REPORT_NOW",
    "rescue": "TABLET_RESCUE",
    "close": "TABLET_CLOSE",
    "report_manual": "TABLET_MANUAL",
}


def validate_command(
    command: str,
    current: AccidentStatus | None,
    *,
    target_exists: bool = True,
) -> ErrorCode | None:
    """명령을 받아들일 수 있는가. 받아들이면 None, 아니면 거부 사유.

    **무효한 명령을 조용히 무시하면 안 된다.** 키오스크는 버튼을 누른 뒤 응답을 기다리는데,
    아무것도 안 오면 "전달 실패"로 보고 재시도하고, 사용자는 연타한다.
    거부도 응답이다.
    """
    if command not in _COMMAND_VALID_IN:
        return ErrorCode.INVALID_STATE

    # report_manual 만 사고를 새로 만든다. 나머지는 기존 사고를 가리킨다.
    if command != "report_manual" and not target_exists:
        return ErrorCode.ACCIDENT_NOT_FOUND

    allowed = _COMMAND_VALID_IN[command]
    if current in allowed:
        return None

    # 진행 중 사고가 있는데 수동 신고를 걸었다 — 동시 사고 1건 (E1)
    if command == "report_manual" and current in ACTIVE:
        return ErrorCode.ACCIDENT_IN_PROGRESS

    return ErrorCode.INVALID_STATE


# ── 카운트다운 ───────────────────────────────────────────────────────
def countdown_deadline(now: int, wait_sec: int = config.WAIT_SEC) -> int:
    """자동 신고 예정 **절대 시각**.

    남은 초를 보내지 않는 이유: 메시지가 3초 늦게 도착하면 키오스크는 33초를 세고
    Pi 는 30초에 쏜다. 화면에 7초 남았는데 이미 신고가 나간 상태가 된다.
    재접속했을 때 남은 시간을 복구할 방법도 없다.
    """
    return now + wait_sec


def countdown_expired(due_at: int | None, now: int, *, clock_valid: bool) -> bool:
    """카운트다운이 만료됐는가.

    🔴 **시계를 믿을 수 없으면 언제나 False 다.**

    Pi 5 에는 RTC 배터리가 없고 폐쇄망이라 NTP 도 없다(DES-31 C-6). 첫 GPS fix 전에는
    시각이 엉뚱한 값이라, 이 가드가 없으면 **부팅하자마자 report_due_at 이 과거로 보여
    신고가 나간다.** 재부팅에 40초 걸린 경우와 시계가 1970년인 경우를 구분할 방법이
    이것뿐이다.
    """
    if due_at is None:
        return False
    if config.BLOCK_AUTO_TRANSITIONS_WHEN_CLOCK_INVALID and not clock_valid:
        return False
    return now >= due_at


# ── 발사 검증 (DES-38 §6) ────────────────────────────────────────────
def validate_launch(
    solution: LaunchSolution | None,
    *,
    now: int,
    is_loaded: bool,
    clock_valid: bool = True,
) -> str | None:
    """발사해도 되는가. 되면 None, 아니면 `pi_launch.fail_reason` 값.

    **Pi 는 Jetson 이 보낸 각도를 그대로 믿지 않는다.** 조준 해를 내는 쪽과
    실제로 쏘는 쪽을 분리한 이유가 이 검증이다 (DES-38 §5).

    순서가 의미를 갖는다 — 먼저 걸리는 것이 보고되는 사유가 된다.
    '해가 없다'와 '장전이 안 됐다'가 동시면 전자를 보고해야 원인 추적이 쉽다.
    """
    # 1. 조준 해 자체가 없다. 탐지는 유효하지만 쏠 수가 없다.
    #    Jetson 이 GPS 를 못 받고 있을 때가 대표적이다 (jetson/status.gps_received=false).
    if solution is None:
        return "NO_SOLUTION"

    # 2. 보정 범위 밖. 소프트 리밋이라 기구가 물리적으로 갈 수 있어도 거부한다.
    if not (config.YAW_MIN_DEG <= solution.target_yaw_deg <= config.YAW_MAX_DEG):
        return "OUT_OF_RANGE"
    if not (config.PITCH_MIN_DEG <= solution.target_pitch_deg <= config.PITCH_MAX_DEG):
        return "OUT_OF_RANGE"

    # 3. 미등록 프로파일. AI 가 임의의 힘 값을 모터로 직접 보내지 못하게 하는 장치다.
    #    ⚠ DES-37 §4 스프링 실측 전에는 어떤 프로파일도 승인되지 않는다.
    if solution.launch_profile not in config.APPROVED_LAUNCH_PROFILES:
        return "OUT_OF_RANGE"

    # 4. 만료. 배가 10노트면 1초에 약 5m 움직이므로 묵은 해는 목표점이 어긋나 있다.
    #    시계를 못 믿으면 만료 판정도 못 하므로 건너뛴다 — 여기서 거부해버리면
    #    GPS fix 전에는 영영 못 쏜다.
    if clock_valid and now - solution.solved_at > config.LAUNCH_SOLUTION_TTL_SEC:
        return "OUT_OF_RANGE"

    # 5. 장전 안 됨 (IOT-04 물리 스위치, E4)
    if not is_loaded:
        return "NOT_LOADED"

    return None


# ── 사고 유형 → 신고 등급 ────────────────────────────────────────────
def route(accident_type: AccidentType, *, roll_deg: float | None = None) -> tuple[ReportType, int | None]:
    """사고 유형에서 신고 등급과 DSC 코드를 정한다.

    ⚠ 이 매핑은 Pi 와 Backend 양쪽에 **중복 구현하면 안 된다** (상세기획 §8 지침).
      contracts.ACCIDENT_ROUTING 한 곳에만 둔다.

    FLOODING 만 IMU 기울기로 갈린다 — 101(침수) / 104(전복 위험).
    임계 각도 `미정`⚠️ TODO(IoT). 기본은 침수로 둔다.
    """
    report_type, dsc = ACCIDENT_ROUTING[accident_type]

    if accident_type is AccidentType.FLOODING and roll_deg is not None:
        # TODO(IoT): 전복 판정 임계 롤 각 확정 필요.
        #   ⚠ IMU 의 roll 은 **각도(deg)** 다. ERD 주석의 deg/s 로 읽으면 이 판정이 무의미해진다.
        CAPSIZE_ROLL_DEG = 45.0
        if abs(roll_deg) >= CAPSIZE_ROLL_DEG:
            return report_type, 104

    return report_type, dsc

"""도메인 모델. ORM 도 아니고 와이어 페이로드도 아니다.

셋을 구분하는 이유:

    contracts.py   와이어    — 선을 타는 모양. 버전이 붙고 모르는 필드를 무시한다
    domain.py      도메인    — core 가 다루는 모양. I/O 를 모른다      ← 여기
    models.py      ORM       — SQLite 에 앉는 모양

필드명은 셋 다 같게 유지한다(snake_case, DB 컬럼명과 동일). 그래서 변환이 거의 없다.
그렇다고 하나로 합치지는 않는다 — 와이어에 버전 필드가 생기거나 DB 에 인덱스용
컬럼이 붙을 때 도메인이 같이 흔들리면 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from floaq.contracts import AccidentStatus, AccidentType, ReportType, TriggerSource


@dataclass(frozen=True, slots=True)
class Accident:
    """진행 중이거나 종료된 사고 하나. `pi_accident` 와 1:1.

    frozen 인 이유: 상태 전이를 **새 객체 생성**으로 표현하면 "언제 무엇이 바뀌었는지"가
    호출부에 드러난다. 제자리에서 필드를 고치면 전이 이력을 남기는 걸 빠뜨리기 쉽다.
    """

    accident_id: str
    ship_id: str
    status: AccidentStatus
    accident_type: AccidentType
    trigger_source: TriggerSource
    report_type: ReportType
    report_dsc: int | None
    accident_lat: float | None
    accident_lon: float | None
    #: 그 사고에 적용된 대기 시간. 전역 설정이 아니라 **행마다 박제**한다 —
    #: 나중에 30초를 바꿔도 과거 기록이 흔들리지 않는다.
    wait_sec: int
    #: 자동 신고 예정 절대 시각. WAIT 일 때만 값이 있다.
    report_due_at: int | None
    model_version: str | None
    created_at: int
    updated_at: int
    rescued_at: int | None = None
    closed_at: int | None = None

    def with_status(
        self,
        status: AccidentStatus,
        *,
        now: int,
        report_due_at: int | None = None,
        rescued_at: int | None = None,
        closed_at: int | None = None,
    ) -> Accident:
        """전이된 새 사고. `report_due_at` 은 WAIT 이 아니면 항상 지워진다.

        지우지 않으면 CANCEL·CLOSE 된 사고에 만료 시각이 남아서, 재부팅 복구 때
        '만료된 WAIT'으로 오인될 여지가 생긴다.
        """
        return replace(
            self,
            status=status,
            report_due_at=report_due_at if status is AccidentStatus.WAIT else None,
            rescued_at=rescued_at if rescued_at is not None else self.rescued_at,
            closed_at=closed_at if closed_at is not None else self.closed_at,
            updated_at=now,
        )


@dataclass(frozen=True, slots=True)
class StateTransition:
    """상태 변경 한 건. `pi_accident_state` 와 1:1.

    **append-only 다.** 덮어쓰면 S-05 타임라인이 사라지고, DES-38 §9 의
    "전원 재인가 시 자동 발사하지 않음"을 증명할 근거도 없어진다.
    """

    accident_id: str
    status: AccidentStatus
    prev_status: AccidentStatus | None
    reason: str
    #: 이 변경을 유발한 command 의 request_id. 감사용.
    #: TIMEOUT·AI_DETECT 처럼 명령 없이 일어난 변경은 None 이다.
    caused_by: str | None
    created_at: int


@dataclass(frozen=True, slots=True)
class LaunchRecord:
    """투하 시도 한 건. `pi_launch` 와 1:1. 사고당 하나 — 재투하는 없다 (E5)."""

    accident_id: str
    detection_id: str | None
    result: str                      # 'SUCCESS' | 'FAILED'
    fail_reason: str | None
    launch_lat: float
    launch_lon: float
    target_lat: float | None
    target_lon: float | None
    #: 실제로 명령한 각도. 소프트 리밋에 걸리면 Jetson 이 보낸 target 과 다를 수 있다.
    horizontal_angle: float
    vertical_angle: float
    confidence_score: float | None
    created_at: int

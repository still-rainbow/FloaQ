"""키오스크가 발행하는 페이로드.

키오스크는 표시와 명령만 한다 — 도메인 상태를 소유하지 않는다.
GPS 를 Pi 로 옮긴 뒤로는 센서 발행도 없어서, 남은 건 사람이 누른 버튼뿐이다.
"""

from __future__ import annotations

from typing import Literal

from floaq.contracts.enums import AccidentStatus, AccidentType
from floaq.contracts.types import Base, Lat, Lon, Uuid

class CommandBase(Base):
    accident_id: Uuid
    issued_by: Literal["TABLET"] = "TABLET"


class CommandCancel(CommandBase):
    """WAIT 에서만 유효 (APP-04)."""


class CommandReportNow(CommandBase):
    """WAIT 에서만 유효 (APP-05)."""


class CommandRescue(CommandBase):
    """REPORT 에서만 유효 (APP-10)."""


class CommandClose(CommandBase):
    """REPORT 에서만 유효 (APP-11)."""


class CommandReportManual(Base):
    """진행 중 사고가 없을 때만 유효 (APP-06).

    accident_id 를 키오스크가 UUID v7 로 만든다 — 재전송해도 같은 ID 라 사고가 중복되지 않는다.
    """

    accident_id: Uuid
    accident_type: AccidentType
    lat: Lat
    lon: Lon
    issued_by: Literal["TABLET"] = "TABLET"


class CommandResult(Base):
    """`pi/command/response` 의 data. 거부일 때도 현재 status 를 실어준다 —
    사유만 받으면 키오스크가 화면을 무엇으로 되돌릴지 모른다."""

    accident_id: Uuid
    command: Literal["cancel", "report_now", "report_manual", "rescue", "close"]
    status: AccidentStatus


# 상태별 유효 명령. Pi 는 이 조합만 받아들이고 나머지는 INVALID_STATE 로 거부한다.
VALID_COMMAND_STATES: dict[str, frozenset[AccidentStatus | None]] = {
    "cancel": frozenset({AccidentStatus.WAIT}),
    "report_now": frozenset({AccidentStatus.WAIT}),
    "rescue": frozenset({AccidentStatus.REPORT}),
    "close": frozenset({AccidentStatus.REPORT}),
    "report_manual": frozenset({None}),   # 진행 중 사고가 없어야 한다
}

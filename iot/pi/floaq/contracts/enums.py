"""열거형과 라우팅 표.

`StrEnum` 인 이유: `use_enum_values=True` 와 함께 쓰면 직렬화가 문자열이고,
SQLite STRICT 의 TEXT 컬럼에 변환 없이 그대로 들어간다.
"""

from __future__ import annotations

from enum import StrEnum

class AccidentStatus(StrEnum):
    DETECT = "DETECT"
    WAIT = "WAIT"
    REPORT = "REPORT"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"


class ReportType(StrEnum):
    """신고 등급. `확정` 2026-09-17 — 둘뿐이다.

    ⚠ SAFETY 를 뺐다. SAFETY 는 항행경보 수준(암초·부유물 발견 같은)이라 익수자
      구조 시스템에서 누를 일이 없었다. `api.json` 의 IPiAccident 와 같다.
    """

    DISTRESS = "DISTRESS"
    URGENCY = "URGENCY"


class TriggerSource(StrEnum):
    AI = "AI"
    MANUAL = "MANUAL"


class AccidentType(StrEnum):
    MOB = "MOB"                        # 인명 추락      DISTRESS  dsc 110
    FIRE = "FIRE"                      # 선박 화재      DISTRESS  dsc 100
    FLOODING = "FLOODING"              # 침수/전복      DISTRESS  dsc 101|104 (IMU 로 결정)
    COLLISION = "COLLISION"            # 충돌          DISTRESS  dsc 102
    GROUNDING = "GROUNDING"            # 좌초          DISTRESS  dsc 103
    ENGINE_FAILURE = "ENGINE_FAILURE"  # 기관 고장      DISTRESS  dsc 106
    OTHER_DISTRESS = "OTHER_DISTRESS"  # 기타 조난      DISTRESS  dsc 107
    MEDICAL = "MEDICAL"                # 응급 환자      URGENCY

    # ⚠ 8종이다 `확정` 2026-09-17. `api.json` 의 IPiAccident 와 글자까지 같다.
    #   HAZARD(위험물 발견) — 항행경보라 SAFETY 등급이었는데 SAFETY 가 사라져 갈 곳이 없다.
    #   ABANDON_SHIP(퇴함) — 1차 범위에서 뺐다. 되살린다면 (DISTRESS, 108) 이다:
    #     DSC 의 category 108(safety)과 nature of distress 108(abandoning ship)은 다른 표고,
    #     퇴선은 조난이다. 이 자리에 그 사실을 남겨 두는 이유는 다시 넣을 때 또 틀리지 않게다.


class ReportChannel(StrEnum):
    AIS_MOB = "AIS_MOB"
    AIS_SART = "AIS_SART"
    DSC = "DSC"


class DeviceHealth(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class ImuPosition(StrEnum):
    HULL = "HULL"
    CAMERA_L = "CAMERA_L"
    CAMERA_R = "CAMERA_R"


class ErrorCode(StrEnum):
    INVALID_STATE = "INVALID_STATE"
    ACCIDENT_NOT_FOUND = "ACCIDENT_NOT_FOUND"
    ACCIDENT_IN_PROGRESS = "ACCIDENT_IN_PROGRESS"
    DEVICE_ERROR = "DEVICE_ERROR"


# 사고 유형 → (신고 등급, DSC 코드). 한 곳에만 둔다 — Pi 와 Backend 에 중복 구현 금지.
# FLOODING 만 IMU 기울기로 101(침수)/104(전복 위험)이 갈린다.
ACCIDENT_ROUTING: dict[AccidentType, tuple[ReportType, int | None]] = {
    AccidentType.MOB: (ReportType.DISTRESS, 110),
    AccidentType.FIRE: (ReportType.DISTRESS, 100),
    AccidentType.FLOODING: (ReportType.DISTRESS, 101),
    AccidentType.COLLISION: (ReportType.DISTRESS, 102),
    AccidentType.GROUNDING: (ReportType.DISTRESS, 103),
    AccidentType.ENGINE_FAILURE: (ReportType.DISTRESS, 106),
    AccidentType.OTHER_DISTRESS: (ReportType.DISTRESS, 107),
    # URGENCY 는 M.493 nature 표에 대응이 없어 DSC 코드가 비어 있다.
    AccidentType.MEDICAL: (ReportType.URGENCY, None),
}

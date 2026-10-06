"""MQTT 와이어 계약. Pi · Jetson · 키오스크가 공유하는 유일한 정본.

문서(docs/edge/mqtt.md)가 아니라 **이 패키지가 계약이다.** 문서와 어긋나면 이쪽이 맞다.
다른 팀에는 `python -m floaq.contracts` 로 뽑은 JSON Schema 를 넘긴다.

── 모듈 구성 ────────────────────────────────────────────────────────
토픽 트리(`ship/{ship_id}/{pi|jetson|kiosk}/...`)와 같은 축으로 나눴다.
"누가 발행하는가"가 이 시스템의 중심 개념이라 파일 경계도 거기 맞추는 게 읽기 쉽다.

    types.py      값 타입 별칭 (Unix, Lat, Lon, Deg …) + Base
    enums.py      열거형 + 사고유형→신고등급 라우팅
    envelope.py   Envelope / CommandAck / ErrorInfo
    jetson.py     Jetson 이 발행하는 것
    pi.py         Pi 가 발행하는 것
    kiosk.py      키오스크가 발행하는 것
    topics.py     토픽 → (타입, QoS, retain)

    lora.py       ⚠ MQTT 가 아니다. 부표 LoRa 고정 19바이트 이진 프레임.
                  airtime 이 비용이라 JSON 봉투를 못 쓴다. 규약이 따로다.
                  여기서 재수출하지 않는다 — `from floaq.contracts.lora import ...`

── 규약 ─────────────────────────────────────────────────────────────
    시각   : Unix epoch **초** 정수. 밀리초 아님
    UUID   : UUID v7 문자열 36자. 문자열 정렬이 곧 시간 순서
    필드명 : snake_case. SQLite 컬럼명과 같아서 변환 계층이 없다
    좌표   : lon (lng 금지)

── 문서에서 의도적으로 벗어난 곳 ────────────────────────────────────
선박 GPS 는 **Pi 가 발행**한다 (`pi/sensor/gps`). mqtt.md 는 아직 키오스크 발행으로
적혀 있으나 2026-09-11 에 Pi 에 GPS 모듈을 달기로 정했다. 시각 기준(GPS UTC)도 여기서 온다.

── 타입 층 ──────────────────────────────────────────────────────────
    contracts/   와이어   (pydantic)        ← 여기
    core/domain  도메인   (frozen dataclass)
    sqlite row   저장     (TEXT/INTEGER/REAL)

셋을 합치지 않는다. 와이어엔 봉투(`v`·`request_id`)가 붙고 도메인엔 없어야 하며,
`AccidentState.reason`·`prev_status` 는 **전이 시점에만** 존재해서 도메인 객체에 자리가 없다.
"""

from __future__ import annotations

from floaq.contracts.enums import (
    ACCIDENT_ROUTING,
    AccidentStatus,
    AccidentType,
    DeviceHealth,
    ImuPosition,
    ReportChannel,
    ReportType,
    TriggerSource,
)
from floaq.contracts.envelope import CommandAck, Envelope, ErrorCode, ErrorInfo
from floaq.contracts.jetson import (
    AccidentSnapshot,
    AimCommand,
    JetsonDetection,
    JetsonStatus,
    LaunchSolution,
)
from floaq.contracts.kiosk import (
    VALID_COMMAND_STATES,
    CommandBase,
    CommandCancel,
    CommandClose,
    CommandReportManual,
    CommandReportNow,
    CommandRescue,
    CommandResult,
)
from floaq.contracts.pi import (
    AccidentState,
    BuoyDrift,
    BuoyPosition,
    DeviceStatus,
    LaunchResult,
    OnlineStatus,
    ReportStatus,
    SensorGps,
    SensorImu,
)
from floaq.contracts.topics import PUBLISHERS, TOPICS, parse_topic, topic
from floaq.contracts.types import (
    Base,
    Bearing,
    Confidence,
    Deg,
    Lat,
    Lon,
    Unix,
    Uuid,
)

__all__ = [
    # types
    "Base", "Bearing", "Confidence", "Deg", "Lat", "Lon", "Unix", "Uuid",
    # enums
    "ACCIDENT_ROUTING", "AccidentStatus", "AccidentType", "DeviceHealth",
    "ImuPosition", "ReportChannel", "ReportType", "TriggerSource",
    # envelope
    "CommandAck", "Envelope", "ErrorCode", "ErrorInfo",
    # jetson
    "AccidentSnapshot", "AimCommand", "JetsonDetection", "JetsonStatus", "LaunchSolution",
    # pi
    "AccidentState", "BuoyDrift", "BuoyPosition", "DeviceStatus", "LaunchResult",
    "OnlineStatus", "ReportStatus", "SensorGps", "SensorImu",
    # kiosk
    "VALID_COMMAND_STATES", "CommandBase", "CommandCancel", "CommandClose",
    "CommandReportManual", "CommandReportNow", "CommandRescue", "CommandResult",
    # topics
    "PUBLISHERS", "TOPICS", "parse_topic", "topic",
]

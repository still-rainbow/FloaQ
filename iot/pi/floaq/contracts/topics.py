"""토픽 트리와 토픽별 (타입, QoS, retain).

발행 측과 구독 측이 **같은 표 하나**를 본다. 두 곳에 적으면 갈라진다.

⚠ `pi/online` · `kiosk/online` 만 **봉투(Envelope)를 쓰지 않는다.**
  LWT 페이로드는 접속 시점에 고정되므로 `request_id`·`ts` 를 의미 있게 채울 수 없다
  (mqtt.md §1.4 — `ts` 는 0 으로 둔다). 날것 그대로 `{"online": bool, "ts": int}` 다.
  수신 측은 이 둘을 따로 처리해야 한다.
"""

from __future__ import annotations

from pydantic import BaseModel

from floaq.contracts.jetson import AimCommand, AccidentSnapshot, JetsonDetection, JetsonStatus
from floaq.contracts.kiosk import (
    CommandCancel, CommandClose, CommandReportManual, CommandReportNow,
    CommandRescue, CommandResult,
)
from floaq.contracts.pi import (
    AccidentState, BuoyDrift, BuoyPosition, DeviceStatus, LaunchResult,
    OnlineStatus, ReportStatus, SensorGps, SensorImu,
)

#: 봉투를 쓰지 않는 토픽. LWT 라서 페이로드가 접속 시점에 고정된다.
RAW_TOPICS = frozenset({"pi/online", "kiosk/online"})


PUBLISHERS = ("pi", "jetson", "kiosk")


def topic(ship_id: str, publisher: str, subject: str) -> str:
    if publisher not in PUBLISHERS:
        raise ValueError(f"발행자는 {PUBLISHERS} 중 하나여야 한다: {publisher}")
    return f"ship/{ship_id}/{publisher}/{subject}"


def parse_topic(t: str) -> tuple[str, str, str]:
    """'ship/{id}/pi/accident/state' → (ship_id, 'pi', 'accident/state')"""
    parts = t.split("/")
    if len(parts) < 4 or parts[0] != "ship":
        raise ValueError(f"토픽 형식이 아니다: {t}")
    return parts[1], parts[2], "/".join(parts[3:])


# 토픽별 (페이로드 타입, QoS, retain). 발행·구독 양쪽이 이 표 하나를 본다.
TOPICS: dict[str, tuple[type[BaseModel], int, bool]] = {
    "jetson/detection":     (JetsonDetection, 1, False),
    "jetson/aim":           (AimCommand, 0, False),
    "jetson/snapshot":      (AccidentSnapshot, 1, True),
    "jetson/status":        (JetsonStatus, 1, True),
    "pi/accident/state":    (AccidentState, 1, True),
    "pi/launch/result":     (LaunchResult, 1, True),
    "pi/buoy/position":     (BuoyPosition, 0, False),
    "pi/buoy/drift":        (BuoyDrift, 1, True),
    "pi/sensor/imu":        (SensorImu, 0, False),
    "pi/sensor/gps":        (SensorGps, 0, True),
    "pi/device/status":     (DeviceStatus, 1, True),
    "pi/report/status":     (ReportStatus, 1, True),
    "pi/command/response":  (CommandResult, 1, False),
    "pi/online":            (OnlineStatus, 1, True),
    "kiosk/command/cancel":         (CommandCancel, 1, False),
    "kiosk/command/report_now":     (CommandReportNow, 1, False),
    "kiosk/command/report_manual":  (CommandReportManual, 1, False),
    "kiosk/command/rescue":         (CommandRescue, 1, False),
    "kiosk/command/close":          (CommandClose, 1, False),
    "kiosk/online":                 (OnlineStatus, 1, True),
}

# retain 을 거는 것은 "지금 상태가 무엇인가"뿐이다.
# kiosk/command/* 에 retain 을 걸면 Pi 가 재접속할 때마다 30분 전 [즉시 신고]가 되살아난다.
assert not any(r for t, (_, _, r) in TOPICS.items() if t.startswith("kiosk/command/"))

"""Pi 가 발행하는 페이로드.

Pi 가 오케스트레이터라 가짓수가 제일 많다. 사고 상태·투하 결과·부표·센서·신고·장비.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from floaq.contracts.enums import (
    AccidentStatus, DeviceHealth, ImuPosition, ReportChannel,
)
from floaq.contracts.types import (
    Base, Bearing, Confidence, Deg, HalfBearing, Lat, Lon, Meters, Unix, Uuid,
)

class AccidentState(Base):
    """`pi/accident/state` — retained. **현재 사고의 유일한 진실.**

    재접속 시 다른 retained 의 accident_id 를 이것과 대조해서 다르면 버린다.
    """

    accident_id: Uuid
    status: AccidentStatus
    prev_status: AccidentStatus | None
    reason: Literal[
        "AI_DETECT", "COUNTDOWN_START", "TIMEOUT",
        "TABLET_CANCEL", "TABLET_REPORT_NOW", "TABLET_MANUAL",
        "TABLET_RESCUE", "TABLET_CLOSE",
    ]
    caused_by: str | None    # 이 변경을 유발한 command 의 request_id. 감사용
    report_due_at: Unix | None   # WAIT 일 때만. **키오스크는 자체 타이머를 돌리지 않는다**
    changed_at: Unix

    @model_validator(mode="after")
    def _due_when_wait(self):
        if self.status == AccidentStatus.WAIT and self.report_due_at is None:
            raise ValueError("WAIT 이면 report_due_at 이 있어야 한다")
        return self


class LaunchResult(Base):
    """`pi/launch/result` — retained. E5(발사 실패)는 재발사 없이 알림만."""

    accident_id: Uuid
    detection_id: Uuid | None        # 어느 탐지의 조준 해로 쐈는지
    result: Literal["SUCCESS", "FAILED"]
    fail_reason: Literal["NOT_LOADED", "DEVICE_ERROR", "OUT_OF_RANGE", "NO_SOLUTION"] | None
    launch_lat: Lat
    launch_lon: Lon
    target_lat: Lat | None
    target_lon: Lon | None
    horizontal_angle: Deg            # 실제 명령한 값. 소프트 리밋에 걸리면 target 과 다르다
    vertical_angle: Deg
    confidence_score: Confidence | None
    launched_at: Unix

    @model_validator(mode="after")
    def _reason_matches(self):
        if (self.result == "SUCCESS") != (self.fail_reason is None):
            raise ValueError("result 와 fail_reason 이 어긋난다")
        return self


class BuoyPosition(Base):
    """`pi/buoy/position` — QoS 0, 1초. 한 개 유실돼도 다음 게 온다."""

    accident_id: Uuid
    buoy_log_id: int
    seq: int                 # 부표가 매긴 순번. 유실 감지용
    lat: Lat
    lon: Lon
    is_pressed: Literal[0, 1]    # LoRa 패킷·SQLite 가 둘 다 정수라 bool 로 안 둔다
    measured_at: Unix        # 부표 GPS 측정 시각 — 지도에는 이걸 쓴다
    received_at: Unix        # Pi 가 LoRa 로 받은 시각
    rssi: float | None


class BuoyDrift(Base):
    """`pi/buoy/drift` — retained. 두절 중 현재 수색 범위 (APP-09)."""

    accident_id: Uuid
    estimate_id: int
    base_lat: Lat            # 마지막 LoRa 수신 위치
    base_lon: Lon
    last_received_at: Unix
    elapsed_sec: int
    center_lat: Lat          # 표류 예상 중심
    center_lon: Lon
    radius_m: float          # 시간에 따라 커진다
    # 1σ 타원. **배율을 먹이기 전 값이다** — 50/75/95% 는 같은 타원에 배율만
    # 다르므로(명세 §6), 미리 곱해 보내면 받는 쪽이 어느 배율인지 모르고 또 곱한다.
    # 🔴 표류는 원이 아니다. crosswind 불확실성이 바람 방향 불확실성보다 3배 커서
    #    타원은 보통 **바람 직각**으로 길다. 원으로 그리면 수색선이 엉뚱한 쪽을 훑는다.
    axis_major_m: Meters
    axis_minor_m: Meters
    axis_bearing_deg: HalfBearing
    # 부표와 사람은 풍력 표류 계수가 3배 차이난다. 같은 타원을 쓸 수 없다
    target: Literal["BUOY", "PERSON"]
    # 계산에 쓴 해양 데이터 스냅샷. 전부 None 이면 해양 데이터 없이 추정한 것.
    # input_observed_at 을 화면에 반드시 같이 띄운다 — 3시간 전 조류로 그린 원과
    # 3분 전 조류로 그린 원은 화면에서 똑같이 생겼다.
    input_current_speed: float | None
    input_current_dir: Bearing | None
    input_wind_speed: float | None
    input_wind_dir: Bearing | None
    input_observed_at: Unix | None
    estimated_at: Unix

    @model_validator(mode="after")
    def _axes_ordered(self):
        # 뒤집히면 타원이 90° 돌아간다. 화면은 그걸 알아챌 방법이 없다
        if self.axis_major_m < self.axis_minor_m:
            raise ValueError("장축이 단축보다 짧다")
        return self


class SensorImu(Base):
    """`pi/sensor/imu` — QoS 0. roll/pitch/yaw 는 **각도(deg)**, 각속도 아니다."""

    accident_id: Uuid | None
    imu_position: ImuPosition
    accel_x: float | None    # m/s^2
    accel_y: float | None
    accel_z: float | None
    roll: Deg
    pitch: Deg
    yaw: Deg
    heading_deg: Bearing | None   # GPS 로 보정한 방위
    measured_at: Unix


class SensorGps(Base):
    """`pi/sensor/gps` — retained, 1Hz. **Pi 가 발행한다.**

    speed_kn·heading_deg 는 Jetson 의 조준 해 입력이다 — 발사대가 움직이는 배 위에 있어서
    목표점이 '착수 예상 시점의 위치'여야 한다. 그래서 DB 기록(5초)과 달리 항상 1Hz 로 쏜다.
    """

    ship_id: Uuid
    lat: Lat
    lon: Lon
    speed_kn: float
    heading_deg: Bearing
    accuracy_m: float | None
    measured_at: Unix        # GPS UTC. Pi 의 시각 기준도 여기서 온다


class DeviceStatus(Base):
    """`pi/device/status` — retained, 5초 + 변화 시.

    변화 시에만 보내면 키오스크가 '값이 안 옴'과 'Pi 가 죽음'을 구분 못 한다.
    """

    is_loaded: bool          # 투하 장치 장전 (IOT-04 물리 스위치)
    camera_l: DeviceHealth
    camera_r: DeviceHealth
    camera_dirty: bool
    imu: DeviceHealth
    lora: DeviceHealth
    ai: DeviceHealth
    gps: DeviceHealth
    internet: bool           # false 면 키오스크가 '신고 불가'를 명시해야 한다
    last_buoy_rx_at: Unix | None


class ReportStatus(Base):
    """`pi/report/status` — retained, 채널당 1개. **발신 주체는 Pi 다.**"""

    accident_id: Uuid
    report_id: int
    channel: ReportChannel
    status: Literal["SENDING", "ACKED", "STOPPED", "FAILED"]
    sent_count: int
    first_sent_at: Unix | None
    last_sent_at: Unix | None
    acked_at: Unix | None    # DSC 만 값이 들어온다. AIS 는 단방향이라 ACK 이 없다
    acked_by: str | None     # ACK 을 보낸 국의 MMSI 9자리
    fail_reason: Literal["NO_INTERNET", "NO_RECEIVER", "TIMEOUT"] | None

    @model_validator(mode="after")
    def _ack_only_dsc(self):
        if self.acked_at is not None and self.channel != ReportChannel.DSC:
            raise ValueError("AIS 채널에는 ACK 이 올 수 없다")
        if (self.status == "ACKED") != (self.acked_at is not None):
            raise ValueError("status=ACKED 와 acked_at 은 항상 같이 간다")
        return self


class OnlineStatus(Base):
    """`pi/online` · `kiosk/online` — LWT. 페이로드가 접속 시점에 고정되므로 ts 는 의미 없다."""

    online: bool
    ts: Unix = 0

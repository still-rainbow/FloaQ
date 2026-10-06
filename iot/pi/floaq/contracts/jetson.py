"""Jetson 이 발행하는 페이로드.

Jetson 은 "사람을 봤고 쏜다면 이 각도다"까지만 말한다. 사고 판정은 Pi 가 한다.
"""

from __future__ import annotations

from typing import Literal

from floaq.contracts.enums import DeviceHealth
from floaq.contracts.types import Base, Bearing, Confidence, Deg, Lat, Lon, Unix, Uuid

class LaunchSolution(Base):
    """조준 해. Jetson 이 계산한다 — 스테레오 거리·선박 GPS·침로가 거기 모여 있다."""

    target_yaw_deg: Deg      # 선수 기준. 명목 -45 ~ +45. 보정 범위 밖이면 Pi 가 거부
    target_pitch_deg: Deg    # 수평 기준. 명목 0 ~ 45
    launch_profile: str      # 등록된 프로파일만. 미등록이면 Pi 가 거부
    target_lat: Lat
    target_lon: Lon
    solved_at: Unix          # 해를 계산한 시각. 만료 판정 기준


class AimCommand(Base):
    """`jetson/aim` — 수동 발사 시험용 최신 조준 명령. 해제 권한은 없다."""

    target_yaw_deg: Deg
    target_pitch_deg: Deg
    confidence: Confidence
    track_id: int | None = None
    solved_at: Unix


class JetsonDetection(Base):
    """`jetson/detection` — Jetson 은 '사람을 봤고 쏜다면 이 각도다'까지만 말한다.

    사고 판정은 Pi 가 한다. 그래서 accident_id 가 없다.
    """

    detection_id: Uuid
    ship_id: Uuid
    lat: Lat                 # 추락 추정 위치
    lon: Lon
    distance_m: float        # 스테레오 거리 (AI-03)
    confidence: Confidence
    frame_count: int         # 연속 탐지 프레임 수 (AI-02 근거)
    model_version: str
    camera: Literal["L", "R"]
    bbox: tuple[int, int, int, int] | None   # x, y, w, h
    detected_at: Unix
    launch: LaunchSolution | None            # 해를 못 내면 None → 발사 불가, 탐지는 유효


class AccidentSnapshot(Base):
    """`jetson/snapshot` — retained. 사고당 1회라 놓치면 다시 안 온다."""

    accident_id: Uuid
    format: Literal["jpeg"]
    width: int
    height: int
    bytes: int               # base64 디코드 후 크기
    data: str                # base64. data: 접두사 없음
    captured_at: Unix
    confidence: Confidence
    bbox: tuple[int, int, int, int] | None
    camera: Literal["L", "R"]


class JetsonStatus(Base):
    """`jetson/status` — retained, 5초. LWT 대신 이걸로 생존을 본다(15초 미수신이면 죽음)."""

    model_version: str
    inference_fps: float
    camera_l: DeviceHealth
    camera_r: DeviceHealth
    camera_dirty: bool       # AI-06 이물질
    gps_received: bool       # pi/sensor/gps 를 받고 있는가 — false 면 조준 해를 못 낸다
    uptime_sec: int

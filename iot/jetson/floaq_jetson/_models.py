"""와이어 스키마. `iot/pi/floaq/contracts/` 의 거울이다.

**왜 import 하지 않고 거울을 두는가.** Jetson 이 Pi 저장소 경로에 의존하면 배포가
둘로 묶인다 — Pi 코드를 고칠 때마다 Jetson 을 다시 밀어야 한다. 대신 갈라짐은
런타임에 잡는다: `Floaq.start()` 가 Pi 의 `/contract.json` 을 받아 필드 집합을
대조하고, 다르면 **경고를 남긴다**(§verify_against).

🔴 **손으로 검사식을 쓰지 않는다.** `if not -90 <= lat <= 90` 같은 코드는 정본과
   갈라져도 아무도 모른다. pydantic 이 한 곳에서 하면 메시지도 필드명을 달고 나온다.

⚠ `extra="forbid"` 다. Pi 쪽 `Base` 는 `extra="ignore"`(수신 측이라 관대해야 한다)
  인데, **보내는 쪽은 반대**여야 한다 — 오타 난 필드를 조용히 버리면 그 값이 영영
  안 간다. `distanc_m=12.4` 가 통과해서 거리가 늘 0 인 상태를 시연 날 발견하게 된다.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

# ── 값 타입 ──────────────────────────────────────────────────────────
# Pi 의 contracts/types.py 와 같은 제약이다. 모양이 아니라 **범위**가 핵심이다.
Unix = StrictInt
Uuid = Annotated[str, Field(min_length=36, max_length=36)]
Deg = float
Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]
Confidence = Annotated[float, Field(ge=0, le=1)]


class _Out(BaseModel):
    """내보내는 페이로드의 기반."""

    model_config = ConfigDict(extra="forbid")


class LaunchSolution(_Out):
    """조준 해. Jetson 이 계산한다 — 스테레오 거리·선박 GPS·침로가 여기 모여 있다.

    ⚠ 범위는 명목값이고 Pi 가 다시 검증한다. 여기서 막지 않는 이유: 보정 범위는
      장비 설정(DES-38)이라 SDK 가 알 수 없고, 여기서 막으면 장비를 바꿀 때마다
      Jetson 을 다시 배포해야 한다.
    """

    target_yaw_deg: Deg
    target_pitch_deg: Deg
    launch_profile: str = Field(min_length=1)
    target_lat: Lat
    target_lon: Lon
    solved_at: Unix


class AimCommand(_Out):
    """Latest-only yaw/pitch command. It never authorizes release."""

    target_yaw_deg: Deg
    target_pitch_deg: Deg
    confidence: Confidence
    track_id: int | None = None
    solved_at: Unix


class JetsonStatus(_Out):
    """`jetson/status` — retained, 5초.

    🔴 **Pi 는 이걸로 젯슨의 생존을 본다** (LWT 대신). 15초 미수신이면 죽은 것으로
       친다. 그리고 카메라 L/R 과 AI 의 상태는 젯슨만 알기 때문에, 이게 안 나가면
       키오스크의 장치 패널이 통째로 '모름' 으로 남는다 — 실제로 그 상태였다
       (2026-09-22, 계약과 받는 쪽은 있는데 보내는 쪽이 없었다).
    """

    model_version: str = Field(min_length=1)
    inference_fps: float = Field(ge=0)
    camera_l: Literal["OK", "ERROR", "UNKNOWN"]
    camera_r: Literal["OK", "ERROR", "UNKNOWN"]
    #: AI-06 이물질. 아직 판정하는 코드가 없어 늘 False 다
    camera_dirty: bool
    #: `pi/sensor/gps` 를 받고 있는가. false 면 조준 해를 못 낸다
    gps_received: bool
    uptime_sec: StrictInt


class JetsonDetection(_Out):
    """`jetson/detection`.

    `accident_id` 가 **없다.** Jetson 은 사고 번호를 모른다 — Pi 가 사고를 열고
    `pi/accident/state` 로 알려준다.
    """

    detection_id: Uuid
    ship_id: Uuid
    lat: Lat
    lon: Lon
    distance_m: Annotated[float, Field(ge=0)]
    confidence: Confidence
    frame_count: Annotated[int, Field(ge=1)]
    model_version: str = Field(min_length=1)
    camera: Literal["L", "R"]
    bbox: tuple[int, int, int, int] | None
    detected_at: Unix
    launch: LaunchSolution | None

    @model_validator(mode="after")
    def _bbox_is_positive(self):
        # 🔴 w·h 가 0 이면 키오스크가 상자를 못 그린다. 그림만 안 나오고 오류는 없어서
        #   화면을 직접 보기 전까지 모른다
        if self.bbox is not None and (self.bbox[2] <= 0 or self.bbox[3] <= 0):
            raise ValueError("bbox 의 w·h 는 0 보다 커야 한다")
        return self


#: `/contract.json` 대조에 쓸 토픽 이름. Pi 가 이 키로 스키마를 내려준다.
DETECTION_TOPIC = "jetson/detection"


def verify_against(contract: dict) -> list[str]:
    """Pi 의 `/contract.json` 과 필드 집합을 대조한다. 어긋난 것들을 돌려준다.

    ⚠ **예외를 던지지 않는다.** 계약이 갈라졌다고 탐지를 멈추면, 필드 하나 늘어난
      것 때문에 사람을 못 건진다. 경고만 하고 계속 보낸다 — 모르는 필드는 Pi 가
      무시하도록(`extra="ignore"`) 돼 있다.
    """
    topics = contract.get("topics") or {}
    spec = topics.get(DETECTION_TOPIC)
    if not isinstance(spec, dict):
        return [f"{DETECTION_TOPIC} 가 계약에 없다 — Pi 가 구버전이거나 토픽 이름이 바뀌었다"]

    remote = _field_names(spec)
    if not remote:
        return []
    local = set(JetsonDetection.model_fields)
    out = []
    if missing := remote - local:
        out.append(f"Pi 가 요구하는데 SDK 에 없는 필드: {sorted(missing)}")
    if extra := local - remote:
        out.append(f"SDK 가 보내는데 Pi 계약에 없는 필드: {sorted(extra)}")
    return out


def _field_names(spec: dict) -> set[str]:
    """계약 조각에서 필드 이름을 꺼낸다. 모양이 몇 가지라 다 받아 준다."""
    for key in ("properties", "fields"):
        if isinstance(spec.get(key), dict):
            return set(spec[key])
    payload = spec.get("payload")
    if isinstance(payload, dict):
        return _field_names(payload)
    return set()

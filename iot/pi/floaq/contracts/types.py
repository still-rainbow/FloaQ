"""값 타입 별칭과 모든 페이로드의 기반 클래스.

여기 있는 것은 **모양이 아니라 제약**이다. `Lat` 은 float 이지만 -90~90 이고,
`Unix` 는 int 이지만 실수를 거부한다. 페이로드마다 범위를 다시 적지 않으려고 모아 뒀다.
"""

from __future__ import annotations

from typing import Annotated, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt

T = TypeVar("T")

# ── 별칭 ──────────────────────────────────────────────────────────────
# StrictInt 인 이유: SQLite STRICT 는 1757000000.0 을 조용히 정수로 바꿔 넣는다.
# 실측으로 확인함 — 막아주지 않는다. 앱에서 거부해야 한다.
Unix = StrictInt
Uuid = Annotated[str, Field(min_length=36, max_length=36)]
Deg = float
Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]
Bearing = Annotated[float, Field(ge=0, le=360)]
#: 타원 축의 방위. 0~180 이다 — 타원은 180° 대칭이라 90° 와 270° 가 같은 축이다.
#: `Bearing` 을 쓰면 같은 축을 두 가지로 적을 수 있고, 두 추정을 비교할 수가 없다.
HalfBearing = Annotated[float, Field(ge=0, lt=180)]
#: 거리·반경. 음수가 없다
Meters = Annotated[float, Field(ge=0)]
Confidence = Annotated[float, Field(ge=0, le=1)]


class Base(BaseModel):
    # 모르는 필드는 무시하고 진행한다. 송신 측이 필드를 추가해도 수신 측이 안 죽는다.
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

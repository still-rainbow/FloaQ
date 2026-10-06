"""봉투. 모든 메시지가 이 둘 중 하나에 담긴다.

`Request`/`Response` 로 부르지 않는 이유는 둘이 짝이 아니기 때문이다 —
트래픽의 대부분이 단방향이고 대응하는 응답이 영영 오지 않는다.
실제 요청-응답 쌍은 `kiosk/command/*` 하나뿐이다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal

from pydantic import model_validator

from floaq.contracts.types import Base, T, Unix


class ErrorCode(StrEnum):
    INVALID_STATE = "INVALID_STATE"
    ACCIDENT_NOT_FOUND = "ACCIDENT_NOT_FOUND"
    ACCIDENT_IN_PROGRESS = "ACCIDENT_IN_PROGRESS"
    DEVICE_ERROR = "DEVICE_ERROR"


class ErrorInfo(Base):
    code: ErrorCode      # string 아님 — 키오스크가 화면 분기에 쓴다
    message: str         # 로그용. 영어라 화면에 그대로 띄우지 말 것


class Envelope(Base, Generic[T]):
    """단방향 — 텔레메트리·이벤트·명령. 응답이 오는지는 봉투가 아니라 토픽이 정한다."""

    request_id: str          # UUID v7. 로그 상관 + 명령일 때는 응답 상관에도 쓴다
    v: Literal[1]            # 모르는 v 가 오면 ValidationError → 버리고 로그만
    ts: Unix                 # 발행 시각. data 안의 측정 시각과는 다르다
    data: list[T]            # 항상 배열. 단건도 길이 1 — 배치로 바꿔도 타입이 안 바뀐다


class ErrorInfo(Base):
    code: ErrorCode
    message: str             # 로그용. 영어라 화면에 그대로 띄우지 말 것 — 화면은 code 로 분기


class CommandAck(Base, Generic[T]):
    """kiosk/command/* 의 응답 전용."""

    request_id: str          # 요청의 request_id 를 그대로 반사
    v: Literal[1]
    ts: Unix
    is_success: bool
    error: ErrorInfo | None
    data: T                  # 언제나 1건. 배열이 아니다

    @model_validator(mode="after")
    def _consistent(self):
        if self.is_success != (self.error is None):
            raise ValueError("is_success 와 error 가 어긋난다")
        return self

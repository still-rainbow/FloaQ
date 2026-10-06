"""UUID v7 생성.

표준 `uuid` 모듈에는 Python 3.14 부터 들어간다. Pi 는 3.13 이라 직접 만든다 —
의존성 하나를 아끼려는 것이고, 구현이 10줄이라 그럴 만하다.

**v4 가 아니라 v7 이어야 하는 이유가 셋이다.**

1. 상위 48비트가 밀리초 타임스탬프라 **문자열 정렬이 곧 시간 순서**다.
   SQLite 에 TEXT 로 넣어도 `ORDER BY accident_id` 가 시간순이 된다.
2. 같은 이유로 B-tree 오른쪽 끝에 append 된다. v4 면 랜덤 삽입이라 페이지가 쪼개진다.
3. Pi 가 **인터넷 없이** 발급해도 서버와 충돌하지 않는다. 재전송 멱등의 근거가 이것이다.

레이아웃 (RFC 9562):
    48 bit  unix_ts_ms (big endian)
     4 bit  version = 7
    12 bit  rand_a
     2 bit  variant = 0b10
    62 bit  rand_b
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7(ts_ms: int | None = None) -> str:
    """UUID v7 문자열 36자.

    ts_ms 를 넘기면 그 시각으로 만든다 — 테스트에서 정렬 순서를 고정하는 데 쓴다.
    """
    if ts_ms is None:
        ts_ms = time.time_ns() // 1_000_000

    rand = os.urandom(10)

    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    # version 7 을 상위 니블에, 나머지 12비트는 랜덤
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]
    # variant 0b10 을 상위 2비트에
    b[8] = 0x80 | (rand[2] & 0x3F)
    b[9:16] = rand[3:10]

    return str(uuid.UUID(bytes=bytes(b)))


def uuid7_timestamp_ms(value: str) -> int:
    """UUID v7 에서 생성 시각(ms)을 되꺼낸다. 로그 추적·디버깅용."""
    return int.from_bytes(uuid.UUID(value).bytes[0:6], "big")

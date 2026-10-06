"""계약을 기계가 읽을 수 있는 형태로 뽑는다.

    python -m floaq.contracts            전체 JSON
    python -m floaq.contracts --topics   토픽 표만 (사람이 읽는 용)
    python -m floaq.contracts -o tools/contract.json

**파이썬이 정본이고 나머지는 이걸 읽는다.** 손으로 복제하면 갈라진다 —
이 프로젝트는 이미 그 실패를 겪었다(문서가 "13 테이블 / CHECK 67" 이라 적어둔 사이
실물은 9 테이블 / CHECK 0 이었다).

쓰는 곳
  tools/kiosk.html   토픽·유효 명령·enum 을 여기서 읽는다
  Jetson 팀          jetson/* 페이로드 스키마
  웹 팀              TS 타입 생성 (json-schema-to-typescript)
"""

from __future__ import annotations

import argparse
import json
import sys

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
from floaq.contracts.envelope import ErrorCode
from floaq.contracts.topics import PUBLISHERS, TOPICS

# ⚠ core 를 import 한다. contracts 가 core 를 의존하는 건 정상 방향이 아니지만,
#   "상태별 유효 명령"은 도메인 규칙이라 core 가 정본이다. 여기서 다시 적으면
#   그게 바로 없애려는 그 중복이 된다. 내보내기 전용 모듈이라 이 예외를 둔다.
from floaq.core.state import _COMMAND_VALID_IN, TRANSITIONS


def build() -> dict:
    return {
        "version": 1,
        "topic_pattern": "ship/{ship_id}/{publisher}/{subject}",
        "publishers": list(PUBLISHERS),
        "topics": {
            subject: {
                "payload": model.__name__,
                "qos": qos,
                "retain": retain,
                "publisher": subject.split("/", 1)[0],
                "schema": model.model_json_schema(),
            }
            for subject, (model, qos, retain) in sorted(TOPICS.items())
        },
        "enums": {
            e.__name__: [m.value for m in e]
            for e in (AccidentStatus, AccidentType, ReportType, TriggerSource,
                      ReportChannel, DeviceHealth, ImuPosition, ErrorCode)
        },
        # 사고 유형 -> (신고 등급, DSC 코드). Pi 와 Backend 에 중복 구현 금지 (상세기획 §8)
        "accident_routing": {
            t.value: {"report_type": rt.value, "dsc": dsc}
            for t, (rt, dsc) in ACCIDENT_ROUTING.items()
        },
        # 상태별 유효 명령. 키오스크가 버튼 활성화에 쓴다.
        # ⚠ Pi 가 정본이다. 키오스크는 힌트로만 쓰고, 실제 거부는 Pi 가 한다.
        "valid_command_states": {
            cmd: sorted(s.value if s else None for s in states)
            for cmd, states in _COMMAND_VALID_IN.items()
        },
        # (현재 상태, 사유) -> 다음 상태. 표에 없는 조합은 전부 거부한다.
        "transitions": [
            {"from": (f.value if f else None), "reason": r, "to": t.value}
            for (f, r), t in TRANSITIONS.items()
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m floaq.contracts")
    p.add_argument("-o", "--out", help="파일로 저장. 없으면 표준출력")
    p.add_argument("--topics", action="store_true", help="토픽 표만 사람이 읽는 형태로")
    args = p.parse_args()

    if args.topics:
        print("%-26s %-22s %3s %-6s %s" % ("subject", "payload", "QoS", "retain", "publisher"))
        print("-" * 76)
        for subject, (model, qos, retain) in sorted(TOPICS.items()):
            print("%-26s %-22s %3d %-6s %s"
                  % (subject, model.__name__, qos, "O" if retain else "-",
                     subject.split("/", 1)[0]))
        return 0

    text = json.dumps(build(), ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"{args.out}  ({len(text):,} bytes)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

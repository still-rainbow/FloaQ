"""진행 중 사고를 닫는다. 반복 시험용.

    uv run python tools/close_accident.py            사고 종료(close)
    uv run python tools/close_accident.py --rescue   구조 확정(rescue)

E1(선박당 진행 중 1건) 때문에 앞 사고가 열려 있으면 새 탐지가 409 로 거부된다.
그게 정상 동작이라 반복 시험을 하려면 매번 닫아야 한다.

⚠ 키오스크 명령 토픽으로 발행한다. 운영에서는 사람이 화면에서 누를 자리다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from floaq import config

#: 명령을 보내고 DB 가 바뀔 때까지 기다리는 시간(초).
#: Pi 의 MQTT 왕복 + SQLite 쓰기라 1초면 충분하지만 여유를 둔다.
WAIT_SEC = 10


def main() -> int:
    p = argparse.ArgumentParser(description="진행 중 사고를 닫는다")
    p.add_argument("--db", default="floaq.db")
    p.add_argument("--host", default=config.MQTT_HOST)
    p.add_argument("--port", type=int, default=config.MQTT_PORT_TCP)
    p.add_argument("--rescue", action="store_true",
                   help="구조 확정으로 닫는다. 기본은 사고 종료")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    ship = conn.execute("SELECT ship_id FROM pi_ship WHERE is_deleted = 0"
                        " LIMIT 1").fetchone()
    if ship is None:
        print("등록된 배가 없다", file=sys.stderr)
        return 2

    row = conn.execute(
        "SELECT accident_id, status FROM pi_accident"
        " WHERE status IN ('DETECT','WAIT','REPORT')"
        " ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        print("진행 중 사고가 없다. 바로 새 탐지를 보내면 된다")
        return 0

    accident_id, status = row
    command = "rescue" if args.rescue else "close"
    print(f"{status}  {accident_id}  ->  {command}")

    # ⚠ DETECT 는 아직 카운트다운 전이라 close 가 거부될 수 있다.
    #   그때는 Pi 로그의 pi/command/response 에 INVALID_STATE 가 남는다.
    payload = json.dumps({
        "request_id": str(uuid.uuid4()),
        "v": 1,
        "ts": int(time.time()),
        "data": [{"accident_id": accident_id}],
    }, ensure_ascii=False).encode()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        c.connect(args.host, args.port, 15)
    except OSError as e:
        # 스택을 그대로 뱉으면 원인이 안 보인다. 브로커가 안 떠 있는 것뿐이다
        print(f"브로커에 못 붙었다 {args.host}:{args.port} ({e.__class__.__name__})",
              file=sys.stderr)
        print("  ./scripts/dev.sh broker  또는  sudo systemctl start mosquitto",
              file=sys.stderr)
        return 2
    c.loop_start()
    info = c.publish(f"ship/{ship[0]}/kiosk/command/{command}", payload, qos=1)
    info.wait_for_publish(timeout=5)
    c.loop_stop()
    c.disconnect()

    # 🔴 **발행만 하고 끝내지 않는다.** Pi 가 안 떠 있으면 브로커가 받아서 버리는데
    #   (QoS 1 이어도 구독자가 없으면 큐에 안 남는다) 그래도 발행은 성공한다.
    #   "닫았다"고 믿고 Jetson 에서 다시 쏘면 409 로 프레임 200장을 버린다 —
    #   실제로 밟았다. DB 가 실제로 바뀌었는지 본다.
    for _ in range(WAIT_SEC * 2):
        time.sleep(0.5)
        now = conn.execute(
            "SELECT status FROM pi_accident WHERE accident_id = ?",
            (accident_id,)).fetchone()
        if now is None or now[0] not in ("DETECT", "WAIT", "REPORT"):
            print(f"닫혔다  {status} -> {now[0] if now else '(사라짐)'}")
            return 0

    print(f"[실패] {WAIT_SEC}초 기다렸는데 아직 {status} 다", file=sys.stderr)
    print("  Pi 가 떠 있는지 확인할 것 — 명령을 받을 프로세스가 없으면", file=sys.stderr)
    print("  브로커가 받아서 그냥 버린다 (발행은 성공한다)", file=sys.stderr)
    print("    ./scripts/dev.sh status", file=sys.stderr)
    print("  떠 있는데도 안 닫히면 Pi 로그의 pi/command/response 를 볼 것",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

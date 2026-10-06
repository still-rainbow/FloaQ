"""가짜 Jetson. 유효한 탐지를 발행한다.

Postman 이나 mosquitto_pub 으로 손으로 치는 것보다 이쪽이 낫다 —
`floaq.contracts` 를 그대로 쓰므로 **페이로드가 항상 계약에 맞는다.**
봉투(`v`·`ts`·`request_id` UUID v7)를 매번 타이핑할 일도 없다.

실행:
    python tools/fake_jetson.py --ship-id <uuid>                # 정상 탐지 1회
    python tools/fake_jetson.py --ship-id <uuid> --no-solution  # 조준 해 없음
    python tools/fake_jetson.py --ship-id <uuid> --bad-angle    # 범위 밖
    python tools/fake_jetson.py --ship-id <uuid> --stale        # 만료된 해
    python tools/fake_jetson.py --ship-id <uuid> --status       # jetson/status 만 주기 발행
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from floaq import config
from floaq.contracts import (
    DeviceHealth, Envelope, JetsonDetection, JetsonStatus, LaunchSolution,
)
from floaq.ids import uuid7


def publish(client: mqtt.Client, ship_id: str, subject: str, payload, qos=1, retain=False) -> None:
    env = Envelope[type(payload)](
        request_id=uuid7(), v=1, ts=int(time.time()), data=[payload]
    )
    topic = f"ship/{ship_id}/{subject}"
    client.publish(topic, env.model_dump_json(), qos=qos, retain=retain)
    print(f"-> {topic}\n   {env.model_dump_json()[:160]}...")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ship-id", required=True)
    p.add_argument("--host", default=config.MQTT_HOST)
    p.add_argument("--port", type=int, default=config.MQTT_PORT_TCP)
    p.add_argument("--no-solution", action="store_true", help="조준 해 없음 -> NO_SOLUTION")
    p.add_argument("--bad-angle", action="store_true", help="yaw 90도 -> OUT_OF_RANGE")
    p.add_argument("--bad-profile", action="store_true", help="미등록 프로파일 -> OUT_OF_RANGE")
    p.add_argument("--stale", action="store_true", help="묵은 해 -> OUT_OF_RANGE")
    p.add_argument("--status", action="store_true", help="jetson/status 를 5초마다 발행")
    args = p.parse_args()

    now = int(time.time())

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"jetson-{args.ship_id}")
    client.connect(args.host, args.port, keepalive=config.MQTT_KEEPALIVE_SEC)
    client.loop_start()
    time.sleep(0.3)

    if args.status:
        # jetson/status 는 LWT 대신 생존 신호를 겸한다 — 15초 미수신이면 죽은 것으로 본다.
        try:
            while True:
                publish(client, args.ship_id, "jetson/status", JetsonStatus(
                    model_version="v1", inference_fps=12.5,
                    camera_l=DeviceHealth.OK, camera_r=DeviceHealth.OK,
                    camera_dirty=False, gps_received=True, uptime_sec=int(time.time()) - now,
                ), retain=True)
                time.sleep(config.DEVICE_STATUS_SEC)
        except KeyboardInterrupt:
            pass
        client.loop_stop(); client.disconnect()
        return 0

    sol = None
    if not args.no_solution:
        sol = LaunchSolution(
            target_yaw_deg=90.0 if args.bad_angle else 12.5,
            target_pitch_deg=20.0,
            launch_profile="max-power" if args.bad_profile else "demo-low-v1",
            target_lat=35.11, target_lon=129.01,
            # 만료 기준은 config.LAUNCH_SOLUTION_TTL_SEC (기본 3초)
            solved_at=now - 60 if args.stale else now,
        )

    publish(client, args.ship_id, "jetson/detection", JetsonDetection(
        detection_id=uuid7(), ship_id=args.ship_id,
        lat=35.1, lon=129.0, distance_m=12.5,
        confidence=0.93, frame_count=5, model_version="v1", camera="L",
        bbox=(10, 20, 30, 40), detected_at=now, launch=sol,
    ))

    time.sleep(0.5)   # QoS 1 전송 완료 대기
    client.loop_stop()
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())

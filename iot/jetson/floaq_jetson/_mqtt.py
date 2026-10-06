"""MQTT 배관. 탐지 발행 + 사고 상태 구독.

3자 브로커다 — Jetson 이 Pi 를 거치지 않고 직접 붙는다(`mqtt.md` §1.3). 발행자
세그먼트가 토픽에 박혀 있어서 나중에 ACL 을 켜도 그대로 간다.

    발행  ship/{ship_id}/jetson/detection      QoS 1
    구독  ship/{ship_id}/pi/accident/state     QoS 1, retained
    구독  ship/{ship_id}/pi/sensor/gps         QoS 0, retained, 1Hz

🔴 **QoS 1 이라 끊겨 있어도 버려지지 않는다.** paho 가 큐에 쥐고 있다가 재접속 때
   보낸다. QoS 0 으로 두면 재접속 전에 난 탐지가 조용히 사라진다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

#: LWT·재접속 판정 기준. Pi 쪽 설정과 같은 값을 쓴다 — 다르면 두절 판정이 어긋난다.
KEEPALIVE = 15


def envelope(data: dict) -> bytes:
    """`Request<T>` 공통 봉투. `data` 는 **항상 배열**이다.

    단건도 길이 1 이다. 나중에 묶어 보낼 때 인터페이스가 안 바뀐다.
    """
    return json.dumps({
        "request_id": str(uuid.uuid4()),
        "v": 1,
        "ts": int(time.time()),
        "data": [data],
    }, ensure_ascii=False, separators=(",", ":")).encode()


class Bus:
    """paho 래핑. 재접속·구독 복구를 알아서 한다."""

    def __init__(self, host: str, port: int, ship_id: str, *,
                 on_accident_state=None, on_gps=None) -> None:
        self.host, self.port, self.ship_id = host, port, ship_id
        self._on_state = on_accident_state
        self._on_gps = on_gps
        self.connected = threading.Event()
        #: `stop()` 이 세운다. 정상 종료와 진짜 끊김을 가른다
        self._closing = False

        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"jetson-{ship_id[:8]}-{uuid.uuid4().hex[:6]}")
        self._c.on_connect = self._handle_connect
        self._c.on_disconnect = self._handle_disconnect
        self._c.on_message = self._handle_message

    def topic(self, suffix: str) -> str:
        return f"ship/{self.ship_id}/{suffix}"

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self, timeout: float = 5.0) -> bool:
        """붙고 네트워크 루프를 띄운다. 못 붙어도 예외를 내지 않는다.

        ⚠ Pi 가 아직 안 떴을 수 있다. paho 가 알아서 재접속하므로 실패는 정상 경로다.
        """
        try:
            self._c.connect_async(self.host, self.port, KEEPALIVE)
            self._c.loop_start()
        except Exception as e:
            log.warning("MQTT 연결 시도 실패: %s - 재접속은 계속한다", e)
            return False
        return self.connected.wait(timeout)

    def stop(self) -> None:
        # 정상 종료라고 표시해 둔다. 안 하면 _handle_disconnect 가 "재접속한다" 를
        # 찍고, 시연 마지막 줄이 경고로 남아 문제가 난 것처럼 보인다
        self._closing = True
        self._c.loop_stop()
        try:
            self._c.disconnect()
        except Exception:
            pass

    # ── 발행 ─────────────────────────────────────────────────────────
    def publish(self, suffix: str, data: dict, *, qos: int = 1,
                retain: bool = False) -> bool:
        info = self._c.publish(self.topic(suffix), envelope(data),
                               qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    # ── 콜백 ─────────────────────────────────────────────────────────
    def _handle_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc != 0:
            log.error("MQTT 접속 거부 rc=%s", rc)
            return
        self.connected.set()
        # 🔴 재접속마다 다시 구독한다. clean session 이면 브로커가 구독을 안 들고 있다.
        #   이걸 빼면 첫 접속만 되고 재접속 뒤로는 조용히 아무것도 안 온다
        client.subscribe(self.topic("pi/accident/state"), 1)
        if self._on_gps:
            client.subscribe(self.topic("pi/sensor/gps"), 0)
        log.info("MQTT 접속 %s:%d  ship=%s", self.host, self.port, self.ship_id)

    def _handle_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        self.connected.clear()
        if self._closing:
            log.info("MQTT 종료")
            return
        # 🔴 예기치 못한 끊김만 경고다. paho 가 알아서 다시 붙는다
        log.warning("MQTT 끊김 rc=%s - 재접속한다", rc)

    def _handle_message(self, client, userdata, msg) -> None:
        # 🔴 빈 페이로드는 **retained 삭제**다. json.loads(b"") 가 던지는 예외가
        #   paho 콜백 스레드를 죽여서, 그 뒤로 아무 메시지도 안 온다. 조용하다
        if not msg.payload:
            return
        try:
            data = json.loads(msg.payload)["data"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            log.debug("해석 못 한 메시지 %s", msg.topic)
            return

        try:
            if msg.topic.endswith("pi/accident/state"):
                if self._on_state:
                    self._on_state(data)
            elif msg.topic.endswith("pi/sensor/gps"):
                if self._on_gps:
                    self._on_gps(data)
        except Exception:
            # 사용자 콜백이 던져도 이 스레드는 살아야 한다
            log.exception("콜백 오류 %s", msg.topic)

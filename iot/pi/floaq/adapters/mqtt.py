"""MQTT 어댑터. `ports.MessageBus` 의 paho 구현.

**이 파일이 MQTT 를 아는 유일한 곳이다.** core 는 subject 문자열('pi/accident/state')만
알고, `ship/{ship_id}/` 접두사·QoS·retain·직렬화는 전부 여기서 붙는다.
전송을 WS 로 바꾸게 되면 이 파일만 새로 쓴다.

⚠ paho-mqtt 2.x 는 1.x 와 API 가 다르다. 튜토리얼 대부분이 1.x 라 복붙하면 바로 터진다.
    - `Client(CallbackAPIVersion.VERSION2, ...)` — 첫 인자가 필수
    - `on_connect(client, userdata, flags, reason_code, properties)` — 인자 5개

🔴 **수신 처리를 paho 네트워크 스레드에서 하지 않는다.**
   `on_message` 는 paho 의 루프 스레드에서 불린다. 거기서 GPIO·SQLite 를 만지면
   그 시간만큼 MQTT 수신이 멈춘다. 큐에 넣고 워커 스레드가 꺼내 쓴다 —
   DES-31 §1 의 "안전 판단 경로와 추론 경로를 분리한다"를 프로세스 안에서도 지키는 것이다.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
from pydantic import BaseModel, ValidationError

from floaq import config
from floaq.contracts import TOPICS, CommandAck, Envelope, parse_topic

log = logging.getLogger(__name__)

#: 수신 핸들러. (subject, 검증된 페이로드, request_id) 를 받는다.
Handler = Callable[[str, BaseModel, str], None]


class MqttBus:
    """발행·구독. `ports.MessageBus` 를 만족한다(상속하지 않는다 — Protocol 이라 필요 없다)."""

    def __init__(
        self,
        ship_id: str,
        *,
        host: str = config.MQTT_HOST,
        port: int = config.MQTT_PORT_TCP,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.ship_id = ship_id
        self.host, self.port = host, port
        self._handlers: dict[str, Handler] = {}
        self._inbox: queue.Queue[tuple[str, BaseModel, str]] = queue.Queue(maxsize=1000)
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()

        self._c = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"pi-{ship_id}",
            # 재접속했을 때 필요한 건 끊긴 동안 쌓인 IMU 300개가 아니라
            # "지금 사고가 어떤 상태인가"다. 그건 세션 큐가 아니라 retained 로 받는다.
            clean_session=config.MQTT_CLEAN_SESSION,
            protocol=mqtt.MQTTv311,
        )
        if username:
            self._c.username_pw_set(username, password)

        # LWT. Pi 가 죽으면 브로커가 대신 발행한다.
        # ⚠ 페이로드가 접속 시점에 고정되므로 ts 에 의미 있는 값을 넣을 수 없다 — 0 으로 둔다.
        # ⚠ 브로커는 Keep Alive 의 1.5배(약 22.5초)가 지나야 이걸 발행한다.
        #   30초 카운트다운과 같은 스케일이라 "키오스크가 죽었다" 판정에 이 지연을 감안해야 한다.
        self._c.will_set(
            self._topic("pi/online"),
            json.dumps({"online": False, "ts": 0}),
            qos=1,
            retain=True,
        )

        self._c.on_connect = self._on_connect
        self._c.on_disconnect = self._on_disconnect
        self._c.on_message = self._on_message

    # ── 토픽 ─────────────────────────────────────────────────────────
    def _topic(self, subject: str) -> str:
        """subject → 전체 토픽. 접두사를 core 가 조립하지 않게 여기서만 붙인다."""
        return f"ship/{self.ship_id}/{subject}"

    # ── MessageBus 구현 ──────────────────────────────────────────────
    def publish(self, subject: str, payload: BaseModel, *, retain: bool | None = None) -> None:
        """봉투로 감싸 발행한다. QoS·retain 기본값은 TOPICS 표에서 읽는다.

        페이로드가 이미 봉투(CommandAck 등)면 그대로 보낸다 — 이중으로 감싸지 않는다.
        """
        try:
            _, qos, default_retain = TOPICS[subject]
        except KeyError:
            raise KeyError(f"TOPICS 에 없는 토픽: {subject}") from None

        body = payload if _is_envelope(payload) else Envelope[Any](
            request_id=_new_id(),
            v=1,
            ts=_now(),
            data=[payload],
        )
        raw = body.model_dump_json().encode()

        limit = config.MAX_SNAPSHOT_BYTES if "snapshot" in subject else config.MAX_PAYLOAD_BYTES
        if len(raw) > limit:
            # 조용히 끊기는 대신 여기서 드러낸다. 브로커 message_size_limit 도 따로 걸어야 한다 —
            # mosquitto 기본값은 0(무제한)이라 폭주를 막을 게 없다.
            log.error("페이로드 초과 %s: %d > %d bytes", subject, len(raw), limit)
            return

        self._c.publish(
            self._topic(subject),
            raw,
            qos=qos,
            retain=default_retain if retain is None else retain,
        )

    def clear_retained(self, subject: str) -> None:
        """0바이트 페이로드를 retain 으로 발행해 retained 를 삭제한다.

        ⚠ 발행자만 자기 토픽을 지울 수 있다(§1.2 ACL). Pi 는 `jetson/snapshot` 을 못 지운다 —
          Jetson 이 `pi/accident/state` 에서 CLOSE/CANCEL 을 보고 스스로 지운다.
        """
        publisher = subject.split("/", 1)[0]
        if publisher != "pi":
            log.warning("남의 토픽은 못 지운다(ACL): %s", subject)
            return
        self._c.publish(self._topic(subject), payload=b"", qos=1, retain=True)

    # ── 구독 ─────────────────────────────────────────────────────────
    def on(self, subject: str, handler: Handler) -> None:
        if subject not in TOPICS:
            raise KeyError(f"TOPICS 에 없는 토픽: {subject}")
        self._handlers[subject] = handler

    def _subscriptions(self) -> list[tuple[str, int]]:
        """Pi 가 구독할 것. 자기가 발행하는 건 구독하지 않는다."""
        return [
            (self._topic("jetson/#"), 1),
            (self._topic("kiosk/#"), 1),
        ]

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        """브로커에 붙는다. **못 붙어도 예외를 내지 않는다.**

        🔴 예전에는 `connect()` 가 던지는 `ConnectionRefusedError` 가 그대로 올라와
          프로세스가 끝났다. 브로커가 아직 안 뜬 상태로 Pi 를 켜는 건 흔한 일인데,
          그때 오케스트레이터·HTTP·신고까지 통째로 죽었다 — 실제 Pi 에서 밟았다.

        `connect_async` + `loop_start` 면 paho 가 백그라운드에서 재접속을 계속한다.
        브로커가 나중에 떠도 알아서 붙고, 그 사이 발행은 QoS 1 이라 큐에 쌓인다.
        """
        # ⚠ connect() 가 아니라 connect_async() 다. 전자는 그 자리에서 소켓을 열어
        #   실패하면 던진다. 후자는 loop_start 가 도는 스레드에서 붙는다
        self._c.connect_async(self.host, self.port,
                              keepalive=config.MQTT_KEEPALIVE_SEC)
        self._c.loop_start()          # paho 가 자기 스레드를 돌린다
        log.info("브로커 접속 시도 %s:%d (백그라운드 재접속)", self.host, self.port)
        self._worker = threading.Thread(target=self._drain, name="mqtt-inbox", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stopping.set()
        # 정상 종료면 LWT 대신 online=false 를 직접 발행한다 — 22초를 기다리게 하지 않는다.
        self._c.publish(self._topic("pi/online"),
                        json.dumps({"online": False, "ts": _now()}), qos=1, retain=True)
        self._c.loop_stop()
        self._c.disconnect()

    # ── paho 콜백 (네트워크 스레드에서 불린다) ───────────────────────
    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("브로커 접속 실패: %s", reason_code)
            return
        log.info("브로커 접속 %s:%d", self.host, self.port)
        # ⚠ 구독은 반드시 여기서 한다. 재접속 때마다 다시 걸어야 하는데
        #   clean_session=True 라 브로커가 구독을 기억하지 않는다.
        for topic, qos in self._subscriptions():
            client.subscribe(topic, qos)
        # 접속 직후 LWT 토픽을 online=true 로 덮어쓴다
        client.publish(self._topic("pi/online"),
                       json.dumps({"online": True, "ts": _now()}), qos=1, retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if not self._stopping.is_set():
            log.warning("브로커 연결 끊김: %s (자동 재접속 대기)", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        """🔴 여기서 일을 하지 않는다. 검증만 하고 큐에 넣는다."""
        try:
            _, publisher, subject_tail = parse_topic(msg.topic)
        except ValueError:
            log.warning("토픽 형식 아님: %s", msg.topic)
            return

        subject = f"{publisher}/{subject_tail}"
        entry = TOPICS.get(subject)
        if entry is None or subject not in self._handlers:
            return                    # 구독은 와일드카드라 안 쓰는 것도 들어온다

        if not msg.payload:
            return                    # retained 삭제 알림

        model_cls, _, _ = entry
        try:
            env = Envelope[model_cls].model_validate_json(msg.payload)  # type: ignore[valid-type]
        except ValidationError as e:
            # 모르는 v, 범위 밖 값, 깨진 JSON. **버리고 로그만 남긴다 — 죽지 않는다.**
            # 키오스크만 업데이트된 상태에서 Pi 가 옛 페이로드를 받는 경우가 이것이다.
            log.warning("페이로드 거부 %s: %s", subject, e.errors()[0].get("msg"))
            return

        for item in env.data:
            try:
                self._inbox.put_nowait((subject, item, env.request_id))
            except queue.Full:
                # 큐가 차면 최신을 버린다. 여기서 블로킹하면 MQTT 수신이 멈춘다.
                log.error("수신 큐 포화 — %s 드롭", subject)

    # ── 워커 스레드 ──────────────────────────────────────────────────
    def _drain(self) -> None:
        while not self._stopping.is_set():
            try:
                subject, payload, request_id = self._inbox.get(timeout=0.5)
            except queue.Empty:
                continue
            handler = self._handlers.get(subject)
            if handler is None:
                continue
            try:
                handler(subject, payload, request_id)
            except Exception:
                # 핸들러 하나가 터져도 루프는 계속 돈다. 여기서 죽으면 그 뒤 모든 메시지를 못 받는다.
                log.exception("핸들러 예외 %s", subject)


def _is_envelope(payload: BaseModel) -> bool:
    """이미 봉투인가. 또 감싸면 키오스크가 data[0].data 를 파게 된다.

    ⚠ 이름 비교로 하면 안 된다. pydantic 제네릭을 파라미터화하면 클래스 이름이
      'CommandAck[CommandResult]' 가 되어 'CommandAck' 와 안 맞는다.
      실제로 그렇게 짰다가 응답이 이중으로 감싸졌고, 테스트가 잡았다.
    """
    return isinstance(payload, (Envelope, CommandAck))


def _now() -> int:
    import time
    return int(time.time())


def _new_id() -> str:
    from floaq.ids import uuid7
    return uuid7()


# ── 배선 ─────────────────────────────────────────────────────────────
def wire(bus: MqttBus, orch, jetson_watch=None) -> None:
    """오케스트레이터를 버스에 연결한다.

    core 는 MQTT 를 모르고 MqttBus 는 사고 로직을 모른다. 둘을 아는 건 이 함수뿐이다.

    `jetson_watch` 는 `floaq.device.JetsonWatch`. 주면 `jetson/status` 를 받아
    장치 상태 발행에 쓴다.

    🔴 전에는 `jetson/status` 를 **구독조차 하지 않았다.** 카메라 L/R 과 AI 의
       상태는 젯슨만 알고 키오스크는 Pi 를 통해서만 본다 — 중간이 비어 있어서
       화면의 장치 패널이 통째로 '모름' 이었다.
    """

    def on_detection(subject: str, payload: BaseModel, request_id: str) -> None:
        orch.on_detection(payload)

    def on_aim(subject: str, payload: BaseModel, request_id: str) -> None:
        orch.on_aim(payload)

    def make_command(name: str):
        def handler(subject: str, payload: BaseModel, request_id: str) -> None:
            # request_id 가 멱등 키다 — 같은 값으로 재전송되면 실행은 건너뛰고 응답만 다시 간다
            orch.on_command(name, payload.model_dump(), request_id)
        return handler

    bus.on("jetson/detection", on_detection)
    bus.on("jetson/aim", on_aim)
    if jetson_watch is not None:
        def on_jetson_status(subject: str, payload: BaseModel, request_id: str) -> None:
            jetson_watch.put(payload)

        bus.on("jetson/status", on_jetson_status)
    for cmd in ("cancel", "report_now", "report_manual", "rescue", "close"):
        bus.on(f"kiosk/command/{cmd}", make_command(cmd))

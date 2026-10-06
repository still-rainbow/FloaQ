"""MQTT 어댑터 테스트. **브로커도 paho 도 없이 돈다.**

paho 를 스텁으로 갈아끼워서 우리 코드만 검증한다 — 라이브러리를 테스트할 이유는 없고,
CI 에 브로커를 띄우지 않아도 봉투·토픽·ACL·검증 로직이 맞는지 확인할 수 있다.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── paho 스텁 ────────────────────────────────────────────────────────
class _RC:
    def __init__(self, failure=False):
        self.is_failure = failure

    def __str__(self):
        return "ok"


class _FakeClient:
    def __init__(self, api_version, client_id="", clean_session=None, protocol=None):
        self.client_id = client_id
        self.clean_session = clean_session
        self.protocol = protocol
        self.will = None
        self.published: list[tuple[str, bytes | str, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.creds = None
        self.on_connect = self.on_disconnect = self.on_message = None

    def username_pw_set(self, u, p):
        self.creds = (u, p)

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def publish(self, topic, payload=b"", qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def connect(self, host, port, keepalive=60):
        self.conn = (host, port, keepalive)

    def loop_start(self): ...
    def loop_stop(self): ...
    def disconnect(self): ...


_paho = types.ModuleType("paho")
_mqtt = types.ModuleType("paho.mqtt")
_client_mod = types.ModuleType("paho.mqtt.client")
_client_mod.Client = _FakeClient
_client_mod.MQTTv311 = 4
_client_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION2="v2")
_paho.mqtt = _mqtt
_mqtt.client = _client_mod
sys.modules.setdefault("paho", _paho)
sys.modules.setdefault("paho.mqtt", _mqtt)
sys.modules.setdefault("paho.mqtt.client", _client_mod)

# 스텁을 심은 뒤에 import 해야 한다
from floaq import config                                    # noqa: E402
from floaq.adapters.mqtt import MqttBus, wire               # noqa: E402
from floaq.contracts import (                               # noqa: E402
    AccidentState, AccidentStatus, CommandAck, CommandResult, Envelope, JetsonDetection,
)
from floaq.ids import uuid7                                 # noqa: E402

SHIP = uuid7()
T0 = 1_757_000_000


def bus() -> MqttBus:
    return MqttBus(SHIP, host="localhost", port=1883)


def raw_detection(**over) -> bytes:
    det = dict(
        detection_id=uuid7(), ship_id=SHIP, lat=35.1, lon=129.0, distance_m=12.5,
        confidence=0.93, frame_count=5, model_version="v1", camera="L",
        bbox=[10, 20, 30, 40], detected_at=T0,
        launch=dict(target_yaw_deg=12.5, target_pitch_deg=20.0,
                    launch_profile="demo-low-v1", target_lat=35.11,
                    target_lon=129.01, solved_at=T0),
    )
    env = dict(request_id=uuid7(), v=1, ts=T0, data=[det])
    env.update(over)
    return json.dumps(env).encode()


class _Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


# ── 발행 ─────────────────────────────────────────────────────────────
def test_publish_wraps_and_prefixes():
    b = bus()
    b.publish("pi/accident/state", AccidentState(
        accident_id=uuid7(), status=AccidentStatus.DETECT, prev_status=None,
        reason="AI_DETECT", caused_by=None, report_due_at=None, changed_at=T0))

    topic, payload, qos, retain = b._c.published[-1]
    assert topic == f"ship/{SHIP}/pi/accident/state"   # 접두사는 어댑터가 붙인다
    assert qos == 1 and retain is True                 # TOPICS 표에서 읽었다
    env = json.loads(payload)
    assert env["v"] == 1 and isinstance(env["data"], list) and len(env["data"]) == 1


def test_ack_is_not_double_wrapped():
    """CommandAck 는 이미 봉투다. 또 감싸면 키오스크가 data[0].data 를 파게 된다."""
    b = bus()
    b.publish("pi/command/response", CommandAck[CommandResult](
        request_id=uuid7(), v=1, ts=T0, is_success=True, error=None,
        data=CommandResult(accident_id=uuid7(), command="cancel",
                           status=AccidentStatus.CANCEL)))
    env = json.loads(b._c.published[-1][1])
    assert env["is_success"] is True
    assert isinstance(env["data"], dict)               # 배열이 아니다


def test_unknown_subject_rejected():
    b = bus()
    try:
        b.publish("pi/nope", AccidentState(
            accident_id=uuid7(), status=AccidentStatus.DETECT, prev_status=None,
            reason="AI_DETECT", caused_by=None, report_due_at=None, changed_at=T0))
    except KeyError:
        return
    raise AssertionError("TOPICS 에 없는 토픽이 통과했다")


def test_oversized_payload_dropped():
    """조용히 끊기는 대신 드러낸다. 브로커 message_size_limit 도 따로 걸어야 한다."""
    b = bus()
    before = len(b._c.published)
    b.publish("pi/accident/state", AccidentState(
        accident_id=uuid7(), status=AccidentStatus.DETECT, prev_status=None,
        reason="AI_DETECT", caused_by="x" * (config.MAX_PAYLOAD_BYTES + 100),
        report_due_at=None, changed_at=T0))
    assert len(b._c.published) == before


# ── retained 삭제와 ACL ──────────────────────────────────────────────
def test_clear_retained_publishes_empty():
    b = bus()
    b.clear_retained("pi/launch/result")
    topic, payload, qos, retain = b._c.published[-1]
    assert topic.endswith("/pi/launch/result")
    assert payload == b"" and retain is True           # 0바이트 + retain = 삭제


def test_cannot_clear_other_publishers_topic():
    """🔴 §1.2 ACL — Pi 는 jetson/snapshot 을 못 지운다. 브로커가 막기 전에 여기서 막는다."""
    b = bus()
    before = len(b._c.published)
    b.clear_retained("jetson/snapshot")
    assert len(b._c.published) == before


# ── LWT ──────────────────────────────────────────────────────────────
def test_lwt_registered_before_connect():
    b = bus()
    topic, payload, qos, retain = b._c.will
    assert topic == f"ship/{SHIP}/pi/online"
    assert json.loads(payload) == {"online": False, "ts": 0}   # ts 는 고정이라 의미 없음
    assert qos == 1 and retain is True


def test_clean_session_and_client_id():
    b = bus()
    assert b._c.client_id == f"pi-{SHIP}"
    assert b._c.clean_session is config.MQTT_CLEAN_SESSION


def test_connect_subscribes_and_announces_online():
    """구독은 on_connect 에서 해야 한다 — clean_session 이라 브로커가 기억하지 않는다."""
    b = bus()
    b._on_connect(b._c, None, {}, _RC(), None)
    subs = [t for t, _ in b._c.subscribed]
    assert f"ship/{SHIP}/jetson/#" in subs
    assert f"ship/{SHIP}/kiosk/#" in subs
    assert f"ship/{SHIP}/pi/#" not in subs              # 자기가 쏜 건 안 받는다
    last = b._c.published[-1]
    assert json.loads(last[1])["online"] is True


# ── 수신 ─────────────────────────────────────────────────────────────
def test_inbound_validated_and_queued():
    b = bus()
    b.on("jetson/detection", lambda *a: None)
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", raw_detection()))
    subject, payload, rid = b._inbox.get_nowait()
    assert subject == "jetson/detection"
    assert isinstance(payload, JetsonDetection)


def test_unknown_version_dropped_not_crashed():
    """키오스크만 업데이트된 상태에서 옛 페이로드가 오는 경우. 죽지 않고 버린다."""
    b = bus()
    b.on("jetson/detection", lambda *a: None)
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", raw_detection(v=2)))
    assert b._inbox.empty()


def test_bad_payload_dropped():
    b = bus()
    b.on("jetson/detection", lambda *a: None)
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", b"{not json"))
    assert b._inbox.empty()


def test_retained_delete_ignored():
    """0바이트는 retained 삭제 알림이다. 페이로드로 파싱하면 안 된다."""
    b = bus()
    b.on("jetson/detection", lambda *a: None)
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", b""))
    assert b._inbox.empty()


def test_unsubscribed_subject_ignored():
    """와일드카드 구독이라 핸들러 없는 것도 들어온다. 조용히 흘린다."""
    b = bus()
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/status", b'{"v":1}'))
    assert b._inbox.empty()


def test_malformed_topic_ignored():
    b = bus()
    b.on("jetson/detection", lambda *a: None)
    b._on_message(b._c, None, _Msg("garbage", raw_detection()))
    assert b._inbox.empty()


def test_handler_exception_does_not_kill_worker():
    """핸들러 하나가 터져도 그 뒤 메시지를 계속 받아야 한다."""
    b = bus()
    seen = []

    def boom(subject, payload, rid):
        seen.append(rid)
        raise RuntimeError("의도적 실패")

    b.on("jetson/detection", boom)
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", raw_detection()))
    b._on_message(b._c, None, _Msg(f"ship/{SHIP}/jetson/detection", raw_detection()))

    import threading
    t = threading.Thread(target=b._drain, daemon=True)
    t.start()
    import time
    time.sleep(0.3)   # 워커가 큐를 비울 시간. task_done() 을 안 쓰므로 join() 은 못 쓴다
    b._stopping.set()
    t.join(timeout=2)
    assert len(seen) == 2          # 첫 번째가 터져도 두 번째가 처리됐다


# ── 배선 ─────────────────────────────────────────────────────────────
def test_wire_registers_every_command():
    class _Orch:
        def __init__(self): self.cmds = []
        def on_detection(self, d): ...
        def on_command(self, name, payload, rid): self.cmds.append(name)

    b, orch = bus(), _Orch()
    wire(b, orch)
    for cmd in ("cancel", "report_now", "report_manual", "rescue", "close"):
        assert f"kiosk/command/{cmd}" in b._handlers
    assert "jetson/detection" in b._handlers


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as e:
            failed += 1
            print("  FAIL  %s  %s" % (name, e))
        except Exception as e:
            failed += 1
            print("  ERROR %s  %r" % (name, e))
    print("\n%d passed, %d failed (of %d)" % (len(fns) - failed, failed, len(fns)))
    sys.exit(1 if failed else 0)

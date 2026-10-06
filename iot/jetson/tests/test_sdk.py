"""Jetson SDK 시험. 브로커도 Pi 도 없이 돈다.

여기 걸린 것들은 **AI 팀 루프를 죽이거나 프레임을 조용히 잃는** 종류다.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq_jetson import Detection, Floaq, InvalidCall
from floaq_jetson._ring import RingBuffer
from floaq_jetson._upload import Uploader

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 120 + b"\xff\xd9"
SHIP = "01a0a3ed-01fd-7a09-b3cf-ba5910c52950"


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.connected = _Flag(True)
        self.on_state = None

    def publish(self, suffix, data, **kw):
        self.published.append((suffix, data))
        return True

    def start(self, timeout=0):
        return True

    def stop(self):
        pass


class _Flag:
    def __init__(self, v): self.v = v
    def is_set(self): return self.v


class FakeUploader:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, int | None, str | None]] = []
        self.queued = self.sent = self.failed = self.dropped = 0

    def submit(self, det, ftype, seq, jpeg, camera=None):
        self.items.append((det, ftype, seq, camera))
        return True

    def start(self): pass
    def stop(self, timeout=0): pass

    # 실제 Uploader 와 같은 모양. 빠지면 stats() 가 터진다
    avg_ms = 0.0
    mbps = 0.0


@pytest.fixture
def fq():
    f = Floaq.__new__(Floaq)          # __init__ 의 네트워크 조회를 건너뛴다
    f.pi, f.http = "test", "http://test:8000"
    f.ship_id, f.model_version, f.post_sec = SHIP, "v1", 10
    f.ring = RingBuffer(15, 5)
    f._uploader = FakeUploader()
    f._bus = FakeBus()
    f._stream = None                  # 라이브 스트림은 여기서 안 띄운다
    import threading
    f._lock = threading.Lock()
    f._detection_id = f._accident_id = None
    f._accident_status = None
    f._after_until = 0.0
    f._after_seq = 0
    # 배 GPS. `__init__` 이 세우는 것과 같은 초기값이다 —
    # 여기 빠지면 stats() 가 AttributeError 로 터진다
    f._fix = None
    f._fix_at = 0.0
    return f


def detect(fq, **kw):
    return fq.detected(lat=35.05, lon=129.1, distance_m=12.4, confidence=0.93, **kw)


# ── 잘못된 호출은 크게 터진다 ────────────────────────────────────────
@pytest.mark.parametrize("kw", [
    {"lat": 200}, {"lon": -400}, {"confidence": 1.5},
    {"distance_m": -1}, {"camera": "X"}, {"bbox": (1, 2, 3)},
])
def test_bad_args_raise(fq, kw):
    """🔴 AI 쪽 버그다. 조용히 넘기면 Pi 가 거부한 걸 아무도 모른다."""
    base = dict(lat=35.05, lon=129.1, distance_m=12.4, confidence=0.93)
    with pytest.raises(InvalidCall):
        fq.detected(**{**base, **kw})


def test_half_aim_is_rejected(fq):
    """🔴 조준 해를 절반만 주면 조용히 NO_SOLUTION 이 된다. 왜 발사가 안 되는지 못 찾는다."""
    with pytest.raises(InvalidCall):
        detect(fq, yaw=12.5)


def test_no_aim_is_fine(fq):
    """조준 해가 없어도 탐지는 유효하다. 발사만 안 된다."""
    detect(fq)
    assert fq._bus.published[0][1]["launch"] is None


def test_full_aim_goes_through(fq):
    detect(fq, yaw=12.5, pitch=20.0, target_lat=35.06, target_lon=129.11)
    launch = fq._bus.published[0][1]["launch"]
    assert launch["target_yaw_deg"] == 12.5
    assert launch["target_lat"] == 35.06


def test_aim_only_uses_separate_latest_only_topic(fq):
    assert fq.aim(yaw=12.5, pitch=20.0, confidence=0.93, track_id=7)
    suffix, payload = fq._bus.published[0]
    assert suffix == "jetson/aim"
    assert payload["target_yaw_deg"] == 12.5
    assert payload["target_pitch_deg"] == 20.0
    assert "launch_profile" not in payload


def test_bad_aim_only_confidence_is_rejected(fq):
    with pytest.raises(InvalidCall, match="confidence"):
        fq.aim(yaw=0.0, pitch=10.0, confidence=2.0)


# ── 링 버퍼 ──────────────────────────────────────────────────────────
def test_frames_go_to_ring_while_idle(fq):
    for _ in range(20):
        fq.frame(JPEG, camera="L")
    assert len(fq.ring) == 20
    assert fq._uploader.items == []


def test_ring_is_bounded(fq):
    """🔴 상한이 없으면 하루 종일 도는 프로그램이 Jetson 메모리를 채운다."""
    for _ in range(5000):
        fq.frame(JPEG, camera="L")
    assert len(fq.ring) == fq.ring.capacity == 150


def test_detection_drains_ring_as_before(fq):
    """탐지 순간 링 버퍼가 통째로 BEFORE 로 간다. 그 장면은 다시 못 만든다."""
    for _ in range(30):
        fq.frame(JPEG, camera="L")
    det = detect(fq)

    before = [i for i in fq._uploader.items if i[1] == "BEFORE"]
    assert len(before) == 30
    assert [i[2] for i in before] == list(range(1, 31))     # 1부터 순번
    assert all(i[0] == det.detection_id for i in before)
    assert len(fq.ring) == 0                               # 비운다 — AFTER 와 안 겹치게


def test_before_uploaded_even_if_publish_fails(fq):
    """🔴 MQTT 가 끊겨도 프레임은 올린다. 안 그러면 링 버퍼가 덮어써져 장면을 잃는다."""
    fq._bus.publish = lambda *a, **k: False
    for _ in range(10):
        fq.frame(JPEG, camera="L")
    det = detect(fq)
    assert det.published is False
    assert len([i for i in fq._uploader.items if i[1] == "BEFORE"]) == 10


# ── AFTER 구간 ───────────────────────────────────────────────────────
def test_frames_upload_as_after_within_window(fq):
    det = detect(fq)
    for _ in range(5):
        fq.frame(JPEG, camera="R")
    after = [i for i in fq._uploader.items if i[1] == "AFTER"]
    assert [i[2] for i in after] == [1, 2, 3, 4, 5]
    assert all(i[3] == "R" for i in after)
    assert len(fq.ring) == 0                               # AFTER 중엔 링에 안 쌓는다


def test_after_window_closes_on_time(fq):
    """뒤 10초가 지나면 링 버퍼로 돌아간다."""
    detect(fq)
    fq._after_until = time.time() - 1                       # 창을 강제로 닫는다
    fq.frame(JPEG, camera="L")
    assert [i for i in fq._uploader.items if i[1] == "AFTER"] == []
    assert len(fq.ring) == 1


def test_after_stops_when_accident_closes(fq):
    """🔴 Pi 가 사고를 닫으면 멈춘다. AI 쪽이 종료 시점을 몰라도 된다."""
    detect(fq)
    fq._handle_state({"accident_id": "A1", "status": "CLOSE"})
    fq.frame(JPEG, camera="L")
    assert [i for i in fq._uploader.items if i[1] == "AFTER"] == []


def test_cancel_also_stops_after(fq):
    """오인신고로 취소된 경우다. 계속 올리면 남의 사고 자리에 쌓인다."""
    detect(fq)
    fq._handle_state({"accident_id": "A1", "status": "CANCEL"})
    fq.frame(JPEG, camera="L")
    assert [i for i in fq._uploader.items if i[1] == "AFTER"] == []


def test_detect_state_does_not_stop_after(fq):
    detect(fq)
    fq._handle_state({"accident_id": "A1", "status": "DETECT"})
    fq.frame(JPEG, camera="L")
    assert len([i for i in fq._uploader.items if i[1] == "AFTER"]) == 1


def test_snapshot_is_submitted(fq):
    detect(fq, snapshot=JPEG)
    snaps = [i for i in fq._uploader.items if i[1] == "DETECT_SNAPSHOT"]
    assert len(snaps) == 1
    assert snaps[0][2] is None                              # 순번이 없다


def test_stats_shape(fq):
    detect(fq)
    st = fq.stats()
    assert st["phase"] == "AFTER"
    assert st["mqtt"] == "connected"
    assert set(st) >= {"queued", "sent", "failed", "dropped", "ring"}


# ── 업로드 큐 ────────────────────────────────────────────────────────
def test_queue_drops_after_first():
    """🔴 큐가 차면 AFTER 부터 버린다. BEFORE·스냅샷은 다시 못 만든다."""
    up = Uploader("http://test", max_items=4)
    up.submit("D", "DETECT_SNAPSHOT", None, JPEG)
    for i in (1, 2):
        up.submit("D", "BEFORE", i, JPEG)
    up.submit("D", "AFTER", 1, JPEG)
    assert up.queued == 4

    assert up.submit("D", "AFTER", 2, JPEG) is True         # 오래된 AFTER 를 버리고 자리
    assert up.dropped == 1
    kinds = sorted(up._q.queue, key=lambda i: i.priority)
    assert [i.file_type for i in kinds].count("BEFORE") == 2
    assert any(i.file_type == "DETECT_SNAPSHOT" for i in kinds)


def test_queue_refuses_after_when_nothing_to_drop():
    """버릴 AFTER 가 없으면 들어오는 AFTER 를 버린다. BEFORE 를 대신 버리지 않는다."""
    up = Uploader("http://test", max_items=2)
    up.submit("D", "BEFORE", 1, JPEG)
    up.submit("D", "BEFORE", 2, JPEG)
    assert up.submit("D", "AFTER", 1, JPEG) is False
    assert up.queued == 2


def test_snapshot_goes_first():
    """우선순위: 스냅샷 -> BEFORE -> AFTER. 화면 대표 이미지가 가장 먼저 떠야 한다."""
    up = Uploader("http://test")
    up.submit("D", "AFTER", 1, JPEG)
    up.submit("D", "BEFORE", 1, JPEG)
    up.submit("D", "DETECT_SNAPSHOT", None, JPEG)
    order = [up._q.get().file_type for _ in range(3)]
    assert order == ["DETECT_SNAPSHOT", "BEFORE", "AFTER"]


def test_frame_validates(fq):
    with pytest.raises(InvalidCall):
        fq.frame(b"", camera="L")
    with pytest.raises(InvalidCall):
        fq.frame(JPEG, camera="Z")


# ── 스키마 (pydantic) ────────────────────────────────────────────────
def test_error_message_names_the_field(fq):
    """🔴 메시지에 필드명이 있어야 AI 팀이 고칠 수 있다. pydantic 이 만든 것을 쓴다."""
    with pytest.raises(InvalidCall, match="confidence"):
        fq.detected(lat=35.05, lon=129.1, distance_m=12.4, confidence=2.0)


def test_zero_size_bbox_rejected(fq):
    """w·h 가 0 이면 키오스크가 상자를 못 그린다. 오류는 안 나고 그림만 안 나온다."""
    with pytest.raises(InvalidCall, match="bbox"):
        detect(fq, bbox=(320, 180, 0, 128))


def test_frame_count_must_be_positive(fq):
    with pytest.raises(InvalidCall, match="frame_count"):
        detect(fq, frame_count=0)


def test_payload_has_no_accident_id(fq):
    """🔴 Jetson 은 사고 번호를 모른다. 만들기 시작하면 Pi 의 E1 이 무력해진다."""
    detect(fq)
    assert "accident_id" not in fq._bus.published[0][1]


def test_payload_matches_contract_field_names(fq):
    """Pi 의 JetsonDetection 과 필드 이름이 같아야 한다. 오타는 조용한 null 이 된다."""
    detect(fq, yaw=1.0, pitch=2.0, target_lat=35.0, target_lon=129.0)
    sent = fq._bus.published[0][1]
    assert set(sent) == {
        "detection_id", "ship_id", "lat", "lon", "distance_m", "confidence",
        "frame_count", "model_version", "camera", "bbox", "detected_at", "launch"}
    assert set(sent["launch"]) == {
        "target_yaw_deg", "target_pitch_deg", "launch_profile",
        "target_lat", "target_lon", "solved_at"}


def test_contract_mismatch_is_reported_not_raised():
    """🔴 계약이 갈라졌다고 탐지를 멈추면 필드 하나 때문에 사람을 못 건진다."""
    from floaq_jetson._models import verify_against
    assert verify_against({"topics": {}})                      # 토픽이 없다 -> 보고
    problems = verify_against({"topics": {"jetson/detection": {
        "properties": {"detection_id": {}, "ship_id": {}, "새필드": {}}}}})
    assert any("Pi 가 요구하는데" in p for p in problems)
    assert any("SDK 가 보내는데" in p for p in problems)


def test_internals_are_not_public():
    """`fj.Uploader` 를 쓰기 시작하면 내부 구조를 못 바꾼다."""
    import floaq_jetson as fj
    for name in ("Uploader", "RingBuffer", "Bus", "requests"):
        with pytest.raises(AttributeError, match="공개 API"):
            getattr(fj, name)


# ── 라이브 스트림 ────────────────────────────────────────────────────
def test_stream_gets_every_frame_even_when_idle(fq):
    """🔴 기록 경로와 무관하다. 사고가 아니어도 화면은 카메라를 보고 있어야 한다."""
    from floaq_jetson._stream import StreamServer
    fq._stream = StreamServer(0)                  # 포트를 열지 않는다
    for _ in range(3):
        fq.frame(JPEG, camera="L")
    assert fq._stream.latest.get("L") == JPEG


def test_inference_stream_sends_annotated_frame(monkeypatch):
    """촬영 콜백 뒤 모델 결과가 키오스크용 JPEG로 전달된다."""
    from types import SimpleNamespace

    from floaq_jetson._inference import InferenceStream

    class Image:
        shape = (24, 32, 3)

    class Encoded:
        def tobytes(self):
            return b"annotated-jpeg"

    class Result:
        def plot(self):
            return Image()

    class Model:
        def __init__(self, weights):
            assert weights == "model.onnx"

        def predict(self, image, **options):
            assert isinstance(image, Image)
            assert options["conf"] == 0.4
            return [Result()]

    cv2 = SimpleNamespace(
        IMREAD_COLOR=1, IMWRITE_JPEG_QUALITY=2,
        imdecode=lambda data, mode: Image(),
        imencode=lambda ext, image, options: (True, Encoded()),
    )
    np = SimpleNamespace(uint8=1, frombuffer=lambda data, dtype: data)
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "numpy", np)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))

    frames = []
    delivered = threading.Event()

    def on_frame(jpeg, camera, size):
        frames.append((jpeg, camera, size))
        delivered.set()

    worker = InferenceStream(on_frame, weights="model.onnx", conf=0.4)
    worker.start()
    try:
        # Capture._loop 이 실제로 넘기는 세 인자와 같은 호출 형태다.
        worker.submit(JPEG, "L", (32, 24))
        assert delivered.wait(2.0)
    finally:
        worker.stop()
    assert frames == [(b"annotated-jpeg", "L", (32, 24))]


def test_stream_keeps_cameras_apart(fq):
    from floaq_jetson._stream import StreamServer
    fq._stream = StreamServer(0)
    fq.frame(JPEG, camera="L")
    fq.frame(JPEG + b"R", camera="R")
    assert fq._stream.latest.get("L") == JPEG
    assert fq._stream.latest.get("R") == JPEG + b"R"


def test_stream_holds_only_latest():
    """🔴 쌓아 두면 느린 클라이언트가 메모리를 채우고 화면이 과거를 보여준다."""
    from floaq_jetson._stream import _Latest
    lat = _Latest()
    for i in range(100):
        lat.put(bytes([i]), "L")
    assert lat.get("L") == bytes([99])


def test_stream_start_failure_does_not_raise():
    """🔴 스트림이 안 떠도 탐지는 돌아야 한다. 예외가 아니라 False 를 돌려준다.

    ⚠ "같은 포트 두 번"으로 시험하지 않는다 — Windows 는 `allow_reuse_address` 로
      그게 성공한다. 붙일 수 없는 주소를 쓰면 어느 OS 에서나 실패한다.
    """
    from floaq_jetson._stream import StreamServer
    s = StreamServer(8080, host="203.0.113.1")     # 이 기기 것이 아닌 주소
    assert s.start() is False
    s.stop()                                        # 안 떴어도 정리가 안전해야 한다


def test_health_always_lists_both_cameras():
    """🔴 프레임이 온 것만 나열하면 R 고장과 카메라 한 대를 구분할 수 없다.

    스테레오 거리(AI-03)가 둘 다 필요해서, 한쪽만 도는 상태는 조준 해가 조용히
    나빠지는 것이다. 예외도 로그도 안 남으므로 /health 가 드러내는 유일한 자리다.
    """
    from floaq_jetson._stream import _Latest
    lat = _Latest()
    assert set(lat.health()) == {"L", "R"}
    assert all(not c["live"] for c in lat.health().values())

    lat.put(JPEG, "L")
    h = lat.health()
    assert h["L"]["live"] is True and h["L"]["frames"] == 1
    assert h["R"]["live"] is False and h["R"]["age_sec"] is None

    lat.put(JPEG, "R")
    assert all(c["live"] for c in lat.health().values())


def test_health_marks_stale_camera_dead():
    """잠깐 끊긴 것과 고장을 age_sec 으로 가른다."""
    from floaq_jetson import _stream
    lat = _stream._Latest()
    lat.put(JPEG, "L")
    lat._at["L"] -= _stream.STALE_SEC + 1       # 프레임이 한참 전에 왔다
    assert lat.health()["L"]["live"] is False
    assert lat.health()["L"]["frames"] == 1     # 왔던 사실은 남는다


def test_409_abandons_whole_detection():
    """🔴 409 는 장당이 아니라 **탐지 단위**다.

    하나가 거부되면 나머지 125장도 같은 이유로 거부된다. 큐에 두면 그만큼 요청과
    로그를 태우고(실제로 126줄이 쏟아졌다), 그 사이 다음 탐지의 프레임이 뒤로 밀린다.
    """
    up = Uploader("http://test")
    for i in range(1, 6):
        up.submit("D1", "BEFORE", i, JPEG)
    up.submit("D2", "BEFORE", 1, JPEG)          # 다른 탐지는 남아야 한다
    assert up.queued == 6

    up._abandon("D1")
    assert up.queued == 1
    assert up._q.get().detection_id == "D2"


def test_abandoned_detection_refuses_new_frames():
    """AFTER 프레임이 뒤늦게 들어와도 막는다. 큐에 넣어봐야 같은 답이 온다."""
    up = Uploader("http://test")
    up._abandon("D1")
    assert up.submit("D1", "AFTER", 1, JPEG) is False
    assert up.submit("D2", "AFTER", 1, JPEG) is True


# ── 배 GPS ───────────────────────────────────────────────────────────
def test_ship_fix_is_none_before_any_gps(fq):
    """🔴 좌표가 없으면 None 이어야 한다. 0,0 을 돌려주면 기니 만 앞바다가 된다."""
    assert fq.ship_fix() is None


def test_ship_fix_takes_the_latest_gps(fq):
    fq._handle_gps({"lat": 35.05, "lon": 129.10, "speed_kn": 8.0,
                    "heading_deg": 84.4, "measured_at": 1789000000})
    got = fq.ship_fix()
    assert got["lat"] == 35.05 and got["lon"] == 129.10
    assert got["heading_deg"] == 84.4


def test_ship_fix_goes_stale(fq):
    """🔴 오래된 좌표를 그냥 돌려주면 안 된다. 10노트면 5초에 26m 간다."""
    import time as _t
    fq._handle_gps({"lat": 35.05, "lon": 129.10})
    fq._fix_at = _t.time() - 30.0
    assert fq.ship_fix() is None
    assert fq.ship_fix(max_age_sec=60.0) is not None


def test_malformed_gps_is_ignored(fq):
    """브로커에서 뭐가 오든 이 스레드는 살아야 한다."""
    for bad in ({}, {"lat": "x", "lon": 1}, {"lat": None, "lon": None}, {"lon": 1}):
        fq._handle_gps(bad)
    assert fq.ship_fix() is None


def test_stats_reports_fix_age(fq):
    assert fq.stats()["fix_age"] is None
    fq._handle_gps({"lat": 35.05, "lon": 129.10})
    assert fq.stats()["fix_age"] is not None


# ── 진행 중 사고 ─────────────────────────────────────────────────────
def test_busy_accident_is_none_before_any_state(fq):
    fq._accident_status = None
    assert fq.busy_accident() is None


@pytest.mark.parametrize("status", ["DETECT", "WAIT", "REPORT"])
def test_busy_while_an_accident_is_open(fq, status):
    """🔴 이 상태면 Pi 가 새 탐지를 409 로 거부한다 (E1).

    미리 안 보면 프레임 200장을 다 만들고 나서 통째로 버리게 된다.
    """
    fq._handle_state({"accident_id": "A-1", "status": status})
    assert fq.busy_accident() == "A-1"


@pytest.mark.parametrize("status", ["CLOSE", "CANCEL", "RESCUE"])
def test_not_busy_after_the_accident_ends(fq, status):
    fq._handle_state({"accident_id": "A-1", "status": "WAIT"})
    fq._handle_state({"accident_id": "A-1", "status": status})
    assert fq.busy_accident() is None


def test_accident_open_reads_retained_only(fq):
    """프레임마다 부르는 자리다. HTTP 를 치면 5fps x 2대 = 초당 10번이 된다."""
    assert fq.accident_open() is False
    fq._handle_state({"accident_id": "A-1", "status": "REPORT"})
    assert fq.accident_open() is True
    fq._handle_state({"accident_id": "A-1", "status": "CLOSE"})
    assert fq.accident_open() is False

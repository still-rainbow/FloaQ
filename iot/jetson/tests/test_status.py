"""`jetson/status` — 젯슨의 생존 신호이자 키오스크 장치 패널의 원천.

🔴 계약과 받는 쪽(Pi·키오스크)은 처음부터 있었고 **보내는 쪽만 없었다.**
   그래서 화면의 카메라·AI 가 시연 내내 '모름' 이었다 (2026-09-22).
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from floaq_jetson._models import JetsonStatus
from floaq_jetson.__main__ import CAMERA_STALE_S, _publish_status


class Cap:
    def __init__(self, sources, fresh=(), age=0.0):
        self.sources = {k: 0 for k in sources}
        now = time.monotonic()
        self.last_frame_at = {k: now - age for k in fresh}


class Inference:
    def __init__(self, processed=0):
        self.processed = processed


class Fq:
    def __init__(self):
        self.calls = []

    def status(self, **kw):
        self.calls.append(kw)
        return True


def test_missing_camera_is_unknown_not_error():
    """⚠ 안 붙인 것과 고장 난 것은 다르다. `--camera L=0` 은 정상이다."""
    fq = Fq()
    _publish_status(fq, Cap(["L"], fresh=["L"]), Inference(), {})
    assert fq.calls[0]["camera_l"] == "OK"
    assert fq.calls[0]["camera_r"] == "UNKNOWN"


def test_opened_but_no_frames_is_error():
    """🔴 `cap.opened` 로 판정하면 케이블이 빠져도 정상으로 그려진다."""
    fq = Fq()
    _publish_status(fq, Cap(["L", "R"], fresh=["L"]), Inference(), {})
    assert fq.calls[0]["camera_l"] == "OK"
    assert fq.calls[0]["camera_r"] == "ERROR"


def test_stale_frames_are_error():
    fq = Fq()
    cap = Cap(["L", "R"], fresh=["L", "R"], age=CAMERA_STALE_S + 1)
    _publish_status(fq, cap, Inference(), {})
    assert fq.calls[0]["camera_l"] == "ERROR"


def test_fps_comes_from_the_difference():
    """추론 fps 는 누적 카운터의 차이로 낸다. 첫 회차는 기준만 잡는다."""
    fq, cap, state = Fq(), Cap(["L"], fresh=["L"]), {}
    _publish_status(fq, cap, Inference(0), state)
    assert fq.calls[0]["inference_fps"] == 0.0
    state["proc"] = (0, time.monotonic() - 2.0)     # 2초 전에 0장이었다
    _publish_status(fq, cap, Inference(10), state)
    assert fq.calls[1]["inference_fps"] == pytest.approx(5.0, abs=0.5)


def test_fps_is_never_negative():
    """⚠ 추론 스트림을 다시 만들면 카운터가 0 으로 돌아간다."""
    fq, cap = Fq(), Cap(["L"], fresh=["L"])
    state = {"proc": (100, time.monotonic() - 1.0)}
    _publish_status(fq, cap, Inference(0), state)
    assert fq.calls[0]["inference_fps"] == 0.0


def test_publish_failure_does_not_escape():
    """🔴 상태 발행이 5초 루프를 죽이면 화면도 통계도 같이 멈춘다."""
    class Boom:
        def status(self, **kw):
            raise RuntimeError("브로커 끊김")

    _publish_status(Boom(), Cap(["L"]), Inference(), {})


def test_contract_rejects_a_bad_health_value():
    """🔴 오타 난 상태값이 조용히 나가면 키오스크가 그 장치를 안 그린다."""
    base = dict(model_version="v8", inference_fps=1.0, camera_l="OK",
                camera_r="OK", camera_dirty=False, gps_received=True,
                uptime_sec=1)
    JetsonStatus(**base)
    with pytest.raises(ValidationError):
        JetsonStatus(**{**base, "camera_l": "GOOD"})
    with pytest.raises(ValidationError):
        JetsonStatus(**{**base, "inference_fps": -1.0})

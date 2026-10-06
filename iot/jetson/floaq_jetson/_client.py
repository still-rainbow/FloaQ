"""Floaq 클라이언트 구현. 공개 이름은 `__init__` 이 재수출한다.

⚠ 여기 있는 것을 직접 import 하지 않는다. 내부 구조는 바뀔 수 있다.
"""


from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import requests

from pydantic import ValidationError

from ._models import (AimCommand, JetsonDetection, JetsonStatus,
                      LaunchSolution, verify_against)
from ._mqtt import Bus
from ._ring import RingBuffer
from ._stream import StreamServer
from ._upload import Uploader
from .ids import uuid7

log = logging.getLogger(__name__)

__all__ = ["Floaq", "Detection", "InvalidCall"]

#: 기본값. Pi 의 `floaq/config.py` 와 같은 값이어야 한다.
FRAME_PRE_SEC = 15
FRAME_POST_SEC = 10
FRAME_FPS = 5

MQTT_PORT = 1883
HTTP_PORT = 8000
#: Jetson 이 여는 라이브 스트림 포트. 키오스크·Pi 가 여기를 본다.
STREAM_PORT = 8080


class InvalidCall(ValueError):
    """호출 인자가 규격 밖이다. **AI 쪽 버그다** — 조용히 넘기지 않는다.

    메시지에 필드명과 받은 값이 들어 있다. pydantic 이 만든 것을 그대로 옮긴다.
    """


#: 발사 프로파일 기본값.
#:
#: 🔴 **Pi 가 화이트리스트로 막는다** (`floaq/config.py` `APPROVED_LAUNCH_PROFILES`).
#:    목록에 없는 이름이면 `state.validate_launch` 가 `OUT_OF_RANGE` 로 거부하고
#:    발사가 아예 안 나간다. 사고·카운트다운·신고는 멀쩡히 돌아서 각도 문제처럼
#:    보인다 — 2026-09-22 전수검사에서 기본값이 `"default"` 인 채로 아무도
#:    안 넘기고 있던 것을 찾았다. 그 값은 화이트리스트에 없다.
#:
#: ⚠ Pi 의 목록과 **글자까지** 같아야 한다. 늘릴 때 양쪽을 같이 고친다.
DEFAULT_LAUNCH_PROFILE = "demo-low-v1"


@dataclass(frozen=True, slots=True)
class Detection:
    """`detected()` 가 돌려주는 것. 보통 쓸 일이 없다."""

    detection_id: str
    detected_at: int
    published: bool      #: MQTT 로 나갔는가. False 면 큐에 쥐고 있다는 뜻이다


class Floaq:
    """Pi 와 말하는 유일한 객체.

    ⚠ 하나만 만든다. 두 개 만들면 링 버퍼가 갈라져서 사고 전 프레임이 반씩 나뉜다.
    """

    def __init__(self, pi: str, *, ship_id: str | None = None,
                 mqtt_port: int = MQTT_PORT, http_port: int = HTTP_PORT,
                 model_version: str = "unknown",
                 pre_sec: int = FRAME_PRE_SEC, post_sec: int = FRAME_POST_SEC,
                 fps: int = FRAME_FPS, stream_port: int | None = STREAM_PORT) -> None:
        """`ship_id` 를 안 주면 Pi 의 `/health` 에서 가져온다.

        🔴 `ship_id` 가 틀리면 **브로커가 아무 에러도 주지 않고 조용히 아무것도 안
          온다.** 토픽이 `ship/{ship_id}/...` 라서 그냥 다른 방에 말하는 셈이다.
          그래서 손으로 적게 두지 않고 Pi 에게 물어본다.
        """
        self.pi = pi
        self.http = f"http://{pi}:{http_port}"
        self.model_version = model_version
        self.post_sec = post_sec
        #: 기동 시각. `jetson/status.uptime_sec` 에 쓴다
        self._started_at = time.monotonic()

        self.ship_id = ship_id or self._ask_ship_id()
        self.ring = RingBuffer(pre_sec, fps)
        # 라이브 보기용. `stream_port=None` 이면 안 띄운다
        self._stream = StreamServer(stream_port) if stream_port else None
        self._uploader = Uploader(self.http)
        self._bus = Bus(pi, mqtt_port, self.ship_id,
                        on_accident_state=self._handle_state,
                        on_gps=self._handle_gps)

        self._lock = threading.Lock()
        #: 배의 마지막 측위. `pi/sensor/gps` 를 그대로 받아 둔다.
        #:
        #: 🔴 **탐지에 좌표가 필요한데 Jetson 에는 GPS 가 없다.** 배가 갖고 있고
        #:   Pi 가 1Hz 로 뿌린다. 그걸 안 받으면 `detected()` 에 넣을 lat/lon 이
        #:   없어서 AI 가 좌표를 지어내게 된다 — 구조대가 그 좌표로 간다.
        self._fix: dict | None = None
        self._fix_at = 0.0
        self._detection_id: str | None = None
        self._accident_id: str | None = None
        #: 마지막으로 들은 사고 상태. 브로커의 retained 라 붙자마자 온다.
        #: 진행 중인 사고가 있으면 새 탐지는 Pi 가 409 로 거부한다 (E1)
        self._accident_status: str | None = None
        self._after_until = 0.0
        self._after_seq = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self, timeout: float = 5.0) -> bool:
        """워커를 띄우고 브로커에 붙는다. 못 붙어도 예외는 없다 — 재접속한다."""
        self._uploader.start()
        if self._stream:
            self._stream.start()
        ok = self._bus.start(timeout)
        self._verify_contract()
        return ok

    def close(self, timeout: float = 5.0) -> None:
        """남은 업로드를 잠깐 기다렸다가 정리한다."""
        self._bus.stop()
        if self._stream:
            self._stream.stop()
        self._uploader.stop(timeout)

    def __enter__(self) -> Floaq:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── ① 매 프레임 ──────────────────────────────────────────────────
    def frame(self, jpeg: bytes, camera: str = "L",
              captured_at: float | None = None) -> None:
        """프레임 한 장. **매 프레임 부른다.** 즉시 돌아온다.

        평소에는 링 버퍼에만 쌓인다(앞 15초). 탐지 뒤 AFTER 구간에는 업로드 큐로도
        간다(뒤 10초). 그 전환은 여기서 알아서 한다.
        """
        if camera not in ("L", "R"):
            raise InvalidCall(f"camera: 'L' 또는 'R' 이어야 한다 (받은 값 {camera!r})")
        if not jpeg:
            raise InvalidCall("jpeg: 빈 프레임")
        now = captured_at if captured_at is not None else time.time()

        # 라이브 스트림은 **항상** 최신 한 장을 받는다. 기록 경로(링 버퍼·업로드)와
        # 무관하다 — 사고가 아니어도 화면은 카메라를 보고 있어야 한다
        if self._stream:
            self._stream.put(jpeg, camera)

        with self._lock:
            det, until = self._detection_id, self._after_until
            if det and now < until:
                self._after_seq += 1
                seq = self._after_seq
            else:
                seq = 0
                if det and now >= until:
                    # 뒤 10초가 끝났다. 링 버퍼로 돌아간다
                    self._detection_id = None
                    log.info("AFTER 수집 종료")

        if seq:
            self._uploader.submit(det, "AFTER", seq, jpeg, camera)
        else:
            self.ring.push(jpeg, camera, now)

    # ── ② 탐지 ───────────────────────────────────────────────────────
    def aim(self, *, yaw: float, pitch: float, confidence: float,
            track_id: int | None = None) -> bool:
        """Send latest-only CH0/CH1 aiming data without release authority."""
        try:
            command = AimCommand(
                target_yaw_deg=yaw, target_pitch_deg=pitch,
                confidence=confidence, track_id=track_id,
                solved_at=int(time.time()),
            )
        except ValidationError as e:
            raise InvalidCall(_brief(e)) from None
        return self._bus.publish("jetson/aim", command.model_dump(mode="json"), qos=0)

    def status(self, *, camera_l: str = "UNKNOWN", camera_r: str = "UNKNOWN",
               inference_fps: float = 0.0, camera_dirty: bool = False) -> bool:
        """`jetson/status`. **Pi 가 젯슨의 생존을 이걸로 본다** (15초 미수신이면 죽음).

        🔴 이게 안 나가면 키오스크 장치 패널의 카메라·AI 가 통째로 '모름' 이다.
           카메라 L/R 상태는 젯슨만 알고, 키오스크는 Pi 를 통해서만 본다.

        ⚠ `gps_received` 는 여기서 직접 본다 — 배 GPS 가 없으면 조준 해를 못 내고
          탐지도 안 올라가는데, 그 사실이 화면에 안 보이면 원인을 못 찾는다.
        """
        try:
            st = JetsonStatus(
                model_version=self.model_version,
                inference_fps=max(0.0, float(inference_fps)),
                camera_l=camera_l, camera_r=camera_r,
                camera_dirty=bool(camera_dirty),
                gps_received=self.ship_fix() is not None,
                uptime_sec=int(time.monotonic() - self._started_at),
            )
        except ValidationError as e:
            raise InvalidCall(_brief(e)) from None
        return self._bus.publish("jetson/status", st.model_dump(mode="json"),
                                 qos=1, retain=True)

    def detected(self, *, lat: float, lon: float, distance_m: float,
                 confidence: float, camera: str = "L",
                 bbox: tuple[int, int, int, int] | None = None,
                 frame_count: int = 1, snapshot: bytes | None = None,
                 yaw: float | None = None, pitch: float | None = None,
                 target_lat: float | None = None, target_lon: float | None = None,
                 launch_profile: str = DEFAULT_LAUNCH_PROFILE) -> Detection:
        """사람을 봤다. **한 번만 부르면 나머지는 전부 자동이다.**

        조준 해(`yaw`·`pitch`·`target_*`)는 낼 수 있을 때만 준다. 없으면 탐지는
        유효하고 발사만 안 된다 — Pi 가 `NO_SOLUTION` 으로 기록한다.

        ⚠ 각도를 보냈다고 발사가 확정되는 건 아니다. Pi 가 범위·만료·장전 상태를
          검증하고 거부하면 그대로 버려진다.
        """
        aim = (yaw, pitch, target_lat, target_lon)
        has_aim = None not in aim
        if any(v is not None for v in aim) and not has_aim:
            # 절반만 준 것은 버그다. 조용히 NO_SOLUTION 으로 떨어뜨리면 왜 발사가
            # 안 되는지 시연 날까지 모른다
            raise InvalidCall(
                "조준 해는 yaw·pitch·target_lat·target_lon 을 전부 주거나 전부 생략한다")

        now = int(time.time())
        detection_id = uuid7()
        # 🔴 검증은 pydantic 한 곳에서 한다. 손으로 쓴 if 문은 정본과 갈라져도
        #   아무도 모른다 (`_models.py`)
        try:
            det = JetsonDetection(
                detection_id=detection_id, ship_id=self.ship_id,
                lat=lat, lon=lon, distance_m=distance_m, confidence=confidence,
                frame_count=frame_count, model_version=self.model_version,
                camera=camera, bbox=bbox, detected_at=now,
                launch=LaunchSolution(
                    target_yaw_deg=yaw, target_pitch_deg=pitch,
                    launch_profile=launch_profile,
                    target_lat=target_lat, target_lon=target_lon,
                    solved_at=now) if has_aim else None,
            )
        except ValidationError as e:
            raise InvalidCall(_brief(e)) from None

        published = self._bus.publish("jetson/detection", det.model_dump(mode="json"))

        # 🔴 발행 성공 여부와 무관하게 프레임을 올린다. QoS 1 이라 탐지는 재접속 때
        #   나가고, 그 사이 링 버퍼가 덮어써지면 사고 전 장면을 영영 잃는다
        pre = self.ring.drain()
        for i, f in enumerate(pre, start=1):
            self._uploader.submit(detection_id, "BEFORE", i, f.jpeg, f.camera)
        if snapshot:
            self._uploader.submit(detection_id, "DETECT_SNAPSHOT", None,
                                  snapshot, camera)

        with self._lock:
            self._detection_id = detection_id
            self._after_until = time.time() + self.post_sec
            self._after_seq = 0

        log.warning("탐지 발행 %s  (%.6f, %.6f)  conf=%.2f  조준해=%s  BEFORE %d장",
                    detection_id, lat, lon, confidence, "있음" if has_aim else "없음",
                    len(pre))
        return Detection(detection_id, now, published)

    # ── 상태 ─────────────────────────────────────────────────────────
    #: 이 상태면 Pi 가 새 탐지를 409 로 거부한다 (E1, 동시 사고 1건)
    BUSY_STATUS = ("DETECT", "WAIT", "REPORT")

    def accident_open(self) -> bool:
        """진행 중 사고가 있나. **retained 만 본다 — 값이 싸다.**

        프레임마다 부르는 자리(`on_detect`)용이다. `busy_accident()` 는 Pi 에
        HTTP 를 치므로 5fps x 2대 = 초당 10번 부를 수 없다.

        ⚠ retained 는 늦거나 낡을 수 있다. 여기서 틀려도 손해는 "탐지를 한 번
          더 만들었다가 409 로 버린다" 뿐이라 감당된다. **판단이 중요한 자리에는
          `busy_accident()` 를 쓸 것.**
        """
        with self._lock:
            return self._accident_status in self.BUSY_STATUS

    def busy_accident(self) -> str | None:
        """진행 중인 사고 id. 없으면 None.

        🔴 **새 탐지를 쏘기 전에 본다.** E1 때문에 Pi 가 409 로 거부하는데,
          그걸 프레임을 다 만들고 나서 알면 그 30초와 200장이 통째로 버려진다.
          실제로 그랬다 — "남은 212장을 버린다" 한 줄로 끝났다.

        🔴 **Pi 에게 직접 묻는다.** `pi/accident/state` retained 로도 같은 것이
          오지만 그건 브로커에 남는 **소문**이다. Pi 가 재시작하거나 CLOSE 발행을
          놓치면 옛 `WAIT` 이 영원히 남고, 사고를 닫았는데도 계속 막힌다 —
          실제로 밟았다. DB 가 원본이다.

        ⚠ HTTP 가 안 되면 retained 로 물러선다. 아무것도 모르는 것보다는 낫다.
        """
        try:
            r = requests.get(f"{self.http}/api/accidents/active", timeout=(3.0, 5.0))
            if r.ok:
                return (r.json() or {}).get("accident_id")
        except Exception as e:
            log.warning("진행 중 사고 조회 실패 (%s). retained 로 판단한다",
                        type(e).__name__)
        with self._lock:
            if self._accident_status in self.BUSY_STATUS:
                return self._accident_id
            return None

    def ship_fix(self, max_age_sec: float = 5.0) -> dict | None:
        """배의 최근 측위. 너무 오래됐으면 None.

        🔴 **오래된 좌표를 그냥 돌려주면 안 된다.** 10노트면 5초에 26m 간다.
          Pi 가 끊긴 줄 모르고 몇 분 전 위치로 신고하는 것이 제일 나쁜 실패다.
        """
        with self._lock:
            if self._fix is None or time.time() - self._fix_at > max_age_sec:
                return None
            return dict(self._fix)

    def _handle_gps(self, data: dict) -> None:
        """`pi/sensor/gps` 수신. 봉투는 Bus 가 벗겨서 준다."""
        try:
            lat, lon = float(data["lat"]), float(data["lon"])
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self._fix = {"lat": lat, "lon": lon,
                         "speed_kn": data.get("speed_kn"),
                         "heading_deg": data.get("heading_deg"),
                         "measured_at": data.get("measured_at")}
            self._fix_at = time.time()

    def stats(self) -> dict:
        """지금 상태. 배선이 되는지 확인할 때 이걸 찍는다."""
        with self._lock:
            phase = "AFTER" if self._detection_id else "IDLE"
            accident_id = self._accident_id
            fix_age = time.time() - self._fix_at if self._fix else None
        return {
            "mqtt": "connected" if self._bus.connected.is_set() else "disconnected",
            "phase": phase,
            "accident_id": accident_id,
            "fix_age": round(fix_age, 1) if fix_age is not None else None,
            "ring": len(self.ring),
            "ring_bytes": self.ring.bytes_held,
            "queued": self._uploader.queued,
            "sent": self._uploader.sent,
            "failed": self._uploader.failed,
            "dropped": self._uploader.dropped,
            "up_ms": self._uploader.avg_ms,
            "up_mbps": self._uploader.mbps,
            "stream": f"http://0.0.0.0:{self._stream.port}/" if self._stream else None,
        }

    # ── 내부 ─────────────────────────────────────────────────────────
    def _handle_state(self, data: dict) -> None:
        """`pi/accident/state`. 사고가 닫히면 AFTER 수집을 멈춘다."""
        status = data.get("status")
        with self._lock:
            self._accident_id = data.get("accident_id")
            self._accident_status = status
            if status in ("CANCEL", "CLOSE") and self._detection_id:
                self._detection_id = None
                log.info("사고 %s - AFTER 수집 중단", status)

    def _ask_ship_id(self) -> str:
        try:
            r = requests.get(f"{self.http}/health", timeout=(3.0, 5.0))
            ship_id = r.json().get("ship_id")
        except Exception as e:
            raise InvalidCall(
                f"Pi 의 /health 에서 ship_id 를 못 받았다 ({type(e).__name__}). "
                f"{self.http} 가 떠 있는지 확인하거나 ship_id= 를 직접 줄 것") from None
        if not ship_id:
            raise InvalidCall("Pi 가 ship_id 를 안 준다 — 선박 등록이 아직 안 됐다")
        return ship_id

    def _verify_contract(self) -> None:
        """Pi 의 `/contract.json` 과 필드를 대조한다. 어긋나도 **멈추지 않는다.**

        계약이 갈라졌다고 탐지를 막으면 필드 하나 때문에 사람을 못 건진다.
        경고만 남기고 계속 보낸다 — Pi 는 모르는 필드를 무시하게 돼 있다.
        """
        try:
            r = requests.get(f"{self.http}/contract.json", timeout=(3.0, 5.0))
            problems = verify_against(r.json())
        except Exception as e:
            log.info("계약 대조를 건너뛴다 (%s)", type(e).__name__)
            return
        for p in problems:
            log.warning("계약 불일치: %s", p)


def _brief(e: ValidationError) -> str:
    """pydantic 오류를 한 줄로. 필드명과 받은 값이 남아야 고칠 수 있다."""
    parts = []
    for err in e.errors()[:3]:
        loc = ".".join(str(x) for x in err["loc"]) or "?"
        parts.append(f"{loc}: {err['msg']}")
    return " / ".join(parts)

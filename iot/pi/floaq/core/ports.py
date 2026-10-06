"""core 가 바깥 세계에 대해 아는 전부.

**여기 있는 것 말고는 core 가 아무것도 import 하지 않는다.** paho 도, serial 도, lgpio 도,
sqlalchemy 도 모른다. 경계가 지켜지는지는 한 줄로 확인할 수 있다:

    grep -rn "import paho\\|import serial\\|import lgpio\\|import sqlalchemy" floaq/core/

비어 있어야 한다.

얻는 것이 둘이다.

1. **하드웨어 없이 테스트된다.** DES-37 §4 스프링 실측이 끝나기 전까지 기구 쪽은 전부
   정지 상태인데, 상태머신과 거부 규칙은 지금 전부 검증할 수 있다.
   DES-38 §9 의 승인 조건 — "범위·만료·중복 명령 거부 시험", "비상 정지와 전원 재인가 시
   자동 발사하지 않음" — 이 실물 없이 증명된다.

2. **전송을 갈아끼울 수 있다.** 지금은 MQTT 지만 키오스크 구간이 WS 로 바뀌어도
   core 는 그대로다. 어댑터만 새로 쓴다.

ABC 가 아니라 `Protocol` 을 쓴다 — 구현체가 상속할 필요가 없고 런타임 비용도 없다.
어댑터는 그냥 메서드 이름만 맞추면 된다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class Clock(Protocol):
    """시각. 주입하는 이유는 테스트에서 30초 카운트다운을 기다리지 않기 위해서다.

    구현체는 GPS UTC 를 쓴다 — Pi 5 에 RTC 가 없고 폐쇄망이라 NTP 도 없다.
    """

    def now(self) -> int:
        """Unix epoch 초."""

    def is_valid(self) -> bool:
        """GPS fix 를 받아 시각을 믿을 수 있는가.

        False 인 동안 orchestrator 는 **자동 전이를 하지 않는다.**
        안 그러면 부팅 직후 report_due_at 이 과거로 보여 신고가 나간다.
        """


@runtime_checkable
class GnssSource(Protocol):
    """배의 GPS. **Pi 에 GPS 모듈을 달지 않는다** — 배가 이미 갖고 있다.

    DSC·AIS 장비를 단 배는 GPS 가 필수라(없으면 그 장비가 동작을 못 한다) 플로터가
    NMEA 0183 으로 `$xxRMC` 를 계속 뱉는다. 그걸 읽는다.

    한 문장에 필요한 게 다 들어 있다 — 위치·UTC 시각·침로.
    그래서 시계 문제(Pi 5 는 RTC 가 없고 폐쇄망이라 NTP 도 없다)까지 같이 풀린다.

    ⚠ **풀(pull) 방식이다.** 어댑터가 자기 스레드에서 읽어 최신값만 들고 있고,
      호출자는 그 스냅샷을 가져간다. 콜백이면 시리얼 읽기 스레드에서 SQLite·발행을
      하게 되는데, 그건 `adapters/mqtt.py` 가 이미 피하고 있는 함정이다.
    """

    def read(self) -> object | None:
        """마지막 측위. 아직 없으면 None. **블로킹하지 않는다.**"""


@runtime_checkable
class BuoyLink(Protocol):
    """부표 LoRa 수신기. 배에 라디오 하나, 부표에 라디오 하나. **단방향이다.**

    다운링크가 없다 — 부표는 발사관 안에서 나가므로 `accident_id` 를 받을 경로가
    애초에 없다. Pi 가 `repo.active()` 로 붙인다 (`docs/lora.md` §3.3).

    ⚠ **푸시가 아니라 드레인이다.** `GnssSource` 는 최신값 하나만 들고 있으면 되지만
      부표는 다르다 — 한 프레임이 `pi_buoy` 한 행이라 사이를 건너뛰면 익수자
      궤적에 구멍이 난다. 그래서 큐에 쌓아 두고 통째로 가져간다.

    ⚠ 콜백으로 만들지 않는다. 그러면 시리얼 읽기 스레드에서 SQLite 쓰기와 MQTT 발행을
      하게 된다 — `adapters/mqtt.py` 가 이미 피하고 있는 함정이다.
    """

    def drain(self) -> list[object]:
        """쌓인 수신을 전부 가져가고 큐를 비운다. **블로킹하지 않는다.**

        원소는 `contracts.lora.Reception` 이다.
        """


@runtime_checkable
class MessageBus(Protocol):
    """발행·구독. MQTT 인지 WS 인지 core 는 모른다.

    subject 는 발행자 세그먼트를 포함한 상대 경로다 — 'pi/accident/state' 처럼.
    `ship/{ship_id}/` 접두사는 어댑터가 붙인다. core 가 ship_id 를 문자열로
    조립하기 시작하면 토픽 규약이 core 로 새어 들어온다.
    """

    def publish(self, subject: str, payload: BaseModel, *, retain: bool | None = None) -> None:
        """발행. qos·retain 기본값은 contracts.TOPICS 표에서 어댑터가 읽는다.

        retain 을 명시로 넘기는 경우는 **retained 를 지울 때**뿐이다 (사고 종료 후).
        """

    def clear_retained(self, subject: str) -> None:
        """0바이트 페이로드를 retain 으로 발행해 retained 를 삭제한다.

        ⚠ 발행자만 자기 토픽을 지울 수 있다. ACL 이 그렇게 걸려 있어서
          Pi 는 jetson/snapshot 을 못 지운다 — Jetson 이 pi/accident/state 에서
          CLOSE/CANCEL 을 보고 스스로 지운다.
        """


@runtime_checkable
class AccidentRepo(Protocol):
    """사고 영속화. SQLite 인지 core 는 모른다.

    ⚠ Pi 의 상태 원본은 브로커의 retained 가 아니라 이 저장소다.
      재부팅하면 여기서 복구하고 retained 를 다시 발행한다.
    """

    def active(self) -> object | None:
        """진행 중 사고(DETECT/WAIT/REPORT) 하나 또는 None. 동시 1건이라 단수다."""

    def get(self, accident_id: str) -> object | None: ...

    def create(self, accident: object) -> None:
        """⚠ 중복은 DB 의 uq_pi_accident_active 가 한 번 더 막는다.
        코드가 AI-05 를 놓쳐도 두 번째 INSERT 가 실패한다."""

    def update(self, accident: object) -> None: ...

    def append_state(self, transition: object) -> None:
        """상태 전이 이력. append-only — 덮어쓰면 S-05 타임라인이 사라지고,
        DES-38 §9 의 '전원 재인가 시 자동 발사하지 않음'을 증명할 근거도 없어진다."""

    def seen_request(self, request_id: str) -> bool:
        """명령 중복 판정. QoS 1 은 at-least-once 라 같은 명령이 두 번 온다.

        ⚠ 디스크에 남겨야 한다. 메모리에만 두면 재부팅 후 replay 된 명령이 통과한다.
        """

    def remember_request(self, request_id: str) -> None: ...

    # ── 부표 LoRa ────────────────────────────────────────────────────
    def add_buoy(self, accident_id: str, *, seq: int, lat: float, lon: float,
                 is_pressed: bool, rssi: float | None,
                 measured_at: int, received_at: int, now: int) -> int | None:
        """`buoy_log_id` 또는 None. **None 은 오류가 아니라 같은 초 중복이다.**

        1Hz 전제의 의도한 dedup 이라(`UNIQUE (accident_id, created_at)`) 호출자는
        조용히 넘긴다. 로그를 남기면 초당 한 줄이 된다.
        """

    def last_buoy(self, accident_id: str) -> object | None:
        """마지막 수신 행. 두절 판정이 `received_at` 을 본다."""

    def open_comm_loss(self, accident_id: str, *, detected_at: int,
                       last_buoy_log_id: int | None, last_lat: float, last_lon: float,
                       last_received_at: int, threshold_sec: int, now: int) -> int: ...

    def active_comm_loss(self, accident_id: str) -> object | None:
        """아직 안 닫힌 두절 구간. 없으면 None."""

    def close_comm_loss(self, comm_loss_id: int, recovered_at: int, now: int) -> None: ...

    def save_drift(self, accident_id: str, **kw: object) -> int:
        """표류 추정 한 건. `estimate_id`.

        🔴 쌓는다. 이전 건은 `is_current = 0` 으로 내린다 — 덮어쓰면 "그때 어디를
           수색 범위로 봤는지"가 사라진다.
        """

    def current_drift(self, accident_id: str, target: str = "BUOY") -> object | None:
        """지금 유효한 추정. 재부팅 복구가 retained 를 다시 발행할 때 쓴다."""


@runtime_checkable
class OceanSource(Protocol):
    """표류 계산에 넣을 해양 값.

    core 가 EC2 도 SQLite 도 모르게 하려고 한 겹 둔다. 구현은
    `floaq.ocean.OceanStore` 이고, 캐시(`pi_ocean_data`)에서 읽는다 —
    **두절 났을 때 인터넷이 있다는 보장이 없다.**
    """

    def ocean(self, now: int) -> object:
        """`floaq.drift.Ocean`. 값이 없으면 `usable` 이 False 인 것을 준다."""


@runtime_checkable
class Launcher(Protocol):
    """발사 장치. 서보·GPIO 는 어댑터 안에만 있다.

    안전 상태머신(SAFE→AIMING→ARMED→READY→RELEASED, +FAULT)은
    DES-38 §6 이 정본이고 **어댑터 구현 내부**에 산다.
    core 는 "쏴라"와 그 결과만 안다 — 사고 상태머신과 층이 다르다.
    """

    def is_loaded(self) -> bool:
        """물리 스위치 (IOT-04). 장전 안 됐으면 발사 시도 자체를 하지 않는다."""

    def aim(self, yaw_deg: float, pitch_deg: float) -> str:
        """CH0/CH1만 움직인다. 잠금 해제 또는 발사는 수행하지 않는다."""

    def aim_and_release(self, yaw_deg: float, pitch_deg: float, profile: str) -> str:
        """조준 후 해제. 'SUCCESS' 또는 fail_reason 을 돌려준다.

        ⚠ 재발사는 없다 (E5). 실패해도 다시 부르지 않는다.
        ⚠ 각도 범위·프로파일 검증은 **부르기 전에** core 가 한다.
          여기까지 왔다는 건 이미 통과했다는 뜻이다.
        """

    def safe(self) -> None:
        """무조건 안전 상태로. 부팅 시와 FAULT 복구 시 부른다.

        DES-38 §7: 부팅 시 구동 허가 기본값은 false 다.
        DES-38 §9: 전원 재인가 시 자동 발사하지 않는다 — 이 호출이 그 보증이다.
        """


@runtime_checkable
class Reporter(Protocol):
    """조난 신고 발신. UDP 소켓은 어댑터 안에 있다.

    발신 주체는 Pi 다 `확정` 2026-09-11.
    """

    def start(self, accident_id: str, lat: float, lon: float, dsc: int | None,
              *, trigger_kind: str = "AUTO") -> None:
        """채널별 반복 전송 시작. 인터넷이 없으면 NO_INTERNET 으로 실패를 보고한다 —
        조용히 삼키면 사용자는 신고가 나간 줄 안다.

        `trigger_kind` 는 `pi_report.trigger_kind`(AUTO/MANUAL/RESCUE)로 그대로 간다.
        발신 방식이 아니라 **행의 유래**다 — 채널 3개가 같은 값을 갖는다."""

    def stop(self, accident_id: str, reason: str) -> None:
        """구조 확정·사고 종료 시 중지 (IOT-12).

        ⚠ DSC 는 ACK 을 받으면 자동 중지하고 AIS 2채널은 수동 중지만 있다.
          채널별 분기를 한 루프에서 돌리면 빠뜨리기 쉽다.
        """

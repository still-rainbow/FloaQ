"""정책값 한 곳.

상세기획 §8 이 "코드에 흩뿌리지 말고 상수 파일 한 곳에 두세요"라고 요구한 그 파일이다.
값이 두 곳에 생기면 반드시 갈라진다 — 이 프로젝트는 이미 그 실패를 한 번 겪었다
(서버 application.yml 의 report-delay-sec 과 Pi 의 카운트다운이 각자 흘렀다).

`확정` 은 팀 결정, `제안` 은 승인 대기, `미정` 은 결정 없이 임시값이다.
임시값에는 반드시 TODO 와 담당을 적는다 — 안 적으면 그게 확정값으로 굳는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ── 사고 대응 ────────────────────────────────────────────────────────
#: 자동 신고 대기. `확정` — 설정 기능 없음, 스누즈 없음 (상세기획 §8)
#: 이 값은 `pi_accident.wait_sec` 에 **행마다 스냅샷**으로 박힌다.
#: 나중에 기준이 바뀌어도 과거 사고 기록이 흔들리지 않게 하려는 것이다.
WAIT_SEC: Final[int] = 30

#: 동시 사고 1건 (E1). DB 의 uq_pi_accident_active 부분 UNIQUE 인덱스가 같은 규칙을 강제한다.
#: 코드가 놓쳐도 두 번째 INSERT 가 실패하므로 여기 값은 "먼저 걸러내는" 용도다.
MAX_CONCURRENT_ACCIDENTS: Final[int] = 1

# ── 부표 ─────────────────────────────────────────────────────────────
#: 부표 LoRa 송신 주기 `확정` (IOT-05)
BUOY_TX_SEC: Final[int] = 1

#: LoRa 두절 판정. 이만큼 미수신이면 두절로 보고 표류 추정을 시작한다 `확정`
BUOY_TIMEOUT_SEC: Final[int] = 60

#: 표류 추정 재발행 주기 `제안`⚠️ — 반경이 시간에 따라 커지는 게 화면에 보여야 한다
DRIFT_PUBLISH_SEC: Final[int] = 10

#: 부표 LoRa 수신 요약 로그 주기. 🔴 쪽지를 받는지·왜 버리는지가 로그에 안 보여서
#: Pi 를 끄기 전까지 아무것도 몰랐다 (2026-09-28). 받은 게 없어도 "없음" 을 찍는다.
BUOY_LOG_SEC: Final[int] = 5

# ── 센서·영상 ────────────────────────────────────────────────────────
#: 선박 GPS. MQTT 발행은 **항상 1Hz** 다 — Jetson 의 조준 해 입력이라
#: 5초 전 값을 쓰면 안 된다. 10노트면 5초에 26m 움직인다.
GPS_PUBLISH_SEC: Final[int] = 1

#: DB 기록은 5초. 항적(APP-01)·ETA 용이라 이 정도면 충분하고,
#: pi_ship_position 이 유일한 상시 테이블이라 여기서 microSD 수명이 갈린다.
GPS_PERSIST_SEC: Final[int] = 5

#: 사고 중에는 다시 촘촘하게. 사고 전후 배 궤적은 조사에 쓰인다.
GPS_PERSIST_SEC_INCIDENT: Final[int] = 1

#: 장비 상태 발행. 변화 시 + 주기 둘 다 보낸다 —
#: 변화 시에만 보내면 키오스크가 "값이 안 옴"과 "Pi 가 죽음"을 구분 못 한다.
DEVICE_STATUS_SEC: Final[int] = 5

#: 사고 전후 영상 `확정` 2026-09-17 — 앞 15초 · 뒤 10초.
#:
#: 5fps 기준 앞 75장 + 뒤 50장 = 125장. 200KB 로 잡으면 사고당 25MB 다.
#: 앞 구간은 Jetson 이 링 버퍼로 상시 들고 있다가 탐지 순간에 쏟아낸다 —
#: 사고가 난 뒤에는 그 전 장면을 다시 만들 수 없다.
#:
#: ⚠ 이전 값은 앞 30초(150장)였다. `mqtt.md` 의 "사고 전 30초 150장"은 낡았다.
FRAME_PRE_SEC: Final[int] = 15
FRAME_POST_SEC: Final[int] = 10
FRAME_FPS: Final[int] = 5

#: 사고 후 프레임 수집을 강제로 끊는 상한. 종결·중지 신호를 놓쳤을 때의 안전장치다.
#: ⚠ 정상 경로는 FRAME_POST_SEC 이고, 이 값은 그게 안 왔을 때만 쓰인다.
FRAME_POST_MAX_SEC: Final[int] = 3600

#: 센서 데이터 DB 보관 범위 `확정` — 상시 기록은 RAM 링버퍼(IOT-09)에만 있다
SENSOR_KEEP_AROUND_SEC: Final[int] = 600

# ── MQTT ─────────────────────────────────────────────────────────────
MQTT_HOST: Final[str] = "localhost"
MQTT_PORT_TCP: Final[int] = 1883      # Jetson, orchestrator
MQTT_PORT_WS: Final[int] = 9001       # 키오스크 — 브라우저는 raw TCP 를 못 연다

#: Keep Alive. LWT 는 이 값의 1.5배가 지나야 브로커가 발행한다 —
#: 15초면 약 22.5초다. 30초 카운트다운과 같은 스케일이라 §1.4 주의사항이 여기서 나온다.
MQTT_KEEPALIVE_SEC: Final[int] = 15

#: LWT 지연을 계산해 둔 값. "키오스크가 죽었다"를 판정할 때 이만큼 늦다는 걸 감안해야 한다.
LWT_DELAY_SEC: Final[float] = MQTT_KEEPALIVE_SEC * 1.5

#: 재접속했을 때 필요한 건 끊긴 동안 쌓인 IMU 300개가 아니라 "지금 사고가 어떤 상태인가"다.
#: 그건 세션 큐가 아니라 retained 메시지로 받는다.
MQTT_CLEAN_SESSION: Final[bool] = True

#: 명령 재시도 (§5.9). 같은 request_id 로 재발행해야 한다 —
#: 새 ID 로 보내면 Pi 가 별개 명령으로 처리해서 신고가 두 번 나간다.
COMMAND_ACK_TIMEOUT_SEC: Final[float] = 2.0
COMMAND_MAX_RETRY: Final[int] = 1

#: 명령 중복 제거 창. kiosk/command/* 에만 적용한다 —
#: QoS 0 토픽은 애초에 중복이 안 생기므로 1초마다 UUID 를 기억하는 건 낭비다.
COMMAND_DEDUP_WINDOW: Final[int] = 100

#: 페이로드 상한. 브로커 message_size_limit 도 명시적으로 걸어야 한다 —
#: mosquitto 기본값은 0(무제한)이라 폭주를 막을 게 없다.
MAX_PAYLOAD_BYTES: Final[int] = 4 * 1024
MAX_SNAPSHOT_BYTES: Final[int] = 300 * 1024

# ── 발사 ─────────────────────────────────────────────────────────────
#: 조준 해 유효 시간 `미정`⚠️ TODO(IoT) — 탐지→발사→착수 실측 지연을 재야 정할 수 있다.
#: 10노트면 1초에 약 5m 이동하므로 해가 묵을수록 목표점이 그만큼 어긋난다.
LAUNCH_SOLUTION_TTL_SEC: Final[int] = 3

#: 실시간 조준은 재연결 후 재생하지 않으며, 이 시간보다 오래된 명령은 버린다.
AIM_COMMAND_TTL_SEC: Final[int] = 2

#: 보정 범위. DES-38 §1 의 명목값이며 실측 보정 후 확정한다.
#: 소프트 리밋이라 여기 밖이면 발사하지 않고 OUT_OF_RANGE 로 거부한다.
YAW_MIN_DEG: Final[float] = -45.0
YAW_MAX_DEG: Final[float] = 45.0
#: 가까운 목표는 발사관보다 아래라 -10 까지 받는다 (2026-09-23). Jetson
#: `stereo_targeting.yaml` 의 `min_pitch_deg` 와 아래 `PITCH_CAL` 과 같이 움직인다.
PITCH_MIN_DEG: Final[float] = -10.0
PITCH_MAX_DEG: Final[float] = 45.0

#: pitch 보정표 `(각도°, CH1 명령값)`. `--pitch-cal` 을 안 주면 이것을 쓴다.
#: 명령값은 `2servo.py` 와 같은 숫자다(0~180 = 500~2500µs). 클수록 아래를 본다.
#:
#: 🔴 2026-09-23 실측: **CH1 140 이 수평(0°)**이고 110 은 위를 본다. 전 표
#:    (2.5:110 / 25:90, 09-18 측정)는 재장착(09-21) 뒤 영점이 약 28 밀려 안 맞았다 —
#:    그 표로 -10° 라고 보낸 121.1 은 실제로 위를 보고 있었다.
#: ⚠ **임시값이다.** 0:140 만 실측이고, 기울기는 전 표의 것(명령값 1 당 1.125°)을
#:   빌렸다. 한 점 더 재면(예: CH1 110 이 위로 몇 도인가) 양 끝을 다시 구한다.
#: ⚠ 양 끝은 `PITCH_MIN_DEG` 와 같고, Jetson `min_pitch_deg`/`max_pitch_deg` 는 이 안에
#:   있어야 한다. 보정표 밖 각도가 오면 서보가 얼어붙는다(좌우까지).
PITCH_CAL: Final[tuple[tuple[float, float], ...]] = (
    (-10.0, 148.9),
    (0.0, 140.0),
    (25.0, 117.8),
)

#: 실물 시험으로 승인된 프로파일만 선택한다. AI 가 임의의 힘 값을 모터로 직접 보내지 않는다.
#: ⚠ demo-low-v1 은 예시이며 아직 검증 기록이 없다 (DES-38 §5).
#:   그리고 DES-37 §4 스프링 실측이 끝나기 전에는 어떤 프로파일도 승인될 수 없다.
APPROVED_LAUNCH_PROFILES: Final[frozenset[str]] = frozenset({"demo-low-v1"})

# ── 신고 ─────────────────────────────────────────────────────────────
#: 발신 주체는 Pi 다 `확정` 2026-09-11.
#: 상세기획 §3.2⑥·§7.1 은 [Backend] 로 적혀 있으나 §4.2 IOT-11/12/13 은 IoT 였다.
#: Pi 가 쏴야 인터넷 두절을 Pi 가 직접 알고 화면에 띄울 수 있다.
REPORT_BURST_COUNT: Final[int] = 8        # 1분에 8회 (AIS-SART 규격 참고)
REPORT_BURST_WINDOW_SEC: Final[int] = 60

#: DSC 조난 경보 반복. ITU-R M.541 §3.1.3.1 `확정`
#:
#: 한 번의 "호출 시도"는 **연속 5회**다. 그 시도를 같은 주파수에서 다시 하려면
#: 첫 호출 시작으로부터 **3½~4½분 사이의 무작위 지연**을 둔다.
#:
#: 🔴 무작위인 이유가 핵심이다 — 규격 원문: "호출 충돌과 **확인응답 유실**을 피하기
#:    위해". 고정 간격이면 재전송이 확인응답 수신 창을 계속 같은 자리에서 막는다.
#:    확인응답은 해안국 운용자가 **수동으로** 보내므로(M.541 §3.3) 언제 올지 모른다.
#:    그래서 이 무작위화가 편의가 아니라 필수다.
#:
#: ⚠ 반복마다 새로 뽑아야 한다. 한 번 뽑아 재사용하면 고정 간격과 같아진다.
DSC_ATTEMPT_CALLS: Final[int] = 5
DSC_REPEAT_MIN_SEC: Final[int] = 210      # 3½분
DSC_REPEAT_MAX_SEC: Final[int] = 270      # 4½분

#: 확인응답을 받으면 자동 반복을 종료한다. M.541 §3.3.5 `확정`
#: AIS 2채널은 ACK 이 없어 해당되지 않는다.
DSC_AUTO_STOP_ON_ACK: Final[bool] = True

# ── 시각 ─────────────────────────────────────────────────────────────
#: Pi 5 에는 RTC 백업 배터리가 없고 폐쇄망이라 NTP 도 없다.
#: 시각 기준은 **GPS UTC** 다 `확정` 2026-09-11.
#:
#: ⚠ 첫 GPS fix 전에는 시계가 엉뚱한 값이다. 그 상태에서 report_due_at 을 비교하면
#:   부팅하자마자 "이미 만료됐다"고 판단해 신고가 나갈 수 있다.
#:   아래 값보다 이전이면 시계를 믿지 않는다.
CLOCK_SANITY_MIN_EPOCH: Final[int] = 1_757_000_000   # 2025-09 경

#: 시계가 유효하지 않은 동안은 자동 전이를 보류한다 — 신고도, 동기화도 하지 않는다.
BLOCK_AUTO_TRANSITIONS_WHEN_CLOCK_INVALID: Final[bool] = True


@dataclass(frozen=True, slots=True)
class ShipIdentity:
    """이 Pi 가 어느 배인지. 부록 C 선박 등록에서 받아 설정 파일에 넣는다.

    ⚠ `미정`⚠️ TODO(웹) — 등록 절차가 확정 안 됐다. 모든 MQTT 토픽 경로가 여기 걸려 있다.
       개발 중에는 환경변수로 주입한다.
    """

    ship_id: str

    @property
    def client_id(self) -> str:
        return f"pi-{self.ship_id}"


def clock_is_valid(now: int) -> bool:
    """GPS fix 전의 엉뚱한 시각을 걸러낸다.

    이 검사가 없으면 RTC 없는 Pi 가 부팅 직후 report_due_at 이 과거라고 판단하고
    즉시 신고로 전이한다. DES-31 C-6 이 경고한 그 상황이다.
    """
    return now >= CLOCK_SANITY_MIN_EPOCH

"""IMU 상시 기록 펌프. 1Hz 로 **디스크에 쓰고** 화면으로 내보낸다.

    IMU --1Hz--> pi_imu_log (상시)       --> 사고 나면 창을 pi_imu 로
            \\
             --> pi/sensor/imu (MQTT)    --> 키오스크 롤·피치

🔴 **인메모리 링버퍼를 쓰지 않는다.** 필요한 것이 "사고 10분 전" 인데, 그 구간을
   메모리에만 들고 있으면 재부팅·프로세스 재시작에 통째로 사라진다. 사고는 그
   재시작 직후에도 난다. `pi_imu_log` 에 바로 쓴다.

🔴 **`pi_imu` 에 직접 못 쓴다.** 그 테이블은 `accident_id` 가 NOT NULL 이고
   FK 가 걸려 있다 — 사고가 생기기 **전에는 쓸 곳이 없다.** 그래서 사고와 무관한
   롤링 로그에 쌓고, 사고가 나면 `copy_imu_window` 로 옮긴다.

── EC2 로 가는 범위 ────────────────────────────────────────────────
관제는 **사고 10분 전부터 사고 중까지**만 받는다 (`PRE_SEC`). 상시 로그는
sync 대상이 아니다 — 1Hz × 24시간이면 8.6만 행이고, 좁은 어선 상향 대역이 죽는다.

사고가 열려 있는 동안 이 펌프가 주기적으로 창을 다시 긁는다. `INSERT OR IGNORE`
와 `UNIQUE (accident_id, created_at, imu_position)` 덕에 여러 번 불러도 안전하고,
그 사이에 들어온 새 행만 붙는다.

── 키오스크 ────────────────────────────────────────────────────────
⚠ 키오스크는 **고칠 것이 없다.** `decode.ts` 의 `TOPIC.sensorImu` 와
  `DevicePane.tsx` 의 "롤 —° · 피치 —°" 가 이미 있다. 지금 비어 보이는 이유는
  Pi 가 발행하지 않아서였다.

⚠ 각도를 모르면(설치 영점 없음) `roll`·`pitch` 를 **빼고** 보낸다. 디코더가
  `null` 이면 필드를 안 넣어 화면이 `—°` 로 남는다 — 0 을 보내면 "수평" 이 된다.
"""

from __future__ import annotations

import logging
import threading

from floaq.contracts import ImuPosition, SensorImu

log = logging.getLogger(__name__)

#: 기록·발행 주기. 계약이 QoS 0 이라 한 개 빠져도 다음 게 온다
PERIOD_SEC = 1.0

#: 사고 앞으로 이만큼을 관제에 올린다 `확정` — 사용자 요청 2026-09-22.
#: 사고 10분 전부터 무슨 일이 있었는지가 사후 분석의 본문이다
PRE_SEC = 10 * 60

#: 상시 로그 보관. PRE_SEC 보다 넉넉해야 한다 — 딱 맞추면 사고 직전 행이
#: 프룬과 경합해 사라진다
KEEP_SEC = 20 * 60

#: 로그 프룬 간격. 매 초 DELETE 를 돌릴 이유가 없다
PRUNE_EVERY_SEC = 60


class ImuPump:
    """1Hz 로 읽어 DB 에 쓰고 MQTT 로 내보내는 스레드.

    ⚠ `imu` 는 `adapters.imu.Mpu6050` 또는 `FakeImu` 다. 둘 다 `read()` 로
      `Sample | None` 을 준다 — Protocol 을 따로 두지 않는다.
    """

    def __init__(self, repo, bus, clock, ship_id: str, imu,
                 *, position: ImuPosition = ImuPosition.HULL,
                 period: float = PERIOD_SEC) -> None:
        self.repo = repo
        self.bus = bus
        self.clock = clock
        self.ship_id = ship_id
        self.imu = imu
        #: 배 바닥. 카메라에 붙이면 CAMERA_L/R 로 준다
        self.position = position
        self.period = period
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_prune = 0
        #: 창을 어디까지 옮겼나. 사고가 바뀌면 되돌린다
        self._copied_for: str | None = None
        self.written = 0
        self.published = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="imu-pump", daemon=True)
        self._thread.start()
        log.info("IMU 기록 시작 (%.0f초 주기, 사고 %d분 전까지 관제로)",
                 self.period, PRE_SEC // 60)

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.round_once()
            except Exception:
                # 🔴 죽으면 사고 전 기록이 통째로 없는데, 그 사실을 사고 뒤에 안다
                log.exception("IMU 기록 루프 오류")
            self._stopping.wait(self.period)

    # ── 한 회차 ──────────────────────────────────────────────────────
    def round_once(self) -> None:
        """한 번 읽어 쓰고 내보낸다.

        🔴 **시계를 못 믿으면 쓰지 않는다.** `created_at` 이 틀린 행은 나중에
           창을 긁을 때 범위 밖으로 빠지거나, 더 나쁘게는 미래 행이 섞인다
           (Pi 5 에는 RTC 가 없다).
        """
        if not self.clock.is_valid():
            return
        s = self.imu.read()
        if s is None:
            return

        now = self.clock.now()
        self._write(s, now)
        self._publish(s, now)
        self._carry_to_accident(now)
        self._prune(now)

    def _write(self, s, now: int) -> None:
        row = self.repo.add_imu_log(
            self.ship_id, position=str(self.position), now=now,
            accel_x=s.accel_x, accel_y=s.accel_y, accel_z=s.accel_z,
            roll=s.roll, pitch=s.pitch, heading_deg=None)
        if row is not None:
            self.written += 1

    def _publish(self, s, now: int) -> None:
        """화면으로. 사고가 없어도 보낸다 — 평상시 자세도 보여야 한다.

        ⚠ 각도를 모르면 0 이 아니라 **계약이 요구하는 값을 못 채운다.**
          `SensorImu.roll` 은 float 필수라 None 을 못 넣는다 — 그래서 각도가
          없으면 **발행 자체를 건너뛴다.** 화면은 `—°` 로 남는다.
        """
        if s.roll is None or s.pitch is None:
            return
        acc = self.repo.active()
        self.bus.publish("pi/sensor/imu", SensorImu(
            accident_id=acc.accident_id if acc else None,
            imu_position=self.position,
            accel_x=s.accel_x, accel_y=s.accel_y, accel_z=s.accel_z,
            roll=s.roll, pitch=s.pitch,
            # ⚠ MPU6050 에는 자력계가 없다. yaw 를 만들어 내지 않는다 —
            #   방위는 GPS 진행방향이 말한다 (`SensorImu.heading_deg`)
            yaw=0.0, heading_deg=None,
            measured_at=s.measured_at))
        self.published += 1

    def _carry_to_accident(self, now: int) -> None:
        """사고가 있으면 로그의 창을 그 사고로 옮긴다.

        ⚠ 사고가 열려 있는 동안 매 초 부른다. `INSERT OR IGNORE` 라 이미 옮긴
          행은 그냥 걸러지고 새 행만 붙는다 — 사고 중 구간이 자동으로 이어진다.
        """
        acc = self.repo.active()
        if acc is None:
            self._copied_for = None
            return
        if self._copied_for != acc.accident_id:
            # 새 사고다. 사고 시각 기준으로 앞 10분부터 긁는다
            self._copied_for = acc.accident_id
            n = self.repo.copy_imu_window(
                acc.accident_id, self.ship_id,
                since=acc.created_at - PRE_SEC, until=now, now=now)
            log.info("IMU 사고 전 구간 %d행 옮김 (%s)", n, acc.accident_id)
            return
        # 같은 사고. 직전 몇 초만 보면 된다 — 매번 10분을 긁으면 1Hz 에서 무겁다
        self.repo.copy_imu_window(
            acc.accident_id, self.ship_id,
            since=now - 10, until=now, now=now)

    def _prune(self, now: int) -> None:
        if now - self._last_prune < PRUNE_EVERY_SEC:
            return
        self._last_prune = now
        n = self.repo.prune_imu_log(self.ship_id, now - KEEP_SEC)
        if n:
            log.debug("pi_imu_log %d행 정리", n)

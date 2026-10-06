"""사고 대응 오케스트레이터. **Pi 가 이 시스템의 오케스트레이터다.**

Jetson 은 "사람을 봤고 쏜다면 이 각도다"까지만 말하고, 키오스크는 표시와 명령만 한다.
판정·발사·카운트다운·신고를 순서대로 몰고 가는 건 전부 여기다.

오케스트레이션이라서 지키는 규칙 넷:

1. **모든 바깥 호출에 타임아웃이 있어야 한다.** 응답을 기다리는 쪽이라 하나가 막히면
   전체가 선다. 어댑터가 그걸 보장하고, 여기서는 부르기만 한다.
2. **멱등하다.** `request_id`·`detection_id` 중복은 거부가 아니라 무시한다.
3. **상태를 먼저 남기고 부작용을 낸다.** 발사·신고 전에 DB 에 쓴다 —
   중간에 죽어도 "뭘 하려던 중이었는지"가 남아야 재부팅 복구가 된다.
4. **시계를 못 믿으면 자동 전이를 하지 않는다.** RTC 없는 Pi 의 부팅 직후를 위한 것.

⚠ 이 클래스는 I/O 를 직접 하지 않는다. 전부 ports 의 Protocol 을 통한다.
  그래서 하드웨어·브로커·DB 없이 전 과정을 테스트할 수 있다.
"""

from __future__ import annotations

import logging

from floaq import config, drift
from floaq.contracts import (
    AccidentState,
    AccidentStatus,
    AccidentType,
    BuoyDrift,
    BuoyPosition,
    CommandResult,
    ErrorCode,
    ErrorInfo,
    JetsonDetection,
    LaunchResult,
    ReportChannel,
    TriggerSource,
)
from floaq.contracts.lora import Reception
from floaq.core import state as st
from floaq.core.domain import Accident, LaunchRecord, StateTransition
from floaq.core.ports import (
    AccidentRepo, Clock, Launcher, MessageBus, OceanSource, Reporter,
)
from floaq.ids import uuid7

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        *,
        ship_id: str,
        clock: Clock,
        bus: MessageBus,
        repo: AccidentRepo,
        launcher: Launcher,
        reporter: Reporter,
        ocean: OceanSource | None = None,
    ) -> None:
        self.ship_id = ship_id
        self.clock = clock
        self.bus = bus
        self.repo = repo
        self.launcher = launcher
        self.reporter = reporter
        #: 표류 계산에 넣을 해양 값. 없으면 표류 추정을 아예 하지 않는다 —
        #: 해양 데이터 없이 위치오차 원판만 그린 타원은 수색에 쓸모가 없다
        self.ocean = ocean
        #: 마지막으로 `pi/buoy/drift` 를 낸 시각. 1초마다 다시 내지 않으려는 것뿐이다
        self._drift_at = 0
        #: 지금 화면에 범위가 떠 있나. 못 내게 됐을 때 **지워야 하는지**를 가른다
        self._drift_on = False

    # ── 부팅 ─────────────────────────────────────────────────────────
    def boot(self) -> None:
        """재부팅 복구. **브로커의 retained 가 아니라 DB 가 상태의 원본이다.**

        retained 는 브로커(=Pi 자신)에 있으므로 재부팅하면 날아갈 수 있다.
        DB 에서 복구하고 retained 를 **다시 발행**한다.
        """
        # DES-38 §7·§9: 부팅 시 구동 허가 기본값은 false. 무조건 안전 상태로 내린다.
        # 전원이 재인가됐다고 해서 하던 발사를 이어서 하면 안 된다.
        self.launcher.safe()

        acc = self.repo.active()
        if acc is None:
            log.info("boot: 진행 중 사고 없음")
            return

        log.warning("boot: 진행 중 사고 복구 %s status=%s", acc.accident_id, acc.status)
        # 복구한 상태를 그대로 재발행한다. 키오스크가 이걸로 화면을 되돌린다.
        self._publish_state(acc, reason="AI_DETECT" if acc.status is AccidentStatus.DETECT else "COUNTDOWN_START",
                            prev=None, caused_by=None, persist=False)

        # ⚠ 만료된 WAIT 을 여기서 바로 신고로 보내지 않는다.
        #   시계가 아직 GPS fix 를 못 받았을 수 있고, 그 상태에서 판단하면
        #   전원 재인가만으로 신고가 나간다. tick() 이 시계가 유효해진 뒤에 처리한다.
        #   `미정`⚠️ TODO(팀): 재부팅으로 만료된 경우 즉시 신고 vs 취소 기회 부여 — §7 #11

    # ── Jetson 탐지 ──────────────────────────────────────────────────
    def on_aim(self, command) -> None:
        """Apply a fresh aim-only command without touching the release axis."""
        now = self.clock.now()
        if now - command.solved_at > config.AIM_COMMAND_TTL_SEC:
            log.info("aim 무시: 만료된 명령 track=%s", command.track_id)
            return
        if not config.YAW_MIN_DEG <= command.target_yaw_deg <= config.YAW_MAX_DEG:
            log.info("aim 무시: yaw 범위 밖 %.2f", command.target_yaw_deg)
            return
        if not config.PITCH_MIN_DEG <= command.target_pitch_deg <= config.PITCH_MAX_DEG:
            log.info("aim 무시: pitch 범위 밖 %.2f", command.target_pitch_deg)
            return
        self.launcher.aim(command.target_yaw_deg, command.target_pitch_deg)

    def _stamp(self, sent_at: int, now: int, what: str) -> int:
        """남의 장비가 찍어 보낸 시각을 믿을지 정한다.

        🔴 **젯슨도 RTC 가 없다.** NTP 없이 부팅하면 `time.time()` 이 epoch+업타임을
           돌려주고, 그 값이 그대로 `pi_accident.created_at` 에 박혀 EC2 까지 올라간다.
           2026-09-22 관제에서 `1970-01-01T01:29:34Z` 로 확인했다 — 업타임 1시간
           29분 34초였다. Pi DB 17건 중 3건이 그랬다.

        🔴 **사고를 거부하지 않는다.** 시계가 틀렸다고 익수자를 안 구하면 본말이
           뒤집힌다. 시각만 우리 것으로 갈아 끼우고 크게 남긴다.

        ⚠ Pi 시계도 못 믿으면 보낸 값을 그대로 쓴다. 둘 다 틀린 마당에 바꿔 봐야
          더 나을 것이 없고, 적어도 **보낸 쪽 로그와는 맞는** 값이 남는다.
        """
        if config.clock_is_valid(sent_at):
            return sent_at
        if not config.clock_is_valid(now):
            log.error("%s 시각이 이상한데 Pi 시계도 못 믿는다: sent=%d now=%d "
                      "— 그대로 쓴다. 이 사고의 시각은 나중에 못 고친다",
                      what, sent_at, now)
            return sent_at
        log.error("%s 시각이 이상해 Pi 시계로 바꾼다: %d -> %d "
                  "(보낸 장비가 GPS·NTP 없이 부팅했다)", what, sent_at, now)
        return now

    def on_detection(self, det: JetsonDetection) -> None:
        """`jetson/detection` 수신. 사고로 승격할지 판정하고, 통과하면 투하까지 간다."""
        now = self.clock.now()

        # 1. AI-02 임계값. `미정`⚠️ TODO(AI) — 기준이 없어 임시로 프레임 수만 본다.
        if det.frame_count < 1 or det.confidence <= 0:
            log.info("detection 무시: AI-02 임계 미달 %s", det.detection_id)
            return

        # 2. 진행 중 사고가 있으면 새로 만들지 않는다 (AI-05 / E1).
        #    DB 의 uq_pi_accident_active 가 한 번 더 막지만, 여기서 먼저 걸러야
        #    불필요한 INSERT 실패 로그가 안 쌓인다.
        if self.repo.active() is not None:
            log.info("detection 무시: 진행 중 사고 있음 %s", det.detection_id)
            return

        # 3. 사고 생성. accident_id 는 **Pi 가** 발급한다 — Jetson 은 사고 번호를 모른다.
        report_type, dsc = st.route(AccidentType.MOB)
        acc = Accident(
            accident_id=uuid7(),
            ship_id=self.ship_id,
            status=AccidentStatus.DETECT,
            accident_type=AccidentType.MOB,       # AI 감지는 MOB 만 만든다
            trigger_source=TriggerSource.AI,
            report_type=report_type,
            report_dsc=dsc,
            accident_lat=det.lat,
            accident_lon=det.lon,
            wait_sec=config.WAIT_SEC,
            report_due_at=None,
            model_version=det.model_version,
            # 탐지 시각이지 수신 시각이 아니다. 단 젯슨 시계가 이상하면 우리 것으로 바꾼다
            created_at=self._stamp(det.detected_at, now, "탐지"),
            updated_at=now,
        )
        self.repo.create(acc)
        self._publish_state(acc, reason="AI_DETECT", prev=None, caused_by=None)

        # 4. 투하. 실패해도 사고는 그대로 진행한다 (E5 — 재발사 없음).
        acc = self._try_launch(acc, det, now)

        # 5. 카운트다운 시작
        self._start_countdown(acc, now)

    def _try_launch(self, acc: Accident, det: JetsonDetection, now: int) -> Accident:
        """조준 해를 검증하고 발사한다. 결과는 항상 발행한다 — 실패도 알려야 한다.

        🔴 **`solved_at` 도 `detected_at` 과 같은 시계 보정을 받는다.** 만료 검사가
           `now - solved_at > 3초` 인데(`state.validate_launch`), 젯슨이 NTP 없이
           부팅하면 그 차이가 수십 년이 되어 **발사가 `OUT_OF_RANGE` 로 조용히
           거부된다.** 사고 시각은 `_stamp` 가 고쳐 놔서 화면은 정상으로 보이고,
           실패 사유는 각도 문제처럼 읽힌다 — 2026-09-22 전수검사에서 찾았다.
        """
        launch = det.launch
        if launch is not None:
            fixed = self._stamp(launch.solved_at, now, "조준 해")
            if fixed != launch.solved_at:
                launch = launch.model_copy(update={"solved_at": fixed})

        fail = st.validate_launch(
            launch,
            now=now,
            is_loaded=self.launcher.is_loaded(),
            clock_valid=self.clock.is_valid(),
        )

        if fail is None:
            sol = launch
            assert sol is not None  # validate_launch 가 None 을 걸러냈다
            try:
                outcome = self.launcher.aim_and_release(
                    sol.target_yaw_deg, sol.target_pitch_deg, sol.launch_profile
                )
            except Exception:
                # 🔴 장치 예외가 여기서 나가면 **5단계 신고 카운트다운이 안 돈다.**
                #    버스 디스패처가 예외를 삼켜 사고만 뜬 채 멈춘다. I2C 한 번
                #    끊긴 것으로 조난신고가 통째로 사라지면 안 된다.
                log.exception("발사 장치 예외 accident=%s", acc.accident_id)
                outcome = "DEVICE_ERROR"
            result = "SUCCESS" if outcome == "SUCCESS" else "FAILED"
            fail_reason = None if result == "SUCCESS" else outcome
            yaw, pitch = sol.target_yaw_deg, sol.target_pitch_deg
            t_lat, t_lon = sol.target_lat, sol.target_lon
        else:
            # 검증에서 걸렸으면 장치를 건드리지 않는다
            result, fail_reason = "FAILED", fail
            yaw = pitch = 0.0
            t_lat = t_lon = None

        rec = LaunchRecord(
            accident_id=acc.accident_id,
            detection_id=det.detection_id,
            result=result,
            fail_reason=fail_reason,
            launch_lat=det.lat,
            launch_lon=det.lon,
            target_lat=t_lat,
            target_lon=t_lon,
            horizontal_angle=yaw,
            vertical_angle=pitch,
            confidence_score=det.confidence,
            created_at=now,
        )
        self.repo.update(rec)

        self.bus.publish("pi/launch/result", LaunchResult(
            accident_id=acc.accident_id,
            detection_id=det.detection_id,
            result=result,                      # type: ignore[arg-type]
            fail_reason=fail_reason,            # type: ignore[arg-type]
            launch_lat=det.lat,
            launch_lon=det.lon,
            target_lat=t_lat,
            target_lon=t_lon,
            horizontal_angle=yaw,
            vertical_angle=pitch,
            confidence_score=det.confidence,
            launched_at=now,
        ))
        if result == "FAILED":
            log.error("발사 실패 %s: %s (재발사 없음)", acc.accident_id, fail_reason)
        return acc

    def _start_countdown(self, acc: Accident, now: int) -> None:
        due = st.countdown_deadline(now, acc.wait_sec)
        acc2 = acc.with_status(AccidentStatus.WAIT, now=now, report_due_at=due)
        self.repo.update(acc2)
        self._publish_state(acc2, reason="COUNTDOWN_START", prev=acc.status, caused_by=None)

    # ── 주기 처리 ────────────────────────────────────────────────────
    def tick(self) -> None:
        """카운트다운 만료와 부표 두절을 감시한다. 초당 한 번 정도 부른다.

        **키오스크가 살아있든 아니든 Pi 가 혼자 판단한다.** 화면이 꺼져 있어도
        30초가 지나면 신고가 나가야 한다 — 그게 이 시스템의 요지다.
        """
        acc = self.repo.active()
        if acc is None:
            return

        # ⚠ 시계를 못 믿으면 시간 기반 판정을 전부 보류한다. 부팅 직후 `now` 가
        #   과거면 모든 것이 "1분 넘게 안 왔다"로 보인다.
        if self.clock.is_valid():
            now = self.clock.now()
            # 상태와 무관하다. 투하 후에는 REPORT 중에도 부표를 계속 듣는다.
            self._check_buoy_link(acc, now)
            # 두절이 열려 있으면 수색 범위를 다시 그린다. 위에서 방금 연 것도 포함이다
            cl = self.repo.active_comm_loss(acc.accident_id)
            if cl is not None:
                self._update_drift(acc, cl, now)

        if acc.status is not AccidentStatus.WAIT:
            return

        if not st.countdown_expired(
            acc.report_due_at, self.clock.now(), clock_valid=self.clock.is_valid()
        ):
            return

        log.warning("카운트다운 만료 → 자동 신고 %s", acc.accident_id)
        self._to_report(acc, reason="TIMEOUT", caused_by=None)

    # ── 부표 LoRa ────────────────────────────────────────────────────
    def on_buoy(self, rx: Reception) -> str:
        """부표 프레임 한 개. `adapters/lora.py` 가 걸러낸 뒤 넘긴 것이다.

        🔴 **`accident_id` 는 프레임에 없다.** 부표는 발사관 안에서 나가 다운링크가
          없으므로 받을 경로가 없다 (`docs/lora.md` §3.3). 여기서 붙인다 —
          동시 사고 1건(E1)이라 모호하지 않다.

        ⚠ 진행 중 사고가 없으면 **버린다.** 지난 사고 부표가 바다에 남아 계속 쏘는
          경우이거나, `ship_tag` 가 우연히 겹친 남의 부표다. 둘 다 기록할 곳이 없다.

        돌려주는 값: "stored" / "no_accident" / "duplicate". `main.py` 가 세어서
        `BUOY_LOG_SEC` 마다 요약 로그로 찍는다 — 여기서 쪽지마다 찍으면 초당 한 줄이다.
        """
        acc = self.repo.active()
        if acc is None:
            return "no_accident"

        now = self.clock.now()
        # 🔴 수신 스레드는 시계를 안 본다. 거기서 epoch 를 찍으면 GPS fix 전의
        #   틀린 시각이 그대로 들어간다. 경과만 받아 여기서 환산한다.
        received_at = now - round(rx.age_sec)
        f = rx.frame
        buoy_log_id = self.repo.add_buoy(
            acc.accident_id, seq=f.seq, lat=f.lat, lon=f.lon,
            is_pressed=f.is_pressed, rssi=rx.rssi,
            measured_at=f.measured_at, received_at=received_at, now=now)
        if buoy_log_id is None:
            # 같은 초 두 번째. 1Hz 전제의 의도한 dedup 이라 조용히 넘긴다 —
            # 로그를 남기면 초당 한 줄이 된다 (개수는 main.py 의 요약 로그에 나온다)
            return "duplicate"

        self._recover_comm_loss(acc.accident_id, received_at, now)

        self.bus.publish("pi/buoy/position", BuoyPosition(
            accident_id=acc.accident_id, buoy_log_id=buoy_log_id, seq=f.seq,
            lat=f.lat, lon=f.lon, is_pressed=1 if f.is_pressed else 0,
            # ⚠ 지도에 찍는 건 measured_at 이다. received_at 은 LoRa 지연만큼 늦다
            measured_at=f.measured_at, received_at=received_at, rssi=rx.rssi))
        return "stored"

    def _recover_comm_loss(self, accident_id: str, received_at: int, now: int) -> None:
        cl = self.repo.active_comm_loss(accident_id)
        if cl is None:
            return
        self.repo.close_comm_loss(cl["comm_loss_id"], received_at, now)
        log.warning("부표 LoRa 복구 %s (두절 %d초)",
                    accident_id, received_at - cl["detected_at"])
        # 표류 추정은 두절 중에만 의미가 있다. 실제 위치가 다시 들어오므로 지운다.
        self.bus.clear_retained("pi/buoy/drift")
        # ⚠ 주기 타이머를 푼다. 안 그러면 다음 두절이 10초 안에 나면 첫 범위가
        #   그 시간만큼 늦게 뜬다 — 두절 직후가 제일 급한 순간이다
        self._drift_at = 0
        self._drift_on = False

    def _check_buoy_link(self, acc: Accident, now: int) -> None:
        """1분 미수신이면 두절로 찍는다 (상세기획 §8).

        ⚠ 한 번도 안 받았으면 아무것도 하지 않는다. 투하 전이거나 투하 직후라
          두절이 아니다 — 그걸 두절로 찍으면 모든 사고가 두절로 시작한다.
        """
        row = self.repo.last_buoy(acc.accident_id)
        if row is None:
            return
        if now - row["received_at"] < config.BUOY_TIMEOUT_SEC:
            return
        if self.repo.active_comm_loss(acc.accident_id) is not None:
            return          # 이미 열려 있다. 1초마다 새 구간을 만들지 않는다

        self.repo.open_comm_loss(
            acc.accident_id, detected_at=now, last_buoy_log_id=row["buoy_log_id"],
            last_lat=row["lat"], last_lon=row["lon"],
            last_received_at=row["received_at"],
            threshold_sec=config.BUOY_TIMEOUT_SEC, now=now)
        log.warning("부표 LoRa 두절 %s — 마지막 수신 %d초 전",
                    acc.accident_id, now - row["received_at"])

    # ── 표류 추정 ────────────────────────────────────────────────────
    def _update_drift(self, acc: Accident, cl, now: int) -> None:
        """두절 중인 동안 수색 범위를 다시 계산해 발행한다.

        🔴 **시간이 갈수록 넓어지는 것이 보여야 한다.** 한 번 그리고 두면 화면이
           멈춘 것처럼 보이고, 구조 세력은 30분 전 범위를 지금 범위로 읽는다.

        ⚠ 매 tick(1초)마다 하지 않는다. 1초 사이의 변화는 화면에서 안 보이는데
          retained 발행과 DB 행만 초당 하나씩 쌓인다.
        """
        if self.ocean is None:
            return
        if now - self._drift_at < config.DRIFT_PUBLISH_SEC:
            return
        self._drift_at = now

        last_rx = cl["last_received_at"]
        elapsed = now - last_rx
        if elapsed <= 0:
            return                      # 시계가 뒤로 갔다. 그릴 것이 없다

        ocean = self.ocean.ocean(now)
        if not ocean.usable:
            # 해양 데이터가 없거나 너무 오래됐다. 위치오차 원판만 남은 타원은
            # "50m 안에 있다"고 말하는 셈이라 수색에 쓰면 오히려 위험하다 (§2)
            self._stop_drift("해양 데이터 없음")
            return

        try:
            est = drift.estimate(
                base_lat=cl["last_lat"], base_lon=cl["last_lon"],
                elapsed_sec=elapsed, leeway=drift.BUOY, ocean=ocean)
        except drift.TooLong:
            # 6시간을 넘었다 (§8). 조류가 이미 한 번 바뀌어 중심 자체가 틀리다
            self._stop_drift("6시간 초과")
            return
        except ValueError as e:
            log.warning("표류 추정 실패 %s: %s", acc.accident_id, e)
            self._stop_drift(str(e))
            return

        estimate_id = self.repo.save_drift(
            acc.accident_id, comm_loss_id=cl["comm_loss_id"],
            base_lat=cl["last_lat"], base_lon=cl["last_lon"],
            last_received_at=last_rx, elapsed_sec=elapsed,
            center_lat=est.center_lat, center_lon=est.center_lon,
            radius_m=est.radius_m,
            axis_major_m=est.ellipse.major_m, axis_minor_m=est.ellipse.minor_m,
            axis_bearing_deg=est.ellipse.bearing_deg, target="BUOY",
            input_current_speed=ocean.current_speed,
            input_current_dir=ocean.current_dir,
            input_wind_speed=ocean.wind_speed,
            # 🔴 관측 원값(불어오는 쪽)이다. 계산이 쓰는 toward 가 아니다 —
            #    저장 규약이 사고 행의 ocean_wind_dir_deg 와 같아야 한다
            input_wind_dir=ocean.wind_dir,
            input_observed_at=ocean.observed_at, now=now)

        self.bus.publish("pi/buoy/drift", BuoyDrift(
            accident_id=acc.accident_id, estimate_id=estimate_id,
            base_lat=cl["last_lat"], base_lon=cl["last_lon"],
            last_received_at=last_rx, elapsed_sec=elapsed,
            center_lat=est.center_lat, center_lon=est.center_lon,
            radius_m=est.radius_m,
            axis_major_m=est.ellipse.major_m, axis_minor_m=est.ellipse.minor_m,
            axis_bearing_deg=est.ellipse.bearing_deg, target="BUOY",
            input_current_speed=ocean.current_speed,
            input_current_dir=ocean.current_dir,
            input_wind_speed=ocean.wind_speed,
            input_wind_dir=ocean.wind_dir,
            input_observed_at=ocean.observed_at, estimated_at=now))
        self._drift_on = True

    def _stop_drift(self, why: str) -> None:
        """추정을 더 못 낸다. **마지막으로 낸 범위를 지운다.**

        🔴 남겨 두면 안 된다. 멈춘 타원은 지금 범위와 화면에서 똑같이 생겼고,
           구조 세력은 그게 30분 전 값인 줄 모른다. 아무것도 없는 편이 낫다 —
           "범위를 모른다"는 화면에 보이지만 "범위가 멈췄다"는 안 보인다.

        ⚠ 낸 적이 있을 때만 지운다. 매번 지우면 두절마다 빈 발행이 쌓인다.
        """
        if not self._drift_on:
            return
        self._drift_on = False
        log.warning("표류 추정 중단 (%s) — 수색 범위를 내린다", why)
        self.bus.clear_retained("pi/buoy/drift")

    # ── 키오스크 명령 ────────────────────────────────────────────────
    def on_command(self, command: str, payload: dict, request_id: str) -> None:
        """`kiosk/command/*` 수신.

        **무효한 명령을 조용히 무시하지 않는다.** 거부도 응답이다 — 응답이 없으면
        키오스크가 2초 뒤 재시도하고, 사용자는 버튼을 연타한다.
        """
        now = self.clock.now()

        # QoS 1 은 at-least-once 라 같은 명령이 두 번 온다. 같은 request_id 면
        # 실행은 건너뛰고 응답만 다시 보낸다 — 키오스크의 재시도 정책(§5.9)과 짝이다.
        if self.repo.seen_request(request_id):
            log.info("중복 명령 무시(응답만 재전송) %s", request_id)
            acc = self.repo.active()
            self._ack(request_id, command, acc, now, error=None)
            return

        acc = self.repo.active()
        target_id = payload.get("accident_id")
        current = acc.status if acc else None

        # report_manual 이 아닌데 대상 사고가 다르면 이미 끝난 사고를 가리키는 것이다
        exists = acc is not None and (target_id is None or target_id == acc.accident_id)

        err = st.validate_command(command, current, target_exists=exists)
        if err is not None:
            log.warning("명령 거부 %s: %s (현재 %s)", command, err, current)
            self._ack(request_id, command, acc, now, error=err)
            return

        self.repo.remember_request(request_id)

        if command == "report_manual":
            acc = self._manual_report(payload, now, request_id)
        elif command == "cancel":
            acc = self._transition(acc, AccidentStatus.CANCEL, "TABLET_CANCEL", now, request_id)
        elif command == "report_now":
            acc = self._to_report(acc, reason="TABLET_REPORT_NOW", caused_by=request_id)
        elif command in ("rescue", "close"):
            reason = "TABLET_RESCUE" if command == "rescue" else "TABLET_CLOSE"
            # 신고 중지가 먼저다 (IOT-12/13). 상태만 바꾸고 송신을 안 끊으면
            # 종료된 사고의 조난 신호가 계속 나간다.
            self.reporter.stop(acc.accident_id, reason)
            acc = self._transition(
                acc, AccidentStatus.CLOSE, reason, now, request_id,
                rescued_at=now if command == "rescue" else None,
                closed_at=now,
            )

        self._ack(request_id, command, acc, now, error=None)

    def _manual_report(self, payload: dict, now: int, request_id: str) -> Accident:
        """수동 긴급 신고 (APP-06). 카운트다운 없이 바로 REPORT.

        accident_id 를 **키오스크가** 만든다 — 재전송해도 같은 ID 라 사고가 중복되지 않는다.
        """
        atype = AccidentType(payload["accident_type"])
        report_type, dsc = st.route(atype)
        acc = Accident(
            accident_id=payload["accident_id"],
            ship_id=self.ship_id,
            status=AccidentStatus.REPORT,
            accident_type=atype,
            trigger_source=TriggerSource.MANUAL,
            report_type=report_type,
            report_dsc=dsc,
            accident_lat=payload["lat"],
            accident_lon=payload["lon"],
            wait_sec=0,                     # 대기 없음
            report_due_at=None,
            model_version=None,
            created_at=now,
            updated_at=now,
        )
        self.repo.create(acc)
        self._publish_state(acc, reason="TABLET_MANUAL", prev=None, caused_by=request_id)
        self.reporter.start(acc.accident_id, acc.accident_lat, acc.accident_lon,
                            acc.report_dsc,
                            trigger_kind=st.REPORT_TRIGGER_KIND["TABLET_MANUAL"])
        return acc

    def _to_report(self, acc: Accident, *, reason: str, caused_by: str | None) -> Accident:
        """신고 상태로 전이하고 실제 발신을 시작한다. **발신 주체는 Pi 다.**"""
        now = self.clock.now()
        acc2 = self._transition(acc, AccidentStatus.REPORT, reason, now, caused_by)
        # 상태를 먼저 남기고 부작용을 낸다 — 송신 중에 죽어도 REPORT 였다는 게 남는다
        self.reporter.start(acc2.accident_id, acc2.accident_lat, acc2.accident_lon,
                            acc2.report_dsc,
                            # 표에 없는 사유로 신고에 들어오면 사람이 안 누른 것이다
                            trigger_kind=st.REPORT_TRIGGER_KIND.get(reason, "AUTO"))
        return acc2

    def _transition(
        self,
        acc: Accident,
        target: AccidentStatus,
        reason: str,
        now: int,
        caused_by: str | None,
        **extra,
    ) -> Accident:
        expected = st.next_status(acc.status, reason)
        if expected is not target:
            # 여기 오면 코드 버그다. 상태머신 표와 호출부가 어긋난 것.
            raise RuntimeError(f"허용되지 않은 전이: {acc.status} --{reason}--> {target}")
        acc2 = acc.with_status(target, now=now, **extra)
        self.repo.update(acc2)
        self._publish_state(acc2, reason=reason, prev=acc.status, caused_by=caused_by)
        return acc2

    # ── 발행 ─────────────────────────────────────────────────────────
    def _publish_state(
        self,
        acc: Accident,
        *,
        reason: str,
        prev: AccidentStatus | None,
        caused_by: str | None,
        persist: bool = True,
    ) -> None:
        """`pi/accident/state` 발행 + 이력 적재.

        이 토픽이 **현재 사고의 유일한 진실**이다. 키오스크는 재접속 시 다른 retained 의
        accident_id 를 이것과 대조해서 다르면 버린다.
        """
        if persist:
            self.repo.append_state(StateTransition(
                accident_id=acc.accident_id,
                status=acc.status,
                prev_status=prev,
                reason=reason,
                caused_by=caused_by,
                created_at=acc.updated_at,
            ))

        self.bus.publish("pi/accident/state", AccidentState(
            accident_id=acc.accident_id,
            status=acc.status,
            prev_status=prev,
            reason=reason,                      # type: ignore[arg-type]
            caused_by=caused_by,
            report_due_at=acc.report_due_at,
            changed_at=acc.updated_at,
        ))

        # 사고가 끝나면 딸린 retained 를 비운다. 안 그러면 재접속한 키오스크가
        # 이미 끝난 사고의 스틸컷과 발사 결과를 받는다.
        #
        # ⚠ pi/accident/state 를 **맨 마지막에** 지운다. 먼저 지우면 그 틈에 재접속한
        #   키오스크가 "사고 없음"으로 보면서 아직 안 지워진 launch/result 를 받는다.
        # ⚠ jetson/snapshot 은 Pi 가 못 지운다 — ACL 이 자기 prefix 밖 쓰기를 막는다.
        #   Jetson 이 이 메시지에서 CLOSE/CANCEL 을 보고 스스로 지운다.
        if acc.status in st.TERMINAL:
            self.bus.clear_retained("pi/launch/result")
            self.bus.clear_retained("pi/report/status")
            self.bus.clear_retained("pi/buoy/drift")
            self.bus.clear_retained("pi/accident/state")

    def _ack(
        self,
        request_id: str,
        command: str,
        acc: Accident | None,
        now: int,
        *,
        error: ErrorCode | None,
    ) -> None:
        """`pi/command/response`. **거부일 때도 현재 status 를 실어준다** —
        사유만 받으면 키오스크가 화면을 무엇으로 되돌릴지 모른다."""
        from floaq.contracts import CommandAck

        result = CommandResult(
            accident_id=acc.accident_id if acc else "0" * 36,
            command=command,                    # type: ignore[arg-type]
            status=acc.status if acc else AccidentStatus.CLOSE,
        )
        self.bus.publish("pi/command/response", CommandAck[CommandResult](
            request_id=request_id,
            v=1,
            ts=now,
            is_success=error is None,
            error=None if error is None else ErrorInfo(code=error, message=_message(error, acc)),
            data=result,
        ))


def _message(code: ErrorCode, acc: Accident | None) -> str:
    """로그용 영문 메시지. ⚠ 화면에 그대로 띄우지 말 것 — 키오스크는 code 로 분기한다."""
    cur = acc.status if acc else "none"
    return {
        ErrorCode.INVALID_STATE: f"command not valid in current state ({cur})",
        ErrorCode.ACCIDENT_NOT_FOUND: "accident_id not found",
        ErrorCode.ACCIDENT_IN_PROGRESS: f"another accident is active ({cur})",
        ErrorCode.DEVICE_ERROR: "device error",
    }[code]

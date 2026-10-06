"""인메모리 어댑터. 테스트와 개발용.

ports 의 Protocol 을 구현하는 **가장 단순한 구현체**다. 이게 있어서
브로커·SQLite·서보 없이 사고 전 과정을 돌려볼 수 있다.

⚠ 운영에 쓰지 않는다. 프로세스가 죽으면 전부 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from floaq import config
from floaq.contracts import TOPICS, AccidentStatus
from floaq.core.domain import Accident, LaunchRecord, StateTransition


class FakeClock:
    """테스트에서 30초를 실제로 기다리지 않으려고 시각을 주입한다."""

    def __init__(self, now: int = 1_757_000_000, valid: bool = True) -> None:
        self._now = now
        self._valid = valid

    def now(self) -> int:
        return self._now

    def is_valid(self) -> bool:
        return self._valid

    # 테스트 편의
    def advance(self, sec: int) -> None:
        self._now += sec

    def set_valid(self, v: bool) -> None:
        self._valid = v

    def break_clock(self) -> None:
        """RTC 없는 Pi 가 GPS fix 전에 보고하는 상태를 흉내낸다."""
        self._now = 100
        self._valid = False


@dataclass
class Published:
    subject: str
    payload: BaseModel | None      # None 이면 retained 삭제
    retain: bool


class MemoryBus:
    """발행된 것을 전부 기록만 한다. 구독자는 없다."""

    def __init__(self) -> None:
        self.sent: list[Published] = []
        #: 토픽별 마지막 retained. 브로커의 retained 저장소를 흉내낸다.
        self.retained: dict[str, BaseModel] = {}

    def publish(self, subject: str, payload: BaseModel, *, retain: bool | None = None) -> None:
        if subject not in TOPICS:
            raise KeyError(f"TOPICS 에 없는 토픽: {subject}")
        _, _, default_retain = TOPICS[subject]
        do_retain = default_retain if retain is None else retain
        self.sent.append(Published(subject, payload, do_retain))
        if do_retain:
            self.retained[subject] = payload

    def clear_retained(self, subject: str) -> None:
        self.sent.append(Published(subject, None, True))
        self.retained.pop(subject, None)

    # 테스트 편의
    def subjects(self) -> list[str]:
        return [p.subject for p in self.sent]

    def last(self, subject: str) -> BaseModel | None:
        for p in reversed(self.sent):
            if p.subject == subject and p.payload is not None:
                return p.payload
        return None

    def count(self, subject: str) -> int:
        return sum(1 for p in self.sent if p.subject == subject and p.payload is not None)


class MemoryRepo:
    def __init__(self) -> None:
        self.accidents: dict[str, Accident] = {}
        self.transitions: list[StateTransition] = []
        self.launches: dict[str, LaunchRecord] = {}
        self._seen: set[str] = set()
        #: `pi_buoy` 대역. SQLite 의 UNIQUE 와 AUTOINCREMENT 를 흉내낸다
        self.buoys: list[dict] = []
        self.comm_losses: list[dict] = []
        self.drifts: list[dict] = []
        #: pi_imu_log 대역 (상시) 과 pi_imu 대역 (사고에 붙은 것)
        self.imu_log: list[dict] = []
        self.imus: list[dict] = []

    def active(self) -> Accident | None:
        found = [
            a for a in self.accidents.values()
            if a.status in (AccidentStatus.DETECT, AccidentStatus.WAIT, AccidentStatus.REPORT)
        ]
        if len(found) > 1:
            # DB 라면 uq_pi_accident_active 가 막았을 상황이다. 조용히 넘기지 않는다.
            raise RuntimeError(f"동시 사고 {len(found)}건 — E1 위반")
        return found[0] if found else None

    def get(self, accident_id: str) -> Accident | None:
        return self.accidents.get(accident_id)

    def create(self, accident: Accident) -> None:
        if self.active() is not None:
            raise RuntimeError("동시 사고 1건 위반 (E1)")
        if accident.accident_id in self.accidents:
            raise RuntimeError(f"중복 accident_id: {accident.accident_id}")
        self.accidents[accident.accident_id] = accident

    def update(self, obj) -> None:
        if isinstance(obj, Accident):
            self.accidents[obj.accident_id] = obj
        elif isinstance(obj, LaunchRecord):
            if obj.accident_id in self.launches:
                # 사고당 1회, 재투하 없음 (E5). DB 의 PK(accident_id)가 같은 규칙을 강제한다.
                raise RuntimeError("재투하 시도 — E5 위반")
            self.launches[obj.accident_id] = obj
        else:
            raise TypeError(type(obj))

    def append_state(self, transition: StateTransition) -> None:
        self.transitions.append(transition)

    def seen_request(self, request_id: str) -> bool:
        return request_id in self._seen

    def remember_request(self, request_id: str) -> None:
        self._seen.add(request_id)

    # ── 부표 LoRa ────────────────────────────────────────────────────
    def add_buoy(self, accident_id, *, seq, lat, lon, is_pressed, rssi,
                 measured_at, received_at, now) -> int | None:
        # SQLite 의 `UNIQUE (accident_id, created_at)` 과 같은 규칙. 초 단위다
        if any(b["accident_id"] == accident_id and b["created_at"] == measured_at
               for b in self.buoys):
            return None
        row = {"buoy_log_id": len(self.buoys) + 1, "accident_id": accident_id,
               "seq": seq, "lat": lat, "lon": lon,
               "is_pressed": 1 if is_pressed else 0, "rssi": rssi,
               "created_at": measured_at, "received_at": received_at,
               "updated_at": now}
        self.buoys.append(row)
        return row["buoy_log_id"]

    def last_buoy(self, accident_id):
        rows = [b for b in self.buoys if b["accident_id"] == accident_id]
        return max(rows, key=lambda b: (b["received_at"], b["buoy_log_id"])) if rows else None

    def open_comm_loss(self, accident_id, *, detected_at, last_buoy_log_id,
                       last_lat, last_lon, last_received_at, threshold_sec, now) -> int:
        row = {"comm_loss_id": len(self.comm_losses) + 1, "accident_id": accident_id,
               "detected_at": detected_at, "last_buoy_log_id": last_buoy_log_id,
               "last_lat": last_lat, "last_lon": last_lon,
               "last_received_at": last_received_at, "threshold_sec": threshold_sec,
               "recovered_at": None, "updated_at": now}
        self.comm_losses.append(row)
        return row["comm_loss_id"]

    def active_comm_loss(self, accident_id):
        open_rows = [c for c in self.comm_losses
                     if c["accident_id"] == accident_id and c["recovered_at"] is None]
        return open_rows[-1] if open_rows else None

    def close_comm_loss(self, comm_loss_id: int, recovered_at: int, now: int) -> None:
        for c in self.comm_losses:
            if c["comm_loss_id"] == comm_loss_id and c["recovered_at"] is None:
                c["recovered_at"], c["updated_at"] = recovered_at, now

    # ── IMU 대역 ─────────────────────────────────────────────────────
    def add_imu_log(self, ship_id, *, position, now, **kw):
        # UNIQUE (ship_id, created_at, imu_position) 를 흉내낸다
        for r in self.imu_log:
            if (r["ship_id"], r["created_at"], r["imu_position"]) == (ship_id, now, position):
                return None
        row = {"imu_log_id": len(self.imu_log) + 1, "ship_id": ship_id,
               "imu_position": position, "created_at": now, **kw}
        self.imu_log.append(row)
        return row["imu_log_id"]

    def prune_imu_log(self, ship_id, before):
        n = len(self.imu_log)
        self.imu_log = [r for r in self.imu_log
                        if not (r["ship_id"] == ship_id and r["created_at"] < before)]
        return n - len(self.imu_log)

    def copy_imu_window(self, accident_id, ship_id, *, since, until, now):
        """⚠ 각도를 모르는 행은 안 옮긴다 — pi_imu.roll 이 NOT NULL 이다."""
        moved = 0
        for r in self.imu_log:
            if r["ship_id"] != ship_id or not since <= r["created_at"] <= until:
                continue
            if r.get("roll") is None or r.get("pitch") is None:
                continue
            key = (accident_id, r["created_at"], r["imu_position"])
            if any((i["accident_id"], i["created_at"], i["imu_position"]) == key
                   for i in self.imus):
                continue
            self.imus.append({**r, "accident_id": accident_id})
            moved += 1
        return moved

    def save_drift(self, accident_id: str, **kw) -> int:
        """`pi_drift_estimate` 대역. 쌓고 이전 건을 내린다.

        ⚠ `uq_pi_drift_current` 를 흉내낸다 — (사고, 대상) 당 is_current 는 하나다.
          여기서 안 내리면 시험이 통과하는데 실제 INSERT 는 UNIQUE 로 실패한다.
        """
        target = kw.get("target", "BUOY")
        for d in self.drifts:
            if d["accident_id"] == accident_id and d["target"] == target:
                d["is_current"] = 0
        row = {"estimate_id": len(self.drifts) + 1, "accident_id": accident_id,
               "is_current": 1, **kw}
        self.drifts.append(row)
        return row["estimate_id"]

    def current_drift(self, accident_id: str, target: str = "BUOY"):
        rows = [d for d in self.drifts if d["accident_id"] == accident_id
                and d.get("target", "BUOY") == target and d["is_current"]]
        return rows[-1] if rows else None


@dataclass
class FakeLauncher:
    """발사 장치. 실제로는 DES-38 §6 안전 상태머신이 이 안에 있다."""

    loaded: bool = True
    #: 조준은 됐는데 기구가 걸린 경우를 흉내낸다
    outcome: str = "SUCCESS"
    calls: list[tuple[float, float, str]] = field(default_factory=list)
    aim_calls: list[tuple[float, float]] = field(default_factory=list)
    safe_calls: int = 0

    def is_loaded(self) -> bool:
        return self.loaded

    def aim(self, yaw_deg: float, pitch_deg: float) -> str:
        self.aim_calls.append((yaw_deg, pitch_deg))
        return self.outcome

    def aim_and_release(self, yaw_deg: float, pitch_deg: float, profile: str) -> str:
        if not self.loaded:
            # core 가 미리 걸렀어야 한다. 여기까지 왔으면 검증이 샌 것이다.
            raise RuntimeError("장전 안 된 상태로 발사 호출 — core 검증이 새고 있다")
        self.calls.append((yaw_deg, pitch_deg, profile))
        self.loaded = False          # 재장전은 사람이 한다
        return self.outcome

    def safe(self) -> None:
        self.safe_calls += 1


@dataclass
class FakeReporter:
    started: list[str] = field(default_factory=list)
    stopped: list[tuple[str, str]] = field(default_factory=list)
    #: 마지막으로 시작한 신고의 trigger_kind. 오케스트레이터가 사유에서 뽑아 넘긴다
    trigger_kinds: list[str] = field(default_factory=list)

    def start(self, accident_id: str, lat, lon, dsc, *, trigger_kind: str = "AUTO") -> None:
        self.started.append(accident_id)
        self.trigger_kinds.append(trigger_kind)

    def stop(self, accident_id: str, reason: str) -> None:
        self.stopped.append((accident_id, reason))

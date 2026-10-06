"""EC2 전송 펌프. `sync` 커서를 읽어 밀린 행을 배치로 올린다.

정본은 `docs/edge/api.json` 이다.

    for 테이블 in FK 순서:
        (synced_at, synced_pk) 이후 행을 LIMIT 만큼 읽는다
        api.json 이 요구하는 컬럼만 골라 봉투에 담아 POST
        2xx 를 받은 **뒤에만** 커서를 전진시킨다

🔴 **2xx 전에 커서를 전진시키면 안 된다.** 전송 시점이 아니라 저장 확정 시점이다
   (`database/pi.sql` `sync`). 먼저 옮기면 서버가 못 받은 행이 영영 재전송 대상에서
   빠지고, 그 손실은 아무 로그도 남기지 않는다.

🔴 **순서는 FK 를 따른다.** 사고 행 없이 자식을 먼저 올리면 서버에서 FK 위반으로
   배치가 통째로 롤백된다. 404 `ACCIDENT_NOT_FOUND` 로 돌아오면 그 테이블은 이번
   회차를 건너뛰고 다음에 다시 온다 — 그때는 사고가 먼저 올라가 있다.

🔴 **승인 전에는 아무것도 안 보낸다.** `WAIT` 인 선박의 데이터는 서버가 거절한다.
   보내봐야 403 만 쌓이므로 `Enroller` 가 ACTIVE 로 바꿔줄 때까지 큐를 쥔다.

⚠ 컬럼을 그대로 보내지 않고 **골라서** 보낸다. `updated_at` 은 서버가 자기 값으로
  채우고, `pi_report.report_id` 같은 INTEGER PK 는 Pi 안에서만 뜻이 있다.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

from floaq import provision
from floaq.adapters.ec2 import Action, EdgeClient, EdgeResult, envelope
from floaq.ids import uuid7

log = logging.getLogger(__name__)

#: 한 배치 최대 행 수. `api.json` 에 상한이 없어 보수적으로 잡는다 —
#: 선박 위치가 원소당 200바이트 남짓이라 500건이면 100KB 언저리다.
BATCH = 200

#: 아무것도 못 보냈을 때 다음 회차까지. 인터넷이 없을 때 이 간격으로 다시 본다.
IDLE_SEC = 10

#: 서버 사정(5xx·타임아웃)일 때. 짧게 두면 좁은 어선 상향 대역을 태운다.
BACKOFF_SEC = 60


class Table:
    """테이블 하나를 어느 경로로 어떤 컬럼으로 보내는지.

    ⚠ `columns` 는 `api.json` 의 필드 목록과 **글자까지** 같아야 한다. 이름이 다르면
      서버가 `extra` 로 무시하고 그 값은 영영 안 간다 — 오류가 안 나서 못 찾는다.
    """

    __slots__ = ("name", "pk", "path", "columns", "casts")

    def __init__(self, name: str, pk: str, path: str, columns: tuple[str, ...],
                 casts: dict[str, type] | None = None) -> None:
        self.name, self.pk, self.path = name, pk, path
        self.columns = columns
        #: SQLite 는 boolean 이 없어 0/1 로 들어 있다. api.json 이 boolean 을 요구하는
        #: 필드는 여기서 바꾼다 — 안 바꾸면 서버 검증에서 400 이다.
        self.casts = casts or {}

    def row(self, r: sqlite3.Row) -> dict:
        out = {}
        for c in self.columns:
            v = r[c]
            cast = self.casts.get(c)
            out[c] = cast(v) if cast is not None and v is not None else v
        return out


#: 🔴 **순서가 곧 FK 순서다.** 바꾸면 서버에서 롤백된다.
#:   pi_ship_position 은 사고와 무관해서 아무 때나 되지만, 가볍고 자주 생겨 앞에 둔다.
TABLES: tuple[Table, ...] = (
    Table("pi_ship_position", "position_id", "/api/pi/ship-positions",
          ("ship_id", "lat", "lon", "speed_kn", "heading_deg", "accuracy_m",
           "created_at")),
    # ⚠ `rescued_at`·`closed_at`·`model_version` 이 빠져 있었다 (2026-09-22).
    #   서버 DTO(`PiAccident.java`)와 `PiIngestService.updateAccidents` 는 셋 다 받는데
    #   우리가 안 보내서 관제의 구조·종료 시각이 **영영 비어 있었다.** 상태는 CLOSE 로
    #   바뀌는데 언제 끝났는지는 모르는 상태였다.
    Table("pi_accident", "accident_id", "/api/pi/accidents",
          ("accident_id", "ship_id", "accident_type", "trigger_source",
           "report_type", "report_dsc", "status", "accident_lat", "accident_lon",
           "report_due_at", "wait_sec", "rescued_at", "closed_at",
           "model_version", "created_at")),
    # 🔴 `prev_status`·`reason`·`caused_by` 가 빠져 있었다 (2026-09-22).
    #   이 셋이 **전이 이유** 다 — 자동 신고(TIMEOUT)인지 사람이 누른 것(TABLET_*)인지,
    #   어느 명령이 시켰는지(`caused_by` = request_id). 상태 글자만 올라가서 관제
    #   타임라인이 "왜" 를 통째로 못 받았다. 사고 후 경위를 설명할 수 없는 상태였다.
    Table("pi_accident_state", "accident_state_id", "/api/pi/accident-states",
          ("accident_id", "status", "prev_status", "reason", "caused_by",
           "created_at")),
    Table("pi_launch", "accident_id", "/api/pi/launches",
          ("accident_id", "detection_id", "result", "fail_reason",
           "launch_lat", "launch_lon", "target_lat", "target_lon",
           "horizontal_angle", "vertical_angle", "confidence_score", "created_at")),
    Table("pi_buoy", "buoy_log_id", "/api/pi/buoys",
          ("accident_id", "seq", "lat", "lon", "is_pressed", "rssi",
           "created_at", "received_at"),
          casts={"is_pressed": bool}),
    Table("pi_imu", "imu_id", "/api/pi/imus",
          ("accident_id", "imu_position", "accel_x", "accel_y", "accel_z",
           "roll", "pitch", "yaw", "heading_deg", "created_at")),
    Table("pi_comm_loss", "comm_loss_id", "/api/pi/comm-losses",
          ("accident_id", "detected_at", "last_lat", "last_lon",
           "last_received_at", "threshold_sec", "recovered_at")),
    # 🔴 **`target` 을 반드시 같이 보낸다.** 서버의 재전송 멱등 키가
    #   `(accident_id, target, created_at)` 이다 (V20260921_1830__drift_ellipse.sql).
    #   Pi 는 부표와 사람 추정을 **같은 틱에** 만들어 `created_at` 이 같으므로,
    #   target 을 빼면 둘 중 하나가 ON CONFLICT 에 걸려 **조용히 버려진다.**
    #   Pi 쪽에는 그 키에 해당하는 UNIQUE 가 없어(PK 가 로컬 INTEGER) 두 행이
    #   정상적으로 생기는 탓에, 없어진 쪽을 Pi 로그만 봐서는 못 찾는다.
    #
    # ⚠ 축 셋은 **1σ 값이다** — 배율을 먹이기 전. 서버 컬럼 주석도 같은 말을 한다.
    #   미리 곱해 보내면 화면이 어느 배율인지 모르고 또 곱한다.
    Table("pi_drift_estimate", "estimate_id", "/api/pi/drift-estimates",
          ("accident_id", "base_lat", "base_lon", "last_received_at",
           "elapsed_sec", "center_lat", "center_lon", "radius_m",
           "axis_major_m", "axis_minor_m", "axis_bearing_deg", "target",
           "input_current_speed", "input_current_dir", "input_wind_speed",
           "input_wind_dir", "input_observed_at", "is_current", "created_at"),
          casts={"is_current": bool}),
    # ⚠ 신고는 **마지막**이다. 사고 행이 먼저 있어야 붙는다.
    Table("pi_report", "report_id", "/api/pi/reports",
          ("accident_id", "channel", "trigger_kind", "status", "sent_count",
           "report_lat", "report_lon", "first_sent_at", "last_sent_at",
           "acked_at", "acked_by", "fail_reason", "created_at")),
)


class SyncPump:
    """한 스레드가 전 테이블을 순서대로 민다.

    ⚠ `EdgeClient` 는 스레드 하나에서만 쓴다. `Enroller` 와 같은 클라이언트를 공유하되
      등록이 끝난 뒤에 이 스레드가 시작한다.
    """

    def __init__(self, conn: sqlite3.Connection, repo, client: EdgeClient,
                 clock, ship_id: str) -> None:
        self.conn = conn
        self.repo = repo
        self.client = client
        self.clock = clock
        self.ship_id = ship_id
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.halted = False

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sync", daemon=True)
        self._thread.start()
        log.info("EC2 전송 펌프 시작")

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                wait = self.round_once()
            except Exception:
                # 🔴 이 스레드가 죽으면 EC2 로 아무것도 안 올라가는데 아무도 모른다
                log.exception("전송 루프 오류")
                wait = BACKOFF_SEC
            self._stopping.wait(wait)

    # ── 한 회차 ──────────────────────────────────────────────────────
    def round_once(self) -> float:
        """전 테이블을 한 번씩 민다. 다음 회차까지 기다릴 초를 돌려준다."""
        if not provision.is_approved(self.conn, self.ship_id):
            # 승인 전에는 서버가 전부 거절한다. 보내봐야 403 만 쌓인다
            return BACKOFF_SEC

        moved = 0
        for table in TABLES:
            if self._stopping.is_set():
                break
            action, n = self.push(table)
            moved += n
            if action is Action.HALT:
                # 키·버전 문제다. 사람이 풀어야 하고, 다른 테이블도 같은 이유로 막힌다
                self.halted = True
                return BACKOFF_SEC
            if action is Action.RETRY:
                return BACKOFF_SEC
            # DEFER 는 이 테이블만 건너뛴다 — 선행 행이 다음 회차에 올라간다

        self.halted = False
        # 보낼 게 남아 있으면 바로 이어서 돈다. 두절 복귀 때 밀린 것을 빨리 비운다
        return 0.5 if moved >= BATCH else IDLE_SEC

    def push(self, table: Table) -> tuple[Action, int]:
        """테이블 하나를 한 배치 보낸다. `(동작, 보낸 행 수)`."""
        rows = self.repo.pending(table.name, table.pk, limit=BATCH)
        if not rows:
            return Action.DONE, 0

        res = self._post(table, rows)

        if res.action is Action.DONE:
            # 🔴 여기서만 커서가 움직인다. 응답을 받은 뒤다
            self._advance(table, rows[-1])
            self.sent += len(rows)
            log.info("%s %d행 전송 (inserted %d · duplicated %d · stale %d)",
                     table.name, len(rows), res.inserted, res.duplicated, res.stale)
            return Action.DONE, len(rows)

        if res.action is Action.DROP:
            return self._salvage(table, rows, res)

        if res.action is Action.DEFER:
            log.info("%s 보류 — 선행 행을 먼저 보낸다 (%s)", table.name, res.code)
        elif res.action is Action.HALT:
            log.error("%s 전송 중단 (HTTP %d %s) — 사람이 풀어야 한다. 큐는 쥐고 있다",
                      table.name, res.status, res.code)
        return res.action, 0

    def _post(self, table: Table, rows: list) -> EdgeResult:
        payload = envelope(uuid7(), self.clock.now(), [table.row(r) for r in rows])
        return self.client.post(table.path, payload)

    def _advance(self, table: Table, row) -> None:
        self.repo.advance_cursor(table.name, row["updated_at"], row[table.pk],
                                 now=self.clock.now())

    def _salvage(self, table: Table, rows: list,
                 first: EdgeResult) -> tuple[Action, int]:
        """DROP 된 배치에서 **나쁜 행만** 버리고 나머지는 보낸다.

        🔴 전에는 한 행이 나빠도 배치(최대 200행)를 통째로 버렸다. 좋은 행까지 조용히
           사라졌다 (2026-09-23). 서버는 배치를 한 트랜잭션으로 받아 하나라도 틀리면
           전부 거절한다 — 그래서 여기서 골라낸다.

        - 서버가 `failed[].index` 를 주면 그 행만 버리고 나머지를 다시 보낸다
        - 안 주면(JSON 형식 오류 등) 반으로 나눠 보내며 좁힌다. 한 행까지 좁혀도
          DROP 이면 그 행이 나쁜 행이다
        - 도중에 RETRY·HALT·DEFER 가 나오면 멈추고, **앞에서부터 처리가 끝난 행까지만**
          커서를 옮긴다. 커서는 `(updated_at, pk)` 순서라 중간을 건너뛸 수 없다
        """
        done: set[int] = set()        # 보냈거나 버린 행 — rows 의 인덱스
        dropped: list[int] = []
        sent = 0
        work = [list(range(len(rows)))]   # 보낼 묶음. 앞에서부터 처리한다
        res, stop = first, Action.DONE
        while work:
            batch = work.pop(0)
            if res is None:
                res = self._post(table, [rows[i] for i in batch])
            r, res = res, None
            if r.action is Action.DONE:
                done.update(batch)
                sent += len(batch)
                continue
            if r.action is not Action.DROP:
                stop = r.action
                break
            bad = {batch[f["index"]] for f in r.failed
                   if isinstance(f, dict) and isinstance(f.get("index"), int)
                   and 0 <= f["index"] < len(batch)}
            if bad:
                dropped.extend(sorted(bad))
                done.update(bad)
                rest = [i for i in batch if i not in bad]
                if rest:
                    work.insert(0, rest)
            elif len(batch) == 1:
                dropped.append(batch[0])
                done.add(batch[0])
            else:
                half = len(batch) // 2
                work[0:0] = [batch[:half], batch[half:]]

        # 앞에서부터 끊김 없이 끝난 데까지만 커서를 옮긴다
        upto = 0
        while upto < len(rows) and upto in done:
            upto += 1
        if upto:
            self._advance(table, rows[upto - 1])
        self.sent += sent
        if dropped:
            log.error("%s %d행 폐기 (HTTP %d %s) — 서버가 형식을 거부했다. pk %s",
                      table.name, len(dropped), first.status, first.code,
                      [rows[i][table.pk] for i in dropped[:10]])
        if sent:
            log.info("%s %d행 전송 (나쁜 행을 빼고 다시 보냈다)", table.name, sent)
        # 버린 행도 처리한 것으로 센다 — 밀린 게 남았으면 다음 회차를 바로 돈다
        return stop, sent + len(dropped)

    # ── 상태 ─────────────────────────────────────────────────────────
    def backlog(self) -> dict[str, int]:
        """테이블별로 아직 안 올라간 행 수. 두절이 길었는지 여기서 본다."""
        out = {}
        for t in TABLES:
            at, pk = self.repo.cursor_for(t.name)
            n = self.conn.execute(
                f"SELECT count(*) FROM {t.name} WHERE (updated_at, {t.pk}) > (?, ?)",
                (at, pk)).fetchone()[0]
            if n:
                out[t.name] = n
        return out

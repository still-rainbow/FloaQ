"""SQLite 어댑터. `ports.AccidentRepo` 의 구현.

**이 파일이 SQL 을 아는 유일한 곳이다.** core 는 도메인 객체만 주고받는다.

── 왜 ORM 이 아닌가 ─────────────────────────────────────────────────
`database/pi.sql` 이 스키마의 정본이다. ORM 모델이 스키마를 **또** 정의하면 둘이 갈라진다 —
이 프로젝트는 이미 그 실패를 겪었다(문서가 "13 테이블 / CHECK 67" 이라 적어둔 사이
실물은 9 테이블 / CHECK 0 이었다).

Pi 는 단일 writer 인 임베디드 장치라 ORM 의 identity map·unit of work 가 벌어주는 게 적고,
가용 RAM 2.4GB 에서 의존성 하나를 아끼는 편이 낫다.

SQLAlchemy 로 가고 싶으면 **이 파일만** 갈아끼우면 된다. core 는 `AccidentRepo` Protocol
만 보므로 아무것도 바뀌지 않는다. 그때는 모델을 정본으로 삼고 pi.sql 을 생성하거나,
아래 `assert_schema_matches()` 같은 대조 테스트를 둬서 드리프트를 막는다.

── 타입 층 ──────────────────────────────────────────────────────────
    contracts.Accident*   와이어    (pydantic)
    domain.Accident       도메인    (frozen dataclass)   ← core 가 다루는 것
    sqlite row            저장      (TEXT/INTEGER/REAL)  ← 이 파일이 변환
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from floaq.contracts import AccidentStatus, AccidentType, ReportType, TriggerSource
from floaq.core.domain import Accident, LaunchRecord, StateTransition

log = logging.getLogger(__name__)

#: 진행 중으로 보는 상태. DB 의 uq_pi_accident_active 부분 인덱스와 **같아야 한다.**
#: 갈라지면 코드는 통과시키는데 INSERT 가 실패하거나, 동시 사고가 두 개 생긴다.
_ACTIVE = ("DETECT", "WAIT", "REPORT")


def connect(path: str | Path, *, schema: str | Path | None = None) -> sqlite3.Connection:
    """연결하고 PRAGMA 를 건다.

    🔴 **`foreign_keys` 는 SQLite 기본이 OFF 다.** 안 켜면 pi.sql 의 FK 13개와
      ON DELETE CASCADE 가 전부 조용히 무시된다. 연결마다 켜야 한다 — DB 속성이 아니다.
    """
    # check_same_thread=False 인 이유: MQTT 워커 스레드(_drain)와 메인 루프(tick)가
    # 같은 연결을 쓴다. 기본값 True 면 워커에서 ProgrammingError 로 죽는다.
    #
    # ⚠ 이것만으로는 부족하다. SQLite 자체는 스레드 안전하지만 파이썬 커서/트랜잭션이
    #   섞이면 결과가 엉킨다. SqliteRepo 가 모든 접근을 락으로 감싼다.
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    # 1Hz 쓰기 중에도 키오스크 조회가 막히지 않는다
    conn.execute("PRAGMA journal_mode = WAL")
    # WAL 과 조합. microSD 쓰기를 줄인다 — 전원이 갑자기 끊기면 마지막 몇 트랜잭션을
    # 잃을 수 있지만, 사고 기록은 어차피 발생 즉시 쓰고 EC2 로도 올라간다
    conn.execute("PRAGMA synchronous = NORMAL")
    # 쓰기 잠금 대기. 기본 0 이라 동시 접근 시 즉시 SQLITE_BUSY 가 난다
    conn.execute("PRAGMA busy_timeout = 5000")

    if schema is not None:
        conn.executescript(Path(schema).read_text(encoding="utf-8"))

    if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise RuntimeError("foreign_keys 를 켜지 못했다 — FK 가 무시되는 상태로 뜨면 안 된다")
    return conn


class SqliteRepo:
    """`ports.AccidentRepo` 를 만족한다(상속하지 않는다 — Protocol 이다)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        # 🔴 MQTT 워커 스레드와 메인 루프가 같은 연결을 공유한다.
        #    RLock 인 이유: 한 메서드가 다른 메서드를 부르는 경우(create -> active)가 있어
        #    같은 스레드가 재진입한다. Lock 이면 거기서 데드락.
        self._lock = threading.RLock()

    # ── 사고 ─────────────────────────────────────────────────────────
    def active(self) -> Accident | None:
        """진행 중 사고 하나 또는 None. 동시 1건(E1)이라 단수다."""
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM pi_accident WHERE status IN ({_q(_ACTIVE)})", _ACTIVE
            ).fetchall()
            if len(rows) > 1:
                # uq_pi_accident_active 가 막았어야 하는 상황이다. 조용히 첫 번째를 쓰지 않는다.
                raise RuntimeError(f"동시 사고 {len(rows)}건 — E1 위반. 인덱스를 확인할 것")
            return _to_accident(rows[0]) if rows else None

    def get(self, accident_id: str) -> Accident | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM pi_accident WHERE accident_id = ?", (accident_id,)
            ).fetchone()
            return _to_accident(row) if row else None

    def create(self, accident: Accident) -> None:
        """⚠ 중복은 DB 가 한 번 더 막는다. 코드가 AI-05 를 놓쳐도 INSERT 가 실패한다."""
        with self._lock:
            self.conn.execute(
                """INSERT INTO pi_accident (
                       accident_id, ship_id, accident_lat, accident_lon, accident_type,
                       trigger_source, report_type, report_dsc, status, wait_sec,
                       report_due_at, model_version, rescued_at, closed_at,
                       created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    accident.accident_id, accident.ship_id,
                    accident.accident_lat, accident.accident_lon,
                    str(accident.accident_type), str(accident.trigger_source),
                    str(accident.report_type), accident.report_dsc,
                    str(accident.status), accident.wait_sec, accident.report_due_at,
                    accident.model_version, accident.rescued_at, accident.closed_at,
                    accident.created_at, accident.updated_at,
                ),
            )

    def update(self, obj: Any) -> None:
        """도메인 객체 종류로 분기한다. core 가 테이블 이름을 알 필요는 없다."""
        with self._lock:
            if isinstance(obj, Accident):
                self._update_accident(obj)
            elif isinstance(obj, LaunchRecord):
                self._insert_launch(obj)
            else:
                raise TypeError(f"저장할 수 없는 타입: {type(obj).__name__}")

    def _update_accident(self, a: Accident) -> None:
        cur = self.conn.execute(
            """UPDATE pi_accident SET
                   status = ?, report_due_at = ?, rescued_at = ?, closed_at = ?,
                   accident_lat = ?, accident_lon = ?, updated_at = ?
               WHERE accident_id = ?""",
            (str(a.status), a.report_due_at, a.rescued_at, a.closed_at,
             a.accident_lat, a.accident_lon, a.updated_at, a.accident_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"없는 사고를 갱신하려 했다: {a.accident_id}")

    def _insert_launch(self, r: LaunchRecord) -> None:
        """사고당 1회. PK 가 accident_id 라 재투하(E5 위반)는 DB 가 막는다."""
        self.conn.execute(
            """INSERT INTO pi_launch (
                   accident_id, detection_id, result, fail_reason,
                   launch_lat, launch_lon, target_lat, target_lon,
                   horizontal_angle, vertical_angle, confidence_score,
                   created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r.accident_id, r.detection_id, r.result, r.fail_reason,
             r.launch_lat, r.launch_lon, r.target_lat, r.target_lon,
             r.horizontal_angle, r.vertical_angle, r.confidence_score,
             r.created_at, r.created_at),
        )

    # ── 상태 이력 ────────────────────────────────────────────────────
    def append_state(self, t: StateTransition) -> None:
        """append-only. 덮어쓰면 S-05 타임라인과 DES-38 §9 증빙이 사라진다.

        UNIQUE(accident_id, status, created_at) 가 걸려 있어 같은 전이를 두 번 넣으면
        실패한다 — 재전송 멱등을 DB 가 받아주는 것이라 조용히 무시한다.
        """
        with self._lock:
            try:
                self.conn.execute(
                    """INSERT INTO pi_accident_state (
                           accident_id, status, prev_status, reason, caused_by,
                           created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (t.accident_id, str(t.status),
                     str(t.prev_status) if t.prev_status else None,
                     t.reason, t.caused_by, t.created_at, t.created_at),
                )
            except sqlite3.IntegrityError:
                log.info("중복 상태 전이 무시: %s %s", t.accident_id, t.reason)

    def history(self, accident_id: str) -> list[StateTransition]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM pi_accident_state WHERE accident_id = ? ORDER BY created_at, accident_state_id",
                (accident_id,),
            ).fetchall()
            return [
                StateTransition(
                    accident_id=r["accident_id"],
                    status=AccidentStatus(r["status"]),
                    prev_status=AccidentStatus(r["prev_status"]) if r["prev_status"] else None,
                    reason=r["reason"],
                    caused_by=r["caused_by"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def list_accidents(self, *, limit: int = 20, offset: int = 0,
                       status: str | None = None) -> list[sqlite3.Row]:
        """지난 사고 목록. 최신순.

        ⚠ 키오스크가 선내에서 본다. EC2 에도 같은 목록이 있지만 **배에 인터넷이
          없을 때도 보여야** 하고, 사진은 Pi 에만 있다 (EC2 는 R2 키만 안다).

        ⚠ `is_deleted` 같은 건 없다. 사고는 지우지 않는다 — 조난 기록이다.
        """
        with self._lock:
            if status:
                return self.conn.execute(
                    "SELECT * FROM pi_accident WHERE status = ?"
                    " ORDER BY created_at DESC, accident_id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset)).fetchall()
            return self.conn.execute(
                "SELECT * FROM pi_accident"
                " ORDER BY created_at DESC, accident_id DESC LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()

    def count_accidents(self, status: str | None = None) -> int:
        with self._lock:
            if status:
                row = self.conn.execute(
                    "SELECT count(*) AS n FROM pi_accident WHERE status = ?",
                    (status,)).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT count(*) AS n FROM pi_accident").fetchone()
            return row["n"]

    def launch_for(self, accident_id: str) -> sqlite3.Row | None:
        """투하 기록. 사고당 하나다 (E5, 재투하 없음)."""
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_launch WHERE accident_id = ?",
                (accident_id,)).fetchone()

    def buoy_track(self, accident_id: str, *, every: int = 1,
                   limit: int = 2000) -> list[sqlite3.Row]:
        """부표 궤적. 지도에 선으로 그린다.

        🔴 **1Hz 라 10분이면 600점이다.** 지도에 다 찍을 필요가 없는데 매번 전부
          보내면 좁은 선내 무선에서 화면이 늦게 뜬다. `every` 로 솎는다.

        ⚠ 솎아도 **처음과 끝은 남긴다**. 투하 지점과 마지막 수신 위치는 수색에
          직접 쓰는 값이라 빠지면 안 된다.
        """
        every = max(1, every)
        with self._lock:
            rows = self.conn.execute(
                "SELECT buoy_log_id, seq, lat, lon, is_pressed, rssi,"
                "       created_at, received_at"
                "  FROM pi_buoy WHERE accident_id = ?"
                " ORDER BY created_at LIMIT ?",
                (accident_id, limit)).fetchall()
        if every == 1 or len(rows) <= 2:
            return rows
        thinned = rows[::every]
        if thinned[-1] is not rows[-1]:
            thinned.append(rows[-1])
        return thinned

    def comm_losses_for(self, accident_id: str) -> list[sqlite3.Row]:
        """두절 구간. 지도에서 궤적이 끊긴 이유를 설명한다."""
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_comm_loss WHERE accident_id = ?"
                " ORDER BY detected_at",
                (accident_id,)).fetchall()

    # ── 명령 중복 제거 ───────────────────────────────────────────────
    def seen_request(self, request_id: str) -> bool:
        """🔴 디스크에 남는다. 메모리면 재부팅 후 replay 된 명령이 통과한다."""
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM pi_command_log WHERE request_id = ?", (request_id,)
            ).fetchone() is not None

    def remember_request(self, request_id: str, *, command: str = "", accident_id: str | None = None,
                         now: int = 0) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO pi_command_log (request_id, command, accident_id, created_at)"
                " VALUES (?,?,?,?)",
                (request_id, command or "cancel", accident_id, now),
            )

    def prune_commands(self, before: int) -> int:
        """오래된 항목 정리. 키오스크 재시도는 2초 안에 끝나므로 길게 둘 이유가 없다."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM pi_command_log WHERE created_at < ?", (before,))
            return cur.rowcount

    # ── 동기화 커서 ──────────────────────────────────────────────────
    # ── 사고 파일 ────────────────────────────────────────────────────
    def accident_by_detection(self, detection_id: str) -> str | None:
        """`detection_id` -> `accident_id`.

        🔴 Jetson 은 `accident_id` 를 모른다. 탐지 시점엔 사고가 아직 없고, Pi 가
           `jetson/detection` 을 받고 나서 만들기 때문이다. 그래서 Jetson 은 자기가
           만든 `detection_id` 로 파일을 올리고 여기서 풀어준다.

        ⚠ `pi_accident` 에는 `detection_id` 가 없다. `pi_launch` 가 들고 있다 —
          투하가 실패해도(NO_SOLUTION 등) 행은 남으므로 조회에 문제가 없다.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT accident_id FROM pi_launch WHERE detection_id = ?",
                (detection_id,),
            ).fetchone()
            return row["accident_id"] if row else None

    def add_file(self, *, accident_id: str, file_type: str, sequence_no: int | None,
                 file_path: str, now: int, camera: str | None = None,
                 width: int | None = None, height: int | None = None,
                 size_bytes: int | None = None) -> int:
        """파일 한 건 기록. 같은 자리에 다시 오면 덮어쓴다.

        🔴 멱등이어야 한다. Jetson 이 응답을 못 받고 재전송하면 같은 `(accident_id,
           file_type, sequence_no)` 로 다시 온다. `pi_accident_file` 의 UNIQUE 가
           그 조합이라 upsert 로 받는다 — 새 행을 만들면 프레임이 두 배가 된다.

        ⚠ 다시 올라오면 `object_key` 를 NULL 로 되돌린다. 내용이 바뀌었을 수 있으니
          업로드를 다시 해야 한다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO pi_accident_file (
                       accident_id, file_type, sequence_no, file_path,
                       width, height, bytes, camera, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (accident_id, file_type, sequence_no) DO UPDATE SET
                       file_path  = excluded.file_path,
                       width      = excluded.width,
                       height     = excluded.height,
                       bytes      = excluded.bytes,
                       camera     = excluded.camera,
                       object_key = NULL,
                       updated_at = excluded.updated_at
                   RETURNING file_id""",
                (accident_id, file_type, sequence_no, file_path,
                 width, height, size_bytes, camera, now, now),
            )
            return cur.fetchone()["file_id"]

    def file_path(self, accident_id: str, file_type: str,
                  sequence_no: int | None) -> str | None:
        """저장된 로컬 경로. 키오스크가 이미지를 달라고 할 때 쓴다."""
        with self._lock:
            row = self.conn.execute(
                """SELECT file_path FROM pi_accident_file
                   WHERE accident_id = ? AND file_type = ?
                     AND sequence_no IS ?""",
                (accident_id, file_type, sequence_no),
            ).fetchone()
            return row["file_path"] if row else None

    def files_for(self, accident_id: str,
                  file_type: str | None = None) -> list[sqlite3.Row]:
        """사고 하나의 파일 목록. 키오스크가 타임라인을 그릴 때 쓴다.

        ⚠ `sequence_no` 순으로 준다. 앞 15초·뒤 10초가 125장이라 순서 없이는 재생이 안 된다.
        """
        with self._lock:
            if file_type is None:
                return self.conn.execute(
                    """SELECT * FROM pi_accident_file WHERE accident_id = ?
                       ORDER BY file_type, sequence_no""",
                    (accident_id,),
                ).fetchall()
            return self.conn.execute(
                """SELECT * FROM pi_accident_file
                   WHERE accident_id = ? AND file_type = ?
                   ORDER BY sequence_no""",
                (accident_id, file_type),
            ).fetchall()

    def pending_uploads(self, limit: int = 4) -> list[sqlite3.Row]:
        """아직 R2 에 안 올라간 파일. `object_key IS NULL` 이 곧 대기열이다.

        인터넷이 없으면 행이 쌓이고 복구되면 비운다. 백오프·재시도 횟수·데드레터를
        따로 만들지 않는다.

        ⚠ 동시 업로드 수를 제한한다. 어선 상향 대역이 좁다.
        """
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM pi_accident_file WHERE object_key IS NULL
                   ORDER BY created_at LIMIT ?""",
                (limit,),
            ).fetchall()

    def pending_upload_accidents(self, limit: int = 4) -> list[str]:
        """아직 다 안 올라간 사고들. 오래된 순.

        🔴 **타르볼은 사고 단위다.** `pending_uploads()` 는 LIMIT 으로 잘라 와서
          사고 경계를 모른다 — 그걸로 묶으면 한 사고가 여러 타르볼로 쪼개지고,
          `manifest.json` 이 반쪽이 된다.
        """
        with self._lock:
            rows = self.conn.execute(
                """SELECT accident_id, MIN(created_at) AS first_at
                     FROM pi_accident_file WHERE object_key IS NULL
                    GROUP BY accident_id ORDER BY first_at LIMIT ?""",
                (limit,),
            ).fetchall()
            return [r["accident_id"] for r in rows]

    def pending_files_of(self, accident_id: str, limit: int = 200) -> list[sqlite3.Row]:
        """사고 하나에서 아직 안 올라간 파일. 순서는 재생 순서다."""
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM pi_accident_file
                    WHERE accident_id = ? AND object_key IS NULL
                    ORDER BY file_type, sequence_no LIMIT ?""",
                (accident_id, limit),
            ).fetchall()

    def file_by_slot(self, accident_id: str, file_type: str,
                     sequence_no: int | None) -> sqlite3.Row | None:
        """서버 응답을 로컬 행에 되짚을 때 쓴다.

        🔴 `sequence_no` 에 `IS` 를 쓴다. `DETECT_SNAPSHOT` 은 NULL 이라
          `= NULL` 이면 한 행도 안 잡힌다 — 스냅샷만 영영 안 올라간 상태가 된다.
        """
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM pi_accident_file
                    WHERE accident_id = ? AND file_type = ? AND sequence_no IS ?""",
                (accident_id, file_type, sequence_no),
            ).fetchone()

    def mark_uploaded(self, file_id: int, object_key: str, now: int) -> None:
        """🔴 EC2 가 키를 돌려준 **뒤에만** 부른다.

        R2 에는 올라갔는데 EC2 가 모르는 상태로 두면 안 된다. 여기서 키를 채우기
        전이면 다음 라운드에 다시 올린다 — 같은 키에 덮어쓰므로 안전하다.
        """
        with self._lock:
            self.conn.execute(
                "UPDATE pi_accident_file SET object_key = ?, updated_at = ? WHERE file_id = ?",
                (object_key, now, file_id),
            )

    # ── 신고 기록 ────────────────────────────────────────────────────
    def upsert_report(self, accident_id: str, *, channel: str, trigger_kind: str,
                      status: str, sent_count: int, report_lat: float, report_lon: float,
                      first_sent_at: int | None, last_sent_at: int | None,
                      acked_at: int | None, acked_by: str | None,
                      fail_reason: str | None, now: int) -> int:
        """`pi_report` 채널당 한 행을 갱신한다. 없으면 만든다. `report_id` 를 돌려준다.

        🔴 **재전송마다 행을 만들면 안 된다.** DSC 는 M.541 에 따라 5회 연속 + 3.5~4.5분
          간격으로 반복하므로, 사고 하나가 수십 행이 된다. `UNIQUE (accident_id, channel)`
          이 그걸 막고 여기서는 `sent_count` 만 올린다.

        🔴 **`first_sent_at` 은 NULL 일 수 있다.** 인터넷이 없어 `SENDING` 조차 못 간
          채널의 행이 먼저 생긴다. "못 쏜 채널"이 관제에 보여야 하므로 그 행을 버리지
          않는다 — 서버도 `created_at` 을 따로 받기로 했다 (`api.json` IPiReportRequest.first_sent_at).

        🔴 **`sent_count` 는 줄어들지 않는다.** 늦게 도착한 옛 상태가 누적 횟수를
          되돌리면 신고를 덜 보낸 것처럼 보인다. `MAX` 로 고정한다.
        """
        with self._lock:
            self.conn.execute(
                """INSERT INTO pi_report (accident_id, channel, trigger_kind, status,
                       sent_count, report_lat, report_lon, first_sent_at, last_sent_at,
                       acked_at, acked_by, fail_reason, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(accident_id, channel) DO UPDATE SET
                       trigger_kind  = excluded.trigger_kind,
                       status        = excluded.status,
                       sent_count    = MAX(pi_report.sent_count, excluded.sent_count),
                       first_sent_at = COALESCE(pi_report.first_sent_at, excluded.first_sent_at),
                       last_sent_at  = excluded.last_sent_at,
                       acked_at      = excluded.acked_at,
                       acked_by      = excluded.acked_by,
                       fail_reason   = excluded.fail_reason,
                       updated_at    = excluded.updated_at""",
                (accident_id, channel, trigger_kind, status, sent_count,
                 report_lat, report_lon, first_sent_at, last_sent_at,
                 acked_at, acked_by, fail_reason, now, now),
            )
            # report_id 는 MQTT `pi/report/status` 가 요구한다. RETURNING 대신 다시 읽는다 —
            # 이 PK 는 Pi 안에서만 뜻이 있고 EC2 로는 안 나간다 (`docs/ec2.md` §3).
            return self.conn.execute(
                "SELECT report_id FROM pi_report WHERE accident_id = ? AND channel = ?",
                (accident_id, channel),
            ).fetchone()["report_id"]

    def reports_for(self, accident_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_report WHERE accident_id = ? ORDER BY channel",
                (accident_id,),
            ).fetchall()

    # ── 선박 위치 ────────────────────────────────────────────────────
    def add_position(self, ship_id: str, *, lat: float, lon: float,
                     speed_kn: float | None, heading_deg: float | None,
                     accuracy_m: float | None, measured_at: int, now: int) -> bool:
        """`pi_ship_position` 한 행. 넣었으면 True, 같은 초라 버렸으면 False.

        🔴 **`created_at` 은 측정 시각(GPS UTC)이지 수신 시각이 아니다.** 수신 시각으로
          쓰면 두절 복귀 때 몇 시간 전 위치가 "방금"이 된다.

        ⚠ `UNIQUE (ship_id, created_at)` 이 초 단위라 같은 초 두 번째는 조용히 버려진다.
          1Hz 전제의 의도된 dedup 이고 서버 자연키와 같다 (`docs/ec2.md` §3).
          `INSERT OR IGNORE` 로 두면 호출자가 그 사실을 모르므로 boolean 으로 돌려준다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO pi_ship_position
                       (ship_id, lat, lon, speed_kn, heading_deg, accuracy_m,
                        created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ship_id, lat, lon, speed_kn, heading_deg, accuracy_m, measured_at, now),
            )
            return cur.rowcount > 0

    def last_position(self, ship_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_ship_position WHERE ship_id = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (ship_id,),
            ).fetchone()

    # ── 부표 LoRa ────────────────────────────────────────────────────
    def add_buoy(self, accident_id: str, *, seq: int, lat: float, lon: float,
                 is_pressed: bool, rssi: float | None,
                 measured_at: int, received_at: int, now: int) -> int | None:
        """`pi_buoy` 한 행. `buoy_log_id` 또는 None(같은 초라 버림).

        🔴 **`created_at` 은 부표 GPS 가 잰 시각이지 LoRa 수신 시각이 아니다.**
          LoRa 지연만큼 벌어지고, 지도에 찍는 것은 `created_at` 이다 (mqtt.md §3.4).
          수신 시각으로 쓰면 두절 복귀 때 몇 분 전 위치가 "방금"이 된다.

        ⚠ `UNIQUE (accident_id, created_at)` 이 초 단위다. 1Hz 전제에서 의도한
          dedup 이고 서버 자연키와 같다 — LoRa 중복 수신도 여기서 막힌다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO pi_buoy
                       (accident_id, seq, lat, lon, is_pressed, rssi,
                        created_at, received_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (accident_id, seq, lat, lon, 1 if is_pressed else 0, rssi,
                 measured_at, received_at, now),
            )
            return cur.lastrowid if cur.rowcount > 0 else None

    def last_buoy(self, accident_id: str) -> sqlite3.Row | None:
        """마지막 수신. 두절 판정이 `received_at` 을 본다.

        ⚠ `created_at DESC` 가 아니라 `received_at DESC` 다. 부표 GPS 시각이 튀어도
          두절 판정은 "우리가 마지막으로 들은 때"로 해야 한다.
        """
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_buoy WHERE accident_id = ?"
                " ORDER BY received_at DESC, buoy_log_id DESC LIMIT 1",
                (accident_id,),
            ).fetchone()

    def open_comm_loss(self, accident_id: str, *, detected_at: int,
                       last_buoy_log_id: int | None, last_lat: float, last_lon: float,
                       last_received_at: int, threshold_sec: int, now: int) -> int:
        """두절 구간을 연다.

        ⚠ `threshold_sec` 을 행에 박제한다. 나중에 `config.BUOY_TIMEOUT_SEC` 을 바꿔도
          지난 구간이 "왜 이때 두절로 봤나"를 스스로 설명해야 한다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO pi_comm_loss
                       (accident_id, detected_at, last_buoy_log_id, last_lat, last_lon,
                        last_received_at, threshold_sec, recovered_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,NULL,?)""",
                (accident_id, detected_at, last_buoy_log_id, last_lat, last_lon,
                 last_received_at, threshold_sec, now),
            )
            return cur.lastrowid

    def active_comm_loss(self, accident_id: str) -> sqlite3.Row | None:
        """아직 안 닫힌 두절 구간. 없으면 None."""
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_comm_loss WHERE accident_id = ? AND recovered_at IS NULL"
                " ORDER BY detected_at DESC LIMIT 1",
                (accident_id,),
            ).fetchone()

    def close_comm_loss(self, comm_loss_id: int, recovered_at: int, now: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE pi_comm_loss SET recovered_at = ?, updated_at = ?"
                " WHERE comm_loss_id = ? AND recovered_at IS NULL",
                (recovered_at, now, comm_loss_id))

    # ── IMU (pi_imu_log · pi_imu) ────────────────────────────────────
    def add_imu_log(self, ship_id: str, *, position: str, now: int,
                    accel_x: float | None = None, accel_y: float | None = None,
                    accel_z: float | None = None,
                    roll: float | None = None, pitch: float | None = None,
                    heading_deg: float | None = None) -> int | None:
        """상시 로그 한 행. `imu_log_id` 또는 None(같은 초라 버림).

        ⚠ `roll`·`pitch` 가 None 일 수 있다. 설치 영점이 없으면 각도를 **모르는
          것**이고, 0 을 넣으면 화면이 "수평" 으로 읽는다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO pi_imu_log
                       (ship_id, imu_position, accel_x, accel_y, accel_z,
                        roll, pitch, heading_deg, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (ship_id, position, accel_x, accel_y, accel_z,
                 roll, pitch, heading_deg, now, now))
            return cur.lastrowid if cur.rowcount > 0 else None

    def prune_imu_log(self, ship_id: str, before: int) -> int:
        """오래된 로그를 지운다. 지운 행 수.

        🔴 1Hz 다. 이게 없으면 microSD 가 하루 8.6만 행씩 찬다.
        """
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM pi_imu_log WHERE ship_id = ? AND created_at < ?",
                (ship_id, before))
            return cur.rowcount

    def copy_imu_window(self, accident_id: str, ship_id: str,
                        *, since: int, until: int, now: int) -> int:
        """로그의 `[since, until]` 을 그 사고의 `pi_imu` 로 옮긴다. 옮긴 행 수.

        🔴 **사고 전 구간이 이 함수의 존재 이유다.** `pi_imu.accident_id` 가
           NOT NULL 이라 사고가 생기기 전에는 거기 못 쓴다. 그래서 상시 로그에
           쌓아 두고 사고가 나면 창을 긁어 온다.

        ⚠ `pi_imu.roll`·`pitch`·`yaw` 는 NOT NULL 이다. 영점이 없어 각도를 모르는
          행은 **옮기지 않는다** — 0 으로 채우면 "수평이었다" 는 거짓 기록이 된다.
        ⚠ `yaw` 는 MPU6050 으로 못 구한다(자력계 없음). heading_deg 가 있으면 그
          값을, 없으면 0 을 넣는다 — 스키마가 NOT NULL 이라 자리를 비울 수 없다.
        ⚠ 여러 번 불러도 안전하다. `UNIQUE (accident_id, created_at, imu_position)`
          이 막는다 — 사고 중에 주기적으로 불러 이어 붙이는 것이 정상 사용이다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO pi_imu
                       (accident_id, imu_position, accel_x, accel_y, accel_z,
                        roll, pitch, yaw, heading_deg, created_at, updated_at)
                   SELECT ?, imu_position, accel_x, accel_y, accel_z,
                          roll, pitch, COALESCE(heading_deg, 0), heading_deg,
                          created_at, ?
                     FROM pi_imu_log
                    WHERE ship_id = ? AND created_at BETWEEN ? AND ?
                      AND roll IS NOT NULL AND pitch IS NOT NULL""",
                (accident_id, now, ship_id, since, until))
            return cur.rowcount

    # ── 표류 추정 (pi_drift_estimate) ────────────────────────────────
    def save_drift(self, accident_id: str, *, comm_loss_id: int | None,
                   base_lat: float, base_lon: float, last_received_at: int,
                   elapsed_sec: int, center_lat: float, center_lon: float,
                   radius_m: float, axis_major_m: float, axis_minor_m: float,
                   axis_bearing_deg: float, target: str,
                   input_current_speed: float | None,
                   input_current_dir: float | None,
                   input_wind_speed: float | None,
                   input_wind_dir: float | None,
                   input_observed_at: int | None, now: int) -> int:
        """추정 한 건. `estimate_id`.

        🔴 **덮어쓰지 않고 쌓는다.** 이전 건은 `is_current = 0` 으로 내린다 —
           덮어쓰면 "그때 어디를 수색 범위로 봤는지"가 사라진다. 구조가 끝난 뒤
           왜 그쪽을 뒤졌는지 설명할 수 있어야 한다.

        ⚠ 내리는 것과 넣는 것이 **한 트랜잭션**이어야 한다. 사이에서 죽으면
          `uq_pi_drift_current` 가 다음 INSERT 를 영영 막는다 — 같은 (사고, 대상)
          의 is_current = 1 이 둘이 될 수는 없지만, 0 이 되는 것은 막지 않는다.
        """
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    "UPDATE pi_drift_estimate SET is_current = 0, updated_at = ?"
                    " WHERE accident_id = ? AND target = ? AND is_current = 1",
                    (now, accident_id, target))
                cur = self.conn.execute(
                    """INSERT INTO pi_drift_estimate
                           (accident_id, comm_loss_id, base_lat, base_lon,
                            last_received_at, elapsed_sec, center_lat, center_lon,
                            radius_m, axis_major_m, axis_minor_m, axis_bearing_deg,
                            input_current_speed, input_current_dir,
                            input_wind_speed, input_wind_dir, input_observed_at,
                            target, is_current, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                    (accident_id, comm_loss_id, base_lat, base_lon,
                     last_received_at, elapsed_sec, center_lat, center_lon,
                     radius_m, axis_major_m, axis_minor_m, axis_bearing_deg,
                     input_current_speed, input_current_dir,
                     input_wind_speed, input_wind_dir, input_observed_at,
                     target, now, now))
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")
            return int(cur.lastrowid or 0)

    def current_drift(self, accident_id: str, target: str = "BUOY") -> sqlite3.Row | None:
        """지금 유효한 추정. 재부팅 복구가 retained 를 다시 발행할 때 쓴다."""
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM pi_drift_estimate"
                " WHERE accident_id = ? AND target = ? AND is_current = 1",
                (accident_id, target)).fetchone()

    # ── 해양 데이터 (pi_ocean_data) ──────────────────────────────────
    def save_ocean(self, ship_id: str, *, source: str, observed_at: int,
                   fetched_at: int, now: int,
                   wind_speed: float | None = None, wind_dir: float | None = None,
                   current_speed: float | None = None, current_dir: float | None = None,
                   current_spread: float | None = None,
                   wave_height: float | None = None,
                   water_temp: float | None = None,
                   lat: float | None = None, lon: float | None = None,
                   distance_km: float | None = None) -> int | None:
        """관측 한 건. `ocean_data_id` 또는 None(이미 있는 관측).

        ⚠ `UNIQUE (ship_id, source, observed_at)` 이 막는다. 같은 관측을 30분마다
          다시 받는 것이 **정상**이다 — ROMS 는 1시간 간격이라 폴링이 더 잦다.
          덮어쓰지 않고 버린다: 같은 시각의 값이 달라질 이유가 없고, 덮어쓰면
          updated_at 이 바뀌어 sync 가 매번 같은 행을 다시 올린다.
        """
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO pi_ocean_data
                       (ship_id, observed_at, source, lat, lon, distance_km,
                        wind_speed, wind_dir,
                        current_speed, current_dir, current_spread,
                        wave_height, water_temp, fetched_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ship_id, observed_at, source, lat, lon, distance_km,
                 wind_speed, wind_dir,
                 current_speed, current_dir, current_spread,
                 wave_height, water_temp, fetched_at, now),
            )
            return cur.lastrowid if cur.rowcount > 0 else None

    def latest_ocean(self, ship_id: str, source: str,
                     *, not_before: int | None = None) -> sqlite3.Row | None:
        """그 소스의 가장 최근 관측.

        🔴 `not_before` 를 주면 그보다 오래된 것은 **안 준다.** 3시간 전 조류로 그린
           타원과 3분 전 조류로 그린 타원은 화면에서 똑같이 생긴다 — 오래된 값을
           조용히 쓰느니 "해양 데이터 없음"이 낫다.
        """
        sql = ("SELECT * FROM pi_ocean_data WHERE ship_id = ? AND source = ?")
        args: list[Any] = [ship_id, source]
        if not_before is not None:
            sql += " AND observed_at >= ?"
            args.append(not_before)
        sql += " ORDER BY observed_at DESC LIMIT 1"
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def prune_ocean(self, ship_id: str, before: int) -> int:
        """오래된 관측을 지운다. 지운 행 수.

        ⚠ microSD 다. 30분마다 두 행이면 1년에 3.5만 행인데, 표류 계산은 최근
          몇 시간만 본다 (명세 §8 이 6시간에서 추정을 끊는다).
        """
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM pi_ocean_data WHERE ship_id = ? AND observed_at < ?",
                (ship_id, before))
            return cur.rowcount

    def cursor_for(self, table: str, direction: str = "PUSH") -> tuple[int, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT synced_at, synced_pk FROM sync WHERE table_name = ? AND direction = ?",
                (table, direction),
            ).fetchone()
            return (row["synced_at"], row["synced_pk"]) if row else (0, 0)

    def pending(self, table: str, pk: str, limit: int = 100) -> list[sqlite3.Row]:
        """커서 이후 행. **복합 커서를 쓴다.**

        updated_at 이 초 단위인데 1Hz 테이블이 있어서, 시각만으로 자르면
          `>`  는 같은 초의 안 읽은 행을 건너뛰고 (유실)
          `>=` 는 매번 같은 초를 다시 보낸다 (중복)
        (updated_at, pk) 로 비교하면 둘 다 안 생긴다. SQLite 3.15+ 의 row value 비교다.
        """
        with self._lock:
            at, spk = self.cursor_for(table)
            return self.conn.execute(
                f"SELECT * FROM {table} WHERE (updated_at, {pk}) > (?, ?)"
                f" ORDER BY updated_at, {pk} LIMIT ?",
                (at, spk, limit),
            ).fetchall()

    def advance_cursor(self, table: str, synced_at: int, synced_pk: Any,
                       *, direction: str = "PUSH", now: int = 0) -> None:
        """⚠ **저장 확정 응답을 받은 뒤에만** 부른다.

        영상에 대해 DES-31 C-8 이 정한 원칙과 같다 — 전송 시점이 아니라 확정 시점이다.
        먼저 전진시키면 서버가 못 받은 행이 영영 재전송 대상에서 빠진다.
        """
        with self._lock:
            self.conn.execute(
                "INSERT INTO sync (table_name, direction, synced_at, synced_pk, updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(table_name, direction) DO UPDATE SET"
                "   synced_at = excluded.synced_at,"
                "   synced_pk = excluded.synced_pk,"
                "   updated_at = excluded.updated_at",
                (table, direction, synced_at, synced_pk, now),
            )


# ── row → 도메인 ─────────────────────────────────────────────────────
def _to_accident(r: sqlite3.Row) -> Accident:
    """저장 층 → 도메인 층. enum 복원이 여기서 일어난다.

    DB 는 TEXT 로 갖고 있으므로 잘못된 값이 들어 있으면 여기서 ValueError 가 난다 —
    CHECK 제약이 있어서 정상 경로로는 생길 수 없고, 손으로 고친 DB 를 잡아준다.
    """
    return Accident(
        accident_id=r["accident_id"],
        ship_id=r["ship_id"],
        status=AccidentStatus(r["status"]),
        accident_type=AccidentType(r["accident_type"]),
        trigger_source=TriggerSource(r["trigger_source"]),
        report_type=ReportType(r["report_type"]),
        report_dsc=r["report_dsc"],
        accident_lat=r["accident_lat"],
        accident_lon=r["accident_lon"],
        wait_sec=r["wait_sec"],
        report_due_at=r["report_due_at"],
        model_version=r["model_version"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        rescued_at=r["rescued_at"],
        closed_at=r["closed_at"],
    )


def _q(values: tuple) -> str:
    return ",".join("?" * len(values))


# ── 드리프트 가드 ────────────────────────────────────────────────────
def assert_schema_matches(conn: sqlite3.Connection) -> None:
    """코드가 기대하는 것과 실제 스키마가 맞는지 확인한다.

    `database/pi.sql` 을 고치고 이 파일을 안 고치면(또는 그 반대면) 여기서 걸린다.
    나중에 SQLAlchemy 를 넣더라도 같은 역할의 대조는 남겨두는 편이 좋다 —
    스키마가 두 곳에 정의되는 순간 드리프트는 시간 문제다.
    """
    need = {
        "pi_accident": {"accident_id", "ship_id", "status", "accident_type", "trigger_source",
                        "report_type", "report_dsc", "wait_sec", "report_due_at",
                        "model_version", "rescued_at", "closed_at", "created_at", "updated_at"},
        "pi_accident_state": {"accident_state_id", "accident_id", "status", "prev_status",
                              "reason", "caused_by", "created_at", "updated_at"},
        "pi_launch": {"accident_id", "detection_id", "result", "fail_reason",
                      "target_lat", "target_lon", "created_at", "updated_at"},
        "pi_command_log": {"request_id", "command", "accident_id", "created_at"},
        "pi_credential": {"ship_id", "ship_key", "status", "issued_at", "updated_at"},
        "pi_report": {"report_id", "accident_id", "channel", "trigger_kind", "status",
                      "sent_count", "report_lat", "report_lon", "first_sent_at",
                      "last_sent_at", "acked_at", "acked_by", "fail_reason",
                      "created_at", "updated_at"},
        "pi_ship_position": {"position_id", "ship_id", "lat", "lon", "speed_kn",
                             "heading_deg", "accuracy_m", "created_at", "updated_at"},
        "pi_drift_estimate": {"estimate_id", "accident_id", "comm_loss_id",
                              "base_lat", "base_lon", "last_received_at",
                              "elapsed_sec", "center_lat", "center_lon", "radius_m",
                              "axis_major_m", "axis_minor_m", "axis_bearing_deg",
                              "target", "input_current_speed", "input_current_dir",
                              "input_wind_speed", "input_wind_dir",
                              "input_observed_at", "is_current",
                              "created_at", "updated_at"},
        "pi_imu_log": {"imu_log_id", "ship_id", "imu_position",
                       "accel_x", "accel_y", "accel_z", "roll", "pitch",
                       "heading_deg", "created_at", "updated_at"},
        "pi_ocean_data": {"ocean_data_id", "ship_id", "observed_at", "source",
                          "wind_speed", "wind_dir", "current_speed", "current_dir",
                          "current_spread", "wave_height", "water_temp",
                          "lat", "lon", "distance_km",
                          "fetched_at", "updated_at"},
        "sync": {"table_name", "direction", "synced_at", "synced_pk", "updated_at"},
    }
    for table, cols in need.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            raise RuntimeError(f"테이블 없음: {table} — pi.sql 을 적용했는가")
        missing = cols - have
        if missing:
            raise RuntimeError(f"{table} 에 컬럼 없음: {sorted(missing)}")

    # 동시 사고 1건을 강제하는 인덱스가 실제로 있는지. 이게 없으면 코드의 E1 검사만 남는데,
    # 경합에서 새면 사고가 두 개 생긴다.
    idx = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pi_accident'")}
    if "uq_pi_accident_active" not in idx:
        raise RuntimeError("uq_pi_accident_active 인덱스가 없다 — E1 을 DB 가 못 막는다")

    # 🔴 (사고, 대상) 당 현재 추정이 하나임을 DB 가 보장해야 한다. `save_drift` 가
    #   이전 건을 내리고 넣는데, 그 두 문장 사이에서 죽으면 is_current 가 둘이 된다.
    #   그러면 화면이 어느 타원을 그릴지 모른다 — 두 범위는 서로 수백 미터 다르다.
    idx = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
        " AND tbl_name='pi_drift_estimate'")}
    if "uq_pi_drift_current" not in idx:
        raise RuntimeError("uq_pi_drift_current 인덱스가 없다 — 현재 추정이 둘이 될 수 있다")

    # 🔴 시크릿이 sync 대상이 되면 매 요청 본문에 실려 서버로 되돌아간다.
    #   테이블 이름을 sync 에 넣는 실수는 조용히 통과하므로 여기서 막는다.
    if conn.execute("SELECT 1 FROM sync WHERE table_name = 'pi_credential'").fetchone():
        raise RuntimeError("pi_credential 이 sync 에 들어가 있다 — 시크릿을 EC2 로 올리면 안 된다")

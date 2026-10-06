"""이미 만들어진 `floaq.db` 에 새 컬럼·인덱스를 올린다.

🔴 **`database/pi.sql` 은 DB 를 처음 만들 때만 적용된다** (`adapters/sqlite.connect`).
   스키마에 컬럼을 추가해도 이미 도는 Pi 의 DB 는 안 바뀌고, 다음 기동에서
   `assert_schema_matches` 가 막는다. 2026-09-22 실기에서 그렇게 멈췄다:

       RuntimeError: pi_drift_estimate 에 컬럼 없음:
           ['axis_bearing_deg', 'axis_major_m', 'axis_minor_m', 'target']

   DB 를 지우면 사고 기록이 통째로 날아간다. 그래서 올려 쓴다.

⚠ **여러 번 돌려도 안전하다.** 이미 있는 컬럼은 건너뛴다. 기동 스크립트에 넣어도
  되고 손으로 한 번 돌려도 된다.

⚠ SQLite 의 `ALTER TABLE` 은 컬럼 추가만 된다. CHECK 제약은 못 붙인다 —
  새로 만든 DB(`pi.sql`)에는 붙어 있고 올린 DB 에는 없는 차이가 남는다.
  값을 넣는 쪽(`adapters/sqlite.save_drift`)과 계약(`contracts/pi.py`)이 같은
  규칙을 강제하므로 실해는 없지만, **정본은 `pi.sql` 이다.**

    uv run python tools/migrate_db.py --db floaq.db
    uv run python tools/migrate_db.py --db floaq.db --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters.sqlite import assert_schema_matches, connect  # noqa: E402

#: 올릴 컬럼. `(테이블, 컬럼, 타입과 기본값)`.
#:
#: ⚠ 순서가 `pi.sql` 의 선언 순서와 달라도 된다 — `ALTER TABLE` 은 언제나 끝에
#:   붙인다. 컬럼 순서에 기대는 코드가 없어야 하는 이유다(전부 이름으로 읽는다).
COLUMNS: list[tuple[str, str, str]] = [
    # 표류 타원 (공통 명세 §5·§6)
    ("pi_drift_estimate", "axis_major_m", "REAL"),
    ("pi_drift_estimate", "axis_minor_m", "REAL"),
    ("pi_drift_estimate", "axis_bearing_deg", "REAL"),
    # 🔴 NOT NULL 에는 기본값이 있어야 한다. 이미 있는 행은 전부 부표 추정이다
    ("pi_drift_estimate", "target", "TEXT NOT NULL DEFAULT 'BUOY'"),
    # 해양 데이터 (`floaq/ocean.py`)
    ("pi_ocean_data", "current_spread", "REAL"),
    ("pi_ocean_data", "lat", "REAL"),
    ("pi_ocean_data", "lon", "REAL"),
    ("pi_ocean_data", "distance_km", "REAL"),
]

#: 새로 생긴 테이블. `pi.sql` 에서 그대로 옮겨 적는다.
#:
#: ⚠ `ALTER TABLE ADD COLUMN` 과 달리 테이블은 통째로 만들어야 한다. 정본은
#:   `pi.sql` 이고 여기는 복사본이다 — 둘이 갈라지면 새로 만든 DB 와 올린 DB 가
#:   달라진다. 스키마를 고칠 때 양쪽을 같이 본다.
TABLES: list[tuple[str, str]] = [
    ("pi_imu_log", """
        CREATE TABLE pi_imu_log (
            imu_log_id   INTEGER NOT NULL,
            ship_id      TEXT    NOT NULL,
            imu_position TEXT    NOT NULL,
            accel_x      REAL,
            accel_y      REAL,
            accel_z      REAL,
            roll         REAL,
            pitch        REAL,
            heading_deg  REAL,
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL,
            PRIMARY KEY (imu_log_id),
            FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id),
            CHECK (imu_position IN ('HULL', 'CAMERA_L', 'CAMERA_R')),
            CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360),
            UNIQUE (ship_id, created_at, imu_position)
        ) STRICT"""),
]

#: 새로 생긴 인덱스 (위 테이블에 딸린 것 포함)
NEW_INDEXES: list[tuple[str, str]] = [
    ("ix_pi_imu_log_time",
     "CREATE INDEX ix_pi_imu_log_time ON pi_imu_log (ship_id, created_at)"),
]

#: 다시 만들 인덱스. 정의가 바뀐 것만 넣는다.
#:
#: 🔴 `uq_pi_drift_current` 는 전에 `(accident_id)` 였다. 그대로 두면 부표와 사람의
#:    현재 추정을 동시에 담지 못하고, 둘째 INSERT 가 UNIQUE 로 죽는다.
INDEXES: list[tuple[str, str]] = [
    ("uq_pi_drift_current",
     "CREATE UNIQUE INDEX uq_pi_drift_current"
     " ON pi_drift_estimate (accident_id, target) WHERE is_current = 1"),
]


def columns_of(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def index_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row[0] if row else None


def migrate(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """올린 항목 수. 0 이면 이미 최신이다."""
    done = 0

    for name, create in TABLES:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if exists:
            continue
        print(f"  + 테이블 {name}")
        if not dry_run:
            conn.execute(create)
        done += 1

    for name, create in NEW_INDEXES:
        if index_sql(conn, name) is not None:
            continue
        print(f"  + 인덱스 {name}")
        if not dry_run:
            conn.execute(create)
        done += 1

    for table, col, decl in COLUMNS:
        have = columns_of(conn, table)
        if not have:
            print(f"  !! 테이블 없음: {table} — pi.sql 을 적용한 DB 가 맞는가")
            continue
        if col in have:
            continue
        sql = f"ALTER TABLE {table} ADD COLUMN {col} {decl}"
        print(f"  + {table}.{col}")
        if not dry_run:
            conn.execute(sql)
        done += 1

    for name, create in INDEXES:
        cur = index_sql(conn, name)
        # 공백만 다른 경우를 같게 본다 — 매번 다시 만들지 않으려는 것뿐이다
        same = cur is not None and " ".join(cur.split()) == " ".join(create.split())
        if same:
            continue
        print(f"  ~ 인덱스 {name} {'재생성' if cur else '생성'}")
        if not dry_run:
            if cur is not None:
                conn.execute(f"DROP INDEX {name}")
            conn.execute(create)
        done += 1

    return done


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="floaq.db")
    p.add_argument("--dry-run", action="store_true", help="무엇을 올릴지만 보여준다")
    args = p.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"DB 가 없다: {path}  (새로 만들 것이면 main.py 를 그냥 띄운다)")
        return 1

    # 🔴 schema 를 주지 않는다. 주면 pi.sql 을 통째로 다시 실행해 CREATE TABLE 에서 죽는다
    conn = connect(path)
    print(f"{path}")
    n = migrate(conn, dry_run=args.dry_run)

    if n == 0:
        print("  이미 최신이다")
    elif args.dry_run:
        print(f"  {n}개를 올릴 수 있다 (--dry-run 이라 안 건드렸다)")
        return 0
    else:
        print(f"  {n}개 올렸다")

    # 올린 뒤에도 기동이 막히면 여기서 같은 오류를 미리 본다
    try:
        assert_schema_matches(conn)
        print("  스키마 검사 통과")
    except RuntimeError as e:
        print(f"  !! 아직 안 맞는다: {e}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

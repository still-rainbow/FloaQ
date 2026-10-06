"""SQLite 어댑터 테스트. **실제 `database/pi.sql` 로 만든 DB 에 붙는다.**

스키마를 흉내내지 않고 진짜 파일을 적용한다 — 그래야 코드와 스키마가 갈라지면 여기서 걸린다.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = ROOT.parents[1] / "database" / "pi.sql"

from floaq.adapters.sqlite import SqliteRepo, assert_schema_matches, connect  # noqa: E402
from floaq.contracts import AccidentStatus as S                               # noqa: E402
from floaq.contracts import AccidentType, ReportType, TriggerSource           # noqa: E402
from floaq.core.domain import Accident, LaunchRecord, StateTransition         # noqa: E402
from floaq.ids import uuid7                                                   # noqa: E402

T0 = 1_757_000_000
SHIP = uuid7()


def fresh() -> tuple[sqlite3.Connection, SqliteRepo]:
    conn = connect(":memory:", schema=SCHEMA)
    conn.execute(
        "INSERT INTO pi_ship VALUES (?,'test',NULL,'440123456',1,0,?,?,NULL)",
        (SHIP, T0, T0),
    )
    return conn, SqliteRepo(conn)


def make(aid: str | None = None, status=S.DETECT, due=None, atype=AccidentType.MOB,
         src=TriggerSource.AI) -> Accident:
    return Accident(
        accident_id=aid or uuid7(), ship_id=SHIP, status=status,
        accident_type=atype, trigger_source=src,
        report_type=ReportType.DISTRESS, report_dsc=110,
        accident_lat=35.1, accident_lon=129.0,
        wait_sec=30, report_due_at=due, model_version="v1",
        created_at=T0, updated_at=T0,
    )


def ok(label, fn):
    try:
        fn(); print("  PASS(accepted) %s" % label)
    except Exception as e:
        print("  FAIL %s -> %s" % (label, str(e).splitlines()[0]))


def rejected(label, fn):
    try:
        fn(); print("  FAIL(should reject) %s" % label)
    except (sqlite3.IntegrityError, RuntimeError):
        print("  PASS(rejected)  %s" % label)
    except Exception as e:
        print("  FAIL %s -> %r" % (label, e))


# ── 스키마 ───────────────────────────────────────────────────────────
def test_schema_guard_passes():
    """코드가 기대하는 컬럼·인덱스가 실제 스키마에 있는가. 드리프트 가드."""
    conn, _ = fresh()
    assert_schema_matches(conn)


def test_foreign_keys_actually_on():
    """🔴 SQLite 기본이 OFF 다. 안 켜면 FK 13개가 조용히 무시된다."""
    conn, _ = fresh()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_all_tables_strict():
    conn, _ = fresh()
    loose = [r["name"] for r in conn.execute(
        "SELECT name FROM pragma_table_list WHERE schema='main' AND type='table'"
        " AND strict=0 AND name NOT LIKE 'sqlite_%'")]
    assert loose == [], loose


# ── 사고 CRUD ────────────────────────────────────────────────────────
def test_create_and_read_back():
    """저장 → 도메인 왕복. enum 이 TEXT 를 거쳐 제대로 복원되는지."""
    conn, repo = fresh()
    a = make()
    repo.create(a)
    got = repo.get(a.accident_id)
    assert got == a                       # frozen dataclass 라 값 비교가 된다
    assert isinstance(got.status, S)      # 문자열이 아니라 enum 으로 복원됐다


def test_active_returns_only_in_progress():
    conn, repo = fresh()
    a = make(status=S.DETECT)
    repo.create(a)
    assert repo.active().accident_id == a.accident_id

    repo.update(a.with_status(S.CANCEL, now=T0 + 5))
    assert repo.active() is None          # 종료된 건 안 잡힌다


def test_second_active_accident_blocked_by_db():
    """🔴 E1 — 코드가 AI-05 를 놓쳐도 DB 가 막는다 (uq_pi_accident_active)."""
    conn, repo = fresh()
    repo.create(make())
    rejected("두 번째 진행 중 사고", lambda: repo.create(make()))


def test_cancelled_accident_frees_the_slot():
    """E2 — 취소 후 다시 탐지되면 새 사고로 만들 수 있어야 한다."""
    conn, repo = fresh()
    a = make()
    repo.create(a)
    repo.update(a.with_status(S.CANCEL, now=T0 + 5))
    repo.create(make())                   # 터지면 안 된다
    assert repo.active() is not None


def test_wait_requires_due_at():
    """CHECK 제약이 앱 로직과 같은 규칙을 강제한다."""
    conn, repo = fresh()
    bad = make(status=S.WAIT, due=None)
    rejected("WAIT 인데 report_due_at 없음", lambda: repo.create(bad))


def test_ai_detection_must_be_mob():
    conn, repo = fresh()
    rejected("AI + FIRE", lambda: repo.create(make(atype=AccidentType.FIRE)))
    ok("MANUAL + FIRE", lambda: repo.create(
        make(atype=AccidentType.FIRE, src=TriggerSource.MANUAL, status=S.REPORT)))


def test_update_missing_accident_raises():
    conn, repo = fresh()
    rejected("없는 사고 갱신", lambda: repo.update(make()))


def test_due_at_cleared_when_leaving_wait():
    """WAIT 을 벗어나면 만료 시각이 지워져야 한다.

    안 지우면 CANCEL 된 사고에 만료 시각이 남아서 재부팅 복구 때
    '만료된 WAIT' 으로 오인될 여지가 생긴다.
    """
    conn, repo = fresh()
    a = make(status=S.WAIT, due=T0 + 30)
    repo.create(a)
    repo.update(a.with_status(S.CANCEL, now=T0 + 5))
    assert repo.get(a.accident_id).report_due_at is None


# ── 투하 ─────────────────────────────────────────────────────────────
def test_launch_recorded_once():
    """E5 — 재투하 없음. PK 가 accident_id 라 DB 가 막는다."""
    conn, repo = fresh()
    a = make()
    repo.create(a)
    rec = LaunchRecord(
        accident_id=a.accident_id, detection_id=uuid7(), result="SUCCESS",
        fail_reason=None, launch_lat=35.1, launch_lon=129.0,
        target_lat=35.11, target_lon=129.01, horizontal_angle=12.5,
        vertical_angle=20.0, confidence_score=0.93, created_at=T0)
    repo.update(rec)
    rejected("재투하", lambda: repo.update(rec))


def test_launch_success_cannot_have_fail_reason():
    conn, repo = fresh()
    a = make(); repo.create(a)
    bad = LaunchRecord(
        accident_id=a.accident_id, detection_id=None, result="SUCCESS",
        fail_reason="NOT_LOADED", launch_lat=35.1, launch_lon=129.0,
        target_lat=None, target_lon=None, horizontal_angle=0.0,
        vertical_angle=0.0, confidence_score=None, created_at=T0)
    rejected("SUCCESS + fail_reason", lambda: repo.update(bad))


# ── 상태 이력 ────────────────────────────────────────────────────────
def test_history_is_ordered_and_append_only():
    conn, repo = fresh()
    a = make(); repo.create(a)
    for prev, cur, reason in [
        (None, S.DETECT, "AI_DETECT"),
        (S.DETECT, S.WAIT, "COUNTDOWN_START"),
        (S.WAIT, S.REPORT, "TIMEOUT"),
    ]:
        repo.append_state(StateTransition(a.accident_id, cur, prev, reason, None, T0))

    hist = repo.history(a.accident_id)
    assert [h.reason for h in hist] == ["AI_DETECT", "COUNTDOWN_START", "TIMEOUT"]
    assert hist[1].prev_status is S.DETECT


def test_duplicate_transition_swallowed():
    """재전송 멱등. UNIQUE(accident_id, status, created_at) 가 받아준다."""
    conn, repo = fresh()
    a = make(); repo.create(a)
    t = StateTransition(a.accident_id, S.DETECT, None, "AI_DETECT", None, T0)
    repo.append_state(t)
    repo.append_state(t)                  # 터지지 않는다
    assert len(repo.history(a.accident_id)) == 1


def test_cascade_on_accident_delete():
    conn, repo = fresh()
    a = make(); repo.create(a)
    repo.append_state(StateTransition(a.accident_id, S.DETECT, None, "AI_DETECT", None, T0))
    conn.execute("DELETE FROM pi_accident WHERE accident_id = ?", (a.accident_id,))
    assert repo.history(a.accident_id) == []


# ── 명령 중복 제거 ───────────────────────────────────────────────────
def test_command_dedup_survives_restart():
    """🔴 디스크에 남아야 한다. 메모리면 재부팅 후 replay 된 명령이 통과한다."""
    path = ROOT / "_test_dedup.db"
    path.unlink(missing_ok=True)
    try:
        conn = connect(path, schema=SCHEMA)
        repo = SqliteRepo(conn)
        rid = uuid7()
        assert repo.seen_request(rid) is False
        repo.remember_request(rid, command="report_now", now=T0)
        assert repo.seen_request(rid) is True
        conn.close()

        # 재부팅
        conn2 = connect(path)
        assert SqliteRepo(conn2).seen_request(rid) is True
        conn2.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


def test_prune_old_commands():
    conn, repo = fresh()
    repo.remember_request(uuid7(), command="cancel", now=T0 - 3600)
    repo.remember_request(uuid7(), command="cancel", now=T0)
    assert repo.prune_commands(T0 - 60) == 1


# ── 동기화 커서 ──────────────────────────────────────────────────────
def test_cursor_starts_at_zero_and_advances():
    conn, repo = fresh()
    assert repo.cursor_for("pi_accident") == (0, 0)
    repo.advance_cursor("pi_accident", T0, "abc", now=T0)
    assert repo.cursor_for("pi_accident") == (T0, "abc")
    # 방향이 다르면 별개 커서다 (PUSH=업로드, PULL=해양데이터 수신)
    assert repo.cursor_for("pi_accident", "PULL") == (0, 0)


def test_composite_cursor_no_loss_no_dup():
    """🔴 같은 초에 여러 행이 있어도 유실·중복이 없어야 한다.

    updated_at 이 초 단위인데 1Hz 테이블이 있다. 시각만으로 자르면
      >  는 같은 초의 안 읽은 행을 건너뛰고, >= 는 매번 다시 보낸다.
    """
    conn, repo = fresh()
    a = make(); repo.create(a)
    # 같은 초에 3건
    for i in range(3):
        conn.execute(
            "INSERT INTO pi_buoy (accident_id, seq, lat, lon, is_pressed, rssi,"
            " created_at, received_at, updated_at) VALUES (?,?,?,?,0,-90.0,?,?,?)",
            (a.accident_id, i, 35.1, 129.0, T0 + i, T0, T0))

    first = repo.pending("pi_buoy", "buoy_log_id", limit=2)
    assert len(first) == 2
    repo.advance_cursor("pi_buoy", first[-1]["updated_at"], first[-1]["buoy_log_id"])

    rest = repo.pending("pi_buoy", "buoy_log_id", limit=10)
    assert len(rest) == 1                                   # 유실 없음
    assert rest[0]["buoy_log_id"] == first[-1]["buoy_log_id"] + 1   # 중복 없음


# ── 부표 LoRa ────────────────────────────────────────────────────────
def test_add_buoy_writes_the_real_columns():
    """스키마를 흉내내지 않고 진짜 `database/pi.sql` 에 넣는다. 컬럼이 어긋나면 여기서 터진다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    bid = repo.add_buoy(a.accident_id, seq=7, lat=35.11, lon=129.01,
                        is_pressed=True, rssi=-76.0,
                        measured_at=T0 + 5, received_at=T0 + 6, now=T0 + 6)
    assert bid is not None

    row = repo.last_buoy(a.accident_id)
    assert row["seq"] == 7
    assert row["is_pressed"] == 1
    assert row["created_at"] == T0 + 5          # 부표 GPS 가 잰 시각
    assert row["received_at"] == T0 + 6         # 우리가 들은 시각


def test_add_buoy_dedupes_within_one_second():
    """🔴 `UNIQUE (accident_id, created_at)` 은 초 단위다. 서버 자연키와 같다.

    `INSERT OR IGNORE` 로 두면 호출자가 버려진 걸 모른다 — None 으로 알린다.
    """
    _, repo = fresh()
    a = make(); repo.create(a)
    first = repo.add_buoy(a.accident_id, seq=0, lat=35.1, lon=129.0,
                          is_pressed=False, rssi=None,
                          measured_at=T0, received_at=T0, now=T0)
    again = repo.add_buoy(a.accident_id, seq=1, lat=35.2, lon=129.2,
                          is_pressed=True, rssi=-80.0,
                          measured_at=T0, received_at=T0, now=T0)
    assert first is not None
    assert again is None


def test_last_buoy_orders_by_received_not_measured():
    """🔴 부표 GPS 시각이 튀어도 두절 판정은 "우리가 마지막으로 들은 때"여야 한다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    repo.add_buoy(a.accident_id, seq=0, lat=35.1, lon=129.0, is_pressed=False,
                  rssi=None, measured_at=T0 + 100, received_at=T0 + 1, now=T0)
    repo.add_buoy(a.accident_id, seq=1, lat=35.2, lon=129.2, is_pressed=False,
                  rssi=None, measured_at=T0 + 2, received_at=T0 + 9, now=T0)
    assert repo.last_buoy(a.accident_id)["seq"] == 1


def test_comm_loss_open_and_close():
    _, repo = fresh()
    a = make(); repo.create(a)
    assert repo.active_comm_loss(a.accident_id) is None

    cid = repo.open_comm_loss(a.accident_id, detected_at=T0 + 60,
                              last_buoy_log_id=None, last_lat=35.1, last_lon=129.0,
                              last_received_at=T0, threshold_sec=60, now=T0 + 60)
    assert repo.active_comm_loss(a.accident_id)["comm_loss_id"] == cid

    repo.close_comm_loss(cid, T0 + 90, T0 + 90)
    assert repo.active_comm_loss(a.accident_id) is None


def test_close_comm_loss_is_idempotent():
    """복구 프레임이 두 번 와도 첫 복구 시각을 덮어쓰지 않는다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    cid = repo.open_comm_loss(a.accident_id, detected_at=T0 + 60,
                              last_buoy_log_id=None, last_lat=35.1, last_lon=129.0,
                              last_received_at=T0, threshold_sec=60, now=T0 + 60)
    repo.close_comm_loss(cid, T0 + 90, T0 + 90)
    repo.close_comm_loss(cid, T0 + 99, T0 + 99)
    row = repo.conn.execute(
        "SELECT recovered_at FROM pi_comm_loss WHERE comm_loss_id = ?", (cid,)).fetchone()
    assert row["recovered_at"] == T0 + 90


# ── 표류 추정 · 해양 데이터 ──────────────────────────────────────────
def drift_args(**kw):
    base = dict(comm_loss_id=None, base_lat=35.1, base_lon=129.0,
                last_received_at=T0, elapsed_sec=600,
                center_lat=35.11, center_lon=129.01, radius_m=420.0,
                axis_major_m=178.0, axis_minor_m=99.0, axis_bearing_deg=38.0,
                target="BUOY", input_current_speed=0.4, input_current_dir=45.0,
                input_wind_speed=7.5, input_wind_dir=270.0,
                input_observed_at=T0 - 300, now=T0 + 600)
    return {**base, **kw}


def test_save_drift_demotes_the_previous_one():
    """🔴 `uq_pi_drift_current` 가 (사고, 대상) 당 하나만 허용한다.

    내리는 것과 넣는 것이 한 트랜잭션이 아니면 두 번째 INSERT 가 UNIQUE 로 죽는다.
    """
    _, repo = fresh()
    a = make(); repo.create(a)
    first = repo.save_drift(a.accident_id, **drift_args())
    second = repo.save_drift(a.accident_id, **drift_args(elapsed_sec=1200))
    assert first != second
    assert repo.current_drift(a.accident_id)["estimate_id"] == second
    rows = repo.conn.execute(
        "SELECT is_current FROM pi_drift_estimate ORDER BY estimate_id").fetchall()
    assert [r["is_current"] for r in rows] == [0, 1]


def test_buoy_and_person_estimates_coexist():
    """부표와 사람은 leeway 가 3배 넘게 달라 타원이 따로 나온다. 둘 다 현재여야 한다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    repo.save_drift(a.accident_id, **drift_args(target="BUOY"))
    repo.save_drift(a.accident_id, **drift_args(target="PERSON"))
    assert repo.current_drift(a.accident_id, "BUOY") is not None
    assert repo.current_drift(a.accident_id, "PERSON") is not None


def test_swapped_axes_are_rejected():
    """장축이 단축보다 짧으면 둘을 바꿔 넣은 것이다. 지나가면 타원이 90도 돌아간다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    try:
        repo.save_drift(a.accident_id,
                        **drift_args(axis_major_m=50.0, axis_minor_m=180.0))
    except sqlite3.IntegrityError:
        return
    raise AssertionError("CHECK 가 막지 않았다")


def test_bearing_of_180_is_rejected():
    """🔴 축은 0~180 이고 180 은 0 과 같다. 둘 다 받으면 같은 타원을 두 가지로
    적을 수 있고, 그러면 관제 추정과 비교할 수가 없다."""
    _, repo = fresh()
    a = make(); repo.create(a)
    try:
        repo.save_drift(a.accident_id, **drift_args(axis_bearing_deg=180.0))
    except sqlite3.IntegrityError:
        return
    raise AssertionError("CHECK 가 막지 않았다")


def test_ocean_rows_dedupe_by_observation():
    """같은 관측을 30분마다 다시 받는 것이 정상이다. 행이 늘면 안 된다."""
    _, repo = fresh()
    first = repo.save_ocean(SHIP, source="KHOA", observed_at=T0,
                            fetched_at=T0, now=T0, current_speed=0.4,
                            current_dir=45.0, current_spread=0.08)
    again = repo.save_ocean(SHIP, source="KHOA", observed_at=T0,
                            fetched_at=T0 + 1800, now=T0 + 1800, current_speed=0.4)
    assert first is not None and again is None


def test_latest_ocean_respects_not_before():
    """🔴 오래된 값을 조용히 쓰느니 "해양 데이터 없음"이 낫다."""
    _, repo = fresh()
    repo.save_ocean(SHIP, source="KMA", observed_at=T0 - 7200,
                    fetched_at=T0, now=T0, wind_speed=7.5, wind_dir=270.0)
    assert repo.latest_ocean(SHIP, "KMA") is not None
    assert repo.latest_ocean(SHIP, "KMA", not_before=T0 - 3600) is None


def test_prune_ocean_removes_old_rows():
    _, repo = fresh()
    repo.save_ocean(SHIP, source="KMA", observed_at=T0 - 90000,
                    fetched_at=T0, now=T0, wind_speed=7.5)
    repo.save_ocean(SHIP, source="KMA", observed_at=T0,
                    fetched_at=T0, now=T0, wind_speed=7.5)
    assert repo.prune_ocean(SHIP, T0 - 86400) == 1
    assert repo.latest_ocean(SHIP, "KMA")["observed_at"] == T0


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn(); print("  PASS  %s" % name)
        except AssertionError as e:
            failed += 1; print("  FAIL  %s  %s" % (name, e))
        except Exception as e:
            failed += 1; print("  ERROR %s  %r" % (name, e))
    print("\n%d passed, %d failed (of %d)" % (len(fns) - failed, failed, len(fns)))
    sys.exit(1 if failed else 0)


# ── IMU 상시 로그 → 사고 구간 ────────────────────────────────────────
def test_imu_window_copies_only_rows_with_angles():
    """🔴 `pi_imu.roll` 은 NOT NULL 이다. 각도를 모르는 행을 0 으로 옮기면
    "수평이었다" 는 거짓 기록이 남는다 — 침수·전복 판정의 근거가 된다."""
    _, repo = fresh()
    a = make(status=S.REPORT); repo.create(a)

    for i in range(5):
        repo.add_imu_log(SHIP, position="HULL", now=T0 + i,
                         accel_x=0.1, accel_y=0.2, accel_z=9.7,
                         roll=1.5, pitch=-2.0)
    # 영점이 없던 구간. 각도가 없다
    for i in range(5, 8):
        repo.add_imu_log(SHIP, position="HULL", now=T0 + i,
                         accel_x=0.1, accel_y=0.2, accel_z=9.7)

    n = repo.copy_imu_window(a.accident_id, SHIP, since=T0, until=T0 + 100, now=T0 + 100)
    assert n == 5
    rows = repo.conn.execute("SELECT roll, pitch, yaw FROM pi_imu").fetchall()
    assert len(rows) == 5
    assert all(r["roll"] is not None and r["pitch"] is not None for r in rows)


def test_imu_window_is_idempotent():
    """⚠ 사고 중 매 초 부른다. UNIQUE 가 막아야 행이 안 늘어난다."""
    _, repo = fresh()
    a = make(status=S.REPORT); repo.create(a)
    for i in range(3):
        repo.add_imu_log(SHIP, position="HULL", now=T0 + i, roll=1.0, pitch=2.0)

    first = repo.copy_imu_window(a.accident_id, SHIP, since=T0, until=T0 + 9, now=T0 + 9)
    again = repo.copy_imu_window(a.accident_id, SHIP, since=T0, until=T0 + 9, now=T0 + 9)
    assert (first, again) == (3, 0)
    assert repo.conn.execute("SELECT count(*) c FROM pi_imu").fetchone()["c"] == 3


def test_imu_log_dedupes_within_one_second():
    _, repo = fresh()
    assert repo.add_imu_log(SHIP, position="HULL", now=T0, roll=1.0, pitch=2.0)
    assert repo.add_imu_log(SHIP, position="HULL", now=T0, roll=9.0, pitch=9.0) is None


def test_imu_log_prune():
    _, repo = fresh()
    repo.add_imu_log(SHIP, position="HULL", now=T0 - 3000, roll=1.0, pitch=2.0)
    repo.add_imu_log(SHIP, position="HULL", now=T0, roll=1.0, pitch=2.0)
    assert repo.prune_imu_log(SHIP, T0 - 1200) == 1

"""EC2 전송 펌프 시험. **실제 `database/pi.sql` 로 만든 DB 에 붙는다.**

여기 걸린 것들은 전부 **조용히 데이터를 잃거나 큐를 영원히 막는** 종류다.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = ROOT.parents[1] / "database" / "pi.sql"

import pytest

from floaq import provision as pv
from floaq.adapters.ec2 import Action, EdgeResult
from floaq.adapters.sqlite import SqliteRepo, connect
from floaq.contracts import AccidentStatus, AccidentType, ReportType, TriggerSource
from floaq.core.domain import Accident, StateTransition
from floaq.ids import uuid7
from floaq.sync import TABLES, SyncPump

T0 = 1_789_000_000
SHIP = uuid7()
KEY = "9f2c" * 16

OK = EdgeResult(Action.DONE, 200, inserted=1)


class FixedClock:
    def now(self) -> int:
        return T0

    def is_valid(self) -> bool:
        return True


class FakeEdge:
    """응답을 미리 넣어 두고, 무엇이 어느 경로로 갔는지 본다."""

    def __init__(self, *responses) -> None:
        self._q = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, path, payload):
        self.calls.append((path, payload))
        return self._q.pop(0) if self._q else OK

    def use_ship_key(self, k): pass


@pytest.fixture
def ctx():
    conn = connect(":memory:", schema=SCHEMA)
    reg = pv.ShipRegistration(name="시험선", registration_no="12-345", mmsi="440123456")
    pv.register_ship(conn, SHIP, KEY, "ACTIVE", reg, T0)
    repo = SqliteRepo(conn)
    yield conn, repo
    conn.close()


def pump(ctx, edge) -> SyncPump:
    conn, repo = ctx
    return SyncPump(conn, repo, edge, FixedClock(), SHIP)


def add_accident(repo, *, status=AccidentStatus.WAIT) -> str:
    aid = uuid7()
    repo.create(Accident(
        accident_id=aid, ship_id=SHIP, status=status,
        accident_type=AccidentType.MOB, trigger_source=TriggerSource.AI,
        report_type=ReportType.DISTRESS, report_dsc=110,
        accident_lat=35.05, accident_lon=129.1,
        wait_sec=30, report_due_at=T0 + 30, model_version="v1",
        created_at=T0, updated_at=T0))
    # 상태 이력은 오케스트레이터가 따로 남긴다. repo.create() 가 대신 쓰지 않는다
    repo.append_state(StateTransition(
        accident_id=aid, status=status, prev_status=None,
        reason="AI_DETECT", caused_by=None, created_at=T0))
    return aid


def add_positions(repo, n: int) -> None:
    for i in range(n):
        repo.add_position(SHIP, lat=35.05, lon=129.1, speed_kn=8.0,
                          heading_deg=84.4, accuracy_m=None,
                          measured_at=T0 + i, now=T0 + i)


def paths(edge) -> list[str]:
    return [c[0] for c in edge.calls]


def rows_of(edge, path) -> list[dict]:
    return [r for p, pl in edge.calls if p == path for r in pl["data"]]


# ── 기본 ─────────────────────────────────────────────────────────────
def test_nothing_to_send_is_quiet(ctx):
    edge = FakeEdge()
    assert pump(ctx, edge).round_once() > 0
    assert edge.calls == []


def test_sends_and_advances_cursor(ctx):
    conn, repo = ctx
    add_positions(repo, 3)
    p = pump(ctx, FakeEdge())
    p.round_once()
    assert p.sent == 3
    assert repo.pending("pi_ship_position", "position_id") == []   # 커서가 넘어갔다


def test_envelope_shape(ctx):
    """`api.json` 의 IPiEnvelope 다. data 는 항상 배열."""
    conn, repo = ctx
    add_positions(repo, 2)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    _, payload = edge.calls[0]
    assert set(payload) == {"request_id", "v", "ts", "data"}
    assert payload["v"] == 1 and payload["ts"] == T0
    assert isinstance(payload["data"], list) and len(payload["data"]) == 2


def test_only_contract_columns_go(ctx):
    """🔴 `updated_at`·INTEGER PK 는 보내지 않는다. Pi 안에서만 뜻이 있다."""
    conn, repo = ctx
    add_positions(repo, 1)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    row = rows_of(edge, "/api/pi/ship-positions")[0]
    assert set(row) == {"ship_id", "lat", "lon", "speed_kn", "heading_deg",
                        "accuracy_m", "created_at"}
    assert "updated_at" not in row and "position_id" not in row


# ── 커서 ─────────────────────────────────────────────────────────────
def test_cursor_does_not_move_without_2xx(ctx):
    """🔴 2xx 전에 커서를 옮기면 서버가 못 받은 행이 영영 재전송에서 빠진다."""
    conn, repo = ctx
    add_positions(repo, 3)
    edge = FakeEdge(EdgeResult(Action.RETRY, 0))
    p = pump(ctx, edge)
    p.round_once()
    assert p.sent == 0
    assert len(repo.pending("pi_ship_position", "position_id")) == 3   # 그대로 남는다


def test_retry_resends_same_rows(ctx):
    conn, repo = ctx
    add_positions(repo, 2)
    edge = FakeEdge(EdgeResult(Action.RETRY, 0), OK)
    p = pump(ctx, edge)
    p.round_once()
    p.round_once()
    assert p.sent == 2
    assert len(rows_of(edge, "/api/pi/ship-positions")) == 4     # 같은 2행을 두 번


def test_drop_advances_so_queue_is_not_blocked(ctx):
    """🔴 형식 오류를 붙들고 있으면 그 배치가 큐를 영원히 막는다 — 뒤의 사고 기록까지."""
    conn, repo = ctx
    add_positions(repo, 2)
    edge = FakeEdge(EdgeResult(Action.DROP, 400, code="COMMON_INVALID_INPUT"))
    p = pump(ctx, edge)
    p.round_once()
    assert repo.pending("pi_ship_position", "position_id") == []   # 넘어갔다


def created(edge, call: int) -> list[int]:
    """그 호출에 실린 선박 위치의 `created_at`. 어느 행이 갔는지 본다."""
    return [r["created_at"] for r in edge.calls[call][1]["data"]]


def test_drop_with_failed_index_keeps_the_good_rows(ctx):
    """🔴 나쁜 행 하나 때문에 배치를 통째로 버리면 좋은 행까지 조용히 사라진다.
    서버가 `failed[].index` 를 주면 그 행만 버리고 나머지를 다시 보낸다."""
    conn, repo = ctx
    add_positions(repo, 3)
    edge = FakeEdge(EdgeResult(Action.DROP, 400, code="COMMON_INVALID_INPUT",
                               failed=({"index": 1, "id": None, "code": "X"},)))
    p = pump(ctx, edge)
    p.round_once()
    assert created(edge, 1) == [T0, T0 + 2]          # 가운데만 뺐다
    assert p.sent == 2
    assert repo.pending("pi_ship_position", "position_id") == []


def test_drop_without_failed_narrows_down_to_the_bad_row(ctx):
    """서버가 어느 행인지 안 알려주면(JSON 형식 오류) 반으로 나눠 좁힌다."""
    conn, repo = ctx
    add_positions(repo, 4)
    bad = EdgeResult(Action.DROP, 400, code="COMMON_INVALID_INPUT")
    #          전체  [0,1]  [2,3]  [2]  [3]
    edge = FakeEdge(bad, OK, bad, OK, bad)
    p = pump(ctx, edge)
    p.round_once()
    assert [created(edge, i) for i in range(1, 5)] == [
        [T0, T0 + 1], [T0 + 2, T0 + 3], [T0 + 2], [T0 + 3]]
    assert p.sent == 3                                # 나쁜 행 하나만 버렸다
    assert repo.pending("pi_ship_position", "position_id") == []


def test_retry_while_salvaging_keeps_what_was_not_sent(ctx):
    """🔴 좁히는 도중 서버가 죽으면 **앞에서 끝난 데까지만** 커서를 옮긴다.
    못 보낸 행은 다음 회차에 다시 간다."""
    conn, repo = ctx
    add_positions(repo, 4)
    bad = EdgeResult(Action.DROP, 400, code="COMMON_INVALID_INPUT")
    edge = FakeEdge(bad, OK, EdgeResult(Action.RETRY, 0))
    p = pump(ctx, edge)
    p.round_once()
    left = repo.pending("pi_ship_position", "position_id")
    assert [r["created_at"] for r in left] == [T0 + 2, T0 + 3]
    assert p.sent == 2


def test_defer_keeps_rows_for_next_round(ctx):
    """404 ACCIDENT_NOT_FOUND 는 순서 문제다. 다음 회차에 사고가 먼저 올라간다."""
    conn, repo = ctx
    add_positions(repo, 1)
    edge = FakeEdge(EdgeResult(Action.DEFER, 404, code="ACCIDENT_NOT_FOUND"))
    p = pump(ctx, edge)
    p.round_once()
    assert len(repo.pending("pi_ship_position", "position_id")) == 1


def test_halt_stops_the_whole_round(ctx):
    """키 문제는 모든 테이블에 같이 걸린다. 한 번 보고 멈춘다."""
    conn, repo = ctx
    add_positions(repo, 1)
    add_accident(repo)
    edge = FakeEdge(EdgeResult(Action.HALT, 401, code="EDGE_UNAUTHORIZED"))
    p = pump(ctx, edge)
    p.round_once()
    assert len(edge.calls) == 1        # 첫 테이블에서 끊는다
    assert p.halted is True


# ── 순서 ─────────────────────────────────────────────────────────────
def test_accident_goes_before_its_children(ctx):
    """🔴 FK 순서다. 사고 없이 자식을 먼저 올리면 서버에서 배치가 통째로 롤백된다."""
    conn, repo = ctx
    add_accident(repo)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    order = paths(edge)
    assert order.index("/api/pi/accidents") < order.index("/api/pi/accident-states")


def test_reports_go_last(ctx):
    """신고는 사고 행이 있어야 붙는다."""
    names = [t.path for t in TABLES]
    assert names[-1] == "/api/pi/reports"
    assert names.index("/api/pi/accidents") < names.index("/api/pi/reports")


# ── 승인 ─────────────────────────────────────────────────────────────
def test_nothing_sent_before_approval(ctx):
    """🔴 WAIT 인 선박의 데이터는 서버가 거절한다. 보내봐야 403 만 쌓인다."""
    conn, repo = ctx
    pv.set_status(conn, SHIP, "WAIT", T0)
    add_positions(repo, 5)
    edge = FakeEdge()
    p = pump(ctx, edge)
    assert p.round_once() > 0
    assert edge.calls == []
    assert len(repo.pending("pi_ship_position", "position_id")) == 5   # 쥐고 있다


def test_rejected_also_sends_nothing(ctx):
    conn, repo = ctx
    pv.set_status(conn, SHIP, "REJECTED", T0)
    add_positions(repo, 1)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    assert edge.calls == []


# ── 타입 ─────────────────────────────────────────────────────────────
def test_sqlite_ints_become_booleans(ctx):
    """🔴 SQLite 에 boolean 이 없어 0/1 로 들어 있다. 그대로 보내면 서버 검증에서 400."""
    conn, repo = ctx
    aid = add_accident(repo)
    conn.execute(
        "INSERT INTO pi_buoy (accident_id, seq, lat, lon, is_pressed, rssi,"
        " created_at, received_at, updated_at) VALUES (?,1,35.0,129.0,1,-70,?,?,?)",
        (aid, T0, T0, T0))
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    row = rows_of(edge, "/api/pi/buoys")[0]
    assert row["is_pressed"] is True          # 1 이 아니라 True


def test_null_stays_null(ctx):
    """None 에 cast 를 걸면 False 가 된다. 그건 '값 없음'과 다른 뜻이다."""
    conn, repo = ctx
    repo.add_position(SHIP, lat=35.0, lon=129.0, speed_kn=None, heading_deg=None,
                      accuracy_m=None, measured_at=T0, now=T0)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    row = rows_of(edge, "/api/pi/ship-positions")[0]
    assert row["speed_kn"] is None and row["accuracy_m"] is None


# ── 진단 ─────────────────────────────────────────────────────────────
def test_backlog_counts_unsent(ctx):
    conn, repo = ctx
    add_positions(repo, 4)
    p = pump(ctx, FakeEdge())
    assert p.backlog()["pi_ship_position"] == 4
    p.round_once()
    assert "pi_ship_position" not in p.backlog()


def test_table_columns_are_unique_and_nonempty():
    """오타로 컬럼이 빠지면 그 값은 영영 안 간다. 집합으로 한 번 훑는다."""
    for t in TABLES:
        assert t.columns, t.name
        assert len(set(t.columns)) == len(t.columns), t.name
        assert "updated_at" not in t.columns, t.name


# ── 스키마 드리프트 ──────────────────────────────────────────────────
#
# 🔴 **컬럼을 새로 만들고 sync 에 안 넣으면 아무 일도 안 일어난다.** 오류도
#    경고도 없고, 그 값만 관제에 영영 안 간다. 실제로 여섯 개가 그렇게 빠져
#    있었다 (2026-09-22): `rescued_at` · `closed_at` · `model_version` 과
#    `pi_accident_state` 의 `prev_status` · `reason` · `caused_by`.
#    앞의 둘 때문에 관제가 "언제 끝났는지" 를 몰랐고, 뒤의 셋 때문에
#    타임라인이 "왜 그렇게 됐는지" 를 통째로 못 받았다.
#
# 그래서 **안 보내는 컬럼은 여기 이유와 함께 적는다.** 적지 않은 컬럼이
# 스키마에 생기면 이 시험이 깨진다 — 그때 보낼지 말지를 정하면 된다.
SKIP_REASON = {
    # 커서 자체다. 서버는 자기 시각을 쓴다
    ("*", "updated_at"): "sync 커서용. 보낼 값이 아니다",
    # Pi 안의 INTEGER 라 서버에서 뜻이 없다 (api.md §4.3)
    ("pi_comm_loss", "last_buoy_log_id"): "Pi 로컬 id. 서버에 대응 행이 없다",
    ("pi_drift_estimate", "comm_loss_id"): "Pi 로컬 id. 서버 DTO 도 안 받는다",
}


def test_every_synced_column_is_accounted_for():
    """보내지도 않고 이유도 안 적은 컬럼이 있으면 실패한다.

    ⚠ 이 시험이 깨졌다면 스키마에 컬럼이 늘었다는 뜻이다. **둘 중 하나를 해라** —
      `TABLES` 에 넣어 보내거나, 위 `SKIP_REASON` 에 왜 안 보내는지 적거나.
      그냥 지나가면 그 값은 관제에 영영 안 간다.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    missing = []
    for t in TABLES:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t.name})")]
        assert cols, f"{t.name} 테이블이 pi.sql 에 없다"
        for c in cols:
            if c in t.columns or c == t.pk:
                continue
            if ("*", c) in SKIP_REASON or (t.name, c) in SKIP_REASON:
                continue
            missing.append(f"{t.name}.{c}")
    assert not missing, (
        "sync 에 안 실리고 이유도 안 적힌 컬럼: " + ", ".join(missing))


def test_sync_only_sends_columns_that_exist():
    """🔴 반대 방향. 오타 난 컬럼명은 SELECT 에서 죽는다 — 전송이 통째로 멈춘다."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    for t in TABLES:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t.name})")}
        unknown = [c for c in t.columns if c not in cols]
        assert not unknown, f"{t.name} 에 없는 컬럼을 보내려 한다: {unknown}"

"""선박 등록·승인 시험. **실제 `database/pi.sql` 로 만든 DB 에 붙는다.**

여기 걸린 것들은 전부 조용히 실패하는 종류다. 특히 `ship_key` — 서버가 한 번만 주고
해시로만 보관해서, 놓치면 그 배는 영영 못 붙는데 로그에도 안 남는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = ROOT.parents[1] / "database" / "pi.sql"

import pytest

from floaq import provision as pv
from floaq.adapters.ec2 import Action, EdgeResult
from floaq.adapters.sqlite import connect
from floaq.enroll import Enroller

T0 = 1_789_000_000
KEY = "9f2c" * 16          # 64자리


class FixedClock:
    def now(self) -> int:
        return T0

    def is_valid(self) -> bool:
        return True


class FakeEdge:
    """`EdgeClient` 대역. 어느 키가 실려 있는지도 같이 본다."""

    def __init__(self, register=None, status=None) -> None:
        self._register = register or []
        self._status = status or []
        self.ship_key: str | None = None
        self.register_calls: list = []
        self.status_calls: list[str] = []

    def register_ship(self, reg):
        self.register_calls.append(reg)
        return self._pop(self._register, (None, EdgeResult(Action.RETRY, 0)))

    def ship_status(self, ship_id):
        self.status_calls.append(ship_id)
        return self._pop(self._status, (None, EdgeResult(Action.RETRY, 0)))

    def use_ship_key(self, ship_key: str) -> None:
        self.ship_key = ship_key

    @staticmethod
    def _pop(q, default):
        return q.pop(0) if q else default


OK = EdgeResult(Action.DONE, 200)


@pytest.fixture
def ctx():
    conn = connect(":memory:", schema=SCHEMA)
    pending = pv.PendingShip(":memory-not-used:")
    yield conn, pending
    conn.close()


def reg() -> pv.ShipRegistration:
    return pv.ShipRegistration(name="제7금양호", registration_no="1234567-6261102",
                               mmsi="440123456")


def make(conn, pending, edge, on_ready=None) -> Enroller:
    return Enroller(conn, edge, pending, FixedClock(), on_ready=on_ready)


class MemPending(pv.PendingShip):
    """파일 대신 메모리. 등록 로직만 본다."""

    def __init__(self, reg=None) -> None:
        self._reg = reg
        self.cleared = False
        self.path = "(메모리)"        # 대기 로그가 경로를 찍는다

    def read(self):
        return self._reg

    def write(self, reg) -> None:
        self._reg = reg

    def clear(self) -> None:
        self._reg = None
        self.cleared = True


# ── 등록 ─────────────────────────────────────────────────────────────
def test_waits_when_kiosk_has_not_registered(ctx):
    """키오스크가 아직 안 넣었다. 오류가 아니라 대기다 — 서버를 부르지 않는다.

    ⚠ 완전히 조용하지는 않다. 첫 회차에 한 번 로그를 남긴다 — 그게 없으면
      "신청했는데 안 올라간다" 를 진단할 단서가 없다(실제 Pi 에서 밟았다).
    """
    conn, _ = ctx
    edge = FakeEdge()
    e = make(conn, MemPending(None), edge)
    assert e.step() > 0
    assert e.step() > 0            # 두 번째도 조용히 대기
    assert edge.register_calls == []


def test_registers_and_persists_key_in_one_go(ctx):
    """🔴 `ship_key` 는 등록 응답에만 온다. 받는 즉시 DB 에 있어야 한다."""
    conn, _ = ctx
    edge = FakeEdge(register=[(("SID-1", KEY, "WAIT"), OK)])
    make(conn, MemPending(reg()), edge).step()

    assert pv.registered_ship(conn)[0] == "SID-1"
    assert pv.credential(conn, "SID-1") == (KEY, "WAIT")


def test_switches_to_ship_key_after_registering(ctx):
    """등록 키를 버리고 선박 키로 간다. 한 요청에 키는 하나다."""
    conn, _ = ctx
    edge = FakeEdge(register=[(("SID-1", KEY, "WAIT"), OK)])
    make(conn, MemPending(reg()), edge).step()
    assert edge.ship_key == KEY


def test_pending_cleared_only_after_success(ctx):
    """🔴 실패했는데 대기값을 지우면 그 배는 등록 기회를 영영 잃는다."""
    conn, _ = ctx
    pending = MemPending(reg())
    make(conn, pending, FakeEdge(register=[(None, EdgeResult(Action.RETRY, 0))])).step()
    assert pending.read() is not None      # 아직 남아 있다

    make(conn, pending, FakeEdge(register=[(("SID-1", KEY, "WAIT"), OK)])).step()
    assert pending.read() is None


def test_does_not_register_twice(ctx):
    """이미 등록된 배가 있으면 신청하지 않는다. `ship_id` 가 바뀌면 사고가 고아가 된다."""
    conn, _ = ctx
    pv.register_ship(conn, "SID-1", KEY, "ACTIVE", reg(), T0)
    edge = FakeEdge()
    make(conn, MemPending(reg()), edge).step()
    assert edge.register_calls == []


# ── 승인 ─────────────────────────────────────────────────────────────
def test_polls_until_active(ctx):
    """WAIT 동안은 폴링만 한다. 승인되면 상태를 DB 에 반영한다."""
    conn, _ = ctx
    pv.register_ship(conn, "SID-1", KEY, "WAIT", reg(), T0)
    edge = FakeEdge(status=[("WAIT", OK), ("ACTIVE", OK)])
    e = make(conn, MemPending(), edge)

    assert e.step() > 0
    assert pv.is_approved(conn, "SID-1") is False

    assert e.step() == 0.0                 # ACTIVE 면 루프가 끝난다
    assert pv.is_approved(conn, "SID-1") is True


def test_active_needs_no_polling(ctx):
    """이미 ACTIVE 면 서버를 부르지 않는다."""
    conn, _ = ctx
    pv.register_ship(conn, "SID-1", KEY, "ACTIVE", reg(), T0)
    edge = FakeEdge()
    assert make(conn, MemPending(), edge).step() == 0.0
    assert edge.status_calls == []


def test_rejected_stops_retrying(ctx):
    """반려는 자동 재시도로 안 풀린다. 사람이 고쳐서 다시 신청해야 한다."""
    conn, _ = ctx
    pv.register_ship(conn, "SID-1", KEY, "WAIT", reg(), T0)
    e = make(conn, MemPending(), FakeEdge(status=[("REJECTED", OK)]))
    assert e.step() == 0.0
    assert pv.credential(conn, "SID-1")[1] == "REJECTED"


def test_ship_row_without_key_stops(ctx):
    """🔴 pi_ship 은 있는데 키가 없다. 서버는 같은 키를 다시 주지 않는다 — 사람이 풀어야 한다."""
    conn, _ = ctx
    conn.execute(
        "INSERT INTO pi_ship (ship_id, name, registration_no, mmsi, has_buoy,"
        " is_deleted, created_at, updated_at) VALUES ('SID-1','x','r','440123456',1,0,?,?)",
        (T0, T0))
    assert make(conn, MemPending(), FakeEdge()).step() == 0.0


def test_ready_callback_fires_once_on_active(ctx):
    conn, _ = ctx
    seen: list[str] = []
    edge = FakeEdge(register=[(("SID-1", KEY, "ACTIVE"), OK)])
    make(conn, MemPending(reg()), edge, on_ready=seen.append).step()
    assert seen == ["SID-1"]


def test_network_failure_keeps_going(ctx):
    """연결 실패는 정상 경로다. 다음 주기에 다시 시도한다."""
    conn, _ = ctx
    pv.register_ship(conn, "SID-1", KEY, "WAIT", reg(), T0)
    e = make(conn, MemPending(), FakeEdge(status=[(None, EdgeResult(Action.RETRY, 0))]))
    assert e.step() > 0
    assert pv.credential(conn, "SID-1")[1] == "WAIT"     # 상태를 망가뜨리지 않는다


def test_pending_path_keeps_db_name():
    """🔴 `with_suffix` 는 `.db` 를 바꿔치기한다.

    `floaq.db` -> `floaq.pending-ship.json` 이 되어, 문서와 로그가 가리키는 이름과
    실제 파일이 어긋난다. DB 가 둘일 때 대기 파일이 겹칠 수도 있다.
    """
    from pathlib import Path
    assert Path("floaq.db").with_suffix(".pending-ship.json").name \
        == "floaq.pending-ship.json"                      # 이게 옛 동작
    assert Path(str("floaq.db") + ".pending-ship.json").name \
        == "floaq.db.pending-ship.json"                   # 지금 동작

"""사고 산출물 타르볼 업로드 시험. **실제 `database/pi.sql` 로 만든 DB 에 붙는다.**

여기 걸린 것들은 전부 조용히 실패하는 종류다. 사진이 안 올라가도 사고 기록은 멀쩡해서
관제 웹에서 "사진 없는 사고"로만 보인다 — 로그를 안 보면 모른다.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCHEMA = ROOT.parents[1] / "database" / "pi.sql"

import pytest

from floaq import archive as ar
from floaq.adapters.ec2 import Action, EdgeResult
from floaq.adapters.sqlite import SqliteRepo, connect
from floaq.contracts import AccidentStatus as S
from floaq.contracts import AccidentType, ReportType, TriggerSource
from floaq.core.domain import Accident
from floaq.web.files import FileStore
from floaq.ids import uuid7

T0 = 1_757_000_000
SHIP = uuid7()
KEY = "9f2c" * 16


class FixedClock:
    def now(self) -> int:
        return T0

    def is_valid(self) -> bool:
        return True


class FakeEdge:
    """`EdgeClient` 대역. 보낸 타르볼을 그대로 들고 있는다."""

    def __init__(self, results=None) -> None:
        self._results = list(results or [])
        self.calls: list[tuple[str, bytes, str, int]] = []

    def post_archive(self, accident_id, tarball, sha256, created_at):
        self.calls.append((accident_id, tarball, sha256, created_at))
        if self._results:
            return self._results.pop(0)
        return EdgeResult(action=Action.RETRY, status=0)

    @property
    def last_tar(self) -> tarfile.TarFile:
        return tarfile.open(fileobj=io.BytesIO(gzip.decompress(self.calls[-1][1])))

    def manifest(self) -> dict:
        t = self.last_tar
        return json.loads(t.extractfile(ar.MANIFEST).read().decode("utf-8"))


def stored(accident_id, file_type, sequence_no, key, *, duplicated=False) -> dict:
    return {"accident_id": accident_id, "file_type": file_type,
            "sequence_no": sequence_no, "camera": "L", "object_key": key,
            "bytes": 10, "etag": None, "duplicated": duplicated,
            "uploaded_at": T0}


def ok(files) -> EdgeResult:
    data = {"received": len(files), "stored": len(files), "duplicated": 0,
            "failed": 0, "files": files, "videos": []}
    return EdgeResult(action=Action.DONE, status=200, data=data)


@pytest.fixture
def ctx(tmp_path):
    conn = connect(":memory:", schema=SCHEMA)
    conn.execute(
        "INSERT INTO pi_ship VALUES (?,'test','r-1','440123456',1,0,?,?,NULL)",
        (SHIP, T0, T0))
    conn.execute(
        "INSERT INTO pi_credential (ship_id, ship_key, status, issued_at, updated_at)"
        " VALUES (?,?, 'ACTIVE', ?, ?)", (SHIP, KEY, T0, T0))
    repo = SqliteRepo(conn)
    acc = Accident(
        accident_id=uuid7(), ship_id=SHIP, status=S.DETECT,
        accident_type=AccidentType.MOB, trigger_source=TriggerSource.AI,
        report_type=ReportType.DISTRESS, report_dsc=110,
        accident_lat=35.1, accident_lon=129.0, wait_sec=30, report_due_at=None,
        model_version="v1", created_at=T0, updated_at=T0)
    repo.create(acc)
    yield conn, repo, acc.accident_id, tmp_path
    conn.close()


def add(repo, tmp_path, accident_id, file_type, seq, *, body=b"\xff\xd8jpeg"):
    """🔴 **실제 저장 규약을 쓴다.** `file_path` 는 `FileStore` 루트 기준 상대경로다.

    시험에서 절대경로를 넣으면 "상대경로를 현재 작업 디렉터리에서 연다" 는 버그를
    못 잡는다 — 실제로 그 상태로 Pi 에서 전부 FileNotFoundError 가 났다.
    """
    store = FileStore(tmp_path)
    rel, n = store.save(accident_id, file_type, seq, body)
    return repo.add_file(accident_id=accident_id, file_type=file_type,
                         sequence_no=seq, file_path=rel, camera="L",
                         size_bytes=n, now=T0)


# ── 대기열 ───────────────────────────────────────────────────────────
def test_queue_is_object_key_is_null(ctx):
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    add(repo, tmp, aid, "BEFORE", 2)
    assert repo.pending_upload_accidents() == [aid]
    assert len(repo.pending_files_of(aid)) == 2

    for r in repo.pending_files_of(aid):
        repo.mark_uploaded(r["file_id"], "k/" + str(r["file_id"]), T0)
    assert repo.pending_upload_accidents() == []


def test_snapshot_slot_lookup_uses_is_not_equals(ctx):
    """🔴 `DETECT_SNAPSHOT` 은 `sequence_no` 가 NULL 이다.

    `= NULL` 로 찾으면 한 행도 안 잡혀 스냅샷만 영영 안 올라간다.
    """
    _, repo, aid, tmp = ctx
    fid = add(repo, tmp, aid, "DETECT_SNAPSHOT", None)
    row = repo.file_by_slot(aid, "DETECT_SNAPSHOT", None)
    assert row is not None and row["file_id"] == fid


# ── 타르볼 ───────────────────────────────────────────────────────────
def test_tarball_has_manifest_and_files(ctx):
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    add(repo, tmp, aid, "DETECT_SNAPSHOT", None)

    blob, packed = ar.build_tarball(aid, repo.pending_files_of(aid), FileStore(tmp), now=T0)
    assert len(packed) == 2

    t = tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)))
    names = t.getnames()
    assert ar.MANIFEST in names
    assert "BEFORE/00001.jpg" in names
    assert "DETECT_SNAPSHOT/snapshot.jpg" in names

    m = json.loads(t.extractfile(ar.MANIFEST).read().decode("utf-8"))
    assert m["accident_id"] == aid
    assert m["version"] == ar.MANIFEST_VERSION
    assert {f["file_type"] for f in m["files"]} == {"BEFORE", "DETECT_SNAPSHOT"}


def test_member_names_are_regenerated_not_copied(ctx):
    """🔴 타르볼 안 경로를 `file_path` 에서 베끼면 `..` 나 절대경로가 들어갈 수 있다.

    서버가 푸는 쪽에서 경로 탈출이 된다. `file_type/순번.확장자` 로 다시 만든다.
    """
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "AFTER", 3)
    blob, _ = ar.build_tarball(aid, repo.pending_files_of(aid), FileStore(tmp), now=T0)
    names = tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob))).getnames()
    assert "AFTER/00003.jpg" in names
    for n in names:
        assert not n.startswith("/")
        assert ".." not in n


def test_store_rejects_paths_outside_the_root(ctx):
    """DB 가 손상돼 저장소 밖을 가리켜도 읽지 않는다."""
    from floaq.web.files import BadPath
    _, _, _, tmp = ctx
    with pytest.raises(BadPath):
        FileStore(tmp).resolve("../../etc/passwd")


def test_file_path_is_relative_to_the_store_root(ctx):
    """🔴 DB 에 든 것은 `accidents/<id>/<type>/0001.jpg` 형태의 **상대경로**다.

    현재 작업 디렉터리에서 열면 전부 FileNotFoundError 다 — Pi 에서 실제로 밟았다.
    """
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    rel = repo.file_by_slot(aid, "BEFORE", 1)["file_path"]
    assert rel == f"accidents/{aid}/BEFORE/0001.jpg"
    assert not Path(rel).is_absolute()
    # 루트가 틀리면 한 장도 못 읽는다
    with pytest.raises(ar.ArchiveError):
        ar.build_tarball(aid, repo.pending_files_of(aid),
                         FileStore(tmp / "다른곳"), now=T0)


def test_object_key_convention_matches_the_stored_path(ctx):
    """`FileStore.relative()` 문자열을 R2 객체 키로 그대로 쓴다 (`web/files.py`)."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "DETECT_SNAPSHOT", None)
    assert repo.file_by_slot(aid, "DETECT_SNAPSHOT", None)["file_path"] \
        == f"accidents/{aid}/DETECT_SNAPSHOT/snapshot.jpg"


def test_same_content_gives_the_same_digest(ctx):
    """🔴 gzip 은 기본으로 mtime 을 넣는다. 그러면 같은 내용이 매번 다른 바이트가 되고,
    재전송을 서버가 중복으로 못 알아본다.
    """
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    rows = repo.pending_files_of(aid)
    a, _ = ar.build_tarball(aid, rows, FileStore(tmp), now=T0)
    b, _ = ar.build_tarball(aid, rows, FileStore(tmp), now=T0)
    assert a == b


def test_missing_file_is_skipped_not_fatal(ctx):
    """SD 카드에서 지워졌을 수 있다. 나머지는 올라가야 한다."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    gone = add(repo, tmp, aid, "BEFORE", 2)
    FileStore(tmp).resolve(repo.file_by_slot(aid, "BEFORE", 2)["file_path"]).unlink()

    _, packed = ar.build_tarball(aid, repo.pending_files_of(aid), FileStore(tmp), now=T0)
    assert [r["file_id"] for r in packed] != [gone]
    assert len(packed) == 1


def test_all_files_missing_raises(ctx):
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    FileStore(tmp).resolve(repo.file_by_slot(aid, "BEFORE", 1)["file_path"]).unlink()
    with pytest.raises(ar.ArchiveError):
        ar.build_tarball(aid, repo.pending_files_of(aid), FileStore(tmp), now=T0)


def test_size_cap_splits_but_always_packs_one(ctx):
    """상한이 한 장보다 작아도 최소 한 장은 담는다 — 아니면 영원히 진도가 안 나간다."""
    _, repo, aid, tmp = ctx
    for i in range(1, 4):
        add(repo, tmp, aid, "BEFORE", i, body=b"x" * 1000)
    _, packed = ar.build_tarball(aid, repo.pending_files_of(aid), FileStore(tmp), now=T0,
                             max_bytes=1)
    assert len(packed) == 1


# ── 펌프 ─────────────────────────────────────────────────────────────
def pump(ctx, edge):
    conn, repo, aid, tmp = ctx
    return ar.ArchivePump(conn, repo, edge, FixedClock(), SHIP, FileStore(tmp))


def test_uploads_and_writes_back_object_keys(ctx):
    conn, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    add(repo, tmp, aid, "DETECT_SNAPSHOT", None)

    edge = FakeEdge([ok([stored(aid, "BEFORE", 1, "r2/a.jpg"),
                         stored(aid, "DETECT_SNAPSHOT", None, "r2/s.jpg")])])
    pump(ctx, edge).round_once()

    assert repo.pending_upload_accidents() == []
    assert repo.file_by_slot(aid, "BEFORE", 1)["object_key"] == "r2/a.jpg"
    assert repo.file_by_slot(aid, "DETECT_SNAPSHOT", None)["object_key"] == "r2/s.jpg"


def test_digest_matches_the_bytes_sent(ctx):
    import hashlib
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    edge = FakeEdge([ok([stored(aid, "BEFORE", 1, "r2/a.jpg")])])
    pump(ctx, edge).round_once()

    _, blob, digest, _ = edge.calls[0]
    assert digest == hashlib.sha256(blob).hexdigest()
    assert len(digest) == 64


def test_key_is_written_only_after_the_server_answers(ctx):
    """🔴 먼저 박으면 R2 에 없는 파일이 "올라갔다"가 된다. 로컬을 지우면 영영 사라진다."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    pump(ctx, FakeEdge([EdgeResult(action=Action.RETRY, status=0)])).round_once()
    assert repo.file_by_slot(aid, "BEFORE", 1)["object_key"] is None
    assert repo.pending_upload_accidents() == [aid]


def test_duplicated_still_clears_the_queue(ctx):
    """이미 R2 에 있다는 뜻이다. 안 빼면 같은 것을 영원히 올린다."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    edge = FakeEdge([ok([stored(aid, "BEFORE", 1, "r2/a.jpg", duplicated=True)])])
    pump(ctx, edge).round_once()
    assert repo.pending_upload_accidents() == []


def test_2xx_without_keys_does_not_loop_forever(ctx):
    """🔴 2xx 인데 object_key 가 없으면 다시 보내도 같은 응답이다. 무한 루프가 된다."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    edge = FakeEdge([ok([]), ok([]), ok([])])
    p = pump(ctx, edge)
    for _ in range(3):
        p.round_once()
    assert len(edge.calls) == 1              # 한 번 해보고 포기한다
    assert aid in p.status()["skipped"]


def test_413_shrinks_instead_of_dropping(ctx):
    """🔴 본문이 크다고 사진을 버리면 안 된다. 잘라서 다시 보낸다."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    p = pump(ctx, FakeEdge([EdgeResult(action=Action.DROP, status=413)]))
    before = p.status()["max_bytes"]
    p.round_once()
    assert p.status()["max_bytes"] == before // 2
    assert repo.pending_upload_accidents() == [aid]     # 큐에 남아 있다


def test_waits_until_the_ship_is_approved(ctx):
    """승인 전에는 서버가 전부 거절한다. 보내봐야 좁은 상향 대역만 태운다."""
    conn, repo, aid, tmp = ctx
    conn.execute("UPDATE pi_credential SET status = 'WAIT' WHERE ship_id = ?", (SHIP,))
    add(repo, tmp, aid, "BEFORE", 1)
    edge = FakeEdge()
    pump(ctx, edge).round_once()
    assert edge.calls == []


def test_nothing_to_do_is_not_an_error(ctx):
    edge = FakeEdge()
    assert pump(ctx, edge).round_once() == ar.IDLE_SEC
    assert edge.calls == []


def test_reupload_after_jetson_resends(ctx):
    """Jetson 이 같은 자리에 다시 올리면 `object_key` 가 NULL 로 돌아간다 (내용이 바뀌었을 수 있다)."""
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    pump(ctx, FakeEdge([ok([stored(aid, "BEFORE", 1, "r2/a.jpg")])])).round_once()
    assert repo.pending_upload_accidents() == []

    add(repo, tmp, aid, "BEFORE", 1, body=b"\xff\xd8new")
    assert repo.pending_upload_accidents() == [aid]


# ── 백오프 ───────────────────────────────────────────────────────────
def test_backoff_doubles_on_repeated_failure(ctx):
    """🔴 고정 간격이면 성공할 수 없는 일을 영원히 같은 값으로 반복한다.

    서버가 500 을 주는 동안 큐가 안 비므로, 매 회차 쌓인 프레임을 전부 다시
    읽어 gzip 한다. 프레임이 늘수록 그 작업도 커진다.
    """
    p = pump(ctx, FakeEdge())
    waits = [p._backoff() for _ in range(5)]
    assert waits == [min(ar.BACKOFF_MAX_SEC, ar.BACKOFF_SEC * 2 ** i)
                     for i in range(5)]
    assert waits[0] == ar.BACKOFF_SEC
    assert waits[1] == ar.BACKOFF_SEC * 2


def test_backoff_is_capped(ctx):
    p = pump(ctx, FakeEdge())
    for _ in range(30):
        w = p._backoff()
    assert w == ar.BACKOFF_MAX_SEC


def test_success_resets_the_backoff(ctx):
    _, repo, aid, tmp = ctx
    add(repo, tmp, aid, "BEFORE", 1)
    p = pump(ctx, FakeEdge([EdgeResult(action=Action.RETRY, status=500),
                            ok([stored(aid, "BEFORE", 1, "r2/a.jpg")])]))
    p.round_once()
    assert p.status()["fails"] == 1
    p.round_once()
    assert p.status()["fails"] == 0

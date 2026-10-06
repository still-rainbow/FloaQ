"""선내 HTTP 서버 시험. **실제 SQLite 와 디스크를 쓴다.**

경로 주입과 멱등성을 여기서 잡는다. 둘 다 조용히 틀리는 종류라 시험이 없으면
시연 전까지 모른다.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from floaq.adapters.sqlite import SqliteRepo, connect
from floaq.core.domain import Accident, LaunchRecord, StateTransition
from floaq.contracts import AccidentStatus, AccidentType, ReportType, TriggerSource
from floaq.ids import uuid7
from floaq.web.app import MAX_UPLOAD_BYTES, create_app
from floaq.web.files import BadPath, FileStore

SCHEMA = Path(__file__).resolve().parents[3] / "database" / "pi.sql"
T0 = 1_757_000_000
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"


class FixedClock:
    def now(self) -> int:
        return T0

    def is_valid(self) -> bool:
        return True


@pytest.fixture
def ctx(tmp_path):
    conn = connect(str(tmp_path / "t.db"), schema=SCHEMA)
    repo = SqliteRepo(conn)
    ship_id, detection_id = uuid7(), uuid7()
    conn.execute(
        "INSERT INTO pi_ship (ship_id, name, has_buoy, is_deleted, created_at, updated_at)"
        " VALUES (?,?,0,0,?,?)", (ship_id, "시험선", T0, T0))

    accident_id = uuid7()
    repo.create(Accident(
        accident_id=accident_id, ship_id=ship_id, accident_lat=35.1, accident_lon=129.0,
        accident_type=AccidentType.MOB, trigger_source=TriggerSource.AI,
        report_type=ReportType.DISTRESS, report_dsc=110, status=AccidentStatus.WAIT,
        wait_sec=30, report_due_at=T0 + 30, model_version="v1",
        rescued_at=None, closed_at=None, created_at=T0, updated_at=T0))
    # detection_id -> accident_id 를 잇는 건 pi_launch 다
    repo.update(LaunchRecord(
        accident_id=accident_id, detection_id=detection_id, result="SUCCESS",
        fail_reason=None, launch_lat=35.1, launch_lon=129.0,
        target_lat=35.11, target_lon=129.01, horizontal_angle=12.5,
        vertical_angle=20.0, confidence_score=0.93, created_at=T0))

    app = create_app(ship_id=ship_id, repo=repo, clock=FixedClock(),
                     store_root=tmp_path / "files")
    yield TestClient(app), repo, accident_id, detection_id
    conn.close()


def put(client, detection_id, seq, body=JPEG, ftype="BEFORE", **kw):
    return client.put(f"/api/detections/{detection_id}/files/{ftype}/{seq}",
                      content=body, headers={"Content-Type": "image/jpeg", **kw})


# ── 기본 ─────────────────────────────────────────────────────────────
def test_health(ctx):
    client, _, _, _ = ctx
    assert client.get("/health").json()["ok"] is True


def test_contract_is_generated_not_stored(ctx):
    """계약은 요청마다 파이썬에서 만든다. 파일로 굳혀두면 코드와 갈라진다."""
    client, _, _, _ = ctx
    c = client.get("/contract.json").json()
    assert c["version"] == 1
    assert "pi/accident/state" in c["topics"]


# ── 업로드 ───────────────────────────────────────────────────────────
def test_upload_resolves_detection_to_accident(ctx):
    """🔴 Jetson 은 accident_id 를 모른다. detection_id 로 올리면 Pi 가 풀어준다."""
    client, _, accident_id, detection_id = ctx
    r = put(client, detection_id, 1)
    assert r.status_code == 201
    assert r.json()["accident_id"] == accident_id
    assert r.json()["url"] == f"/files/{accident_id}/BEFORE/0001.jpg"


def test_uploaded_file_is_readable(ctx):
    client, _, accident_id, detection_id = ctx
    put(client, detection_id, 7)
    r = client.get(f"/files/{accident_id}/BEFORE/0007.jpg")
    assert r.status_code == 200
    assert r.content == JPEG


def test_upload_is_idempotent(ctx):
    """🔴 Jetson 이 응답을 못 받고 재전송하면 같은 자리로 다시 온다.

    새 행을 만들면 프레임이 두 배가 된다. pi_accident_file 의 UNIQUE 와 짝이다.
    """
    client, repo, accident_id, detection_id = ctx
    a = put(client, detection_id, 1).json()["file_id"]
    b = put(client, detection_id, 1, body=JPEG + b"!").json()["file_id"]
    assert a == b
    assert len(repo.files_for(accident_id)) == 1
    # 내용은 갱신된다
    assert client.get(f"/files/{accident_id}/BEFORE/0001.jpg").content == JPEG + b"!"


def test_reupload_clears_object_key(ctx):
    """다시 올라오면 R2 업로드를 다시 해야 한다. 내용이 바뀌었을 수 있다."""
    client, repo, accident_id, detection_id = ctx
    fid = put(client, detection_id, 1).json()["file_id"]
    repo.mark_uploaded(fid, "accidents/x/BEFORE/0001.jpg", T0)
    assert repo.pending_uploads() == []
    put(client, detection_id, 1)
    assert len(repo.pending_uploads()) == 1


def test_rejected_detection_is_409_not_404(ctx):
    """🔴 두 경우를 갈라서 알려준다.

    진행 중 사고가 있으면 새 탐지가 E1 으로 거부되고, 그 `detection_id` 는 **영영**
    사고에 안 붙는다. 404 로 뭉뚱그리면 Jetson 이 재시도하며 시간을 버린다 —
    실제로 40초를 버렸다.
    """
    client, _, _, _ = ctx           # 픽스처가 WAIT 상태 사고를 만들어 둔다
    r = put(client, uuid7(), 1)
    assert r.status_code == 409
    assert "거부" in r.json()["detail"]


def test_unknown_detection_id_is_404_when_idle(ctx):
    """진행 중 사고가 없으면 Jetson 이 Pi 보다 빨랐던 것이다. 재시도하면 붙는다."""
    client, repo, accident_id, _ = ctx
    # 사고를 닫아 진행 중이 없게 만든다
    acc = repo.get(accident_id)
    repo.update(replace(acc, status=AccidentStatus.CLOSE, closed_at=T0, updated_at=T0))
    assert repo.active() is None

    r = put(client, uuid7(), 1)
    assert r.status_code == 404
    assert "재시도" in r.json()["detail"]


def test_rejects_bad_file_type(ctx):
    client, _, _, detection_id = ctx
    assert put(client, detection_id, 1, ftype="NOPE").status_code == 400


def test_rejects_unsupported_content_type(ctx):
    client, _, _, detection_id = ctx
    r = client.put(f"/api/detections/{detection_id}/files/BEFORE/1",
                   content=b"x", headers={"Content-Type": "application/zip"})
    assert r.status_code == 415


def test_rejects_empty_body(ctx):
    client, _, _, detection_id = ctx
    assert put(client, detection_id, 1, body=b"").status_code == 400


def test_rejects_oversize(ctx):
    """⚠ 상한이 없으면 Jetson 버그 하나가 microSD 를 채운다."""
    client, _, _, detection_id = ctx
    assert put(client, detection_id, 1,
               body=b"x" * (MAX_UPLOAD_BYTES + 1)).status_code == 413


def test_camera_header_recorded(ctx):
    client, repo, accident_id, detection_id = ctx
    put(client, detection_id, 1, **{"X-Camera": "L"})
    assert repo.files_for(accident_id)[0]["camera"] == "L"


# ── 🔴 경로 주입 ─────────────────────────────────────────────────────
def test_path_traversal_rejected(tmp_path):
    """사용자 입력이 파일 경로가 되는 자리다. 형태를 강제하지 않으면 밖으로 나간다."""
    store = FileStore(tmp_path)
    for bad in ("../../etc", "..", "a/../../b", "x" * 40):
        with pytest.raises(BadPath):
            store.path(bad, "BEFORE", 1)


def test_bad_file_type_rejected_in_store(tmp_path):
    store = FileStore(tmp_path)
    with pytest.raises(BadPath):
        store.path(uuid7(), "../BEFORE", 1)


def test_resolve_refuses_outside_root(tmp_path):
    store = FileStore(tmp_path)
    with pytest.raises(BadPath):
        store.resolve("../../secret.txt")


def test_store_path_matches_r2_key_shape(tmp_path):
    """로컬 경로·URL·R2 객체 키가 같은 모양이어야 서로 변환된다."""
    store = FileStore(tmp_path)
    aid = uuid7()
    assert store.relative(aid, "BEFORE", 42) == f"accidents/{aid}/BEFORE/0042.jpg"
    assert store.relative(aid, "DETECT_SNAPSHOT", None) \
        == f"accidents/{aid}/DETECT_SNAPSHOT/snapshot.jpg"


def test_partial_file_not_served(tmp_path):
    """쓰는 도중 읽히면 반쪽짜리 JPEG 이 그려진다. .part 로 쓰고 옮긴다."""
    store = FileStore(tmp_path)
    aid = uuid7()
    rel, size = store.save(aid, "BEFORE", 1, JPEG)
    assert size == len(JPEG)
    assert not list((tmp_path / "accidents" / aid / "BEFORE").glob("*.part"))


# ── 조회 ─────────────────────────────────────────────────────────────
def test_list_files_is_ordered(ctx):
    """사고 전 30초가 150장이라 순서 없이는 재생이 안 된다."""
    client, _, accident_id, detection_id = ctx
    for n in (3, 1, 2):
        put(client, detection_id, n)
    got = client.get(f"/api/accidents/{accident_id}/files").json()
    assert got["count"] == 3
    assert [f["sequence_no"] for f in got["files"]] == [1, 2, 3]


def test_missing_file_is_404(ctx):
    client, _, accident_id, _ = ctx
    assert client.get(f"/files/{accident_id}/BEFORE/0001.jpg").status_code == 404


def test_db_row_without_disk_file_is_410(ctx, tmp_path):
    """DB 에는 있는데 디스크에 없다. 카드가 지워졌거나 손으로 건드린 것이다."""
    client, repo, accident_id, detection_id = ctx
    put(client, detection_id, 1)
    rel = repo.file_path(accident_id, "BEFORE", 1)
    (tmp_path / "files" / rel).unlink()
    assert client.get(f"/files/{accident_id}/BEFORE/0001.jpg").status_code == 410


def test_bad_filename_is_400(ctx):
    client, _, accident_id, _ = ctx
    assert client.get(f"/files/{accident_id}/BEFORE/nope.jpg").status_code == 400


# ── 진행 중 사고 조회 ────────────────────────────────────────────────
def test_active_accident_reports_the_open_one(ctx):
    """Jetson 이 탐지를 쏘기 전에 이걸 본다. E1 으로 409 를 맞기 전에 알려면."""
    client, _, accident_id, _ = ctx
    got = client.get("/api/accidents/active").json()
    assert got["accident_id"] == accident_id
    assert got["status"] == "WAIT"


def test_active_accident_is_null_when_closed(ctx):
    """🔴 없으면 200 + null 이다. 404 로 주면 호출자가 "서버가 이상하다"로 읽는다."""
    client, repo, accident_id, _ = ctx
    acc = repo.get(accident_id)
    repo.update(acc.with_status(AccidentStatus.CLOSE, now=T0 + 100))

    r = client.get("/api/accidents/active")
    assert r.status_code == 200
    assert r.json() == {"accident_id": None, "status": None}


def test_active_accident_does_not_collide_with_the_id_route(ctx):
    """⚠ `/api/accidents/{accident_id}/files` 와 같은 접두사다. `active` 가
    사고 id 로 잡히면 안 되므로 **먼저** 등록돼 있어야 한다."""
    client, _, _, _ = ctx
    assert client.get("/api/accidents/active").status_code == 200


# ── 지난 사고 조회 (키오스크) ────────────────────────────────────────
def test_accident_list_is_newest_first(ctx):
    client, repo, accident_id, _ = ctx
    older = uuid7()
    repo.create(Accident(
        accident_id=older, ship_id=repo.get(accident_id).ship_id,
        accident_lat=35.0, accident_lon=129.0, accident_type=AccidentType.MOB,
        trigger_source=TriggerSource.AI, report_type=ReportType.DISTRESS,
        report_dsc=110, status=AccidentStatus.CLOSE, wait_sec=30,
        report_due_at=None, model_version="v1", rescued_at=None,
        closed_at=T0 - 100, created_at=T0 - 1000, updated_at=T0 - 100))

    got = client.get("/api/accidents").json()
    assert got["total"] == 2
    assert [a["accident_id"] for a in got["accidents"]] == [accident_id, older]


def test_accident_list_filters_by_status(ctx):
    client, _, accident_id, _ = ctx
    assert client.get("/api/accidents?status=WAIT").json()["total"] == 1
    assert client.get("/api/accidents?status=CLOSE").json()["total"] == 0


def test_accident_list_caps_the_page_size(ctx):
    """🔴 limit 을 그대로 믿으면 키오스크 버그 하나가 Pi 를 세운다."""
    client, _, _, _ = ctx
    assert client.get("/api/accidents?limit=99999").json()["limit"] == 100


def test_accident_list_is_snake_case_like_mqtt(ctx):
    """🔴 같은 화면에서 MQTT 와 섞어 쓴다. camelCase 를 섞으면 두 이름을 오간다."""
    client, _, _, _ = ctx
    a = client.get("/api/accidents").json()["accidents"][0]
    assert "accident_id" in a and "created_at" in a
    assert not any(c.isupper() for c in "".join(a.keys()))


def test_accident_detail_has_everything_for_one_screen(ctx):
    """🔴 화면 하나에 요청 다섯 번이면 좁은 선내 무선에서 반쪽으로 뜬다."""
    client, _, accident_id, _ = ctx
    got = client.get(f"/api/accidents/{accident_id}").json()
    assert got["accident_id"] == accident_id
    assert got["launch"]["result"] == "SUCCESS"       # 픽스처가 넣어 둔 것
    assert got["reports"] == []
    assert got["comm_losses"] == []
    assert got["file_count"] == 0
    assert got["snapshot_url"] is None


def test_accident_detail_404_for_unknown(ctx):
    client, _, _, _ = ctx
    assert client.get(f"/api/accidents/{uuid7()}").status_code == 404


def test_accident_detail_points_at_the_snapshot(ctx):
    client, repo, accident_id, detection_id = ctx
    put(client, detection_id, 0, ftype="DETECT_SNAPSHOT")
    got = client.get(f"/api/accidents/{accident_id}").json()
    assert got["file_count"] == 1
    # ⚠ HTTP 로 올라온 스냅샷은 `sequence_no=0` 이라 파일명이 `0000.jpg` 다.
    #   `snapshot.jpg` 는 `sequence_no` 가 NULL 일 때의 이름이고, PUT 경로는
    #   경로 파라미터가 int 라 NULL 이 될 수 없다 (업로더가 None -> 0 으로 보낸다).
    assert "/DETECT_SNAPSHOT/" in got["snapshot_url"]
    assert got["snapshot_url"].endswith(".jpg")


def test_timeline_is_in_order(ctx):
    client, repo, accident_id, _ = ctx
    for i, st in enumerate((AccidentStatus.DETECT, AccidentStatus.WAIT)):
        repo.append_state(StateTransition(
            accident_id=accident_id, status=st, prev_status=None,
            reason="AI_DETECT", caused_by=None, created_at=T0 + i))
    got = client.get(f"/api/accidents/{accident_id}/timeline").json()
    assert [e["status"] for e in got["entries"]] == ["DETECT", "WAIT"]


def test_buoy_track_thins_but_keeps_the_ends(ctx):
    """🔴 솎아도 처음과 끝은 남는다. 투하 지점과 마지막 수신 위치는 수색에 직접 쓴다."""
    client, repo, accident_id, _ = ctx
    for i in range(10):
        repo.add_buoy(accident_id, seq=i, lat=35.0 + i / 1000, lon=129.0,
                      is_pressed=False, rssi=-80.0,
                      measured_at=T0 + i, received_at=T0 + i, now=T0)

    full = client.get(f"/api/accidents/{accident_id}/buoy-positions").json()
    assert full["count"] == 10

    thin = client.get(
        f"/api/accidents/{accident_id}/buoy-positions?every=4").json()
    assert thin["count"] < full["count"]
    assert thin["positions"][0]["seq"] == full["positions"][0]["seq"]
    assert thin["positions"][-1]["seq"] == full["positions"][-1]["seq"]


def test_buoy_track_is_empty_not_404_when_none(ctx):
    """부표가 없는 사고도 있다(투하 실패). 404 면 화면이 오류로 그린다."""
    client, _, accident_id, _ = ctx
    got = client.get(f"/api/accidents/{accident_id}/buoy-positions").json()
    assert got["count"] == 0 and got["positions"] == []


def test_active_route_still_wins_over_the_id_route(ctx):
    """⚠ `/api/accidents/active` 가 사고 id 로 잡히면 안 된다. 먼저 등록돼야 한다."""
    client, _, _, _ = ctx
    assert "accident_id" in client.get("/api/accidents/active").json()

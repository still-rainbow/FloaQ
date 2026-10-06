"""선내 HTTP 서버. FastAPI.

**MQTT 를 대신하지 않는다.** 역할이 다르다.

    MQTT (1883/9001)   이벤트·상태·명령      작고 잦다
    HTTP (8000)        파일·페이지          크고 드물다

왜 FastAPI 인가
    `floaq/contracts/` 가 이미 pydantic v2 다. 그대로 넣으면 OpenAPI 가 나온다.
    손으로 스키마를 옮겨 적는 순간 갈라지는데, 이 프로젝트는 이미 그 실패를
    한 번 겪었다.

⚠ **폐쇄망 전제다.** 선내 랜에만 뜨고 인터넷에서 들어오는 경로가 없다.
  인증을 아직 두지 않은 것은 그 전제 위에서다 — 외부 노출이 생기면 반드시 닫는다.

🔴 **블로킹 호출을 `async def` 안에서 그대로 부르지 않는다.**
   `SqliteRepo` 와 파일 읽기는 전부 블로킹이다. 이벤트 루프에서 직접 부르면
   그 시간 동안 **모든** 요청이 멈춘다 — 1Hz 로 도는 사고 처리까지 같이 밀린다.
   `run_in_threadpool` 로 넘기거나 핸들러를 `def` 로 둔다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import ClientDisconnect

from pydantic import BaseModel

from floaq.provision import InvalidShip, ShipRegistration, credential, registered_ship
from floaq.web.files import EXTENSIONS, FILE_TYPES, BadPath, FileStore

log = logging.getLogger(__name__)

#: 업로드 한 건 상한. 1920x1080 고품질 JPEG 이 300KB 근처라 여유를 둔다.
#: ⚠ 상한이 없으면 Jetson 버그 하나가 microSD 를 채운다.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

router = APIRouter()


def _store(request: Request) -> FileStore:
    return request.app.state.store


def _repo(request: Request):
    return request.app.state.repo


# ── 상태 ─────────────────────────────────────────────────────────────
@router.get("/health")
def health(request: Request) -> dict:
    """살아 있는지. 배선 확인용이라 DB 를 건드리지 않는다."""
    return {"ok": True, "ship_id": request.app.state.ship_id}


# ── Jetson 업로드 ────────────────────────────────────────────────────
@router.put("/api/detections/{detection_id}/files/{file_type}/{sequence_no}",
            status_code=201)
async def put_frame(
    detection_id: str,
    file_type: str,
    sequence_no: int,
    request: Request,
    content_type: Annotated[str, Header()] = "image/jpeg",
    x_camera: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Jetson 이 프레임을 올린다. 본문은 raw 바이트다.

    🔴 **Jetson 은 `accident_id` 를 모른다.** 탐지 시점엔 사고가 아직 없고 Pi 가
       `jetson/detection` 을 받고 나서 만들기 때문이다. 그래서 Jetson 이 자기가 만든
       `detection_id` 로 올리고 Pi 가 `pi_launch` 를 통해 풀어준다.

    ⚠ PUT 인 이유는 멱등해서다. Jetson 이 응답을 못 받고 재전송해도 같은 자리에
      덮어쓰고 `pi_accident_file` 의 UNIQUE 가 새 행을 막는다. POST 면 프레임이
      두 배가 된다.

    ⚠ multipart 가 아니라 raw 본문이다. 메타데이터는 경로와 헤더로 충분하고
      Jetson 쪽 코드가 짧아진다. (EC2 구간은 multipart 다 — 거긴 필드가 많다.)
    """
    if file_type not in FILE_TYPES:
        raise HTTPException(400, f"모르는 file_type: {file_type}")
    ext = EXTENSIONS.get(content_type.split(";")[0].strip())
    if ext is None:
        raise HTTPException(415, f"지원하지 않는 형식: {content_type}")

    # ⚠ `body: bytes` 를 인자로 선언하면 FastAPI 가 쿼리 파라미터로 보고 422 를 낸다.
    #   raw 본문은 요청에서 직접 읽는다.
    #
    # 🔴 **끊긴 연결은 오류가 아니다.** Jetson 이 타임아웃으로 소켓을 닫으면
    #   `ClientDisconnect` 가 올라오는데, 그대로 두면 uvicorn 이 40줄짜리 ASGI
    #   트레이스백을 찍는다. 프레임 150장짜리 사고에서 링크가 흔들리면 Pi 로그가
    #   그걸로 덮여 진짜 오류를 못 본다 — 실제로 그랬다.
    #   Jetson 은 재시도하므로 여기서는 한 줄만 남기고 조용히 끝낸다.
    try:
        body = await request.body()
    except ClientDisconnect:
        log.info("업로드 중 연결 끊김 %s %s/%s — Jetson 이 재시도한다",
                 detection_id[:8], file_type, sequence_no)
        # 499 는 nginx 관례다. 클라이언트가 이미 갔으므로 이 응답은 버려지지만,
        # 4xx 로 끝내야 예외 미들웨어가 스택을 안 찍는다
        return JSONResponse({"detail": "client disconnected"}, status_code=499)
    if not body:
        raise HTTPException(400, "본문이 비었다")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{MAX_UPLOAD_BYTES} 바이트 초과")

    repo, store = _repo(request), _store(request)

    # 🔴 여기부터 전부 블로킹이다(SQLite, 디스크 쓰기). `async def` 안에서 그대로
    #    부르면 이벤트 루프가 멈춰 **모든** 요청이 같이 선다. 스레드풀로 넘긴다.
    def _persist() -> tuple[int, str]:
        accident_id = repo.accident_by_detection(detection_id)
        if accident_id is None:
            # 🔴 두 경우를 반드시 갈라서 알려준다. 같은 404 로 뭉뚱그리면 Jetson 이
            #    영영 안 붙을 것에 대고 재시도하며 시간을 버린다. 실제로 겪었다.
            if repo.active() is not None:
                # 진행 중 사고가 있어 이 탐지가 E1 으로 거부됐다. 재시도해도 안 붙는다.
                raise HTTPException(
                    409, "진행 중 사고가 있어 이 탐지가 거부됐다 (동시 1건). "
                         "재시도해도 붙지 않는다")
            # 아직 Pi 가 탐지를 처리하지 않았다. 재시도하면 붙는다.
            raise HTTPException(404, "아직 사고에 연결되지 않은 detection_id. "
                                     "탐지 발행 직후면 재시도할 것")
        try:
            rel, size = store.save(accident_id, file_type, sequence_no, body, ext=ext)
        except BadPath as e:
            raise HTTPException(400, str(e)) from None
        fid = repo.add_file(accident_id=accident_id, file_type=file_type,
                            sequence_no=sequence_no, file_path=rel,
                            now=request.app.state.clock.now(),
                            camera=x_camera, size_bytes=size)
        return fid, accident_id

    file_id, accident_id = await run_in_threadpool(_persist)
    return JSONResponse(
        {"file_id": file_id, "accident_id": accident_id,
         "url": f"/files/{accident_id}/{file_type}/{sequence_no:04d}.{ext}"},
        status_code=201,
    )


@router.get("/api/accidents/active")
def active_accident(request: Request) -> dict:
    """진행 중인 사고. 없으면 `accident_id: null`.

    🔴 **DB 가 원본이다.** 같은 것을 `pi/accident/state` retained 로도 뿌리지만,
       그건 브로커에 남는 **소문**이다. Pi 가 재시작하거나 발행을 놓치면 옛 상태가
       영원히 남고, 그걸 믿은 Jetson 은 사고가 닫혔는데도 계속 "사고 있음" 으로
       본다 — 실제로 밟았다. 판단이 필요한 쪽은 여기로 묻는다.

    ⚠ `/health` 는 DB 를 안 건드린다는 약속이 있어서 거기 안 넣는다.
    """
    acc = _repo(request).active()
    if acc is None:
        return {"accident_id": None, "status": None}
    return {"accident_id": acc.accident_id, "status": str(acc.status),
            "created_at": acc.created_at}


# ── 키오스크 조회 ────────────────────────────────────────────────────
#
# 🔴 **왜 Pi 가 이걸 내는가.** EC2 에도 같은 조회가 있다(`/api/accidents`).
#    그런데 키오스크는 **선내 화면**이고 배에는 인터넷이 없을 수 있다. 지난 사고를
#    못 보는 화면은 쓸모가 없다. 사진도 Pi 에만 있다 — EC2 는 R2 오브젝트 키만
#    알고, 키오스크는 R2 에 직접 못 붙는다.
#
# ⚠ 응답은 **snake_case + Unix 초**다. EC2 는 camelCase + ISO 지만 그건 관제 웹
#   몫이다. 키오스크는 같은 화면에서 MQTT(snake_case)와 이 HTTP 를 섞어 쓰므로,
#   표기를 하나로 두지 않으면 `accident_id` 와 `accidentId` 를 오가다 버그가 난다.

#: 목록 한 쪽 최대. 배 한 척의 사고는 많아야 수백 건이라 커서가 필요 없다.
ACCIDENT_PAGE_MAX = 100


def _accident_row(r) -> dict:
    """목록·상세가 공유하는 사고 본문."""
    return {
        "accident_id": r["accident_id"], "ship_id": r["ship_id"],
        "status": r["status"], "accident_type": r["accident_type"],
        "trigger_source": r["trigger_source"], "report_type": r["report_type"],
        "report_dsc": r["report_dsc"],
        "lat": r["accident_lat"], "lon": r["accident_lon"],
        "wait_sec": r["wait_sec"], "report_due_at": r["report_due_at"],
        "model_version": r["model_version"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "rescued_at": r["rescued_at"], "closed_at": r["closed_at"],
    }


@router.get("/api/accidents")
def list_accidents(request: Request, limit: int = 20, offset: int = 0,
                   status: str | None = None) -> dict:
    """지난 사고 목록. 최신순.

    ⚠ `total` 을 같이 준다. 안 주면 화면이 "더 있는지"를 다음 요청을 해봐야 안다.
    """
    limit = max(1, min(limit, ACCIDENT_PAGE_MAX))
    offset = max(0, offset)
    repo = _repo(request)
    rows = repo.list_accidents(limit=limit, offset=offset, status=status)
    return {"total": repo.count_accidents(status), "limit": limit,
            "offset": offset, "accidents": [_accident_row(r) for r in rows]}


@router.get("/api/accidents/{accident_id}")
def accident_detail(accident_id: str, request: Request) -> dict:
    """사고 하나. 투하·신고·두절·파일 수를 한 번에 준다.

    🔴 **한 번에 준다.** 화면 하나를 그리는 데 요청을 다섯 번 하면, 좁은 선내
       무선에서 그만큼 늦게 뜨고 중간에 하나만 실패하면 화면이 반쪽이 된다.

    ⚠ 부표 궤적은 여기 없다. 수백 점이라 목록·요약과 수명이 다르다 —
      `/buoy-positions` 로 따로 받는다.
    """
    repo = _repo(request)
    row = repo.conn.execute("SELECT * FROM pi_accident WHERE accident_id = ?",
                            (accident_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "없는 사고")

    launch = repo.launch_for(accident_id)
    files = repo.files_for(accident_id)
    return {
        **_accident_row(row),
        "launch": None if launch is None else {
            "detection_id": launch["detection_id"], "result": launch["result"],
            "fail_reason": launch["fail_reason"],
            "launch_lat": launch["launch_lat"], "launch_lon": launch["launch_lon"],
            "target_lat": launch["target_lat"], "target_lon": launch["target_lon"],
            "horizontal_angle": launch["horizontal_angle"],
            "vertical_angle": launch["vertical_angle"],
            "confidence_score": launch["confidence_score"],
            "created_at": launch["created_at"],
        },
        "reports": [
            {"channel": r["channel"], "status": r["status"],
             "trigger_kind": r["trigger_kind"], "sent_count": r["sent_count"],
             "report_lat": r["report_lat"], "report_lon": r["report_lon"],
             "first_sent_at": r["first_sent_at"], "last_sent_at": r["last_sent_at"],
             "acked_at": r["acked_at"], "acked_by": r["acked_by"],
             "fail_reason": r["fail_reason"]}
            for r in repo.reports_for(accident_id)],
        "comm_losses": [
            {"detected_at": c["detected_at"], "recovered_at": c["recovered_at"],
             "last_lat": c["last_lat"], "last_lon": c["last_lon"],
             "last_received_at": c["last_received_at"],
             "threshold_sec": c["threshold_sec"]}
            for c in repo.comm_losses_for(accident_id)],
        "file_count": len(files),
        # 화면이 목록을 또 받지 않아도 대표 한 장은 바로 그릴 수 있게
        "snapshot_url": next(
            (f"/files/{f['file_path']}".replace("/accidents/", "/")
             for f in files if f["file_type"] == "DETECT_SNAPSHOT"), None),
    }


@router.get("/api/accidents/{accident_id}/timeline")
def accident_timeline(accident_id: str, request: Request) -> dict:
    """상태 전이 이력. append-only 라 이게 곧 그 사고의 서사다."""
    rows = _repo(request).history(accident_id)
    return {"accident_id": accident_id, "entries": [
        {"status": str(t.status),
         "prev_status": str(t.prev_status) if t.prev_status else None,
         "reason": t.reason, "caused_by": t.caused_by,
         "created_at": t.created_at}
        for t in rows]}


@router.get("/api/accidents/{accident_id}/buoy-positions")
def accident_buoy_positions(accident_id: str, request: Request,
                            every: int = 1, limit: int = 2000) -> dict:
    """부표 궤적. 지도에 선으로 그린다.

    ⚠ 1Hz 라 10분이면 600점이다. `every=5` 로 솎으면 5분의 1이 된다.
      솎아도 **처음과 끝은 남는다** — 투하 지점과 마지막 수신 위치는 수색에
      직접 쓰는 값이라 빠지면 안 된다.
    """
    rows = _repo(request).buoy_track(accident_id, every=max(1, every),
                                     limit=max(1, min(limit, 5000)))
    return {"accident_id": accident_id, "every": max(1, every),
            "count": len(rows), "positions": [
                {"seq": r["seq"], "lat": r["lat"], "lon": r["lon"],
                 "is_pressed": bool(r["is_pressed"]), "rssi": r["rssi"],
                 "measured_at": r["created_at"], "received_at": r["received_at"]}
                for r in rows]}


@router.get("/api/accidents/{accident_id}/files")
def list_files(accident_id: str, request: Request,
               file_type: str | None = None) -> dict:
    """사고 하나의 파일 목록. 키오스크가 타임라인을 그릴 때 쓴다."""
    rows = _repo(request).files_for(accident_id, file_type)
    return {"accident_id": accident_id, "count": len(rows), "files": [
        {"file_id": r["file_id"], "file_type": r["file_type"],
         "sequence_no": r["sequence_no"], "camera": r["camera"],
         "bytes": r["bytes"],
         "url": f"/files/{r['file_path']}".replace("/accidents/", "/"),
         "uploaded": r["object_key"] is not None}
        for r in rows]}


@router.get("/files/{accident_id}/{file_type}/{name}")
def get_file(accident_id: str, file_type: str, name: str,
             request: Request) -> Response:
    """이미지 한 장.

    🔴 **키오스크는 R2 가 아니라 여기서 받는다.** 선내 화면이 인터넷에 의존하면
       사고 상황에서 가장 먼저 끊긴다. `pi_accident_file` 에 `file_path`(로컬)와
       `object_key`(R2)가 따로 있는 이유다.

    `FileResponse` 가 `Range`·`ETag`·`Last-Modified` 를 처리한다. 브라우저가
    125장을 다시 받지 않는다.
    """
    stem = name.rsplit(".", 1)[0]
    seq = None if stem == "snapshot" else int(stem) if stem.isdigit() else -1
    if seq == -1:
        raise HTTPException(400, "파일명 형식이 아니다")

    rel = _repo(request).file_path(accident_id, file_type, seq)
    if rel is None:
        raise HTTPException(404, "없는 파일")
    try:
        full = _store(request).resolve(rel)
    except BadPath:
        raise HTTPException(400, "경로 오류") from None
    if not full.exists():
        # DB 에는 있는데 디스크에 없다. 카드가 지워졌거나 수동으로 건드린 것이다.
        log.error("DB 에는 있으나 파일이 없다: %s", rel)
        raise HTTPException(410, "파일이 사라졌다")
    return FileResponse(full)


# ── 선박 등록 (키오스크 → Pi) ────────────────────────────────────────
class ShipRegisterBody(BaseModel):
    """키오스크가 보내는 등록 값. `IPiShipRegisterRequest`(api.json)와 같다.

    ⚠ `ship_id` 는 없다. 서버가 발급한다 — Pi 도 키오스크도 만들지 않는다.
    """

    model_config = {"extra": "forbid"}

    name: str
    registration_no: str
    mmsi: str
    has_buoy: bool = True


@router.post("/api/ship", status_code=202)
async def register_ship(body: ShipRegisterBody, request: Request) -> JSONResponse:
    """등록 신청을 받아 둔다. **서버에 보내는 건 백그라운드가 한다.**

    🔴 여기서 EC2 를 부르지 않는다. 인터넷이 없으면 이 요청이 타임아웃까지 멈추고,
      키오스크 화면은 "저장 중" 에서 20초를 선다. 받아서 파일에 쓰고 바로 202 를
      돌려준 뒤, 등록 루프가 되는 대로 올린다.

    상태는 `GET /api/ship` 으로 본다.
    """
    prov = request.app.state.pending
    if prov is None:
        raise HTTPException(503, "등록 경로가 꺼져 있다 — main.py 배선을 확인할 것")

    ship = await run_in_threadpool(registered_ship, request.app.state.conn)
    if ship is not None:
        # 이미 등록된 배가 있다. 덮어쓰면 pi_accident 의 FK 부모가 바뀌고
        # MQTT 토픽도 전부 어긋난다 — 그건 DB 를 새로 만드는 일이지 등록이 아니다
        raise HTTPException(409, f"이미 등록된 배가 있다: {ship[1]}")

    try:
        reg = ShipRegistration(name=body.name, registration_no=body.registration_no,
                               mmsi=body.mmsi, has_buoy=body.has_buoy)
    except InvalidShip as e:
        raise HTTPException(400, str(e)) from None

    await run_in_threadpool(prov.write, reg)
    # 🔴 등록 루프를 깨운다. 안 깨우면 최대 RETRY_SEC(30초)를 기다리는데,
    #   그동안 화면은 아무 변화가 없어 고장으로 보인다.
    enroller = getattr(request.app.state, "enroller", None)
    if enroller is not None:
        enroller.wake()
    log.warning("선박 등록 신청 접수: %s (%s) — 서버에 바로 올린다",
                reg.name, reg.registration_no)
    return JSONResponse({"pending": True, "name": reg.name}, status_code=202)


@router.get("/api/ship")
def ship_state(request: Request) -> dict:
    """등록·승인 상태. 키오스크가 이걸 폴링해 화면을 고른다.

    ⚠ `ship_key` 는 절대 싣지 않는다. 다시 받을 방법이 없는 값이라 나가는 경로를
      아예 만들지 않는다.
    """
    conn = request.app.state.conn
    ship = registered_ship(conn)
    if ship is None:
        pending = request.app.state.pending
        reg = pending.read() if pending else None
        return {"state": "PENDING" if reg else "NONE",
                "name": reg.name if reg else None}

    ship_id, name, mmsi = ship
    cred = credential(conn, ship_id)
    return {"state": cred[1] if cred else "NO_KEY",   # WAIT · ACTIVE · REJECTED
            "ship_id": ship_id, "name": name, "mmsi": mmsi}


# ── 해양 데이터 중계 (키오스크 -> Pi -> EC2) ─────────────────────────
@router.get("/api/ocean/{path}")
async def ocean(path: str, request: Request) -> JSONResponse:
    """EC2 `/api/ocean/**` 를 중계한다. **키오스크는 EC2 를 직접 부르지 않는다.**

    키오스크 설정이 Pi 주소 하나로 줄고, kiosk 키가 브라우저 번들에 안 들어간다.
    인터넷이 끊기면 마지막 값을 `fresh: false` 로 준다 — 빈 200 을 주면 화면이
    "조류 0.0 m/s" 를 "잔잔하다"로 그린다.
    """
    proxy = request.app.state.ocean
    if proxy is None:
        raise HTTPException(503, "해양 중계가 꺼져 있다 — FLOAQ_EDGE_URL 을 확인할 것")
    body, status = await run_in_threadpool(
        proxy.get, path, dict(request.query_params))
    return JSONResponse(body, status_code=status)


# ── 계약 ─────────────────────────────────────────────────────────────
@router.get("/contract.json")
def contract(request: Request) -> Response:
    """MQTT 계약. 키오스크와 웹 팀이 읽는다.

    ⚠ 파이썬이 정본이다. 요청할 때마다 새로 만들어서 코드와 갈라지지 않게 한다.
    """
    from floaq.contracts.__main__ import build
    return JSONResponse(build())


def create_app(*, ship_id: str, repo, clock, store_root: Path,
               kiosk_dir: Path | None = None, conn=None, pending=None,
               ocean=None) -> FastAPI:
    """앱을 만든다. 오케스트레이터의 수명주기는 `main.py` 가 잡는다.

    ⚠ 여기서 브로커에 붙거나 스레드를 띄우지 않는다. 그건 `main.py` 몫이다 —
      HTTP 서버가 없어도 사고 처리는 돌아야 한다.
    """
    app = FastAPI(title="FloaQ Pi", version="1",
                  description="선내 파일·페이지 서버. 이벤트는 MQTT 가 나른다.")
    app.state.ship_id = ship_id
    app.state.repo = repo
    app.state.clock = clock
    app.state.store = FileStore(store_root)
    # 등록 경로용. 🔴 `conn` 은 SqliteRepo 의 락 밖이라 여기서는 **읽기만** 한다 —
    #   쓰기는 등록 루프(main.py)가 한 스레드에서 한다
    app.state.conn = conn if conn is not None else getattr(repo, "conn", None)
    app.state.pending = pending
    app.state.ocean = ocean
    # 등록 루프. `POST /api/ship` 이 신청을 받으면 이걸 깨운다.
    # main.py 가 나중에 꽂는다 — 등록 루프가 HTTP 뒤에 뜨기 때문이다
    app.state.enroller = None
    app.include_router(router)

    if kiosk_dir is not None:
        from fastapi.staticfiles import StaticFiles
        # 🔴 키오스크 페이지를 Pi 가 내려주면 브라우저의 `location.hostname` 이 곧
        #    Pi 주소가 된다. 키오스크가 별도 컴퓨터여도 설정할 게 없어진다.
        app.mount("/kiosk", StaticFiles(directory=kiosk_dir, html=True), name="kiosk")
    return app

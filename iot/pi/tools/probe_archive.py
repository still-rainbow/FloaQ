"""`POST /api/pi/archives` 한 번 쏴 보고 **응답 원문**을 그대로 보여준다.

서버와 맞춰야 할 것이 셋인데 `api.json` 이 정하지 않았다. 여기서 확인한다.

    ① manifest.json 스키마 — 이름만 정해져 있고 내용이 없다
    ② 압축 — tar.gz 인지 무압축 tar 인지
    ③ nginx client_max_body_size — 기본 1MB 면 전부 413

    # Pi 에서. 기본은 2장만, 로컬 DB 를 건드리지 않는다
    uv run python tools/probe_archive.py

    # 만들기만 하고 안 쏜다. 타르볼 내용을 눈으로 본다
    uv run python tools/probe_archive.py --dry-run

    # 무압축 tar 로도 받는지
    uv run python tools/probe_archive.py --no-gzip

    # 성공하면 object_key 를 로컬에 박는다 (기본은 안 박는다)
    uv run python tools/probe_archive.py --commit

🔴 **이건 실서버에 진짜로 올린다.** 성공하면 R2 에 오브젝트가 생긴다.
   그래서 기본 2장이고, `--commit` 없이는 로컬 상태를 안 바꾼다 —
   같은 파일을 다시 올려도 서버가 duplicated 로 센다.

⚠ `--commit` 없이 성공하면 그 파일들은 R2 에 있는데 로컬은 아직 대기 상태다.
  운영 업로더가 나중에 다시 올리고, 그때 duplicated 로 정리된다. 해는 없다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

from floaq import archive as ar
from floaq.adapters import ec2 as ar_ec2
from floaq.adapters.sqlite import SqliteRepo, connect
from floaq.web.files import FileStore

ROOT = Path(__file__).resolve().parents[1]


def pick_ship(conn) -> tuple[str, str]:
    """ACTIVE 인 배와 그 키. 없으면 왜 없는지 말하고 끝낸다."""
    rows = conn.execute(
        "SELECT ship_id, status, ship_key FROM pi_credential").fetchall()
    if not rows:
        sys.exit("등록된 배가 없다. 키오스크에서 먼저 등록할 것")
    for r in rows:
        if r["status"] == "ACTIVE":
            return r["ship_id"], r["ship_key"]
    got = ", ".join(f"{r['ship_id'][:8]}={r['status']}" for r in rows)
    sys.exit(f"ACTIVE 인 배가 없다 ({got}). 관제 웹에서 승인할 것")


def pick_accident(repo, conn, want: str | None) -> str:
    if want:
        return want
    ids = repo.pending_upload_accidents()
    if ids:
        return ids[0]
    row = conn.execute(
        "SELECT accident_id FROM pi_accident_file"
        " ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        sys.exit("pi_accident_file 이 비었다. 사고를 한 번 만들고 다시 볼 것")
    return row["accident_id"]


def rows_for(repo, conn, accident_id: str, limit: int):
    """대기 중인 것 우선, 없으면 이미 올라간 것이라도 집어서 쏴 본다."""
    rows = repo.pending_files_of(accident_id, limit=limit)
    if rows:
        return rows
    return conn.execute(
        "SELECT * FROM pi_accident_file WHERE accident_id = ?"
        " ORDER BY file_type, sequence_no LIMIT ?", (accident_id, limit)).fetchall()


def matrix(url: str, ship_key: str, accident_id: str, blob: bytes,
           digest: str, now: int, timeout: float) -> int:
    """변형을 여러 개 쏴서 **우리 문제인지 서버 문제인지** 가른다.

    500 만 보고는 못 가른다. 일부러 틀린 요청에도 500 이 오면 핸들러가 검증 전에
    터지는 것이고, 400 이 오면 검증은 살아 있으니 우리 페이로드를 보면 된다.
    """
    import gzip as gz

    plain = gz.decompress(blob)
    ghost = "00000000-0000-7000-8000-000000000000"

    cases = [
        ("정상 tar.gz", {"accident_id": accident_id, "archive_sha256": digest,
                         "created_at": str(now)},
         {"archive": ("a.tar.gz", blob, "application/gzip")}),
        ("무압축 tar", {"accident_id": accident_id,
                        "archive_sha256": hashlib.sha256(plain).hexdigest(),
                        "created_at": str(now)},
         {"archive": ("a.tar", plain, "application/x-tar")}),
        ("없는 사고", {"accident_id": ghost, "archive_sha256": digest,
                       "created_at": str(now)},
         {"archive": ("a.tar.gz", blob, "application/gzip")}),
        ("sha256 불일치", {"accident_id": accident_id, "archive_sha256": "0" * 64,
                           "created_at": str(now)},
         {"archive": ("a.tar.gz", blob, "application/gzip")}),
        ("archive 필드 없음", {"accident_id": accident_id,
                               "archive_sha256": digest, "created_at": str(now)}, None),
        ("accident_id 없음", {"archive_sha256": digest, "created_at": str(now)},
         {"archive": ("a.tar.gz", blob, "application/gzip")}),
        ("빈 타르볼", {"accident_id": accident_id,
                       "archive_sha256": hashlib.sha256(b"").hexdigest(),
                       "created_at": str(now)},
         {"archive": ("a.tar.gz", b"", "application/gzip")}),
    ]

    print("\n판별 세트 — 일부러 틀린 것에도 500 이면 서버 핸들러 문제다\n")
    for label, data, files in cases:
        try:
            r = requests.post(f"{url}/api/pi/archives", data=data, files=files,
                              headers={"X-Ship-Secret-Key": ship_key},
                              timeout=(ar_ec2.ARCHIVE_CONNECT_TIMEOUT, timeout))
        except requests.RequestException as e:
            print(f"  {label:18} 연결 실패 {type(e).__name__}")
            continue
        try:
            code = r.json().get("code") or "success"
        except ValueError:
            code = "(JSON 아님)"
        print(f"  {label:18} {r.status_code} {code}")

    print("\n같은 키로 다른 경로도 본다 (키·승인 문제인지 구분)")
    try:
        r = requests.post(f"{url}/api/pi/ship-positions",
                          json={"request_id": ghost, "v": 1, "ts": now, "data": []},
                          headers={"X-Ship-Secret-Key": ship_key,
                                   "Content-Type": "application/json"}, timeout=20)
        try:
            code = r.json().get("code") or "success"
        except ValueError:
            code = "(JSON 아님)"
        print(f"  ship-positions(빈 배치)  {r.status_code} {code}")
    except requests.RequestException as e:
        print(f"  ship-positions  연결 실패 {type(e).__name__}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="archives 엔드포인트 탐침")
    p.add_argument("--db", default=str(ROOT / "floaq.db"))
    p.add_argument("--accident", default=None, help="기본은 대기 중인 첫 사고")
    p.add_argument("--files", type=int, default=2,
                   help="담을 장 수. 탐침이라 작게 둔다 (기본 2)")
    p.add_argument("--no-gzip", action="store_true",
                   help="무압축 tar 로 보낸다. 서버가 받는지 확인용")
    p.add_argument("--dry-run", action="store_true", help="만들기만 하고 안 쏜다")
    p.add_argument("--commit", action="store_true",
                   help="성공하면 object_key 를 로컬에 박는다")
    p.add_argument("--files-root", default="data",
                   help="사고 파일 저장소. main.py 의 --files 와 같아야 한다")
    p.add_argument("--matrix", action="store_true",
                   help="변형을 여러 개 쏴서 우리 문제인지 서버 문제인지 가른다")
    p.add_argument("--timeout", type=float, default=120.0)
    args = p.parse_args()

    load_dotenv(ROOT / ".env", override=False)
    import os
    url = os.environ.get("FLOAQ_EDGE_URL", "https://floaq.example.com").rstrip("/")

    # 🔴 스키마를 적용하지 않는다. 이 도구는 **이미 도는 Pi 의 DB** 를 들여다본다.
    #   무조건 적용하면 `table pi_ship already exists` 로 터진다.
    #   `main.py` 처럼 테이블 존재로 판단하되, 없으면 만들지 않고 그냥 끝낸다 —
    #   빈 DB 를 만들어봐야 볼 사고가 없다.
    conn = connect(args.db)
    if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pi_accident'"
    ).fetchone():
        sys.exit(f"{args.db} 에 스키마가 없다. main.py 를 한 번 띄워 만들 것")
    repo = SqliteRepo(conn)
    ship_id, ship_key = pick_ship(conn)
    accident_id = pick_accident(repo, conn, args.accident)
    rows = rows_for(repo, conn, accident_id, args.files)
    if not rows:
        return print(f"사고 {accident_id} 에 파일이 없다") or 1

    now = int(time.time())
    try:
        blob, packed = ar.build_tarball(accident_id, rows,
                                        FileStore(Path(args.files_root)),
                                        now=now, max_bytes=ar.MAX_BYTES)
    except ar.ArchiveError as e:
        print(f"타르볼을 못 만든다: {e}")
        return 1

    if args.no_gzip:
        # gzip 을 벗겨 순수 tar 로 바꾼다. 같은 내용이라 서버 파서만 다르게 본다
        blob = gzip.decompress(blob)

    digest = hashlib.sha256(blob).hexdigest()
    kind = "tar" if args.no_gzip else "tar.gz"

    print(f"  서버      {url}")
    print(f"  ship_id   {ship_id}")
    print(f"  사고      {accident_id}")
    print(f"  담은 것    {len(packed)}장 / {kind} {len(blob)}바이트")
    print(f"  sha256    {digest}")
    raw = gzip.decompress(blob) if not args.no_gzip else blob
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        for n in t.getnames():
            print(f"            {n}")
        m = json.loads(t.extractfile(ar.MANIFEST).read().decode("utf-8"))
    print("  manifest  " + json.dumps(m, ensure_ascii=False)[:300])

    if args.dry_run:
        print("\n--dry-run. 안 쐈다")
        return 0

    if args.matrix:
        return matrix(url, ship_key, accident_id, blob, digest, now, args.timeout)

    print(f"\n보낸다 ... (읽기 타임아웃 {args.timeout}초)")
    t0 = time.monotonic()
    try:
        r = requests.post(
            f"{url}/api/pi/archives",
            data={"accident_id": accident_id, "archive_sha256": digest,
                  "created_at": str(now)},
            files={"archive": (f"{accident_id}.{kind}", blob,
                               "application/gzip" if not args.no_gzip
                               else "application/x-tar")},
            headers={"X-Ship-Secret-Key": ship_key},
            # 🔴 첫 값을 5초로 두면 안 된다. requests 는 그 값을 **본문을 보내는
            #   동안의 소켓 타임아웃**으로도 쓴다 — --files 를 올리는 순간
            #   `TimeoutError('The write operation timed out')` 으로 죽고,
            #   서버가 끊은 것처럼 보인다 (`adapters/ec2.ARCHIVE_CONNECT_TIMEOUT`).
            timeout=(ar_ec2.ARCHIVE_CONNECT_TIMEOUT, args.timeout),
        )
    except requests.RequestException as e:
        print(f"연결 실패: {type(e).__name__}: {e}")
        return 1
    dt = time.monotonic() - t0

    print(f"\nHTTP {r.status_code}  ({dt:.1f}초)")
    for k in ("content-type", "content-length"):
        if k in r.headers:
            print(f"  {k}: {r.headers[k]}")
    # 🔴 원문을 그대로 찍는다. 파싱해서 보면 어긋난 필드가 안 보인다
    print("─ 본문 ─")
    print(r.text[:2000])

    try:
        body = r.json()
    except ValueError:
        print("\nJSON 이 아니다. nginx 가 먼저 끊었을 수 있다 (413 이면 본문 크기 제한)")
        return 1

    data = (body or {}).get("data") or {}
    files = data.get("files") or []
    print(f"\n  received {data.get('received')} · stored {data.get('stored')}"
          f" · duplicated {data.get('duplicated')} · failed {data.get('failed')}")
    for f in files[:5]:
        print(f"    {f.get('file_type')}/{f.get('sequence_no')} -> {f.get('object_key')}")

    if not r.ok or not body.get("success"):
        print("\n실패. 확인할 것:")
        print("  400  manifest 스키마나 필드 이름이 서버와 다르다")
        print("  404  그 accident_id 가 서버에 없다 — 사고부터 올라가야 한다")
        print("  413  nginx client_max_body_size")
        print("  415  압축 형식. --no-gzip 으로 다시 해 볼 것")
        return 1

    if args.commit:
        n = 0
        for f in files:
            key = f.get("object_key")
            row = repo.file_by_slot(accident_id, f.get("file_type"),
                                    f.get("sequence_no"))
            if key and row is not None:
                repo.mark_uploaded(row["file_id"], key, now)
                n += 1
        print(f"\n로컬 {n}행에 object_key 를 박았다")
    elif files:
        print("\n--commit 을 안 줬다. 로컬은 그대로 대기 상태다 "
              "(운영 업로더가 다시 올리고 서버가 duplicated 로 센다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""실제 프레임 크기로 타르볼을 만들어 **시간과 크기를 잰다.**

지금까지 시험에 쓴 프레임은 534바이트짜리 가짜라 크기 얘기를 할 수 없었다.
실제 Jetson 프레임은 5fps · JPEG quality 80 이고 한 장이 수십~수백 KB 다.
30초면 150장이라 타르볼이 16MB 상한을 넘는지, 업로드가 몇 초 걸리는지가
여기서만 드러난다.

    # 30초 · 5fps · HD 기준 (기본값). 디스크·DB 를 안 건드린다
    uv run python tools/bench_archive.py

    # 해상도별
    uv run python tools/bench_archive.py --preset vga
    uv run python tools/bench_archive.py --preset fhd

    # 실제 사진으로. 크기가 제일 정확하다
    uv run python tools/bench_archive.py --from ~/sample.jpg

    # 실서버로 진짜 올려서 왕복 시간까지
    uv run python tools/bench_archive.py --upload

🔴 **`--upload` 없이는 네트워크도 실DB 도 안 건드린다.** 임시 디렉터리와
   메모리 DB 만 쓰고 끝나면 지운다.

⚠ `--from` 없이 쓰면 프레임을 **난수 바이트**로 만든다. 그림은 아니지만 JPEG 처럼
  압축이 안 되는 바이트라 **크기·시간 측정에는 같은 값**이 나온다. 다만 서버가
  R2 에 넣을 수 있는 이미지가 아니므로 `--upload` 에는 `--from` 을 같이 쓸 것.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq import archive as ar
from floaq.adapters.sqlite import SqliteRepo, connect
from floaq.contracts import AccidentStatus as S
from floaq.contracts import AccidentType, ReportType, TriggerSource
from floaq.core.domain import Accident
from floaq.ids import uuid7
from floaq.web.files import FileStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT.parents[1] / "database" / "pi.sql"

#: 해상도별 JPEG quality 80 한 장 크기(KB). 실사 기준 대략값이다.
#: ⚠ 장면에 따라 2배까지 흔들린다. 바다처럼 단조로우면 작고, 파도·역광이면 크다.
PRESETS = {
    "vga": (640, 480, 45),
    "hd": (1280, 720, 120),
    "fhd": (1920, 1080, 250),
}


def make_frames(n: int, kb: int, sample: Path | None) -> list[bytes]:
    """프레임 n 장을 만든다.

    🔴 난수 바이트를 쓴다. 0 으로 채우면 gzip 이 99% 를 날려서 타르볼이 우스꽝스럽게
       작아지고, 그 숫자로 상한을 판단하면 실전에서 413 을 맞는다. JPEG 는 이미
       압축돼 있어 난수와 비슷하게 **안 줄어든다.**
    """
    if sample is not None:
        base = sample.read_bytes()
        out = []
        for i in range(n):
            # 매 장 조금씩 다르게 한다. 같은 바이트를 반복하면 gzip 이 장 사이
            # 중복까지 지워서 실제보다 작게 나온다
            out.append(base + os.urandom(64) + i.to_bytes(4, "big"))
        return out
    return [os.urandom(kb * 1024) for _ in range(n)]


def human(b: int) -> str:
    return f"{b / 1048576:.2f}MB" if b >= 1048576 else f"{b / 1024:.1f}KB"


def main() -> int:
    p = argparse.ArgumentParser(description="타르볼 크기·시간 측정")
    p.add_argument("--seconds", type=float, default=30.0, help="영상 길이 (기본 30초)")
    p.add_argument("--fps", type=int, default=5, help="Jetson 기본 5")
    p.add_argument("--preset", choices=sorted(PRESETS), default="hd",
                   help="해상도. quality 80 기준 한 장 크기가 정해진다")
    p.add_argument("--kb", type=int, default=0, help="한 장 크기를 직접 지정 (preset 무시)")
    p.add_argument("--from", dest="sample", default=None,
                   help="실제 JPEG 한 장. 크기가 제일 정확하다")
    p.add_argument("--upload", action="store_true",
                   help="실서버로 진짜 올린다. --from 과 같이 쓸 것")
    p.add_argument("--db", default=str(ROOT / "floaq.db"),
                   help="--upload 일 때 선박 키를 읽을 DB")
    args = p.parse_args()

    w, h, preset_kb = PRESETS[args.preset]
    kb = args.kb or preset_kb
    n = max(1, round(args.seconds * args.fps))
    sample = Path(args.sample).expanduser() if args.sample else None
    if sample is not None and not sample.is_file():
        sys.exit(f"{sample} 가 없다")

    print(f"  프레임    {n}장  ({args.seconds:g}초 x {args.fps}fps)")
    if sample is not None:
        print(f"  원본      {sample}  {human(sample.stat().st_size)}")
    else:
        print(f"  해상도    {args.preset} {w}x{h}  quality 80 가정  한 장 ~{kb}KB")
        print("  [!] 난수 바이트다. 크기-시간은 실제와 같지만 그림은 아니다")

    tmp = Path(tempfile.mkdtemp(prefix="floaq-bench-"))
    try:
        return run(args, tmp, n, kb, sample)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(args, tmp: Path, n: int, kb: int, sample: Path | None) -> int:
    conn = connect(":memory:", schema=SCHEMA)
    repo = SqliteRepo(conn)
    now = int(time.time())
    ship = uuid7()
    conn.execute("INSERT INTO pi_ship VALUES (?,'bench','r-b','440123456',1,0,?,?,NULL)",
                 (ship, now, now))
    acc = Accident(
        accident_id=uuid7(), ship_id=ship, status=S.DETECT,
        accident_type=AccidentType.MOB, trigger_source=TriggerSource.AI,
        report_type=ReportType.DISTRESS, report_dsc=110,
        accident_lat=35.05, accident_lon=129.10, wait_sec=30, report_due_at=None,
        model_version="bench", created_at=now, updated_at=now)
    repo.create(acc)

    store = FileStore(tmp)
    t0 = time.monotonic()
    blobs = make_frames(n, kb, sample)
    raw_total = sum(len(b) for b in blobs)

    # 실제 경로 규약대로 쓴다. BEFORE 75장 + AFTER 나머지 + 스냅샷 1장
    before = min(n, round(15 * args.fps))
    for i, data in enumerate(blobs):
        if i < before:
            ftype, seq = "BEFORE", i + 1
        else:
            ftype, seq = "AFTER", i - before + 1
        rel, size = store.save(acc.accident_id, ftype, seq, data)
        repo.add_file(accident_id=acc.accident_id, file_type=ftype, sequence_no=seq,
                      file_path=rel, camera="L" if i % 2 else "R",
                      size_bytes=size, now=now)
    rel, size = store.save(acc.accident_id, "DETECT_SNAPSHOT", None, blobs[0])
    repo.add_file(accident_id=acc.accident_id, file_type="DETECT_SNAPSHOT",
                  sequence_no=None, file_path=rel, camera="L",
                  size_bytes=size, now=now)
    t_write = time.monotonic() - t0
    print(f"\n  원본 합계  {human(raw_total)}  (쓰기 {t_write:.2f}초)")

    # ── 묶기. 상한에 걸리면 여러 덩어리가 된다 ────────────────────────
    chunks: list[bytes] = []
    t0 = time.monotonic()
    while True:
        rows = repo.pending_files_of(acc.accident_id, limit=ar.MAX_FILES)
        if not rows:
            break
        blob, packed = ar.build_tarball(acc.accident_id, rows, store, now=now)
        chunks.append(blob)
        for r in packed:                       # 담긴 것은 큐에서 뺀다
            repo.mark_uploaded(r["file_id"], "bench", now)
    t_pack = time.monotonic() - t0

    total = sum(len(c) for c in chunks)
    print(f"  타르볼     {len(chunks)}덩어리  합계 {human(total)}  (묶기 {t_pack:.2f}초)")
    for i, c in enumerate(chunks, 1):
        t = time.monotonic()
        digest = hashlib.sha256(c).hexdigest()
        print(f"    #{i}  {human(len(c))}  sha256 {time.monotonic() - t:.2f}초"
              f"  {digest[:16]}...")
    print(f"  압축률     {total / raw_total * 100:.1f}%  (JPEG 라 거의 안 줄어든다)")

    cap = ar.MAX_BYTES
    print(f"  상한       {human(cap)}  ->  {len(chunks)}회 POST")
    if len(chunks) > 1:
        print("  [!] 한 사고가 여러 요청으로 나뉜다. 서버가 사고 단위 멱등이라 정상이다")

    # ── 예상 업로드 시간 ─────────────────────────────────────────────
    UP_MBPS = 3.3                              # 실측 2026-09-18, 사내망
    print(f"\n  예상 업로드  {total / 1048576 / UP_MBPS:.1f}초  (상향 {UP_MBPS}MB/s 실측 기준)")

    if not args.upload:
        print("\n--upload 를 안 줬다. 네트워크-실DB 를 안 건드렸다")
        return 0

    return upload(args, chunks, acc.accident_id)


def upload(args, chunks: list[bytes], accident_id: str) -> int:
    """실서버로 진짜 올린다. 선박 키는 실DB 에서 읽는다."""
    import requests
    from dotenv import load_dotenv

    from floaq.adapters import ec2 as ec2mod

    load_dotenv(ROOT / ".env", override=False)
    url = os.environ.get("FLOAQ_EDGE_URL", "https://floaq.example.com").rstrip("/")

    live = connect(args.db)
    row = live.execute(
        "SELECT ship_key FROM pi_credential WHERE status = 'ACTIVE' LIMIT 1").fetchone()
    if row is None:
        sys.exit("ACTIVE 인 배가 없다. 관제 웹에서 승인할 것")

    # 🔴 벤치용 accident_id 는 서버에 없다. 실DB 의 사고를 빌린다 —
    #   없으면 404 가 날 텐데 그건 크기 측정과 무관한 실패라 헷갈린다
    real = live.execute(
        "SELECT accident_id FROM pi_accident ORDER BY created_at DESC LIMIT 1").fetchone()
    aid = real["accident_id"] if real else accident_id
    print(f"\n  올린다  {url}  사고 {aid}")

    ok = 0
    for i, c in enumerate(chunks, 1):
        digest = hashlib.sha256(c).hexdigest()
        t = time.monotonic()
        try:
            r = requests.post(
                f"{url}/api/pi/archives",
                data={"accident_id": aid, "archive_sha256": digest,
                      "created_at": str(int(time.time()))},
                files={"archive": (f"{aid}.tar.gz", c, "application/gzip")},
                headers={"X-Ship-Secret-Key": row["ship_key"]},
                timeout=(ec2mod.ARCHIVE_CONNECT_TIMEOUT, 300))
        except requests.RequestException as e:
            print(f"    #{i}  연결 실패 {type(e).__name__}  {time.monotonic() - t:.1f}초")
            continue
        dt = time.monotonic() - t
        try:
            code = r.json().get("code") or "success"
        except ValueError:
            code = "(JSON 아님 - nginx 413?)"
        speed = len(c) / 1048576 / dt if dt else 0
        print(f"    #{i}  {human(len(c))}  HTTP {r.status_code} {code}"
              f"  {dt:.1f}초  {speed:.1f}MB/s")
        if r.ok:
            ok += 1
    print(f"\n  {ok}/{len(chunks)} 성공")
    return 0 if ok == len(chunks) else 1


if __name__ == "__main__":
    sys.exit(main())

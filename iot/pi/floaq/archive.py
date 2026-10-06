"""사고 산출물 업로드. `POST /api/pi/archives` 로 타르볼을 밀어 올린다.

정본은 `docs/edge/api.json` 이다.

    pi_accident_file 에서 object_key IS NULL 인 사고를 고른다
      -> manifest.json + 이미지들을 tar.gz 하나로 묶는다
      -> multipart 로 올린다 (accident_id · archive · archive_sha256 · created_at)
      -> 서버가 풀어서 **R2 에 직접 PUT** 한다
      -> 응답의 object_key 를 로컬 행에 박는다

🔴 **Pi 는 R2 를 직접 안 본다.** 오브젝트 스토리지 자격증명이 배에 없다.
   서버가 대신 넣고 키만 돌려준다.

── 왜 `sync.py` 에 못 넣는가 ──────────────────────────────────────
전송 펌프의 `Table` 추상화와 모양이 다르다.

    | |            9개 테이블        | archives
    | 본문        | JSON 배치         | multipart/form-data
    | 커서        | sync 복합 커서     | object_key IS NULL 이 곧 큐
    | 크기        | 100KB 급          | 사고당 126장 = 수십 MB
    | 묶음 단위    | 행 BATCH개        | 사고 1건 = 타르볼 1개

크기가 결정적이다. 같은 스레드에 두면 수 MB 업로드가 도는 동안 사고 기록·신고 기록이
멈춘다. **별도 스레드**로 둔다 — 여기가 막혀도 §3 의 9개 테이블은 계속 올라간다.

── 압축 ────────────────────────────────────────────────────────────
`확정` 2026-09-21 실측: **서버가 tar.gz 를 받는다.** 실제로 200 이 왔다.

    POST /api/pi/archives 200
    (received 44 · stored 44 · duplicated 0 · failed 0)

manifest.json 스키마도 이때 같이 검증됐다 — `api.json` 이 이름만 정하고 내용을
안 정해서 우리가 아래 `manifest_entry` 모양으로 보냈고, 서버가 그대로 풀었다.

⚠ JPEG 는 이미 압축돼 있어 gzip 이 **오히려 0.8% 늘린다**(`tools/bench_archive.py`
  실측). `compresslevel=1` 이라 CPU 는 거의 안 쓰지만 이득도 없다. 무압축 tar 로
  바꾸면 그만큼 줄지만, 지금 도는 것을 건드릴 값어치는 없다.

── 중복 ────────────────────────────────────────────────────────────
⚠ 응답이 유실되면 같은 타르볼을 다시 올린다. 서버가 `duplicated` 로 세고 R2 는 같은
  키에 덮어쓰므로 안전하다. 재시도 횟수·데드레터를 따로 두지 않는 이유다.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sqlite3
import tarfile
import threading
import time
from pathlib import Path

from floaq import provision
from floaq.adapters.ec2 import Action, EdgeClient
from floaq.web.files import BadPath, FileStore

log = logging.getLogger(__name__)

#: 한 타르볼에 담을 최대 파일 수. 사고 하나가 125장 + 스냅샷 1장이라 한 번에 들어간다.
#: 더 많으면 여러 번 나눠 올린다 — 서버가 사고 단위 멱등이라 나눠도 안전하다.
MAX_FILES = 200

#: 한 타르볼 최대 바이트. 넘으면 거기서 끊고 나머지는 다음 회차에.
#:
#: 🔴 **실측 2026-09-18: 서버 `client_max_body_size` 는 20MB 다.**
#:   18MB 는 통과(401), 20MB 부터 nginx 가 413 을 준다 — JSON 이 아니라 HTML 로.
#:   multipart 경계와 폼 필드가 몇백 바이트 더 붙으므로 여유를 두고 16MB 로 잡는다.
#:
#: ⚠ 사고 하나가 126장 × 200KB = 약 25MB 라 **두 덩어리로 나뉜다.** 정상이다 —
#:   서버가 사고 단위 멱등이라 나눠 올려도 같은 결과다.
#: ⚠ 그래도 413 을 받으면 버리지 않고 반으로 줄여 다시 시도한다. 서버 설정이
#:   바뀌어도 사진을 잃지 않는다.
MAX_BYTES = 16 * 1024 * 1024

#: 413 을 받았을 때 줄이는 하한. 여기까지 내려가도 413 이면 사람이 볼 문제다.
MIN_BYTES = 1 * 1024 * 1024

#: 올릴 게 없을 때 다음 회차까지.
IDLE_SEC = 30

#: 서버 사정·연결 실패일 때의 첫 간격.
BACKOFF_SEC = 60

#: 연속 실패마다 간격을 두 배로. 여기까지만 늘린다.
#:
#: 🔴 고정 60초면 **성공할 수 없는 일을 영원히 같은 값으로 반복한다.** 서버가
#:   500 을 주는 동안 큐가 안 비므로, 60초마다 쌓인 프레임을 전부 다시 읽어
#:   gzip 한다 — 프레임이 늘수록 그 작업도 커진다. Pi 한 프로세스에 스레드가
#:   일곱 개라 그 CPU 가 HTTP 응답을 밀어낸다. 실제로 /health 가 2.5초 걸렸다.
BACKOFF_MAX_SEC = 900

#: 타르볼 안 메타 파일 이름. `api.json` 이 이름만 정하고 내용은 안 정했다.
MANIFEST = "manifest.json"

#: manifest 포맷 버전. 서버와 갈라지면 이 숫자로 판별한다.
MANIFEST_VERSION = 1


class ArchiveError(RuntimeError):
    """타르볼을 만들 수 없다."""


def manifest_entry(row: sqlite3.Row, name: str) -> dict:
    """`manifest.json` 의 항목 하나.

    응답 `IPiFileStored` 와 같은 열쇠(`file_type` · `sequence_no` · `camera`)를 담는다 —
    서버가 돌려준 `object_key` 를 로컬 행에 되짚으려면 그 셋이 있어야 한다.
    """
    return {
        "name": name,                       # 타르볼 안 경로
        "file_type": row["file_type"],
        "sequence_no": row["sequence_no"],
        "camera": row["camera"],
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "created_at": row["created_at"],
    }


def build_tarball(accident_id: str, rows, store: FileStore, *, now: int,
                  max_bytes: int = MAX_BYTES) -> tuple[bytes, list[sqlite3.Row]]:
    """`(타르볼, 실제로 담긴 행들)`.

    🔴 **`pi_accident_file.file_path` 는 상대경로다.** `FileStore` 루트 기준이고
      (`accidents/{accident_id}/{file_type}/0001.jpg`), 그냥 열면 현재 작업 디렉터리
      기준이 되어 전부 `FileNotFoundError` 다. 실제로 밟았다.

    ⚠ 담긴 행만 돌려준다. 크기 상한에 걸려 빠진 것과 파일이 사라진 것이 있어서,
      호출자가 "보낸 것"과 "보냈다고 생각한 것"을 혼동하면 안 된다.

    🔴 사라진 파일은 **건너뛰되 기록을 남긴다.** SD 카드에서 지워졌거나 경로가
      바뀐 경우다. 조용히 넘기면 그 행이 큐에 영원히 남아 뒤의 사고를 막는다.
    """
    packed: list[sqlite3.Row] = []
    entries: list[dict] = []
    buf = io.BytesIO()
    total = 0

    # ⚠ gzip 은 마지막에 한 번 건다. 안에 넣으면서 크기를 세려면 무압축이어야 한다
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for r in rows:
            try:
                path = store.resolve(r["file_path"])
                data = path.read_bytes()
            except (OSError, BadPath) as e:
                log.error("사고 %s 파일을 못 읽는다 (%s): %s — 건너뛴다",
                          accident_id, r["file_path"], type(e).__name__)
                continue
            if packed and total + len(data) > max_bytes:
                break                       # 최소 한 장은 담고 나서 자른다
            name = _member_name(r)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = r["created_at"]
            tar.addfile(info, io.BytesIO(data))
            entries.append(manifest_entry(r, name))
            packed.append(r)
            total += len(data)

        if not packed:
            raise ArchiveError(f"사고 {accident_id}: 담을 파일이 하나도 없다")

        doc = json.dumps({
            "version": MANIFEST_VERSION,
            "accident_id": accident_id,
            "created_at": now,
            "files": entries,
            "videos": [],                   # pi_video 는 아직 생성하는 코드가 없다
        }, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(doc)
        info.mtime = now
        tar.addfile(info, io.BytesIO(doc))

    import gzip  # noqa: PLC0415

    # ⚠ mtime=0 으로 고정한다. 안 그러면 같은 내용이 매번 다른 바이트가 되어
    #   sha256 이 달라지고, 서버가 재전송을 중복으로 못 알아본다
    return gzip.compress(buf.getvalue(), compresslevel=1, mtime=0), packed


def _member_name(r: sqlite3.Row) -> str:
    """타르볼 안 경로. `file_type/순번.확장자`.

    ⚠ `file_path` 를 그대로 쓰지 않는다. 절대 경로나 `..` 가 들어가면 서버가 푸는
      쪽에서 경로 탈출이 된다.
    """
    ext = Path(r["file_path"]).suffix or ".jpg"
    if r["sequence_no"] is None:
        return f"{r['file_type']}/snapshot{ext}"
    return f"{r['file_type']}/{r['sequence_no']:05d}{ext}"


class ArchivePump:
    """한 스레드가 사고를 하나씩 올린다.

    ⚠ `EdgeClient` 는 스레드 안전이 아니다. 전송 펌프와 **다른 인스턴스**를 준다.
    """

    def __init__(self, conn: sqlite3.Connection, repo, client: EdgeClient,
                 clock, ship_id: str, store: FileStore) -> None:
        self.conn = conn
        self.repo = repo
        self.client = client
        self.clock = clock
        self.ship_id = ship_id
        #: `file_path` 가 이 루트 기준 상대경로다. 없으면 파일을 못 찾는다
        self.store = store
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        #: 이번 프로세스에서 포기한 사고. 파일이 전부 사라진 경우다 —
        #: 계속 고르면 뒤의 사고가 영영 안 올라간다. 재부팅하면 다시 시도한다
        self._skip: set[str] = set()
        self._max_bytes = MAX_BYTES
        #: 연속 실패 횟수. 백오프를 두 배씩 늘리는 근거다
        self._fails = 0
        self.uploaded = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="archive", daemon=True)
        self._thread.start()
        log.info("사고 산출물 업로더 시작")

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                wait = self.round_once()
            except Exception:
                # 🔴 죽으면 사진이 영영 안 올라가는데 아무도 모른다
                log.exception("업로드 루프 오류")
                wait = BACKOFF_SEC
            self._stopping.wait(wait)

    # ── 한 회차 ──────────────────────────────────────────────────────
    def round_once(self) -> float:
        """사고 하나를 올린다. 다음 회차까지 기다릴 초."""
        if not provision.is_approved(self.conn, self.ship_id):
            return BACKOFF_SEC

        for accident_id in self.repo.pending_upload_accidents():
            if accident_id in self._skip:
                continue
            return self._upload(accident_id)
        return IDLE_SEC

    def _upload(self, accident_id: str) -> float:
        rows = self.repo.pending_files_of(accident_id, limit=MAX_FILES)
        if not rows:
            return IDLE_SEC

        now = self.clock.now()
        try:
            tarball, packed = build_tarball(accident_id, rows, self.store,
                                            now=now, max_bytes=self._max_bytes)
        except ArchiveError as e:
            # 파일이 전부 사라졌다. 이 사고를 계속 고르면 뒤가 막힌다
            log.error("%s — 이 사고를 이번 실행에서 건너뛴다", e)
            self._skip.add(accident_id)
            return 0.0

        digest = hashlib.sha256(tarball).hexdigest()
        log.info("사고 %s 산출물 %d/%d장 %.1fMB 업로드",
                 accident_id, len(packed), len(rows), len(tarball) / 1048576)

        res = self.client.post_archive(accident_id, tarball, digest, now)

        if res.action is Action.DONE:
            self._fails = 0          # 성공했다. 백오프를 되돌린다
            stored = self._apply(accident_id, res.data or {})
            self.uploaded += stored
            d = res.data or {}
            log.info("사고 %s 업로드 완료 (received %s · stored %s · duplicated %s"
                     " · failed %s) — 로컬 %d행에 키를 박았다",
                     accident_id, d.get("received"), d.get("stored"),
                     d.get("duplicated"), d.get("failed"), stored)
            if stored == 0:
                # 🔴 2xx 인데 키가 하나도 안 왔다. 다시 보내도 같은 응답이라 무한 루프다.
                #   응답 모양이 바뀐 것이므로 사람이 봐야 한다
                log.error("사고 %s: 2xx 인데 object_key 가 하나도 없다. "
                          "응답 필드를 확인할 것 (data 열쇠 %s)", accident_id, sorted(d))
                self._skip.add(accident_id)
            return 0.0                      # 남은 장이 있으면 바로 이어서

        if res.status == 413:
            # 본문이 너무 크다. 버리지 않고 **반으로 줄여** 다시 시도한다
            if self._max_bytes > MIN_BYTES:
                self._max_bytes = max(MIN_BYTES, self._max_bytes // 2)
                log.warning("413 — 타르볼 상한을 %.0fMB 로 줄인다",
                            self._max_bytes / 1048576)
                return 0.0
            log.error("최소 크기에서도 413 이다. 서버 client_max_body_size 를 확인할 것")
            self._skip.add(accident_id)
            return self._backoff()

        if res.action is Action.DROP:
            log.error("사고 %s 산출물 거부 (HTTP %d %s) — 이번 실행에서 건너뛴다",
                      accident_id, res.status, res.code)
            self._skip.add(accident_id)
            return 0.0

        if res.action is Action.HALT:
            log.error("산출물 업로드 중단 (HTTP %d %s) — 사람이 풀어야 한다",
                      res.status, res.code)
        wait = self._backoff()
        log.info("산출물 업로드 %d회째 실패. %.0f초 뒤 다시 시도한다",
                 self._fails, wait)
        return wait

    def _apply(self, accident_id: str, data: dict) -> int:
        """응답의 `object_key` 를 로컬 행에 박는다. 박은 행 수를 돌려준다.

        🔴 **키를 받은 뒤에만 박는다.** 먼저 박으면 R2 에 없는 파일이 "올라갔다"로
          보이고, 로컬 파일을 지우는 순간 영영 사라진다 (DES-31 C-8).

        ⚠ `duplicated: true` 도 박는다. 이미 R2 에 있다는 뜻이라 큐에서 빼야 한다.
        """
        now = self.clock.now()
        n = 0
        for f in data.get("files") or ():
            key = f.get("object_key")
            if not key:
                continue
            row = self.repo.file_by_slot(accident_id, f.get("file_type"),
                                         f.get("sequence_no"))
            if row is None:
                # 서버가 우리가 안 보낸 것을 돌려줬다. 앞선 회차의 잔여일 수 있다
                log.warning("사고 %s: 응답의 %s/%s 에 맞는 로컬 행이 없다",
                            accident_id, f.get("file_type"), f.get("sequence_no"))
                continue
            self.repo.mark_uploaded(row["file_id"], key, now)
            n += 1
        return n

    def _backoff(self) -> float:
        """연속 실패마다 두 배로 늘어나는 대기. 성공하면 `_fails` 를 0 으로 되돌린다.

        🔴 고정 간격이면 **성공할 수 없는 일을 영원히 같은 값으로 반복한다.**
           서버가 500 을 주는 동안 큐가 안 비므로 60초마다 쌓인 프레임을 전부
           다시 읽어 gzip 한다. 그 CPU 가 같은 프로세스의 HTTP 응답을 밀어낸다.
        """
        self._fails += 1
        return min(BACKOFF_MAX_SEC, BACKOFF_SEC * (2 ** (self._fails - 1)))

    # ── 상태 ─────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"uploaded": self.uploaded, "skipped": sorted(self._skip),
                "max_bytes": self._max_bytes, "fails": self._fails}


def wait_idle(pump: ArchivePump, timeout: float = 30.0) -> bool:
    """대기열이 빌 때까지 기다린다. 시연 스크립트와 시험에서만 쓴다."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not pump.repo.pending_upload_accidents():
            return True
        time.sleep(0.2)
    return False

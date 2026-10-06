"""사고 파일 저장소. 디스크만 안다 — DB 도 HTTP 도 모른다.

MQTT 로 실물 파일을 나르지 않는다. 사고 전 15초 · 후 10초가 125장(`FRAME_PRE_SEC` ·
`FRAME_POST_SEC` × `FRAME_FPS`)이라, retained 로 두면
브로커 RAM 에 상주하고 QoS 1 재전송 비용이 크기에 비례한다. 그동안 1Hz GPS·부표
위치가 밀린다.

경로 규칙은 `pi_accident_file` 과 R2 객체 키와 **같은 모양**으로 맞춘다:

    accidents/{accident_id}/{file_type}/{sequence_no:04d}.{ext}

그래야 로컬 경로·URL·객체 키가 서로 기계적으로 변환된다.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `pi_accident_file.file_type` CHECK 와 같은 값이어야 한다.
FILE_TYPES = ("DETECT_SNAPSHOT", "BEFORE", "AFTER")

#: 받아들일 확장자. 경로 주입을 막으려고 화이트리스트로 둔다.
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}

#: UUID v7 36자. 경로 세그먼트에 그대로 들어가므로 형태를 강제한다.
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


class BadPath(ValueError):
    """경로로 쓸 수 없는 값. **예외 메시지에 입력값을 그대로 싣지 않는다.**"""


def _check(accident_id: str, file_type: str, sequence_no: int | None) -> None:
    # 🔴 사용자 입력이 파일 경로가 되는 자리다. 셋 다 형태를 강제하지 않으면
    #    `../../etc/passwd` 같은 값이 그대로 경로 조립에 들어간다.
    if not _UUID.match(accident_id):
        raise BadPath("accident_id 형식이 아니다")
    if file_type not in FILE_TYPES:
        raise BadPath(f"모르는 file_type: {file_type!r}")
    if sequence_no is not None and not 0 <= sequence_no <= 99_999:
        raise BadPath("sequence_no 범위 밖")


class FileStore:
    """사고 파일을 디스크에 놓고 찾는다."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def relative(self, accident_id: str, file_type: str,
                 sequence_no: int | None, *, ext: str = "jpg") -> str:
        """저장 경로(상대). R2 객체 키도 이 문자열을 그대로 쓴다."""
        _check(accident_id, file_type, sequence_no)
        name = "snapshot" if sequence_no is None else f"{sequence_no:04d}"
        return f"accidents/{accident_id}/{file_type}/{name}.{ext}"

    def path(self, accident_id: str, file_type: str,
             sequence_no: int | None, *, ext: str = "jpg") -> Path:
        rel = self.relative(accident_id, file_type, sequence_no, ext=ext)
        full = (self.root / rel).resolve()
        # 🔴 조립이 끝난 뒤에도 한 번 더 본다. `_check` 를 통과한 값만 와도
        #    심볼릭 링크나 정규화 차이로 밖으로 나갈 수 있다.
        if not full.is_relative_to(self.root):
            raise BadPath("저장소 밖 경로")
        return full

    def save(self, accident_id: str, file_type: str, sequence_no: int | None,
             data: bytes, *, ext: str = "jpg") -> tuple[str, int]:
        """바이트를 쓴다. (상대경로, 크기) 를 준다.

        ⚠ 같은 자리에 다시 오면 덮어쓴다. Jetson 이 응답을 못 받고 재전송하는 경우이며,
          `SqliteRepo.add_file` 의 upsert 와 짝이 맞는다.
        """
        full = self.path(accident_id, file_type, sequence_no, ext=ext)
        full.parent.mkdir(parents=True, exist_ok=True)
        # 같은 디렉터리에 임시로 쓰고 옮긴다. 쓰는 도중에 키오스크가 읽으면
        # 반쪽짜리 JPEG 를 그린다.
        tmp = full.with_suffix(full.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(full)
        return self.relative(accident_id, file_type, sequence_no, ext=ext), len(data)

    def resolve(self, relative: str) -> Path:
        """DB 에 적힌 상대경로 -> 실제 경로. 저장소 밖이면 거부한다."""
        full = (self.root / relative).resolve()
        if not full.is_relative_to(self.root):
            raise BadPath("저장소 밖 경로")
        return full

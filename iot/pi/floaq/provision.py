"""선박 등록. 키오스크가 준 값을 서버 등록 때까지 들고 있는다.

정본은 `docs/edge/api.json` 이다 (`api.md` 는 폐기).

    키오스크 --POST /api/ship------------> Pi(여기)   name·registration_no·mmsi·has_buoy
    Pi       --POST /api/pi/ships--------> 서버       X-Ship-Register-Key (공용 등록 키)
    서버     --200 {ship_id, ship_key, status}-> Pi
    Pi       --INSERT pi_ship + pi_credential->        한 트랜잭션
    Pi       --GET /api/pi/ships/{id}----> 서버       X-Ship-Secret-Key. ACTIVE 될 때까지

🔴 **`ship_id` 를 받기 전에는 `pi_ship` 행을 만들지 않는다.** 임시 uuid 로 먼저 만들고
   나중에 서버 값으로 바꾸면 두 가지가 동시에 깨진다.

     - `pi_accident.ship_id` 가 FK 다. 그 사이 생긴 사고가 전부 고아가 된다
     - MQTT 토픽이 전부 `ship/{ship_id}/...` 다. 키오스크·Jetson 구독이 통째로 어긋난다

   그래서 대기 값은 DB 가 아니라 **파일**에 둔다. `pi_ship` 은 PK 가 NOT NULL 이라
   애초에 `ship_id` 없는 행을 담을 수 없고, 담으려고 컬럼을 NULL 허용으로 풀면
   위 FK 가 같이 풀린다.

🔴 **`ship_key` 는 등록 응답에 한 번만 온다.** 서버가 해시로만 보관해 다시 보여주지
   못한다(의도된 설계). 받는 즉시 `pi_credential` 에 쓰지 않으면 그 배는 영영 못 붙는다.

⚠ 등록은 배 한 척에 **한 번**이다. 재시도는 많아도 성공은 한 번뿐이라, 대기 파일은
  성공하는 순간 지워진다. 남아 있으면 곧 "아직 등록 안 됨"이라는 뜻이다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: MMSI 9자리. `pi_ship` 의 CHECK 와 같은 규칙이다 — 선행 0 이 유효해서 TEXT 다.
MMSI_RE = re.compile(r"^[0-9]{9}$")

#: 선박 이름·번호 길이 상한. `api.json` 의 IPiShipRegisterRequest 와 같다.
#: 서버가 400 을 줄 값을 Pi 가 먼저 막는다 — 인터넷이 없을 때도 즉시 알려줘야 한다.
NAME_MAX = 64
REGISTRATION_MAX = 20


class InvalidShip(ValueError):
    """등록 값이 규격에 안 맞는다. 400 으로 돌려준다."""


@dataclass(frozen=True, slots=True)
class ShipRegistration:
    """키오스크가 보내는 값. `IPiShipRegisterRequest`(api.json)와 같은 모양이다.

    `ship_id` 는 여기 없다 — 서버가 발급한다.
    """

    name: str
    #: 🔴 **필수다.** 서버 멱등의 자연키라 이게 없으면 재시도마다 배가 늘어난다.
    #:   §3.3 의 SA 등록에서는 선택이었지만 Pi 등록에서는 필수로 갈렸다.
    registration_no: str
    #: 🔴 **필수다.** DSC·AIS 가 전파에 싣는 자기 식별자의 원본이다.
    mmsi: str
    has_buoy: bool = True

    def __post_init__(self) -> None:
        if not (self.name or "").strip():
            raise InvalidShip("선박 이름은 필수다")
        if len(self.name) > NAME_MAX:
            raise InvalidShip(f"선박 이름은 {NAME_MAX}자 이하")
        if not (self.registration_no or "").strip():
            raise InvalidShip("선박 번호는 필수다 — 서버 멱등의 자연키다")
        if len(self.registration_no) > REGISTRATION_MAX:
            raise InvalidShip(f"선박 번호는 {REGISTRATION_MAX}자 이하")
        # 🔴 MMSI 는 여기서 막는다. 틀린 값이 들어가면 DSC·AIS 가 그대로 전파에 싣고,
        #   해도에는 멀쩡히 뜨기 때문에 시연 때까지 아무도 모른다.
        if not MMSI_RE.match(self.mmsi or ""):
            raise InvalidShip("MMSI 는 숫자 9자리")


class PendingShip:
    """등록 대기 값을 파일 하나로 관리한다.

    ⚠ 쓰기는 `.part` 에 쓰고 rename 한다. 쓰는 도중 전원이 끊기면 반쪽짜리 JSON 이
      남고, 다음 부팅에서 파싱이 깨져 등록을 영영 못 한다.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> ShipRegistration | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as e:
            # 손상된 파일 때문에 기동이 죽으면 안 된다. 없는 것으로 보고 다시 받는다
            log.error("등록 대기 파일이 깨졌다 (%s). 키오스크에서 다시 등록할 것", e)
            return None
        try:
            return ShipRegistration(**raw)
        except (TypeError, InvalidShip) as e:
            log.error("등록 대기 값이 규격에 안 맞는다: %s", e)
            return None

    def write(self, reg: ShipRegistration) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(reg), ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def register_ship(conn, ship_id: str, ship_key: str, status: str,
                  reg: ShipRegistration, now: int) -> None:
    """서버가 `(ship_id, ship_key, status)` 를 준 뒤에만 부른다. 한 트랜잭션으로 쓴다.

    🔴 **둘이 따로 저장되면 안 된다.** `pi_ship` 만 들어가고 `ship_key` 가 빠지면
      배는 등록됐는데 아무것도 못 올리고, 키는 **다시 안 내려오므로** 복구도 없다.

    ⚠ 이미 있으면 아무것도 하지 않는다 — 응답을 두 번 받는 경우(재시도 중에 첫 응답이
      늦게 도착)가 정상 경로다. 이때 서버는 같은 `ship_id` 를 돌려준다(registration_no 멱등).
    """
    with conn:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT OR IGNORE INTO pi_ship (ship_id, name, registration_no, mmsi,"
            " has_buoy, is_deleted, created_at, updated_at)"
            " VALUES (?,?,?,?,?,0,?,?)",
            (ship_id, reg.name, reg.registration_no, reg.mmsi,
             1 if reg.has_buoy else 0, now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO pi_credential"
            " (ship_id, ship_key, status, issued_at, updated_at) VALUES (?,?,?,?,?)",
            (ship_id, ship_key, status, now, now),
        )


def set_status(conn, ship_id: str, status: str, now: int) -> None:
    """`GET /api/pi/ships/{shipId}` 폴링 결과를 반영한다.

    ⚠ 키는 건드리지 않는다. 상태만 바뀐다.
    """
    conn.execute(
        "UPDATE pi_credential SET status = ?, updated_at = ? WHERE ship_id = ?",
        (status, now, ship_id))


def credential(conn, ship_id: str) -> tuple[str, str] | None:
    """`(ship_key, status)` 또는 None(아직 등록 전).

    🔴 `ship_key` 를 로그에 찍지 않는다. 호출부에서도 값을 출력하지 말 것 — 있는지
      없는지만 찍는다. 다시 받을 방법이 없다.
    """
    row = conn.execute(
        "SELECT ship_key, status FROM pi_credential WHERE ship_id = ?",
        (ship_id,)).fetchone()
    return (row["ship_key"], row["status"]) if row else None


def is_approved(conn, ship_id: str) -> bool:
    """승인됐나. `WAIT` 동안에는 등록 말고 아무것도 못 올린다."""
    cred = credential(conn, ship_id)
    return cred is not None and cred[1] == "ACTIVE"


def registered_ship(conn) -> tuple[str, str, str | None] | None:
    """등록된 배 하나. `(ship_id, name, mmsi)` 또는 None.

    🔴 **선박 키가 있는 배를 먼저 고른다.** 개발 중에 만든 시험용 배가 섞여 있을 때
      단순히 첫 행을 쓰면 키 없는 배를 잡고, 등록 루프가 "재등록 필요" 로 멈춘다.
      서버가 발급한 키를 가진 행이 곧 진짜 등록된 배다.

    ⚠ 배 한 척 전제다. 여러 행이면 경고한다 — 옛 사고가 FK 로 붙어 있어 그냥 지울 수
      없으니, 개발 DB 에서는 실제로 섞인다.
    """
    # 🔴 `AS` 로 컬럼명을 못 박는다. `s.ship_id` 처럼 테이블 별칭을 붙이면 SQLite
    #   빌드에 따라 결과 컬럼명이 `ship_id` 이기도 `s.ship_id` 이기도 하다
    #   (short_column_names 기본값 차이). row["ship_id"] 가 IndexError 로 터진다 —
    #   실제 Pi 에서 밟았다.
    rows = conn.execute(
        "SELECT s.ship_id AS ship_id, s.name AS name, s.mmsi AS mmsi,"
        "       (SELECT 1 FROM pi_credential c WHERE c.ship_id = s.ship_id) AS keyed"
        "  FROM pi_ship s WHERE s.is_deleted = 0"
        " ORDER BY keyed IS NULL, s.created_at, s.ship_id").fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        log.warning("pi_ship 에 배가 %d척 있다. 키가 있는 쪽을 쓴다 — 나머지는 지울 것",
                    len(rows))
    r = rows[0]
    return r["ship_id"], r["name"], r["mmsi"]

"""DB 를 새로 만들고 테스트 선박을 등록한다. 개발용.

`scripts/dev.ps1 reset` 과 `scripts/dev.sh reset` 이 이걸 부른다.

⚠ 인라인 스크립트(`python - <<EOF`)로 두지 않는 이유:
  dev.ps1 은 UTF-8 **with BOM** 이어야 PowerShell 5.1 이 한글을 제대로 읽는데,
  그 BOM 이 파이프로 넘어가면서 파이썬이
    SyntaxError: invalid non-printable character U+FEFF
  로 죽었다. 파일로 분리하면 BOM 이 섞일 자리가 없다.

⚠ 실선박 등록은 부록 C 절차(SUPER_ADMIN 이 관제 웹에서 등록)를 따른다.
  이건 개발 편의용이고 운영에 쓰지 않는다.

🔴 **`ship_id` 는 서버가 발급한다** (EC2 `api.md` §3.3 `POST /api/ships`).
  웹에 **이름·선박번호·MMSI 세 개**를 등록하면 서버가 uuid v7 을 만들어 돌려준다.
  그 값을 `--ship-id` 로 넣어라. 안 넣으면 여기서 uuid 를 만드는데, **그 배는
  서버에 없어서 Edge 전송이 전부 404 `EDGE_SHIP_UNKNOWN` 이다.**
  MQTT 는 잘 도는데 EC2 만 안 붙으므로 원인을 찾기 어렵다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters.sqlite import connect
from floaq.ids import uuid7


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--schema", default=str(Path(__file__).resolve().parents[3] / "database" / "pi.sql"))
    p.add_argument("--db", default="floaq.db")
    p.add_argument("--ship-id", default=None,
                   help="POST /api/ships 가 돌려준 shipId. 없으면 로컬 uuid (개발 전용)")
    p.add_argument("--name", default="테스트선박", help="선박 이름")
    p.add_argument("--registration-no", default="12-345", help="선박 번호")
    p.add_argument("--mmsi", default="440123456", help="MMSI 9자리")
    args = p.parse_args()

    ship_id = args.ship_id
    if ship_id is None:
        ship_id = uuid7()
        # 콘솔이 cp949 면 기호가 깨진다. 경고문에 기호를 쓰지 않는다
        print("[경고] ship_id 를 로컬에서 만들었다. 서버에 없는 배라 Edge 전송은"
              " 404 EDGE_SHIP_UNKNOWN 이 된다. 개발용으로만 쓸 것", file=sys.stderr)

    now = int(time.time())
    conn = connect(args.db, schema=args.schema)
    # 🔴 컬럼을 이름으로 쓴다. 위치 INSERT 는 pi_ship 에 컬럼이 하나 늘면
    #   has_buoy 자리에 created_at 이 들어가고도 STRICT 를 통과한다(둘 다 INTEGER).
    conn.execute(
        "INSERT INTO pi_ship (ship_id, name, registration_no, mmsi,"
        " has_buoy, is_deleted, created_at, updated_at)"
        " VALUES (?,?,?,?,1,0,?,?)",
        (ship_id, args.name, args.registration_no, args.mmsi, now, now),
    )
    conn.close()

    # dev 스크립트가 이 파일을 읽어 SHIP_ID 를 공유한다
    Path(".ship_id").write_text(ship_id, encoding="utf-8")
    print(ship_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

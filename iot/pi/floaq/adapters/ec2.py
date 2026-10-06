"""EC2 `/api/pi/**` 클라이언트.

정본은 `docs/edge/api.json`(OpenAPI, 서버 코드에서 생성) 이다. `api.md` 는 **폐기**다 —
경로(`/api/edge/**`)·헤더 이름·필수 필드가 전부 달라서 그걸 보고 짜면 401 이 난다. 여기서 중요한 건 **응답을 어떻게 해석하느냐**지
어떻게 보내느냐가 아니다 — 보내는 건 JSON POST 한 줄이고, 틀리면 조용히 데이터를
잃는 건 해석 쪽이다.

🔴 **2xx 를 받기 전에는 워터마크를 전진시키지 않는다.** 전송 시점이 아니라 저장 확정
   시점이다(`database/pi.sql` `sync`). 먼저 전진시키면 서버가 못 받은 행이 영영 재전송
   대상에서 빠지고, 그 손실은 아무 로그도 남기지 않는다.

🔴 **모든 오류를 "재시도"로 뭉개면 안 된다.** 401(키 문제)·404 `EDGE_SHIP_UNKNOWN`
   (설정 문제)은 몇 번을 보내도 안 풀리는데, 재시도하면 좁은 어선 상향 대역과 로그만
   태운다. 반대로 400 을 전부 "폐기"로 뭉개면 서버가 구버전일 때 Pi 의 모든 전송이
   폐기된다.

인증이 **두 단계**다. 한 요청에 키는 하나다.

    ① POST /api/pi/ships          X-Ship-Register-Key   공용 등록 키. ship_id 없음
    ②③ 그 밖의 전부               X-Ship-Secret-Key     등록으로 받은 선박 키

⚠ 키를 로그에 찍지 않는다. 만료가 없는 공유 시크릿이라 한 번 새면 재발급밖에 없다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

log = logging.getLogger(__name__)

#: 연결·읽기 타임아웃(초). 🔴 `requests` 는 기본이 **무한 대기**다. 안 주면 EC2 가
#: 응답을 안 줄 때 전송 스레드가 영영 멈추고, 사고가 나도 아무것도 안 올라간다.
TIMEOUT: tuple[float, float] = (5.0, 20.0)

#: 한 배치 최대 원소 수. `api.json` 에 상한이 없어 보수적으로 잡은 값이다.
#: 선박 위치가 원소당 200바이트 남짓이라 5,000건이 1MB 근처인데, 여유를 크게 둔다.
BATCH_LIMIT = 500

#: 타르볼 읽기 타임아웃. 사고 하나가 수 MB 라 일반 요청의 20초로는 모자라다.
#:
#: ⚠ 길게 잡을수록 인터넷이 반쯤 죽었을 때 업로드 스레드가 그만큼 서 있는다.
#:   그래서 업로드는 전송 펌프와 **다른 스레드**다 — 여기가 막혀도 사고 기록은 올라간다.
ARCHIVE_READ_TIMEOUT = 120.0

#: 타르볼 **연결** 타임아웃.
#:
#: 🔴 이름이 connect 지만 requests/urllib3 는 이 값을 **본문을 보내는 동안의 소켓
#:   타임아웃**으로도 쓴다. 읽기 타임아웃은 응답을 기다릴 때만 걸린다.
#:   그래서 여기에 일반 요청의 5초를 쓰면, 업로드가 5초를 넘는 순간 전부
#:   `TimeoutError('The write operation timed out')` 으로 죽는다.
#:
#:   실측 2026-09-18: 상향 약 3.3MB/s. 16MB 가 4.8초라 5초 벽에 정확히 걸렸다.
#:   증상이 "연결 실패"로 보여서 서버 문제로 오해하기 쉽다 — 실제로 오해했다.
ARCHIVE_CONNECT_TIMEOUT = 60.0


class Action(Enum):
    """응답을 받은 뒤 Pi 가 할 일. `docs/ec2.md` §3 재시도 표와 같다."""

    DONE = "DONE"        # 2xx. 워터마크 전진
    RETRY = "RETRY"      # 서버 사정. 백오프 후 같은 배치를 다시 (같은 PK 라 안전)
    DEFER = "DEFER"      # 순서 문제. 선행 행을 먼저 보내고 다시
    DROP = "DROP"        # 형식 오류. 몇 번 보내도 같다 — 실패 표시하고 넘어간다
    HALT = "HALT"        # 사람이 풀어야 한다. 큐는 비우지 않고 쌓아 둔다


#: 오류 코드 → 동작. 여기 없는 코드는 HTTP 상태로 판정한다.
#:
#: ⚠ `api.json` 에는 오류 코드가 없다. 아래는 **실측**이다 (2026-09-17).
#:   문서가 적은 `EDGE_*` 는 서버에 없고 실제로는 `PI_*` 다. 옛 이름도 같이 둔다 —
#:   서버가 바꿔도 조용히 오분류되지 않게.
_BY_CODE: dict[str, Action] = {
    # ── 실측 ─────────────────────────────────────────────────────────
    # 401. 틀린 키·키 없음·등록 키로 데이터 전송·선박 키로 등록 전부 이것이다.
    # 재시도하면 좁은 상향 대역과 서버 로그만 태운다
    "PI_UNAUTHORIZED": Action.HALT,
    # 404. 그 선박이 서버에 없다. ship_id 설정 문제라 재시도해도 안 풀린다.
    # ⚠ 남의 ship_id 를 조회해도 이것이 온다 — 키가 곧 선박 증명이라
    #   "권한 없음"이 아니라 "없는 배"로 답한다 (존재를 안 알린다)
    "PI_SHIP_UNKNOWN": Action.HALT,
    # 400. 형식 오류. 몇 번 보내도 같다
    "COMMON_INVALID_INPUT": Action.DROP,
    # 🔴 400. 봉투 `v` 를 서버가 모른다 (`BE/global/error/ErrorCode.java:65`,
    #   `PiController.java:232` "행을 버리지 않고 전송만 멈춘다"). 여기 없으면 아래
    #   `classify` 가 400 → DROP 으로 떨어뜨려 **배치를 지운다** — 버전을 맞추면 다시
    #   보낼 수 있는 행이다. 옛 이름 `EDGE_UNSUPPORTED_VERSION` 만 있었다 (2026-09-23)
    "PI_UNSUPPORTED_VERSION": Action.HALT,

    # ── 문서에만 있는 이름 (api.json §4, 서버 미구현) ────────────────
    "EDGE_UNSUPPORTED_VERSION": Action.HALT,
    "EDGE_SHIP_UNKNOWN": Action.HALT,
    "ACCIDENT_NOT_FOUND": Action.DEFER,
    "ACCIDENT_ALREADY_ACTIVE": Action.RETRY,
    # 🔴 승인 대기는 **오류가 아니라 상태**다. HALT 로 두면 사람이 관제 웹에서
    #   승인해도 Pi 가 영영 안 보낸다. 큐를 쥐고 긴 간격으로 다시 시도한다.
    #   ⚠ 서버는 현재 이 자리에 500 COMMON_INTERNAL_ERROR 를 준다(실측). 500 은
    #     아래에서 RETRY 라 동작은 같지만, 진짜 장애와 구분이 안 된다. 403 + 전용
    #     코드로 바꿔달라고 요청해 둔 상태다
    "EDGE_SHIP_NOT_APPROVED": Action.RETRY,
    "PI_SHIP_NOT_APPROVED": Action.RETRY,
    "SHIP_NOT_APPROVED": Action.RETRY,
}


@dataclass(frozen=True, slots=True)
class EdgeResult:
    """한 번의 전송 결과."""

    action: Action
    status: int                      #: HTTP 상태. 0 이면 응답을 못 받았다
    code: str | None = None          #: `ErrorResponse.code`
    message: str | None = None
    received: int = 0
    inserted: int = 0
    duplicated: int = 0
    stale: int = 0
    #: 거절된 원소들. `[{"index": 17, "id": "...", "code": "..."}]`
    failed: tuple[dict, ...] = ()
    #: 성공 응답의 `data` 원본. 수신 요약(received/inserted/…) 말고 다른 것을 돌려주는
    #: 엔드포인트(선박 등록의 `ship_id`)를 위해 그대로 들고 있는다.
    #: ⚠ **객체가 아닐 수 있다.** `/api/ocean/observations` 는 배열을 준다
    data: dict | list | None = None

    @property
    def ok(self) -> bool:
        return self.action is Action.DONE


def classify(status: int, code: str | None) -> Action:
    """HTTP 상태 + 오류 코드 → 동작.

    코드가 상태보다 구체적이라 코드를 먼저 본다 — 같은 404 라도
    `ACCIDENT_NOT_FOUND`(보류)와 `EDGE_SHIP_UNKNOWN`(중단)은 정반대다.
    """
    if 200 <= status < 300:
        return Action.DONE
    if code in _BY_CODE:
        return _BY_CODE[code]
    if status in (401, 403):
        # 키 문제. 재시도하면 좁은 상향 대역과 서버 로그만 태운다.
        # ⚠ 승인 대기(403)는 위 코드 표에서 이미 RETRY 로 빠졌다
        return Action.HALT
    if status in (400, 409, 413, 415, 422):
        return Action.DROP
    # 0(연결 실패·타임아웃) 과 5xx. 서버 사정이라 같은 PK 로 다시 보내면 된다
    return Action.RETRY


class EdgeClient:
    """`https://floaq.example.com` 의 `/api/pi/**`.

    ⚠ 스레드 하나에서만 쓴다. `requests.Session` 은 스레드 안전이 보장되지 않는다.
    """

    #: 등록 전용 공용 키. `POST /api/pi/ships` 에만 쓴다
    REGISTER_HEADER = "X-Ship-Register-Key"
    #: 등록으로 받은 선박 키. 그 밖의 전부
    SECRET_HEADER = "X-Ship-Secret-Key"

    def __init__(self, base_url: str, *, register_key: str = "",
                 ship_key: str = "", timeout: tuple[float, float] = TIMEOUT) -> None:
        """둘 중 하나는 있어야 한다. 등록 전이면 `register_key`, 등록 후면 `ship_key`.

        ⚠ 빈 키로 붙으면 전부 401 인데 "키가 없다"인지 "틀리다"인지 응답만 보고는
          못 가른다. 여기서 먼저 막는다.
        """
        if not register_key and not ship_key:
            raise ValueError("register_key 나 ship_key 중 하나는 있어야 한다")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        #: 서버가 마지막으로 **대답한** 시각 (`time.monotonic`). 0 이면 아직 없다.
        #:
        #: 🔴 응답 코드는 안 본다. 401 이든 409 든 대답이 왔으면 인터넷은 살아
        #:    있다. 이 값 하나로 `pi/device/status.internet` 을 낸다 — 키오스크가
        #:    '신고 불가' 를 명시할 근거다. 성공만 세면 보낼 게 없는 동안
        #:    인터넷이 끊긴 것으로 보인다.
        self.last_ok_at: float = 0.0
        self._s = requests.Session()
        self._s.headers["Content-Type"] = "application/json"
        if ship_key:
            self.use_ship_key(ship_key)
        elif register_key:
            self._s.headers[self.REGISTER_HEADER] = register_key

    def use_ship_key(self, ship_key: str) -> None:
        """등록으로 받은 선박 키로 갈아탄다.

        🔴 **등록 키를 지운다.** 남겨 두면 공용 키의 유출 표면만 늘고, 그 키를 회전할 때
          이미 등록된 배를 전부 건드려야 한다. 그리고 한 요청에 키는 하나다.
        """
        self._s.headers.pop(self.REGISTER_HEADER, None)
        self._s.headers[self.SECRET_HEADER] = ship_key

    @property
    def has_ship_key(self) -> bool:
        return self.SECRET_HEADER in self._s.headers

    def close(self) -> None:
        self._s.close()

    # ── 전송 ─────────────────────────────────────────────────────────
    def post(self, path: str, payload: dict) -> EdgeResult:
        """JSON 한 번 보내고 결과를 해석한다. **예외를 밖으로 내보내지 않는다.**

        전송 루프가 예외로 죽으면 사고가 나도 아무것도 안 올라간다. 연결 실패는
        정상 경로다 — 어선은 인터넷이 끊겼다 붙었다 한다.
        """
        url = f"{self.base_url}{path}"
        try:
            r = self._s.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            # 키가 헤더에 있으므로 예외 본문을 그대로 찍지 않는다
            log.warning("EC2 %s 연결 실패: %s", path, type(e).__name__)
            return EdgeResult(action=Action.RETRY, status=0, message=type(e).__name__)
        return self._read(path, r)

    def post_archive(self, accident_id: str, tarball: bytes, sha256: str,
                     created_at: int) -> EdgeResult:
        """`POST /api/pi/archives`. 사고 산출물 타르볼 한 덩어리.

        서버가 풀어서 **R2 에 직접 올린다** — Pi 는 R2 를 안 본다. 배에 오브젝트
        스토리지 자격증명을 두지 않으려는 구조다 (`api.json`).

        🔴 **`Content-Type` 을 세션에서 빼고 보낸다.** 세션 기본값이
           `application/json` 인데, 그대로 두면 requests 가 만든 multipart 경계
           (`boundary=...`)를 덮어써서 서버가 본문을 파싱하지 못한다.
           증상이 400 한 줄이라 원인이 안 보인다.

        🔴 **connect 타임아웃도 같이 늘린다.** requests 는 그 값을 본문 전송 중의
           소켓 타임아웃으로도 쓴다. 5초로 두면 16MB 부터 전부
           `TimeoutError('The write operation timed out')` 이고, 서버가 끊은 것처럼
           보인다 (실측 2026-09-18).
        """
        url = f"{self.base_url}/api/pi/archives"
        headers = {k: v for k, v in self._s.headers.items()
                   if k.lower() != "content-type"}
        try:
            r = requests.post(
                url,
                data={"accident_id": accident_id, "archive_sha256": sha256,
                      "created_at": str(created_at)},
                files={"archive": (f"{accident_id}.tar.gz", tarball,
                                   "application/gzip")},
                headers=headers,
                timeout=(ARCHIVE_CONNECT_TIMEOUT, ARCHIVE_READ_TIMEOUT),
            )
        except requests.RequestException as e:
            log.warning("EC2 /api/pi/archives 연결 실패: %s", type(e).__name__)
            return EdgeResult(action=Action.RETRY, status=0, message=type(e).__name__)
        return self._read("/api/pi/archives", r)

    def _read(self, path: str, r: requests.Response) -> EdgeResult:
        # 여기까지 왔으면 서버가 대답했다 = 인터넷이 있다 (`last_ok_at` 참고)
        self.last_ok_at = time.monotonic()
        try:
            body = r.json()
        except ValueError:
            # nginx 가 먼저 끊으면 JSON 이 아니라 HTML 이 온다 (413 응답)
            log.warning("EC2 %s HTTP %d — JSON 아님 (%s)",
                        path, r.status_code, r.text[:80])
            return EdgeResult(action=classify(r.status_code, None), status=r.status_code)

        if r.ok and body.get("success"):
            d = body.get("data")
            # ⚠ data 가 객체라는 보장이 없다. `/api/ocean/**` 는 배열이나 null 을
            #   준다 — 예전에는 `or {}` 로 받아 놓고 바로 .get 을 불러서, 배열이
            #   오면 AttributeError 로 전송 루프가 통째로 죽었다
            summary = d if isinstance(d, dict) else {}
            return EdgeResult(
                action=Action.DONE, status=r.status_code, data=d,
                received=summary.get("received", 0),
                inserted=summary.get("inserted", 0),
                duplicated=summary.get("duplicated", 0),
                stale=summary.get("stale", 0))

        code = body.get("code")
        action = classify(r.status_code, code)
        # `failed` 가 없으면 배치의 나머지를 버릴지 다시 보낼지 알 수 없다 (`docs/ec2.md` §3).
        # 서버가 아직 안 싣고 있어 빈 튜플이 정상이다 — 그때는 배치 전체가 한 덩어리다
        failed = tuple(body.get("failed") or ())
        log.warning("EC2 %s HTTP %d %s -> %s (failed %d건)",
                    path, r.status_code, code, action.value, len(failed))
        return EdgeResult(action=action, status=r.status_code, code=code,
                          message=body.get("message"), failed=failed)

    # ── 선박 등록 ────────────────────────────────────────────────────
    def register_ship(self, reg) -> tuple[tuple[str, str, str] | None, EdgeResult]:
        """`POST /api/pi/ships`. `(ship_id, ship_key, status)` 를 받는다.

        🔴 **`ship_key` 는 여기서만 내려온다.** 서버가 해시로만 보관해 다시 못 준다.
          받는 즉시 영속 저장해야 하므로, 호출부는 응답을 받자마자 DB 에 쓴다 —
          중간에 로그를 찍거나 다른 일을 하지 않는다.

        ⚠ 봉투(`envelope`)를 쓰지 않는다. 단건이고 배치가 성립하지 않는다.
        ⚠ 멱등키는 `registration_no` 다. 응답이 유실돼 다시 보내도 같은 `ship_id` 가 온다.
        """
        res = self.post("/api/pi/ships", {
            "name": reg.name,
            "registration_no": reg.registration_no,
            "mmsi": reg.mmsi,
            "has_buoy": reg.has_buoy,
        })
        if not res.ok:
            return None, res

        d = res.data or {}
        ship_id, ship_key, status = d.get("ship_id"), d.get("ship_key"), d.get("status")
        if not ship_id or not ship_key:
            # 🔴 거의 항상 **같은 registration_no 로 재등록**한 경우다. 서버는 그때
            #   같은 ship_id 를 주되 ship_key 는 null 로 준다 — 키는 한 번만 내려간다.
            #   DB 를 지웠으면 그 등록번호는 못 쓴다. 새 번호로 등록해야 한다.
            #   값은 찍지 않는다. 어느 키가 왔는지만 남긴다
            log.error("선박 등록 응답에 ship_key 가 없다 (받은 키 %s). "
                      "같은 등록번호로 다시 등록하면 서버가 키를 주지 않는다 — "
                      "**새 registration_no** 로 등록할 것", sorted(d))
            return None, EdgeResult(action=Action.HALT, status=res.status,
                                    code="NO_SHIP_KEY")
        return (str(ship_id), str(ship_key), str(status or "WAIT")), res

    def ship_status(self, ship_id: str) -> tuple[str | None, EdgeResult]:
        """`GET /api/pi/ships/{shipId}`. 승인 상태를 폴링한다. 선박 키로 부른다.

        ⚠ 주기는 Pi 가 정한다. 초 단위 긴급도가 아니다 — 사람이 관제 웹에서
          승인 버튼을 누르는 걸 기다리는 것이다.
        ⚠ `REJECTED` 는 자동 재시도로 안 풀린다. 사람이 고쳐서 다시 신청해야 한다.
        """
        url = f"{self.base_url}/api/pi/ships/{ship_id}"
        try:
            r = self._s.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("승인 상태 조회 연결 실패: %s", type(e).__name__)
            return None, EdgeResult(action=Action.RETRY, status=0,
                                    message=type(e).__name__)
        res = self._read(f"/api/pi/ships/{ship_id}", r)
        if not res.ok:
            return None, res
        return (res.data or {}).get("status"), res


def envelope(request_id: str, ts: int, data: list[Any], *, v: int = 1) -> dict:
    """`api.json` IPiEnvelope 공통 봉투. MQTT `Request<T>` 와 같은 모양이다.

    ⚠ `data` 는 **항상 배열**이다. 단건도 길이 1 — 두절 복귀 때 밀린 것이 한꺼번에
      오는데 건당 요청이면 그 순간 요청 폭주다.
    """
    return {"request_id": request_id, "v": v, "ts": ts, "data": data}

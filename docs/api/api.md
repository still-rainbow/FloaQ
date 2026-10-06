# FloaQ REST API 설계

| | |
|---|---|
| 상태 | **설계 초안 (2026-09-17 갱신)** — `/api/ocean/**` 만 구현됨. §4 Pi 는 `database/pi.sql` 대조 완료 |
| Jira | floaq-105 엔드포인트 · floaq-106 스키마 · floaq-107 에러 코드 · floaq-108 Swagger |
| 코드 기준 | `global/response/ApiResponse` · `ErrorResponse` · `global/error/ErrorCode` · `db/migration/V1__init.sql` |
| 실행 중 명세 | Swagger UI `/swagger-ui.html` (local 프로파일) — **구현된 것만** 보인다. 설계는 이 문서가 원본이다. prod 는 `application-prod.yml` 이 api-docs·UI 둘 다 닫는다 |

각 엔드포인트의 **상태** 표기

| 표기 | 뜻 |
|---|---|
| `구현` | 코드에 있다. Swagger 로 확인 가능 |
| `설계` | 이 문서로 확정. 구현 대기 |
| `제안` | 테이블·컬럼이 아직 없거나 다른 팀 합의가 필요하다. §8·§9 참고 |

---

## 0. 한눈에

```
관제 웹 (브라우저)  ──HTTPS /api/**       JWT            camelCase · ISO-8601
                    ──WSS   /ws           첫 메시지 AUTH  camelCase
Raspberry Pi       ──HTTPS /api/pi/**  X-Ship-*-Key  snake_case · Unix 초
선내 kiosk         ──HTTPS /api/ocean/**  CORS · 조회 공개 · 수집 유발만 X-Floaq-Kiosk-Key (§1.1)
운영               ──      /actuator/**  9090, 127.0.0.1
```

| 원칙 | 이유 |
|---|---|
| **Pi 가 권위, 서버는 받아 적는다** | 인터넷이 끊겨도 감지·신고·종결이 선내에서 돌아야 한다(계획.md §9.2). 서버는 사고를 만들거나 상태를 바꾸지 않는다 |
| **Pi 가 발급한 PK 를 그대로 쓴다** | 재전송 멱등. 서버가 채번하면 두절 복귀 때 행이 두 개가 된다 |
| **관제의 제어는 요청이지 상태 변경이 아니다** | 웹의 사고 종료는 Pi 에게 가는 명령이다. Pi 의 ack 전에는 "요청함"과 "종료됨"을 구분해 보여준다(§3.5) |
| **"값 없음"과 "수집 안 됨"을 가른다** | 빈 200 은 두 경우를 뭉갠다. 후자는 503 이다(§5) |

---

## 0.1 IoT 팀이 먼저 읽을 것

### 참조 문서 경로

| 이 문서의 표기 | 실제 위치 | 비고 |
|---|---|---|
| `계획.md §…` | **웹 팀 내부 설계 문서** (저장소에 없음) | **찾지 않아도 된다.** 인용은 출처 표시이고, 지켜야 할 규칙은 이 문서 본문에 문장으로 적혀 있다 |
| `docs/edge/mqtt.md` | `docs/edge/mqtt.md` (`dev-iot`) | IoT 팀 문서 |
| `database/pi.sql` | `database/pi.sql` (`dev-iot`) | IoT 팀 스키마 |
| `ref/mqtt-연동-웹_v2` | 저장소 밖 — 2026-09-16 에 웹 팀이 받은 사본 | |

### 붙기 전에 받아야 하는 값

**이 넷이 틀리면 조용히 실패한다.** `ship_id` 는 특히 그렇다 — `docs/edge/mqtt.md` §7 #7 이 *"값이 틀리면 브로커가 아무 에러도 주지 않고 조용히 아무것도 오지 않는다"* 고 적은 그 값이다.

| | 값 | 어떻게 받나 |
|---|---|---|
| **서버 주소** | 배포 `https://floaq.example.com` · 로컬 `http://localhost:8080` | nginx `location /api/` 가 백엔드로 넘긴다. `client_max_body_size 40m` |
| **등록 키** | `openssl rand -hex 32` | **웹 팀이 만들어 전달한다.** EC2 `.env` 의 `FLOAQ_PI_ENROLL_KEY`. **`POST /api/pi/ships` 에만** 쓴다 |
| **선박 키** | 서버 발급 | **등록 응답으로 받는다.** 그 뒤 모든 Pi 요청은 이 키다. 🔴 한 번만 내려가니 **받는 즉시 영속 저장** |
| **`ship_id`** | uuid v7 | **서버가 발급한다.** 선박 키와 함께 등록 응답으로 온다(§4.3) — 사람이 옮겨 적지 않는다 |

- ⚠ **HTTPS 전용.** 키가 헤더에 평문으로 실린다. 로컬 개발 외에는 `http` 로 붙지 않는다.
- 🔴 **`ship_id` 를 Pi 가 스스로 만들면 안 된다.** 현재 IoT 쪽은 *"실행할 때마다 새로 발급"*(`mqtt-연동-웹_v2` §12)인데, 그 값으로 올리면 **전부 404 `PI_SHIP_UNKNOWN`** 이다. 서버는 등록된 선박만 받는다(§4.3).
- **먼저 `POST /api/pi/ships` 로 신청한다** — 이것이 `ship_id` 를 받는 유일한 경로이고, **이 엔드포인트만 `ship_id` 를 요구하지 않는다.** 승인(`ACTIVE`)되기 전에는 다른 전송이 거절되니 `GET /api/pi/ships/{ship_id}` 로 상태를 확인한다.
- 키가 비어 있으면 서버가 `/api/pi/**` 를 **전부 401** 로 닫는다(기동 로그에 경고가 남는다). "안 올라온다" 싶으면 여기부터 본다.

### 순서 — 등록이 먼저다

```
① POST /api/pi/ships        등록 키   →  ship_id + ship_key
② GET  /api/pi/ships/{id}   선박 키   →  status 가 ACTIVE 가 될 때까지
③ 그 밖의 모든 Pi 전송        선박 키
```

②가 `WAIT` 인 동안 ③은 403 `PI_SHIP_NOT_APPROVED` 다. **오류가 아니라 대기 상태**이고,
Pi 는 큐를 쥔 채 화면에 "승인 대기"를 띄운다.

🔴 **한 요청에 키는 하나다. 두 키를 같이 싣지 않는다.**

| 언제 | 헤더 | 본문 `ship_id` |
|---|---|---|
| ① 등록 | **등록 키** | 없다 (이때 발급된다) |
| ②③ 그 밖의 전부 | **선박 키** | 있다 — 서버가 키의 선박과 **대조**한다 |

**대조는 2개다**: 헤더의 선박 키로 선박을 찾고, 본문 `ship_id` 가 그 선박인지 본다. 다르면 401.
등록 키는 이 대조에 끼지 않는다 — **공용이라 선박을 특정하지 못해** 보태도 얻는 것이 없다.

**Pi 는 등록에 성공하면 등록 키를 지워도 된다.** 남겨 두면 공용 키의 유출 표면만 늘고,
그 키를 회전할 때 **이미 등록된 배를 전부 건드려야** 한다.

### 첫 요청 — 이것만 통과하면 나머지는 같은 모양이다

```bash
# ① 등록 — 등록 키로. 이때만 ship_id 가 없다
curl -X POST https://floaq.example.com/api/pi/ships   -H 'Content-Type: application/json'   -H 'X-Ship-Register-Key: <등록 키>'   -d '{ "name": "제7금양호", "registration_no": "1234567-6261102",
        "mmsi": "440123456", "has_buoy": true,
}'
# → { "ship_id": "0192…", "ship_key": "9f2c…", "status": "WAIT" }
#   🔴 ship_key 는 여기서만 나온다. 받는 즉시 영속 저장할 것

# ③ 그 밖의 전송 — 선박 키로. 본문 ship_id 를 서버가 키와 대조한다
curl -X POST https://floaq.example.com/api/pi/accident-states   -H 'Content-Type: application/json'   -H 'X-Ship-Secret-Key: <선박 키>'   -d '{
    "request_id": "01923f6e-1111-7000-8000-000000000001",
    "v": 1,
    "ts": 1789456675,
    "data": [
      { "accident_id": "01923f6e-0000-7000-8000-0000000000a1",
        "status": "DETECT", "prev_status": null,
        "reason": "AI_DETECT", "caused_by": null,
        "created_at": 1789456670 }
    ]
  }'
```

```json
// 200
{ "success": true, "message": "OK",
  "data": { "received": 1, "inserted": 1, "duplicated": 0, "stale": 0 } }
```

**같은 요청을 한 번 더 보내면 `duplicated: 1` 이다** — 오류가 아니다. 재전송이 이렇게 동작하는지가 §4.2 멱등의 전부다.

> 사고 행(`POST /api/pi/accidents`)이 먼저 올라가 있어야 한다. 없으면 404 `ACCIDENT_NOT_FOUND` 에 `failed` 가 붙는다 — 순서 문제이지 영구 실패가 아니다(§4.1).

### 전송 순위 (§2.4 표의 숫자)

두절에서 복귀했을 때 **무엇을 먼저 보낼지**다. 무엇을 보낼지가 아니라 — 결국 전부 올라간다.

```
1. 사고 메타데이터 (좌표·시각·상태·신고)   ← 가볍고 가장 급하다. 관제가 즉시 인지해야 한다
2. 발사 기록 + 부표 위치 + 선박 위치
3. IMU 텔레메트리
4. 프레임·영상                              ← 전량 보내되 마지막
```

프레임이 가장 무거워서 마지막이다. 먼저 보내면 **관제가 사고 발생 사실 자체를 늦게 안다.**

### 🟢 지금 바로 구현해도 되는 것

페이로드·멱등키·오류까지 확정됐다.

```
POST /api/pi/ships              GET  /api/pi/ships/{ship_id}
POST /api/pi/accidents          POST /api/pi/accident-states
POST /api/pi/launches           POST /api/pi/buoys
POST /api/pi/ship-positions     POST /api/pi/imus
POST /api/pi/comm-losses        GET  /api/pi/commands
POST /api/pi/commands/ack
```

### 🔴 아직 구현하지 말 것

| 항목 | 왜 | 어디 |
|---|---|---|
| `POST /api/pi/archives` | tar 묶음 ↔ **장당 1요청**(`mqtt-연동-웹_v2` §11) 이 정면으로 다르다 | §4.3 · §8 #20 |
| 사고 영상 (`pi_video` 30초 청크) | 웹 설계는 "진행 중엔 최신 프레임, 종결 시 mp4 1회"이고 **청크 이어붙이기를 명시적으로 기각**했다 | §8 신규 #14 |
| `GET /api/pi/ocean` | `source` 매핑(기관 3종 ↔ 수집기 12종)과 폴링 주기 미정 | §4.4 |
| `POST /api/pi/reports` | `first_sent_at` 이 null 인 행을 서버가 못 받는다 | §4.3 · §8 #22 |
| `POST /api/pi/drift-estimates` 의 두절 연결 | Pi 내부 `comm_loss_id`(INTEGER)가 서버에서 뜻이 없다. 서버는 `comm_loss_detected_at` 을 제안 | §4.3 |
| `PUT /api/pi/device-status` | Pi 에는 `pi/device/status` **MQTT 토픽**만 있고 테이블이 없다(이력을 안 남긴다). **EC2 로도 올릴지 자체가 미정** | §4.3 |
| Pi 요청 HMAC 서명 | 서명 대상·헤더·시각 창 미확정 | §9 3-1 |

### 🔴 Pi 코드를 고쳐야 하는 것

| # | 내용 |
|---|---|
| 1 | **`AccidentType` 을 8종으로.** `HAZARD`·`ABANDON_SHIP` 제거, `ReportType` 에서 `SAFETY` 제거 (결정 2026-09-17 · §1.7) |
| 2 | **`ABANDON_SHIP` 등급 오류** — `(SAFETY, 108)` 로 라우팅돼 있다. **퇴함은 조난이다.** DSC 의 **category** `108`(safety)과 **nature of distress** `108`(abandoning ship)이 다른 표다. 되살릴 때는 `DISTRESS` |
| 3 | **`reason` 에 `WEB_CLOSE`·`AUTO_CLOSE` 추가** — 관제 웹 종료·1시간 자동 종결을 적을 값이 없다 |
| 4 | **`report.created_at`** — 서버는 Pi 의 `created_at`(행 생성 시각)을 쓴다. `first_sent_at` 은 별도 필드로 보낸다 |
| 5 | **`ship_position.accident_id`** — Pi 에 그 컬럼이 없다. **서버가 수신 시각으로 붙이는 쪽**을 제안한다(Pi 변경 0). 이의 없으면 그대로 간다 |

> **PK 는 보내지 않는다.** `buoy_log_id`·`imu_id`·`report_id`·`accident_state_id`·`position_id` 는 Pi 안에서만 뜻이 있다. 서버가 uuid 를 채번하고 **중복은 자연키가 막는다**(§4.2). 예외는 `accident_id`·`ship_id` 둘 — 둘 다 TEXT uuid 다.

---

## 1. 공통 규약

### 1.1 경로 · 인증

| 경로 | 인증 | 사용자 | 등록 방식 |
|---|---|---|---|
| `/api/auth/login` · `/api/auth/signup` | 없음 | 누구나 | — |
| `/api/**` (그 외) | `Authorization: Bearer <JWT>` | 관제 웹 `A` · `SA` | Swagger `bearerAuth` |
| `POST /api/pi/ships` | `X-Ship-Register-Key: <키>` | Raspberry Pi (등록 전) | 공용. 이 경로 하나뿐 |
| `/api/pi/**` (그 외) | `X-Ship-Secret-Key: <키>` | Raspberry Pi | 등록 응답으로 받은 선박 전용 키 |
| `/api/ocean/**` 조회 | 없음 — 공개 | 관제 웹 + kiosk | — |
| `/api/ocean/**` **수집 유발** (본선 주변 ROMS 타일) | `X-Floaq-Kiosk-Key: <kiosk 키>` — 없으면 조회만 하고 수집을 부르지 않는다 | kiosk | **구현** 2026-09-15 (`KioskKey`) |
| `/actuator/**` | 없음 (9090, 127.0.0.1 바인딩) | 운영 | 문서 제외 |

- Pi 키는 **만료가 없다.** Pi에 토큰 수명 관리를 두지 않기 위해서다 — 재부팅이나 두절 복귀 때 갱신에 실패하면 사고 데이터가 통째로 못 올라온다.
- **키가 둘인 이유** (결정 2026-09-17). 하나로 두면 **그 키를 가진 쪽이 아무 `ship_id` 로나 데이터를 올릴 수 있다**(옛 §9 6).
  - **등록 키** — 공용, `.env` 의 `FLOAQ_PI_ENROLL_KEY`. **`POST /api/pi/ships` 에만** 쓴다. 이 경로는 아직 선박이 없어 선박 키가 있을 수 없다(부트스트랩)
  - **선박 키** — 등록 응답으로 받는다. 그 뒤 모든 Pi 요청은 이 키다. **키가 곧 선박 증명**이라 서버는 페이로드의 `ship_id` 가 키의 선박과 같은지 검사한다 — 다르면 401
- 🔴 **한 요청에 키는 하나다.** 등록이 끝나면 **등록 키는 더 이상 보내지 않는다** — 두 키를 같이 싣지 않는다.

  | 언제 | 헤더 | 본문 `ship_id` |
  |---|---|---|
  | `POST /api/pi/ships` (등록) | **등록 키** | 없다 (이때 발급된다) |
  | 그 밖의 모든 Pi 요청 | **선박 키** | 있다 — 서버가 키의 선박과 **대조**한다 |

  **대조는 2개다**: 헤더의 선박 키로 선박을 찾고, 본문 `ship_id` 가 그 선박인지 본다. 다르면 401.
  등록 키는 이 대조에 끼지 않는다 — **공용이라 선박을 특정하지 못해서** 보태 봐야 얻는 것이 없다.

  <b>등록 키를 계속 보내면 오히려 나쁘다</b>: 등록이 끝난 Pi 에 공용 키가 남아 유출 표면이 늘고,
  그 키를 회전하려면 <b>이미 등록된 배를 전부 건드려야 한다</b>. 선박 키만 쓰면 등록 키 회전이 기존 선박에 영향이 없다.
  ⚠ 그래서 <b>Pi 는 등록에 성공하면 등록 키를 지워도 된다.</b>
- 서버는 선박 키를 **해시로만 보관한다**. DB 덤프나 백업으로 새어도 그것만으로는 쓸 수 없다(리프레시 토큰과 같은 방식, 계획.md §2).
- 키 미설정이면 `/api/pi/**` 전부 401 로 닫힌다(`PiApiKeyFilter`).
- **수집 유발만 키를 요구한다 (결정 2026-09-15).** `at` 없는 `current`·`grid`·`series` 는 요청 좌표 주변 0.25° ROMS 타일(1~4개)을 받게 한다(§5.3). 공개로 두면 밖에서 좌표를 바꿔 가며 불러 새 타일마다 약 24페이지(추정)를 태울 수 있다 — ROMS 하루 예산 10,000페이지는 새 타일 약 400개 분량이다(설정값 계산, 재현하지 않았다).
  - 이전(단일 해역)에는 60초마다 이동 1회 약 35페이지로 **약 4.8시간** 소진이었다. 한 번 받은 타일은 예측본당 한 번만 받아 같은 좌표 반복은 막히지만, 좌표를 계속 바꾸는 남용은 키 없이 못 막는다.
  - 조회는 DB 만 읽어 외부 호출이 없으므로 공개로 둔다.
  - 요청 수 제한(nginx `limit_req`)도 건다. 60초에 1회만 넘기면 되는 이동 남용은 요청 수 제한으로 못 막으므로 키와 둘 다 필요하다. 한도 값은 kiosk 실제 요청 패턴을 잰 뒤 정한다(§9 7).
  - kiosk 키는 **비밀이 아니라 선내 한정**이다 — kiosk 번들은 선내 PC localhost 에서만 서빙돼(계획.md §9.13) 공개 인터넷에 나가지 않는다. **웹 번들에는 넣지 않는다.** 웹이 해양 조회를 붙일 때는 `at` 을 넘기거나 키 없이 조회만 한다.
  - 기각: 전체를 키·JWT 로 닫기 — JWT 도입 전까지 웹 해양 조회가 막히거나 웹 번들에 키가 들어가 공개된다. `limit_req` 만 — 위 이동 남용을 못 막는다.
- ⚠ **HTTPS 전용.** `Authorization`·`X-Ship-Register-Key`·`X-Ship-Secret-Key`·`X-Floaq-Kiosk-Key` 가 평문 HTTP 에서 그대로 노출된다.
- ⚠ Pi 요청 **HMAC 서명** — **채택 방향**(2026-09-15). IoT 팀 문서 수령 후 서명 대상·헤더·시각 창을 확정한다 — §9 3-1.
- ⚠ Spring Security 는 아직 없다(`FilterConfig` 주석). JWT 도입 때 `SecurityConfig` 로 옮긴다.

### 1.2 필드 이름 표기 — 경로별로 다르다 (결정 2026-09-14)

| 경로 | 표기 | 이유 |
|---|---|---|
| `/api/**` · `/ws` | **camelCase** | 이미 구현된 `/api/ocean` 이 camelCase 다. 브라우저 코드와 같다 |
| `/api/pi/**` | **snake_case** | `docs/edge/mqtt.md` §3.5 · Pi SQLite 컬럼과 같다. **Pi 가 행을 그대로 보내면 된다** — 이름을 바꾸는 코드가 생기면 오타가 조용한 `null` 이 된다 |

서버는 pi DTO 에만 `@JsonNaming(SnakeCaseStrategy)` 를 붙인다. 전역 설정으로 바꾸지 않는다 — `/api/ocean` 계약이 깨진다.

> ⚠ **"행을 그대로" 는 아직 확인되지 않은 전제다.** Pi 스키마가 저장소에 없다(2026-09-14 기준 `pi/` 없음).
> `docs/edge/mqtt.md` §5.5 는 부표 위치를 `lat`/`lon` 으로 쓰는데 서버 V1 은 `buoy_lat`/`buoy_lon` 이다.
> 이름이 다르면 어느 한쪽이 변환해야 한다 — **IoT 팀과 컬럼명 대조가 선행돼야 한다**(§9 3).
> 이 문서의 pi 필드명은 **서버 V1 컬럼명** 기준이다.

### 1.3 시각

| 경로 | 형식 | 예 |
|---|---|---|
| `/api/**` · `/ws` | ISO-8601 UTC 문자열 (Jackson `Instant` 기본) | `"2026-09-14T03:21:07Z"` |
| `/api/pi/**` | **Unix epoch 초, 정수** (`docs/edge/mqtt.md` §0 `Unix`) | `1757820067` |

- Pi 쪽을 초로 두는 이유: Pi SQLite 가 `INTEGER` 초로 저장한다. 변환은 서버 수신 지점 한 곳에서만 한다.
- 예외: **오류 응답의 `timestamp` 만 서버 오프셋**이 붙는다(`ErrorResponse` 가 `OffsetDateTime.now()`, 예: `+09:00`). 화면은 이 값으로 계산하지 않는다 — 로그 대조용이다.
- ⚠ **초 해상도.** 같은 초 안의 IMU 순서는 `created_at` 으로 가를 수 없다. uuid v7 의 시간 순서로 보조한다.
- **측정 시각과 수신 시각을 섞지 않는다.** `created_at`(측정)은 Pi 가 준 값, `updated_at`(서버 반영)은 서버가 채운다. 서버 수신 시각으로 덮으면 두절 복귀 때 몇 시간 전 사고가 "방금"이 된다.

### 1.4 성공 응답

```json
{ "success": true, "message": "OK", "data": { } }
```

`ApiResponse<T>` (구현). 목록은 `data` 가 배열이거나 §1.6 페이지 객체다.

| 상태 코드 | 쓰는 곳 |
|---|---|
| `200` | 조회 · 멱등 수신(중복 포함) |
| `201` | 서버가 새 리소스를 만든 경우 — 가입 신청, 선박 등록 |
| `202` | **Pi 에게 명령을 넣었고 아직 처리되지 않음** — 사고 종료 요청, 영상 중지 요청 |

> Pi 수신은 새 행이 생겨도 `200` 이다. 같은 요청이 재전송되면 결과가 "중복"이 되는데, 첫 전송과 상태 코드가 달라지면 Pi 가 재시도 여부를 코드로 판단할 수 없다.

### 1.5 오류 응답

```json
{ "code": "ALREADY_RESOLVED", "message": "이미 종결된 사고입니다.",
  "path": "/api/accidents/0192.../close-requests", "timestamp": "2026-09-14T12:21:07.113+09:00" }
```

`ErrorResponse` (구현). **클라이언트는 `message` 가 아니라 `code` 로 분기한다** — kiosk `REJECT_TEXT` 가 이미 그렇게 쓴다. 전체 목록은 §7.

| HTTP | 원칙 |
|---|---|
| 400 | 형식·검증 실패. `COMMON_INVALID_INPUT`, `message` 에 첫 필드 오류 |
| 401 / 403 | 인증 없음·실패 / 권한 없음 |
| 404 | 없거나, **볼 권한이 없는 사고** — `A` 에게 신고 전 사고의 존재를 알리지 않는다 |
| 409 | 리소스는 있는데 지금 상태와 충돌. **"이미 X 됨"은 404 가 아니다** |
| 503 | 의존하는 수집·저장소가 동작하지 않음 |

### 1.6 페이지

`?page=0&size=20` (0부터, Spring Data 규약). `size` 상한은 `제안` 100.

```json
{ "content": [ ], "page": 0, "size": 20, "totalElements": 57, "hasNext": true }
```

### 1.7 공통 enum

DB `CHECK` 제약과 **글자까지 같다.** 화면용 이름은 프론트가 decode 에서 바꾼다 (결정 2026-09-14).

| 이름 | 값 | 출처 |
|---|---|---|
| `AccidentStatus` | `DETECT`(1) `WAIT`(2) `REPORT`(3) `CANCEL`(4) `CLOSE`(5) | `ck_accident_status`. 괄호는 **상태 단조 순위**(§4.2) — 서버가 현재 상태를 바꾸는 기준이다. ⚠ `CANCEL`·`CLOSE` 는 둘 다 종료인데 순위가 다르다. **둘 사이 전이가 없다는 전제**에서만 맞다 |
| `ReportType` (긴급도) | `DISTRESS` `URGENCY` | `ck_accident_report_type` — **`SAFETY` 는 1차 제외(결정 2026-09-17)** |
| `AccidentType` | **8종** — `MOB` `FIRE` `FLOODING` `COLLISION` `GROUNDING` `ENGINE_FAILURE` `OTHER_DISTRESS` (DISTRESS) · `MEDICAL` (URGENCY) | 결정 2026-09-17. ⚠ Pi 는 아직 10종(`HAZARD`·`ABANDON_SHIP` 포함) — 전달 필요 |
| `TriggerSource` | `AI` `MANUAL` | 〃 |
| `ReportChannel` | `AIS_MOB` `AIS_SART` `DSC` | `docs/edge/mqtt.md` §5.10 |
| `ReportSendStatus` | `SENDING` `ACKED` `STOPPED` `FAILED` | 〃 |
| `UserRole` | `A` `SA` (V10 에서 줄임) | `ck_users_role` |
| `UserStatus` | `WAIT` `ACTIVE` `REJECTED` `DELETED` | `ck_users_status` (V5 에서 `REJECTED` 추가) |
| `CommandType` | `CLOSE_ACCIDENT` `STOP_MEDIA` | 계획.md §9.9 |
| `CommandState` | `ISSUED` `DELIVERED` `DONE` `REJECTED` `EXPIRED` | §4.5 |

**상태 전이 순위** — 서버의 단조 가드(§4.2)가 쓴다.

```
DETECT(0) → WAIT(1) → REPORT(2) → CLOSE(3)
                 └──────────────→ CANCEL(3)
수동 신고는 REPORT(2) 로 생성
```

---

## 2. 엔드포인트 목록 (-105)

권한: `A` = 해경 · `SA` = 운영 관리자 · `Pi` = Pi 키 · `—` = 인증 없음

### 2.1 인증 · 계정

| 메서드 | 경로 | 내용 | 권한 | 요구사항 · 화면 | 상태 |
|---|---|---|---|---|---|
| POST | `/api/auth/login` | 로그인 → JWT | — | WEB-01 · W-01 | **구현** |
| POST | `/api/auth/signup` | 가입 신청 (`WAIT`) | — | WEB-02 · W-01 | **구현** |
| GET | `/api/auth/me` | 내 계정 | A SA | W-01 | **구현** |
| GET | `/api/admin/users` | 계정 목록 · 승인 대기 | SA | WEB-07 · W-04 | **구현** |
| POST | `/api/admin/users/{userId}/approve` | 승인 `WAIT → ACTIVE` | SA | WEB-07 · W-04 | **구현** |
| POST | `/api/admin/users/{userId}/reject` | 반려 `WAIT → REJECTED` | SA | WEB-07 · W-04 | **구현** |
| POST | `/api/admin/users/{userId}/deactivate` | 비활성화 `ACTIVE → DELETED` | SA | W-04 | 설계 |

### 2.2 선박

| 메서드 | 경로 | 내용 | 권한 | 요구사항 · 화면 | 상태 |
|---|---|---|---|---|---|
| GET | `/api/ships` | 선박 목록 | A SA | W-05 · 계획.md §9.13 "전국 선박 조회" | 설계 |
| GET | `/api/ships/{shipId}` | 선박 상세 + 최근 장비 상태 | A SA | W-05 | 설계 |
| POST | `/api/ships` | 선박 등록 | SA | WEB-08 · W-05 | 설계 |
| PATCH | `/api/ships/{shipId}` | 선박 정보 수정 | SA | W-05 | 설계 |
| DELETE | `/api/ships/{shipId}` | 논리 삭제 | SA | W-05 | 설계 |

### 2.3 사고 (관제)

| 메서드 | 경로 | 내용 | 권한 | 요구사항 · 화면 | 상태 |
|---|---|---|---|---|---|
| GET | `/api/accidents` | 사고 목록 · 필터 | A | WEB-03 · W-02 | **구현** |
| GET | `/api/accidents/{accidentId}` | 사고 상세 요약 | A | WEB-04 · W-03 | **구현** |
| GET | `/api/accidents/{accidentId}/timeline` | 상태 이력 + 명령 이력 | A | WEB-04 · W-03 | **구현** |
| GET | `/api/accidents/{accidentId}/buoy-positions` | 부표 궤적 | A | WEB-04 · W-03 | **구현** |
| GET | `/api/accidents/{accidentId}/ship-positions` | 사고 구간 선박 위치 | A | W-03 지도 | 제안 |
| GET | `/api/ships/{shipId}/positions` | 평시 항적 (최근 24시간) | A | APP-01 | 제안 |
| GET | `/api/accidents/{accidentId}/drift-estimates` | 표류 추정 범위 이력 | A | WEB-10 · W-03 | 제안 |
| GET | `/api/accidents/{accidentId}/reports` | 채널별 신고 기록 | A | W-03 신고 기록 | **구현** |
| GET | `/api/accidents/{accidentId}/frames` | 수신된 프레임 목록 (진행 중 영상) | A | WEB-05 · W-03 | 설계 |
| GET | `/api/accidents/{accidentId}/frames/{seq}` | 프레임 1장 `image/jpeg` | A | WEB-05 | 설계 |
| GET | `/api/accidents/{accidentId}/video` | 종결 후 mp4 재생 주소 | A | WEB-05 · W-03 | 설계 |
| POST | `/api/accidents/{accidentId}/close-requests` | **사고 종료 요청** → Pi 명령 | A | WEB-06 · 계획.md §9.20 | 설계 |
| POST | `/api/accidents/{accidentId}/media-stop-requests` | **영상 그만 받기** → Pi 명령 | A | W-03 · 상세기획 §5.5 | 설계 |
| GET | `/api/accidents/{accidentId}/commands` | 이 사고에 낸 명령과 처리 상태 | A | W-03 | 설계 |

### 2.4 Pi (Pi → EC2)

| 메서드 | 경로 | 내용 | 전송 순위 (계획.md §9.9) | 요구사항 | 상태 |
|---|---|---|---|---|---|
| POST | `/api/pi/ships` | **선박 등록 신청 → `ship_id` 발급** | — | WEB-08 · W-05 | 설계 |
| GET | `/api/pi/ships/{ship_id}` | 승인 상태 확인 | — | W-05 | 설계 |
| POST | `/api/pi/accidents` | 사고 upsert (생성 + 현재 상태) | 1 | WEB-09 · IOT-18 | 설계 |
| POST | `/api/pi/accident-states` | 상태 변경 이력 | 1 | WEB-09 | 설계 |
| POST | `/api/pi/reports` | 채널별 신고 발신 기록 upsert | 1 (이 문서의 배정) | IOT-11 | 설계 · ⚠ `first_sent_at` 결정 대기(§0.1) |
| POST | `/api/pi/launches` | 부표 투하 결과 | 2 | IOT-03 | 설계 |
| POST | `/api/pi/buoys` | 부표 위치 | 2 | IOT-05 | 설계 |
| POST | `/api/pi/ship-positions` | 선박 위치 (**평시 5초 · 사고 중 1초**) | 2 | APP-01 | 설계 |
| GET | `/api/pi/ocean` | **하행 해양 데이터 (Pi pull)** — 표류 계산 입력 | — | APP-09 | 제안 |
| POST | `/api/pi/comm-losses` | LoRa 두절 구간 (판정 주체 = **Pi**) | 2 | WEB-10 | 설계 |
| POST | `/api/pi/drift-estimates` | 표류 추정 범위 (계산 주체 = **Pi**) | 2 | APP-09 | 설계 · ⚠ 두절 연결키 대기(§0.1) |
| POST | `/api/pi/imus` | IMU (30초 단위) | 3 | IOT-20 | 설계 |
| POST | `/api/pi/archives` | 프레임 tar (multipart) | 4 | IOT-19 | 🔴 **보류** — Pi·v2 는 장당 1요청(§8 #20) |
| — | (사고 영상) | `pi_video` 30초 청크 | 4 | IOT-19 | 🔴 계획.md §9.6 은 종결 시 mp4 1회. 충돌 |
| PUT | `/api/pi/device-status` | 장비 이상 탐지 결과 (최신 1건) | — | APP-15 · 계획.md §9.15 | 제안 — §0.1 |
| GET | `/api/pi/commands` | 미처리 하행 명령 | — | WEB-06 | 설계 |
| POST | `/api/pi/commands/ack` | 명령 처리 결과 | — | WEB-06 | 설계 |

### 2.5 해양 공공데이터

| 메서드 | 경로 | 내용 | 사용처 | 상태 |
|---|---|---|---|---|
| GET | `/api/ocean/sources` | 소스별 최신값 + 경과 시간 | kiosk 해양 패널 · 대시보드 | 구현 |
| GET | `/api/ocean/summary` | 해양 상황 요약 (사전 생성) | kiosk · 웹 | 구현 |
| GET | `/api/ocean/current` | 좌표 최근접 ROMS 격자 + 이웃 산포 (`at` 으로 지난 24시간) | 표류 추정 입력 (유속) | 구현 |
| GET | `/api/ocean/observations` | 기상청 해양 관측 지점 — `at` 기준 최근 관측 (지난 24시간) | 표류 추정 입력 (바람) | 구현 |
| GET | `/api/ocean/grid` | 본선 칸 + 이웃 격자 | 지도 구역 | 구현 |
| GET | `/api/ocean/series` | 격자 시각별 예측 | 시계열 차트 | 구현 |
| GET | `/api/ocean/zones` | 기상청 해구별 예측 한 프레임 (전국 대해구 · 본선 주변 소해구) | 상황판 전국 층 · 본선 지도 파고·바람 | 구현 |

### 2.6 WebSocket

| 경로 | 내용 | 상태 |
|---|---|---|
| `/ws` | 관제 웹 실시간 이벤트 (§6) | 설계 |

---

## 3. 관제 웹 API 상세 (-106)

### 3.1 인증

#### `POST /api/auth/login`

```json
// 요청
{ "loginId": "cg-busan-01", "password": "••••••••" }

// 200
{ "success": true, "message": "OK",
  "data": { "accessToken": "eyJ...", "tokenType": "Bearer",
            "expiresAt": "2026-09-14T15:00:00Z",
            "user": { "userId": 3, "loginId": "cg-busan-01", "name": "김해경",
                      "role": "A", "status": "ACTIVE" } } }
```

| 오류 | 언제 |
|---|---|
| `AUTH_INVALID_CREDENTIALS` 401 | 아이디 없음 · 비밀번호 틀림 — **둘을 구분하지 않는다** (계정 존재 여부 노출 방지) |
| `AUTH_ACCOUNT_PENDING` 403 | 비밀번호는 맞고 `WAIT`. 문구가 달라야 사용자가 기다릴 줄 안다 |
| `AUTH_ACCOUNT_REJECTED` 403 | 비밀번호는 맞고 `REJECTED`. 같은 이메일로 다시 신청할 수 있어 화면은 재신청을 안내한다 |
| `AUTH_ACCOUNT_DELETED` 403 | 비밀번호는 맞고 `DELETED` |

- `loginId` 는 **기관 이메일**이다(결정 2026-09-15, §8 #12). 앞뒤 공백을 지우고 소문자로 저장·조회한다. 필드 이름은 중립으로 둔다.
- refresh token 은 두지 않는다 — 만료 시 재로그인. 만료 시간은 `제안` 미정(§9).
- 로그아웃 API 는 두지 않는다. 무상태 JWT 라 클라이언트가 토큰을 버린다.

#### `POST /api/auth/signup`

```json
// 요청
{ "loginId": "cg-busan-01", "password": "••••••••", "name": "김해경" }

// 201
{ "success": true, "message": "가입 신청이 접수됐습니다.",
  "data": { "userId": 3, "status": "WAIT" } }
```

| 필드 | 규칙 |
|---|---|
| `loginId` | 필수 · 최대 64 (`users.login_id`) |
| `password` | 필수 · bcrypt 72바이트 한계 — 그 이상은 잘린다 |
| `name` | 필수 · 최대 20 (`users.name`) |

오류: `AUTH_ALREADY_REGISTERED` 409 · `COMMON_INVALID_INPUT` 400

- 역할은 요청으로 받지 않는다. 가입 신청은 항상 `A` + `WAIT`. `SA` 은 운영자가 DB 로 만든다.
- 가입 신청 칸은 **이 셋뿐이다**(결정 2026-09-15, §9 #8). 소속·계급·연락처·증빙을 받지 않는다 — 해경 쪽은 신고를 받았는지만 알 수 있어 담당·소속을 둘 이유가 없다.
- **반려(`REJECTED`)된 이메일은 다시 신청할 수 있다** — 반려 행을 지우고 새 신청으로 넣는다(새 `userId`·`createdAt`). 옛 행을 고쳐 쓰면 `created_at` 을 바꿀 수 없어 신청 시각이 예전으로 찍힌다. 반려된 계정은 로그인한 적이 없어 가리키는 기록이 없다. 반려 이력은 남지 않는다.
- 대기(`WAIT`)·승인(`ACTIVE`)·비활성화(`DELETED`)된 이메일은 409 다. `login_id` 가 UNIQUE 다.

#### `GET /api/auth/me`

로그인한 사람 자신. **프론트가 역할 분기에 바로 쓴다** — 토큰을 풀어 `role` 을 읽지 않는다.
토큰 안의 클레임은 발급 시점의 값이라, 그 뒤 권한이 바뀌었으면 화면이 틀린 메뉴를 그린다.

```json
{ "success": true, "message": "OK",
  "data": { "userId": 2, "loginId": "kim@kcg.example", "name": "김해경",
            "role": "A", "status": "ACTIVE" } }
```

- `UserView` 기준 (**구현**). `status` 가 `ACTIVE` 가 아닌 토큰이 살아 있을 수 있다 — §9 13 참고.

#### `GET /api/admin/users?status=WAIT&page=0&size=20`

`status` 생략 시 `DELETED` 를 뺀 전체(`REJECTED` 포함). 최근 신청 순(`createdAt` 내림차순). `size` 는 1~100 으로 자른다.

```json
{ "content": [ { "userId": 3, "loginId": "busan-cg@kcg.example", "name": "김해경",
                 "role": "A", "status": "WAIT",
                 "createdAt": "2026-09-14T02:10:00Z", "updatedAt": "2026-09-14T02:10:00Z" } ],
  "page": 0, "size": 20, "totalElements": 1, "hasNext": false }
```

- `updatedAt` — 승인·반려 시각 컬럼이 따로 없어, 처리된 신청에서는 이 값이 처리 시각이다. 계정을 나중에 또 바꾸면 그 시각으로 밀린다.

#### `POST /api/admin/users/{userId}/approve` · `/reject`

승인·반려 뒤 **바뀐 행을 그대로 돌려준다** — 화면이 목록을 다시 부르지 않아도 그 줄만 갈아끼울 수 있다.

```json
{ "success": true, "message": "OK",
  "data": { "userId": 7, "loginId": "park@kcg.example", "name": "박서연",
            "role": "A", "status": "ACTIVE",
            "createdAt": "2026-09-15T02:10:00Z", "updatedAt": "2026-09-17T04:31:22Z" } }
```

- `AdminUserView` 기준 (**구현**). 목록(`GET /api/admin/users`)과 같은 모양이다.
- 반려는 `status: "REJECTED"` 다. 비활성화(`DELETED`)와 다른 값이다 — 되돌릴 수 있는지가 갈린다(§9 12).

#### `GET /api/ships?q=&includeDeleted=false&page=0&size=20`

```json
{ "content": [ { "shipId": "0192...", "name": "제7금양호", "registrationNo": "1234567-6261102",
                 "mmsi": "440123456", "hasBuoy": true, "deleted": false,
                 "activeAccidentId": null, "createdAt": "2026-09-11T00:00:00Z" } ],
  "page": 0, "size": 20, "totalElements": 1, "hasNext": false }
```

- `q` — 선명·등록번호·MMSI 부분 일치.
- `activeAccidentId` — **`A` 에게는 신고된(`REPORT`) 사고만** 채운다. 그 전 단계는 null. `SA` 은 사고 API 가 없으므로(§3.4) **항상 null** — 값을 주면 열 수 없는 링크가 된다.

#### `GET /api/ships/{shipId}`

```json
{ "success": true, "message": "OK",
  "data": { "shipId": "0192...", "name": "제7금양호", "registrationNo": "부산-1234",
            "status": "ACTIVE",
            "createdAt": "2026-09-15T02:10:00Z", "decidedAt": "2026-09-15T03:00:00Z" } }
```

- `AdminShipView` 기준. ⚠ **"최근 장비 상태"는 아직 없다** — `PUT /api/pi/device-status` 가 `제안` 이라
  받는 경로가 없다(§0.1). 붙으면 `deviceStatus` + `deviceStatusReceivedAt` 을 여기 더한다.
- `mmsi` 는 목록·상세 모두 내리지 않는다. 필요해지면 더한다 — 지금 쓰는 화면이 없다.

#### `POST /api/ships` (SA)

```json
// 요청
{ "name": "제7금양호", "registrationNo": "1234567-6261102", "mmsi": "440123456", "hasBuoy": true }
// 201
{ "success": true, "message": "OK", "data": { "shipId": "0192..." } }
```

| 필드 | 규칙 |
|---|---|
| `name` | 필수 · 최대 64 |
| `registrationNo` | 선택 · 최대 20 · 문자열 (`0`·`-` 포함) |
| `mmsi` | 선택 · 숫자 9자리 |
| `hasBuoy` | 선택 · 기본 false |

- **`shipId` 는 서버(EC2)가 uuid v7 로 발급한다** (확정 2026-09-17).

  <b>사고와 규칙이 다른 이유</b> — `accident_id` 는 Pi 가 채번한다. 인터넷이 끊긴 바다에서도 사고가 만들어져야 하기 때문이다.
  선박 등록은 그렇지 않다: 등록 자체가 온라인 행위이고 승인 주체가 SA 이며,
  **서버가 채번하면 미등록 `ship_id` 로 데이터가 올라올 일이 아예 없어진다.**
  (지금 IoT 쪽은 "실행할 때마다 새로 발급"이라 그 값으로 올리면 전부 404 `PI_SHIP_UNKNOWN` 이다 — §0.1.)

  ⚠ `UUID.randomUUID()` 는 **v4** 라 시간순 정렬이 안 된다. 서버 코드는 `Uuid7` 을 쓴다.
- ⚠ **발급한 값을 Pi·kiosk 설정에 넣는 절차는 아직 미정**(`docs/edge/mqtt.md` §7 #7).
  MQTT 토픽 접두어라 **값이 틀리면 브로커가 아무 에러도 주지 않고 조용히 아무것도 오지 않는다.**
- 오류: `SHIP_ALREADY_REGISTERED` 409 — ⚠ 판정 기준(MMSI? 등록번호?)에 걸 UNIQUE 제약이 V1 에 없다(§9).
- 🔴 **이 엔드포인트(SA 직접 등록)는 뒤집기 전 설계다** (2026-09-17). 정방향은 **Pi 신청 → `WAIT` → SA 승인**이고
  신청은 `POST /api/pi/ships`(§4.3)다. **둘 다 만들지, 이쪽을 버릴지 아직 안 정했다** — 지금은 둘 다 미구현이다.
  SA 가 현장 값(카메라 높이·발사장치 거리)을 알 방법이 없다는 것이 방향을 뒤집은 이유다.
- ✅ **선박 승인·거절은 있다** (2026-09-17 정정. 이전 문장 "상태 컬럼이 없어 두지 않는다"는 낡았다).
  V8 이 `ship.status`(`WAIT`·`ACTIVE`·`REJECTED`)를 넣었고 `POST /api/admin/ships/{shipId}/approve`·`/reject` 가 **구현**돼 있다.
  등록 방향은 **선내 kiosk 신청 → `WAIT` → SA 승인**이다 — 설치 현장에 있는 사람은 선주고
  SA 는 선박 제원을 먼저 알 방법이 없다.
- ⚠ 그래서 이 `POST /api/ships`(SA 직접 등록)와 kiosk 신청 경로의 관계가 아직 정리되지 않았다.
  **둘 다 필요한지, 하나로 합칠지** 정해야 한다 — 지금은 둘 다 미구현이다.

#### `PATCH /api/ships/{shipId}` · `DELETE /api/ships/{shipId}` (SA)

PATCH 는 위 필드 중 보낸 것만 바꾼다. DELETE 는 `is_deleted = true` + `deleted_at` — 과거 사고가 참조하므로 행은 남긴다.
오류: `SHIP_NOT_FOUND` 404 · DELETE 는 진행 중 사고(`DETECT`·`WAIT`·`REPORT`)가 있으면 `INVALID_STATE` 409 — 사고 중인 배를 목록에서 지우면 관제가 그 사고를 못 찾는다.

### 3.4 사고 조회

#### 볼 수 있는 범위

| 역할 | 범위 | 근거 |
|---|---|---|
| `A` | **신고된 사고만** — `status IN ('REPORT', 'CLOSE')`. 종결 후에도 계속 조회 | WEB-03 · W-02 |
| `SA` | 사고 API 없음 (403) | 계획.md §9.13 "관제 화면 없음" — ⚠ 상세기획 §5.5 와 충돌(§8 #6) |

범위 밖 사고는 **404 `ACCIDENT_NOT_FOUND`** 다. 403 이면 "그런 사고가 있다"를 알려준다.

- `status` 두 값으로 충분한 근거: 상세기획 §3.1 상 `CLOSE` 는 `REPORT` 에서만 온다. `CANCEL` 은 `WAIT` 에서만 오므로 신고 전이다. `accident_state` 를 join 하지 않아도 되고 `ix_accident_status` 를 탄다.
- 위 전제가 깨지는 곳: **오종결 재개**(§9 10). 재개를 `CLOSE → REPORT` 로 허용하면 여전히 성립하지만, 새 건으로 여는 방식이면 재개 건은 `DETECT` 로 시작해 잠시 안 보인다.

#### `GET /api/accidents`

| 파라미터 | 뜻 |
|---|---|
| `status` | 여러 번 가능 — `?status=REPORT&status=CLOSE` |
| `shipId` | |
| `from` · `to` | `createdAt` 기준, ISO-8601 |
| `page` · `size` | §1.6. 정렬은 **진행 중(`REPORT`) 먼저, 그다음 `createdAt` 내림차순** — W-02 "진행 중 상단 고정" |

```json
{ "content": [ {
    "accidentId": "0192...",
    "ship": { "shipId": "0192...", "name": "제7금양호" },
    "accidentType": "MOB", "triggerSource": "AI",
    "reportType": "DISTRESS", "reportDsc": 110,
    "status": "REPORT",
    "lat": 35.0712, "lon": 129.0834,
    "createdAt": "2026-09-14T03:20:31Z",
    "reportedAt": "2026-09-14T03:21:01Z",
    "rescuedAt": null,
    "closedAt": null } ],
  "page": 0, "size": 20, "totalElements": 1, "hasNext": false }
```

- `lat`·`lon` 은 **null 가능** — GPS 미수신 사고(`accident_lat` NULL 허용). 0,0 으로 채우지 않는다.
- `reportedAt` = 첫 `REPORT` 상태 시각. **V9 의 `accident.reported_at` 에 비정규화돼 있다** — 목록마다 `accident_state` 를 join 하지 않으려는 것이고, `accident-states` 수신 때 한 번만 채운다.
- `accidentType`·`triggerSource` — ✅ V9 에 있다. Pi 가 안 보내면 null 이다(받은 대로 적는다).
- `rescuedAt` — **구조 확정 시각.** `CLOSE` 는 구조 확정(`TABLET_RESCUE`)과 사고 종료(`TABLET_CLOSE`) 둘 다라 이 값이 없으면 관제는 **구조됐는지 모른다.** Pi `pi_accident.rescued_at` 이 원본이고 ✅ V9 에 컬럼이 있다.

#### `GET /api/accidents/{accidentId}`

**목록 항목과 같은 필드를 평평하게 두고** 아래를 더한다 — 중첩하면 화면이 목록과 상세에서 같은 값을 다른 경로로 읽는다.

```json
{
  "reportDueAt": null,
  "ship": { "shipId": "0192...", "name": "제7금양호", "registrationNo": "...", "mmsi": "440123456" },
  "launch": { "result": "SUCCESS", "failReason": null,
              "launchLat": 35.0710, "launchLon": 129.0831,
              "targetLat": 35.0712, "targetLon": 129.0834,
              "horizontalAngle": 172.5, "verticalAngle": 38.0,
              "confidenceScore": 0.91, "launchedAt": "2026-09-14T03:20:33Z" },
  "buoy": { "lat": 35.0716, "lon": 129.0840, "isPressed": true,
            "measuredAt": "2026-09-14T03:31:10Z", "heldAt": "2026-09-14T03:24:02Z" },
  "commLoss": null,
  "reports": [ { "channel": "DSC", "status": "SENDING", "sentCount": 24,
                 "lastSentAt": "2026-09-14T03:24:01Z" } ],
  "media": { "latestFrameSeq": 4210, "latestFrameAt": "2026-09-14T03:31:09Z",
             "videoStatus": "NONE", "stoppedAt": null },
  "pendingCommands": [ ]
}
```

| 필드 | 없을 때 |
|---|---|
| `launch` | null — 수동 신고 또는 투하 기록 미수신. `result`·`failReason`·`target*` 은 ⚠ 서버 컬럼 없음(§8 #14) |
| `buoy` | null — 투하 없음. **통신 두절이어도 null 이 아니다** — 마지막 실측이 남는다 |
| `buoy.heldAt` | null — **잡았는지 확인 안 됨.** "안 잡았다"가 아니다(E9) |
| `commLoss` | **항상 null** — `comm_loss` 테이블이 없고 판정 주체는 Pi 로 확정됐다(§9 4). 서버가 임시 판정하면 판정 주체가 둘이 된다 — 웹이 `buoy.measuredAt` 경과로 임시 판정하면 판정 주체가 셋이 된다. 임시 표시를 하더라도 "마지막 수신 N초 전" 이지 "두절" 이라는 단어를 쓰지 않는다 |
| `reports` | 빈 배열 — 아직 신고 전 |
| `media.videoStatus` | `NONE` 진행 중 · `ENCODING` · `READY` · `FAILED`. ⚠ `latestFrameSeq`·`latestFrameAt` 은 **항상 null** — 프레임 수신이 규약 미합의로 보류라 저장된 프레임이 없다(§0.1). "0장"이 아니라 "받는 경로가 아직 없다" |

- `ageSec` 같은 경과 시간은 내리지 않는다. 시각을 주면 화면이 자기 시계로 센다 — 서버가 계산하면 응답 지연만큼 틀린다.

#### `GET /api/accidents/{accidentId}/timeline`

```json
[ { "at": "2026-09-14T03:20:31Z", "kind": "STATE",   "status": "DETECT", "reason": "AI_DETECT" },
  { "at": "2026-09-14T03:20:33Z", "kind": "STATE",   "status": "WAIT",   "reason": "COUNTDOWN_START" },
  { "at": "2026-09-14T03:21:01Z", "kind": "STATE",   "status": "REPORT", "reason": "TIMEOUT" },
  { "at": "2026-09-14T03:40:00Z", "kind": "COMMAND", "commandType": "CLOSE_ACCIDENT",
    "commandState": "DELIVERED", "issuedBy": { "userId": 3, "name": "김해경" } } ]
```

시각 오름차순. **상태 전이와 관제 명령을 한 줄기로 섞어 준다** — 따로 주면 화면마다 합치는 방식이 달라진다.
`reason` 은 ✅ V9 에 있다. `kind` 로 갈리고 쓰이지 않는 필드는 응답에서 빠진다(`NON_NULL`) — null 로 채워 보내면 "값이 없는 것"과 "이 종류에 없는 것"을 구분할 수 없다.

#### `GET /api/accidents/{accidentId}/buoy-positions?after=&limit=3600`

```json
[ { "lat": 35.0712, "lon": 129.0834, "isPressed": false, "measuredAt": "2026-09-14T03:20:40Z" } ]
```

- `measuredAt` 오름차순. `after` 로 이어 받는다 — 화면이 WS `BUOY_POS` 를 놓쳤을 때 메우는 용도.
- `limit` 기본·상한 3600 = 1Hz × 사고 후 상한 1시간(계획.md §9.6).
- **실측 궤적만** 준다. 두절 구간의 추정 궤적은 `drift-estimates` 다 — 한 선으로 그리면 어디까지가 실제로 받은 값인지 사라진다.

#### `GET /api/accidents/{accidentId}/drift-estimates?latest=true` — 제안

`pi_drift_estimate` 동기화분. 모양은 IoT 팀 스키마 확정 후 정한다. 그때까지 웹은 `lib/drift.ts` 로 계산한다 — 입력은 `/api/ocean/current`(유속) · `/api/ocean/observations`(바람). **사고 시각을 `at` 으로 넘긴다** — 사고 기록이 늦게 동기화돼도 지난 24시간은 그 시각 값이 남아 있다(§5.3).

#### `GET /api/accidents/{accidentId}/reports`

```json
[ { "reportId": "0192...", "channel": "DSC", "status": "ACKED", "sentCount": 31,
    "firstSentAt": "2026-09-14T03:21:01Z", "lastSentAt": "2026-09-14T03:25:30Z",
    "ackedAt": "2026-09-14T03:25:31Z", "ackedBy": "004401001",
    "failReason": null, "lat": 35.0712, "lon": 129.0834 } ]
```

- `ackedAt`·`ackedBy` 는 **DSC 만** 값이 있다. AIS 는 규격상 ACK 가 없다(`docs/edge/mqtt.md` §5.11).
- `failReason: "NO_INTERNET"` 은 화면에 반드시 드러내야 한다 — 없으면 신고가 나간 줄 안다.
- ✅ `channel`·`status`·`sentCount` 등은 V9 에 있다. ⚠ **`SENDING` 이 오래 가는 것은 정상이다** — DSC 확인응답은 해안국 운용자가 수동으로 보내고 무선전화로 대신 답하면 영영 오지 않는다. 화면이 오류로 표시하면 안 된다.

### 3.5 사고 제어 — 명령 발행

**관제의 사고 종료·영상 중지는 사고 상태를 직접 바꾸지 않는다.** Pi 에게 명령을 넣고(`edge_command`), Pi 가 가져가서 처리하고 ack 한다(계획.md §9.9). 사고 상태는 Pi 가 올린 `accident-states` 로만 바뀐다.

```
웹 POST close-requests ──▶ edge_command ISSUED           202
Pi GET /api/pi/commands ─▶                DELIVERED     WS COMMAND_STATE
Pi 처리 → accident-states CLOSE ─▶ 사고 CLOSE              WS ACCIDENT_STATE
Pi POST ack ─────────────▶                  DONE          WS COMMAND_STATE
```

화면은 `ISSUED`·`DELIVERED` 동안 **"종료 요청함"**, `DONE` 이후 **"종료됨"** 을 보여준다. ack 없이 "종료됨"을 그리면 화면이 거짓말을 한다.

#### `POST /api/accidents/{accidentId}/close-requests`

본문 없음 (`제안` — 종료 사유 메모).

```json
// 202
{ "success": true, "message": "종료 요청을 보냈습니다.",
  "data": { "commandId": "0192...", "type": "CLOSE_ACCIDENT", "state": "ISSUED",
            "issuedAt": "2026-09-14T03:40:00Z" } }
```

| 오류 | 언제 |
|---|---|
| `ACCIDENT_NOT_FOUND` 404 | 없음 · 볼 권한 없음 |
| `ALREADY_RESOLVED` 409 | 이미 `CLOSE` |
| `ALREADY_CANCELLED` 409 | 이미 `CANCEL` |
| `INVALID_STATE` 409 | 같은 사고에 처리 전(`ISSUED`·`DELIVERED`) `CLOSE_ACCIDENT` 가 이미 있음 — 연타로 명령이 쌓이지 않게 |

- 409 판정은 **서버가 아는 마지막 상태** 기준이다. 선내에서 이미 닫았는데 아직 동기화 전이면 명령이 나가고, Pi 가 `REJECTED`(`ALREADY_RESOLVED`)로 ack 한다 — 그 경로가 정상이다.
- **명령은 만료된다.** `ISSUED`·`DELIVERED` 가 `제안` 10분을 넘기면 서버가 `EXPIRED` 로 넘기고 WS `COMMAND_STATE` 를 보낸다. 그 뒤 재요청이 가능하다. 만료가 없으면 Pi 가 가져간 뒤 죽었을 때 그 사고는 **영원히 `INVALID_STATE`** 라 관제가 손을 쓸 수 없다. 10분 근거: 하행 폴링 주기(수 초~수십 초)의 수십 배라 정상 지연과 겹치지 않는다 — 폴링 주기가 정해지면 재계산.
- `EXPIRED` 뒤에 Pi 가 늦게 ack 하면 **ack 를 받아 `DONE`/`REJECTED` 로 바꾼다.** Pi 가 실제로 처리한 사실이 만료 표시보다 진실이다.

#### `POST /api/accidents/{accidentId}/media-stop-requests`

`close-requests` 와 같은 모양, `type: "STOP_MEDIA"`. 추가 오류: 사고 후 영상 전송이 이미 끝남(종결·1시간 상한) → `INVALID_STATE` 409.

#### `GET /api/accidents/{accidentId}/commands`

```json
[ { "commandId": "0192...", "type": "CLOSE_ACCIDENT", "state": "REJECTED",
    "errorCode": "ALREADY_RESOLVED",
    "issuedAt": "2026-09-14T03:40:00Z", "deliveredAt": "2026-09-14T03:40:06Z",
    "handledAt": "2026-09-14T03:40:06Z", "issuedBy": { "userId": 3, "name": "김해경" } } ]
```

### 3.6 영상 · 프레임

**진행 중에는 최신 프레임, 종결 후에는 mp4** 다(계획.md §9.6). 두 요구가 시점으로 갈리므로 API 도 갈린다.

#### `GET /api/accidents/{accidentId}/frames?after=&limit=`

```json
[ { "seq": 4210, "capturedAt": "2026-09-14T03:31:09Z", "phase": "POST" } ]
```

- `phase` — `PRE` 사고 전 링 버퍼 150장 · `POST` 사고 후.
- 새 프레임 도착은 WS `FRAME` 으로 알린다. 화면이 이 목록을 폴링하지 않는다.
- ⚠ 종결 후 mp4 인코딩이 끝나면 원본 프레임은 정리된다(§9.6) → 이 목록은 비고 `video` 로 넘어간다.

#### `GET /api/accidents/{accidentId}/frames/{seq}`

`200 image/jpeg`. 오류: `MEDIA_NOT_FOUND` 404

- ⚠ **`<img src>` 로 직접 못 쓴다** — 브라우저가 `Authorization` 헤더를 붙이지 않는다. `fetch` → `Blob` → `URL.createObjectURL` 로 그린다.

#### `GET /api/accidents/{accidentId}/video`

```json
{ "status": "READY", "url": "https://<r2 presigned>", "urlExpiresAt": "2026-09-14T05:00:00Z",
  "durationSec": 1830, "fps": 5, "startedAt": "2026-09-14T03:20:01Z", "triggerOffsetSec": 30,
  "stoppedAt": null }
```

| `status` | 뜻 |
|---|---|
| `NONE` | 진행 중 — 프레임 API 를 쓴다 |
| `ENCODING` | 종결됨, mp4 만드는 중 |
| `READY` | `url` 로 재생 |
| `FAILED` | 인코딩 실패 — **원본 프레임을 정리하지 않는다**(재시도 근거) |

- `url` 은 R2 presigned URL — `<video src>` 에 바로 쓴다. 만료 시간 `제안` 미정.
- `triggerOffsetSec` — 익수 확정(t=0)까지의 초. 이 앞 구간이 링 버퍼에서만 얻어지는 부분이다(웹 `ClipMeta.trigger`).
- 오류: `MEDIA_NOT_FOUND` 404 (프레임이 한 장도 안 온 사고) · `STORAGE_UNAVAILABLE` 503

---

## 4. Pi API 상세 (Pi → EC2)

### 4.1 공통 봉투

**요청** — `docs/edge/mqtt.md` §3 `Request<T>` 와 같다. Pi 가 MQTT 발행 코드를 그대로 재사용한다.

봉투를 쓰는 곳: `accidents` · `accident-states` · `reports` · `launches` · `buoys` · `ship-positions` · `comm-losses` · `drift-estimates` · `imus` (JSON 배열 수신 9개).
쓰지 않는 곳: `archives`(multipart) · `device-status`(단건 PUT) · `commands`(GET) · `commands/ack`(단건).

```json
{ "request_id": "01923f6e-...", "v": 1, "ts": 1757820067,
  "data": [ { }, { } ] }
```

| 필드 | 규칙 |
|---|---|
| `request_id` | uuid v7. **서버 로그 상관용** — 멱등 판정은 `data` 원소의 PK 가 한다 |
| `v` | 스키마 버전. 서버가 모르는 `v` 면 400 `PI_UNSUPPORTED_VERSION`(§7.3 제안) — **Pi 는 행을 버리지 않고 전송을 멈춘다**(아래 재시도 표). 일반 400 으로 주면 서버가 구버전일 때 Pi 의 모든 전송이 실패로 찍히고 폐기된다 |
| `ts` | Pi 발행 시각(Unix 초). 서버는 수신 시각과의 차이를 로그로만 남긴다 |
| `data` | **항상 배열.** 단건도 길이 1. 두절 복귀 때 밀린 것이 한꺼번에 온다 — 건당 요청이면 그 순간 요청 폭주다 |

**응답** (200)

```json
{ "success": true, "message": "OK",
  "data": { "received": 120, "inserted": 118, "duplicated": 2, "stale": 0 } }
```

| 필드 | 뜻 |
|---|---|
| `inserted` | 새로 반영 |
| `duplicated` | 같은 PK 가 이미 있음 — **재전송이다. 오류가 아니다** |
| `stale` | 늦게 도착한 옛 상태라 현재 상태에 반영 안 함(이력에는 남음, §4.2) |

- **배열 하나 = 트랜잭션 하나.** 원소 하나라도 거절되면 **전부 반영하지 않는다** — 일부만 들어가면 Pi 가 어디까지 성공했는지 알 수 없다.
- **배열 순서대로 처리한다.** Pi 는 `updated_at` 오름차순으로 보낸다(`database/pi.sql` `sync`) — §4.2 의 동시 사고 규칙이 이 순서에 기댄다.

**엔드포인트 사이의 순서는 FK 를 따른다** (`database/pi.sql` `sync` 주석).

```
accidents  →  accident-states · launches
           →  buoy-positions · imu · comm-losses · drift-estimates · (파일·영상)
           →  reports
ship-positions  — 사고와 무관. 아무 때나
```

사고 행 없이 자식을 먼저 올리면 FK 위반으로 **배치가 통째로 롤백된다.** 404 `ACCIDENT_NOT_FOUND` + `failed` 로 돌려주므로 Pi 는 그 원소를 보류하고 사고를 먼저 보낸다(아래 재시도 표).

**Pi 의 워터마크는 저장 확정 응답을 받은 뒤에만 전진한다**(`database/pi.sql`). 즉 2xx 를 못 받은 행은 Pi 가 계속 들고 있다 — 서버가 조용히 버리면 Pi 는 영원히 같은 것을 다시 보낸다.
- 모르는 필드는 무시한다(`docs/edge/mqtt.md` §0.1).
- 요청 크기 상한: JSON 엔드포인트 `제안` 1MB. `frames` 는 §4.3.

**거절 응답** — 배치 전체가 거절될 때 **어느 원소가 왜** 거절됐는지 반드시 싣는다.

```json
// 400 · 404 · 409
{ "code": "ACCIDENT_NOT_FOUND", "message": "...", "path": "/api/pi/buoys",
  "timestamp": "...",
  "failed": [ { "index": 17, "id": "0192...", "code": "ACCIDENT_NOT_FOUND" } ] }
```

`failed` 가 없으면 Pi 는 **배치의 나머지 299건을 버릴지 다시 보낼지 알 수 없다.** 두절 복귀 때 밀린 부표 위치 300건 중 1건이 아직 안 올라간 사고를 가리키는 일은 흔하다 — 그 1건 때문에 300건이 실패로 찍히면 조용한 손실이다. `ErrorResponse` 에 `failed` 필드를 더한다(§7.3).

**Pi 재시도 규칙** — 이 표가 IoT 팀과의 계약이다.

| 응답 | Pi 동작 | 이유 |
|---|---|---|
| 2xx | 전송 완료 표시 | |
| 400 `COMMON_INVALID_INPUT` · 413 | `failed` 의 원소만 **실패 표시 + 로그**, 나머지는 다음 배치로 다시 보낸다 | 형식 오류는 몇 번 보내도 같다. 다른 행까지 막으면 안 된다 |
| 400 `PI_UNSUPPORTED_VERSION` | **전송 중단 + 장비 상태 경고.** 행을 버리지 않는다 | 서버·Pi 버전 불일치. 사람이 풀어야 한다 |
| 404 `ACCIDENT_NOT_FOUND` | `failed` 원소를 **보류**, 선행 행(사고·상태) 전송 후 다시 보낸다 | 순서 문제다. 영구 실패가 아니다 |
| 404 `PI_SHIP_UNKNOWN` | 전송 중단 + 장비 상태 경고 | `ship_id` 설정 문제(`docs/edge/mqtt.md` §7 #7). 재시도해도 안 풀린다 |
| 409 `ACCIDENT_ALREADY_ACTIVE` | **재시도** (백오프) | 앞 사고의 종결이 아직 안 올라온 것 — 순서가 맞으면 풀린다(§4.2) |
| 그 외 409 | `failed` 원소만 실패 표시 | |
| 401 | 전송 중단 + 장비 상태 경고 | 키 설정 문제. 재시도해도 안 풀리고 쿼터·로그만 태운다 |
| 5xx · 타임아웃 · 연결 실패 | 재시도 (백오프) | 서버 사정이다. **같은 PK 로 보내므로 안전하다** |

"전송 중단" 은 큐를 비우는 것이 아니다 — 쌓아 두고 원인이 풀리면 이어 보낸다.

### 4.2 멱등 · 단조

| 규칙 | 방식 |
|---|---|
| **재전송 멱등** | **자연키 UNIQUE 로 한다** (결정 2026-09-17). Pi 는 PK 를 보내지 않고 서버가 uuid 를 채번한다. `ON CONFLICT (자연키) DO NOTHING` — ⚠ `ON CONFLICT (PK)` 로 적으면 매번 새 uuid 라 충돌이 영원히 안 나고 **조용히 중복이 쌓인다** |
| **상태 단조** | 사고의 현재 상태는 **순위(§1.7)가 올라갈 때만** 바뀐다. **낮은 순위가 오면 `stale`** — 그 원소는 상태뿐 아니라 다른 필드도 반영하지 않는다(옛 행이다). **같은 순위면 `stale` 이 아니다** — 상태는 그대로 두고 나머지 갱신 가능 필드(§4.3)를 반영한다. 시각을 비교하지 않는다 — Pi 와 서버의 시계 차이에 기대지 않기 위해서다 |
| **이력은 전부 남긴다** | `accident-states` 는 `stale` 이어도 이력 행으로 저장한다. 타임라인에서 "무엇이 늦게 왔나"가 보여야 한다 |
| **동시 사고 1건** | 서버에도 `uq_accident_active`(선박당 진행 중 1건)가 있다. 앞 사고의 종결보다 새 사고가 먼저 오면 409 `ACCIDENT_ALREADY_ACTIVE` → Pi 재시도. **Pi 가 `updated_at` 순서로 보내면 발생하지 않는다** |
| **종결 1회** | `closed_at` 은 `WHERE closed_at IS NULL` 로 한 번만 채운다(계획.md §9.20) |

> **Pi 는 자기 PK 를 보내지 않는다.** `database/pi.sql` 의 PK 는 `buoy_log_id`·`imu_id`·`report_id`·`accident_state_id`·`position_id` 등 **Pi 안에서만 뜻이 있는 `INTEGER` 자동 채번**이다. 서버로 보내도 쓸 데가 없고, 보내면 "이게 서버 PK 인가" 하는 오해만 남는다.
> **예외는 `accident_id` 와 `ship_id`** — 둘 다 TEXT uuid 다. `accident_id` 는 Pi 가 인터넷 없이 발급해야 해서 uuid v7 이고, `ship_id` 는 서버가 발급해 Pi 가 받아 둔 값이다.

**자연키 목록** — `db/migration/V9__edge.sql` ⓪ 에서 복원한다. 전부 Pi `database/pi.sql` 의 UNIQUE 와 같은 키다.

| 테이블 | 자연키 | 비고 |
|---|---|---|
| `buoy` | `(accident_id, created_at)` | LoRa 중복 수신도 여기서 막힌다. 1초 주기 전제의 의도된 dedup |
| `imu` | `(accident_id, created_at, imu_position)` | **`NULLS NOT DISTINCT`** — 없으면 `imu_position` 이 null 인 행이 중복된다 |
| `accident_state` | `(accident_id, status, created_at)` | 하이퍼테이블 아님 |
| `report` | `(accident_id, channel)` | `uq_report_accident_channel` 이 이미 있다 |
| `ship_position` | `(ship_id, created_at)` | |
| `accident` · `launch` | PK 그대로 | `accident_id` 는 Pi 가 uuid v7 로 만든다 — 인터넷 없이 발급해야 해서다 |

> **왜 바꿨나.** V1 ⑤ 는 자연키 UNIQUE 3개를 지우고 *"Pi 가 uuid v7 을 채번해 재전송 때 같은 값을 보낸다"* 를 계약으로 적었다.
> `database/pi.sql`(2026-09-17 수령)을 보니 Pi 의 PK 는 전부 `INTEGER` 자동 채번이다 — SQLite STRICT 에서 rowid 별칭이 되려면 `INTEGER` 여야 하기 때문이고, 그쪽이 옳다.
> 그리고 Pi 는 테이블마다 자연키 UNIQUE 를 걸고 **"서버 `uq_buoy_accident_measured` 와 같은 멱등키"** 라고 주석에 적었다 — 서버에 그게 있다고 믿고 있었다.
> **양쪽이 서로 상대방이 멱등을 해줄 거라 믿는 상태였다.** 되살리는 쪽이 Pi 변경 0 이고, 하이퍼테이블에서도 동작하는 것을 확인했다(파티셔닝 컬럼 `created_at` 포함).

> 이 구조에서 `PI_STALE_STATE` 409 는 쓰이지 않는다 — 옛 상태는 오류가 아니라 `stale` 계수다. 배치 안의 한 건 때문에 나머지를 거절하면 두절 복귀 때 큐가 멈춘다(§7.3).

### 4.3 수신 엔드포인트

공통: 모든 `data` 원소에 `ship_id` 가 필요한 곳은 **등록된 선박이어야 한다** → 아니면 404 `PI_SHIP_UNKNOWN`(배치 전체 거절, `failed` 에 해당 원소).

`duplicated` 의 뜻은 엔드포인트마다 다르다: 삽입 전용(상태 이력·부표·IMU)은 "같은 PK 가 이미 있음", upsert(사고·신고)는 "이미 같은 내용이라 바뀐 것이 없음".

#### `POST /api/pi/ships` — 선박 등록 신청 (2026-09-17 신설)

**`ship_id` 를 받는 유일한 경로다.** Pi 가 신청하고 서버가 uuid v7 을 발급한다.

> **왜 Pi 경로인가** (결정 2026-09-17). 관제 웹(SA)이 먼저 등록하는 안을 기각했다 —
> 설치 현장에 있는 사람은 선주고 **SA 는 카메라 높이·발사장치 거리 같은 현장 값을 먼저 알 방법이 없다.**
> Pi 로 두면 인증(`X-Ship-Register-Key`)이 이미 있고, **`ship_id` 주입 절차가 저절로 풀린다** —
> 응답으로 받은 값을 Pi 가 그대로 쓰면 된다(사람이 옮겨 적지 않는다).

> ⚠ **이 엔드포인트만 `ship_id` 를 요구하지 않는다.** 나머지 전부가 요구하는 값을 여기서 만들기 때문이다.

```jsonc
// 요청 — 봉투(§4.1)를 쓰지 않는다. 단건이고 배치가 성립하지 않는다
{
  "name":              "제7금양호",   // 필수, 최대 64
  "registration_no":   "1234567-6261102", // 필수, 최대 20. 아래 멱등의 근거
  "mmsi":              "440123456",  // 선택, 숫자 9자리
  "has_buoy":          true,         // 선택, 기본 false
}
```

```json
// 201 (새로 만들어짐) · 200 (이미 있음 — 아래 멱등)
{ "success": true, "message": "OK",
  "data": { "ship_id": "01923f6e-...",
            "ship_key": "9f2c…64자리",
            "status": "WAIT" } }
```

🔴 **`ship_key` 는 이때 한 번만 내려간다.** 서버는 해시로만 보관하므로 다시 보여줄 수 없다 —
Pi 는 **받는 즉시 로컬에 영속 저장**해야 한다(메모리에만 두면 재부팅에 잃는다).

- 이 뒤로 모든 `/api/pi/**` 요청은 **등록 키가 아니라 이 키**를 `X-Ship-Secret-Key` 에 싣는다.
- **키가 곧 선박 증명이다.** 서버는 페이로드의 `ship_id` 가 키의 선박과 같은지 검사하고,
  다르면 **404 `PI_SHIP_UNKNOWN`** 에 `failed[]` 를 실어 배치 전체를 거절한다.
  이것이 "한 키로 아무 `ship_id` 나 올릴 수 있다"를 닫는다.
  - 401 이 아닌 이유: **키 자체는 유효하다.** 401 로 주면 Pi 가 "키가 틀렸다"고 읽고
    재등록 쪽으로 가는데, 실제 원인은 페이로드의 `ship_id` 오타다.
  - 남의 `ship_id` 와 없는 `ship_id` 가 **같은 코드**다. 갈라 주면 id 를 바꿔 가며
    "그 선박이 존재하는지"를 물어볼 수 있게 된다.
- 재전송(200)일 때도 **같은 키를 다시 주지 않는다.** 키를 잃었으면 재발급 절차가 필요하다 — 🔴 미정(§9).
- ⚠ 승인 전(`WAIT`)에도 키는 나온다. 그래야 Pi 가 `GET /api/pi/ships/{ship_id}` 로 상태를 확인할 수 있다.
  **데이터 전송만 막힌다**(`PI_SHIP_NOT_APPROVED`).

**멱등은 `registration_no` 가 한다.** 새 키를 만들지 않는다 — 어선 등록번호가 이미 자연키이고
DB 에 부분 UNIQUE 가 걸려 있다(`uq_ship_registration_no`, `is_deleted = false AND status <> 'REJECTED'`).

| 상황 | 결과 |
|---|---|
| 처음 신청 | **201** · `status: "WAIT"` |
| 같은 등록번호로 다시 신청 (응답 유실 후 재시도) | **200** · **같은 `ship_id`** 를 돌려준다 |
| 반려(`REJECTED`)된 뒤 다시 신청 | **201** · 새 행. 부분 UNIQUE 가 `REJECTED` 를 제외하므로 **고쳐서 다시 낼 수 있다** |

- 🔴 **응답이 유실돼도 Pi 가 같은 등록번호로 다시 보내면 같은 값을 받는다.** 이것이 없으면 재시도마다 선박이 늘고, 그중 어느 것이 진짜인지 아무도 모른다.
- ⚠ `registration_no` 를 **필수**로 둔 이유가 이것이다. §3.3 의 SA 등록에서는 선택이었다.

#### `GET /api/pi/ships/{ship_id}` — 승인 상태 확인

```json
{ "success": true, "message": "OK",
  "data": { "ship_id": "01923f6e-...", "name": "제7금양호", "status": "ACTIVE" } }
```

- Pi 는 `WAIT` 동안 **화면에 "승인 대기"를 띄운다.** 주기는 Pi 가 정한다 — 초 단위 긴급도가 아니다.
- `REJECTED` 면 사람이 고쳐서 다시 신청해야 한다. 자동 재시도로 풀리지 않는다.
- **자기 선박만 볼 수 있다.** 경로의 `ship_id` 가 키의 선박과 다르면 **404 `PI_SHIP_UNKNOWN`** 이다 —
  403 이면 "그런 선박이 있다"를 알려주는 셈이라 `ship_id` 를 바꿔 가며 훑을 수 있다.
- ⚠ 이 경로는 **선박 키로 부른다.** 등록 키로는 열리지 않는다(등록 키는 여러 Pi 가 공유하므로
  그것으로 열리면 남의 선박 상태가 전부 보인다).

#### 승인 전에는 데이터를 받지 않는다

`status` 가 `ACTIVE` 가 아닌 선박의 데이터는 **거절한다** — 404 `PI_SHIP_UNKNOWN` 과 구분되는 코드를 준다.

> **데이터를 잃지 않는다.** §4.1 재시도 표대로 Pi 는 전송을 멈추고 큐를 쥐고 있다가,
> 승인된 뒤 밀린 것부터 보낸다. 승인이 늦어도 사고 기록은 남는다 —
> **받아서 섞어 두는 것보다 낫다**: 승인 안 된 선박의 사고가 관제 목록에 올라오면
> 그게 실제 선박인지 누가 키를 들고 장난친 것인지 구분할 방법이 없다.

#### `POST /api/pi/accidents` — 사고 upsert

Pi `pi_accident` 행 그대로. 새 사고면 INSERT, 있으면 **상태 단조 규칙으로** 갱신한다.

```ts
{
  accident_id:    Uuid;          // PK. Pi 발급
  ship_id:        Uuid;
  accident_type:  AccidentType;
  trigger_source: 'AI' | 'MANUAL';
  report_type:    'DISTRESS' | 'URGENCY';   // SAFETY 는 1차 제외
  report_dsc:     Int | null;    // 100~111. URGENCY 는 null
  status:         AccidentStatus;
  accident_lat:   number | null; // GPS 미수신이면 null
  accident_lon:   number | null;
  report_due_at:  Unix | null;   // WAIT 일 때만 — 없으면 CHECK 위반 400
  wait_sec:       Int | null;    // 카운트다운 길이. 30초가 정책값이라 기록으로 남긴다
  rescued_at:     Unix | null;   // 구조 확정 시각. CLOSE 가 구조인지 종료인지 가르는 유일한 값
  closed_at:      Unix | null;
  model_version:  string | null; // 오탐 분석용
  created_at:     Unix;          // Pi 가 사고를 만든 시각. 서버 수신 시각 아님
}
```

- `pi_accident` 16컬럼(`database/pi.sql`) 중 `updated_at` 만 뺐다 — 서버가 자기 값으로 채운다. **PK 는 Pi 가 만든 uuid v7 그대로 쓴다**(이 테이블만 예외, §4.2).
- 갱신 시 바뀔 수 있는 것: `status`(단조) · `report_due_at` · `rescued_at`(1회) · `closed_at`(1회) · `accident_lat/lon`(null 이었을 때만). **나머지는 불변** — 다른 값이 오면 무시하고 경고 로그.
- 서버가 같이 거는 CHECK (Pi 와 동일) — `status='WAIT'` 이면 `report_due_at` 필수 · `status<>'CLOSE'` 면 `closed_at` 은 null · `trigger_source='AI'` 면 `accident_type='MOB'`(AI 감지는 익수만 만든다).
- ⚠ `wait_sec`·`rescued_at`·`model_version`·`accident_type`·`trigger_source` 는 아직 서버 컬럼 없음 — `V9__edge.sql` ① 이 추가한다.
- ✅ **`SAFETY` 를 1차 범위에서 뺐다 (결정 2026-09-17).** 수동 신고 유형은 **8종**(DISTRESS 7 + URGENCY 1)이고 **전부 사고를 연다.** 예전 설계의 "SAFETY 가 오면 400"은 폐기 — 그 400 이 Pi 의 전송을 막는 구조였다.
  - **뺀 이유**: SAFETY 는 *"내 배에 아무 일도 안 일어났다"* 는 신고라 사고를 열면 종결될 계기가 없어 `closed_at` 이 null 인 행이 쌓이고, `uq_accident_active` 때문에 진행 중 사고가 있으면 발신이 막힌다. 별도 테이블로 가르는 값이 1차 범위에서는 비용보다 작았다.
  - 🔴 **Pi 는 아직 10종이다.** `iot/pi/floaq/contracts/enums.py` 의 `AccidentType` 에 `HAZARD`·`ABANDON_SHIP` 이 남아 있다. **전달 필요.**
  - 🔴 **그중 `ABANDON_SHIP` 은 등급이 틀렸다** — Pi 가 `(SAFETY, 108)` 로 라우팅했는데 **퇴함은 조난이다.** DSC 의 **category** `108`(safety)과 **nature of distress** `108`(abandoning ship)을 섞어 읽은 것으로 보인다. 되살릴 때는 `DISTRESS` 다.
- 오류: `PI_SHIP_UNKNOWN` 404 · `ACCIDENT_ALREADY_ACTIVE` 409(재시도)

#### `POST /api/pi/accident-states` — 상태 이력

```ts
{
  accident_id: Uuid;
  status:      AccidentStatus;
  prev_status: AccidentStatus | null;
  reason:      StateReason;        // 아래 8종
  caused_by:   string | null;      // 누가/무엇이 바꿨나. Pi pi_accident_state.caused_by
  created_at:  Unix;               // 상태가 바뀐 시각
}
// 멱등 자연키 = (accident_id, status, created_at)  ← Pi UNIQUE 와 같다
// PK(accident_state_id, INTEGER)는 보내지 않는다 (§4.2)
```

`StateReason` — `database/pi.sql` CHECK 8종.

```
AI_DETECT · COUNTDOWN_START · TIMEOUT
TABLET_CANCEL · TABLET_REPORT_NOW · TABLET_MANUAL · TABLET_RESCUE · TABLET_CLOSE
```

- 🔴 **관제 웹 종료·1시간 자동 종결을 적을 값이 없다.** 계획.md §9.20 이 "종결 주체를 남긴다"고 한 기록이 여기로 오는데 8종이 전부 선내 동작이다. 후보 `WEB_CLOSE`·`AUTO_CLOSE` — **Pi CHECK 에도 같이 넣어야 한다**(§9 3 #10).
- 모르는 `reason` 은 400 으로 거절한다. 조용히 null 로 두면 종결 주체 기록이 사라진다.
- `backend-plan` 의 `PUT /api/pi/accidents/{id}/state`(단건)를 이것으로 바꿨다 — "전부 배열" 원칙과 맞추기 위해서다(§8 #10).
- 사고 행보다 먼저 오면 FK 위반 → 404 `ACCIDENT_NOT_FOUND` + `failed`. Pi 는 그 원소를 **보류하고 사고를 먼저 보낸 뒤 다시 보낸다**(§4.1 표). 같은 전송 순위 1 안에서 `pi_accident` → `pi_accident_state` 순으로 보내면 생기지 않는다.

#### `POST /api/pi/reports` — 신고 발신 기록 (채널별 upsert)

```ts
{
  accident_id:   Uuid;
  channel:       'AIS_MOB' | 'AIS_SART' | 'DSC';
  trigger_kind:  'AUTO' | 'MANUAL' | 'RESCUE';   // ⚠ accident.report_type 과 다른 것이다
  status:        'SENDING' | 'ACKED' | 'STOPPED' | 'FAILED';
  sent_count:    Int;                 // 누적
  report_lat:    number;              // 전송 좌표 — 불변 스냅샷
  report_lon:    number;
  first_sent_at: Unix | null;         // 🔴 아직 한 번도 못 쏜 채널은 null — 아래
  last_sent_at:  Unix | null;
  acked_at:      Unix | null;         // DSC 만 (AIS 는 단방향이라 ACK 이 올 수 없다)
  acked_by:      string | null;       // 9자리 MMSI
  fail_reason:   'NO_INTERNET' | 'NO_RECEIVER' | 'TIMEOUT' | null;
  created_at:    Unix;                // Pi 가 이 채널 행을 만든 시각
}
// 멱등 자연키 = (accident_id, channel)  ← Pi UNIQUE 와 같다
```

- **서버는 발신하지 않는다.** Pi 가 UDP 로 쏜 사실만 받는다(계획.md §9.4).
- **`trigger_kind` 는 `accident.report_type` 과 다르다.** 구 ERD 가 둘 다 `report_type` 이라 부르고 뜻이 달라서 Pi 가 개명했다(§8 #16 해소). 이 필드는 "자동/수동/구조 중지"이고, `report_type` 은 "DISTRESS/URGENCY"다.
- 🔴 **서버 `report.created_at` = `first_sent_at` 매핑이 깨진다.** Pi 의 `first_sent_at` 은 **NULL 허용**이다 — 인터넷이 없어 `SENDING` 조차 못 간 채널의 행이 먼저 생긴다. 서버 PK 가 `(report_id, created_at)` 이라 `created_at` 이 null 이면 행이 못 들어간다.
  → **`created_at` 은 Pi 의 `created_at`(행 생성 시각)을 쓰고 `first_sent_at` 은 별도 컬럼으로 둔다.** "못 쏜 채널"이 관제에 보여야 하므로 그 행을 버리는 안은 기각(§8 #22).
- 같은 `(accident_id, channel)` 이 다시 오면 `sent_count`·`last_sent_at`·`status`·`acked_*`·`fail_reason` 을 갱신한다. `sent_count` 는 **줄어들지 않는다** — 작은 값이 오면 그 원소는 `stale`(옛 행). `status` 는 `SENDING → ACKED|STOPPED|FAILED` 로만 간다 — 역행도 `stale`.
- ⚠ 지금 서버 `Report` 엔티티는 append-only(`isNew()` 항상 true)라 이 모양을 못 받는다(§8 #8).

#### `POST /api/pi/launches` — 투하 결과

```ts
{
  accident_id:      Uuid;     // PK — 사고당 1회, 재투하 없음(E5)
  detection_id:     string | null;   // Jetson 탐지 건 식별자. 조준 해의 출처 추적용
  result:           'SUCCESS' | 'FAILED';
  fail_reason:      'NOT_LOADED' | 'DEVICE_ERROR' | 'OUT_OF_RANGE' | 'NO_SOLUTION' | null;
  launch_lat:       number;
  launch_lon:       number;
  target_lat:       number | null;   // 조준 해가 없으면(NO_SOLUTION) null
  target_lon:       number | null;
  horizontal_angle: Deg;      // -180 ~ 180. 실제로 명령한 각도
  vertical_angle:   Deg;      //  -90 ~ 90
  confidence_score: number | null;  // 0~1
  created_at:       Unix;           // launched_at
}
```

- `FAILED` 도 저장한다 — 발사 정확도 피드백(APP 요구사항 "발사 데이터 기록")의 근거다.
- `NO_SOLUTION` 은 **Jetson 이 조준 해를 못 낸 경우**다(2026-09-17 `database/pi.sql` 대조로 추가). 나머지 셋과 원인이 다르다 — 장비가 아니라 계산이 실패한 것이다.
- **조준 해는 Jetson 이 계산한다.** Pi 는 범위·만료·프로파일을 검증만 하고 거부하면 `FAILED` 로 남긴다. 소프트 리밋에 걸리면 **명령한 각도가 `target_*` 과 다를 수 있다** — 그래서 둘 다 받는다.
- `(result='SUCCESS') = (fail_reason IS NULL)` 은 서버도 CHECK 로 건다.

#### `POST /api/pi/buoys`

```ts
{
  accident_id: Uuid;
  seq:         Int;     // 부표가 매긴 순번. 유실 감지용
  lat:         number;  // Pi 컬럼명 그대로
  lon:         number;
  is_pressed:  0 | 1;
  rssi:        number | null;
  created_at:  Unix;    // 부표 GPS 가 위치를 측정한 시각
  received_at: Unix;    // Pi 가 LoRa 로 받은 시각. 둘은 지연만큼 벌어진다
}
// 멱등 자연키 = (accident_id, created_at)  ← Pi UNIQUE 와 같다
// PK(buoy_log_id, INTEGER)는 보내지 않는다 (§4.2)
```

- ⚠ **서버 컬럼은 `buoy_lat`/`buoy_lon` 이다.** V1 이 그 이름으로 이미 배포돼 바꾸지 않았다 — **DTO 에서 `lat`→`buoy_lat` 로 매핑한다.** 이 프로젝트에서 매핑 실수가 남은 유일한 자리다(§8 #17). 지도가 조용히 어긋나는 종류라 테스트로 고정할 것.
- 지도에는 `created_at`(측정 시각)을 쓴다. `received_at` 은 LoRa 지연을 재는 값이다.
- `is_pressed = 0` 이 **"사람이 없다"는 뜻은 아니다**(E9).
- 서버는 반영 후 WS `BUOY_POS` 를 보낸다. **측정 시각이 가장 최신인 1건만** — 두절 복귀 때 밀린 300건을 화면에 300번 그리지 않는다.
- ⚠ `seq`·`received_at`·`rssi` 는 `V9__edge.sql` ⑤ 가 추가한다.
- ⚠ 자연키가 초 단위라 **같은 초에 2건이 오면 두 번째가 조용히 버려진다.** 1초 주기 전제의 의도된 dedup 이고 Pi 도 같다.

#### `POST /api/pi/ship-positions`

**평시에도 받는다 (결정 2026-09-17).** 계획.md §9.13 의 *"웹이 선박 위치를 받는 계기는 사고뿐"* 을 뒤집었다.
원천은 `pi/sensor/gps` — **Pi 자체 GPS** 다(`ref/mqtt-연동-웹_v2` §2, 1Hz · retained). 키오스크가 꺼져도 위치가 살아 있어 계획.md §9.2 의 역할 경계가 유지된다.

```ts
{
  ship_id:          Uuid;
  accident_id:      Uuid | null;    // 평시 null. 이 필드의 유무가 평시/사고를 가른다
  lat:              number;         // ✅ Pi 이름 그대로 (database/pi.sql 대조 완료)
  lon:              number;
  speed_kn:         number | null;  // knot. ETA 입력(계획.md §9.14)
  heading_deg:      number | null;  // 진북 기준 0~360
  accuracy_m:       number | null;  // GPS 오차 반경(m). null = Pi 가 모름, 0 아님
  created_at:       Unix;           // GPS 측정 시각(measured_at)
}
// 멱등 자연키 = (ship_id, created_at)  ← Pi UNIQUE 와 같다
// PK(position_id, INTEGER)는 보내지 않는다 (§4.2)
```

⚠ **`pi_ship_position` 에는 `accident_id` 가 없다.** Pi 는 사고와 무관하게 위치만 쌓고 사고 중에 주기를 1초로 올릴 뿐이다.
`accident_id` 를 채우는 주체를 정해야 한다 — **서버가 수신 시각으로 진행 중 사고에 붙이는 쪽**이 싸다(Pi 스키마 변경 0). 🔴 IoT 확인.

| | |
|---|---|
| 주기 | **평시 5초 · 사고 중(DETECT/WAIT/REPORT) 1초** (`database/pi.sql` 제안 채택 2026-09-17) |
| 전송 | Pi 가 DB 에 쌓은 그대로 배열 배치(§4.1) |
| 저장 | `ship_position` 하이퍼테이블, 조각 간격 **1시간** (`db/migration/V9__edge.sql` ⑧) |
| 보관 | **24시간.** 스케줄러가 `drop_chunks` 를 부른다 |

> ⚠ **MQTT 발행 1Hz 와 DB 기록 주기는 다르다.** 서버로 올라오는 건 DB 쪽이라 평시는 5초 간격이다.
> `database/pi.sql` 근거 — 10노트면 5초에 26m 로 지도에서 충분히 부드럽고, 조준 해 입력은 MQTT 1Hz 가 받는다.
> 하루 **17,280행**(1Hz 대비 1/5).

- 🔴 **자동 retention 은 못 쓴다.** `timescale/timescaledb:2.21.3-pg17-oss` 는 apache 라이선스라
  `add_retention_policy` 가 *"not supported under the current apache license"* 다(2026-09-17 실호출).
  `drop_chunks` 는 apache 에서 되므로 그걸 스케줄러가 부른다 — `OceanRetention` 과 같은 줄기다.
- ⚠ **실제 보관은 24~25시간이다.** `drop_chunks` 는 조각 전체가 기준보다 오래됐을 때만 버린다.
  1Hz 3시간치(10,800행)로 재현: 조각 4개 · `older_than 2h` 가 **1개만** 버려 9,136행 남음(2026-09-17).
  평시 5초면 조각당 720행이다.
  조각 간격을 기본값 7일로 두면 24시간 보관에 최대 8일치가 남는다 — 그래서 1시간이다.
- 🔴 **배치 크기 상한에 가장 먼저 부딪히는 엔드포인트다.** §4.1 의 JSON 1MB `제안` 기준,
  원소 하나가 200바이트 남짓이면 약 5,000건이다(실측 아님, 자릿수 확인용).
  평시 5초 기준으로는 **약 7시간치** — 1Hz 였다면 80분치였다. 주기 결정으로 크게 완화됐지만
  **반나절 두절이면 여전히 나눠 보내야 한다.**
- 🔴 **두절이 24시간을 넘으면 밀린 평시 위치가 올라오자마자 지워진다.** 들어간 뒤 다음 스윕이 그 조각을 버린다.
  조용한 손실이라 둘 중 하나를 정해야 한다 — Pi 가 24시간 넘은 평시 행을 안 보내거나, 서버가 받되 `stale` 로 세어 응답에 싣거나.
  ⚠ Pi 의 삭제 정책은 **워터마크 위쪽 행을 절대 건드리지 않는다**(`database/pi.sql` `sync`) — 즉 Pi 는 안 올라간 행을 계속 들고 있다. 버리는 쪽은 서버다.
  **사고 구간 행(`accident_id` 있음)은 지우면 안 된다** — 사고 기록의 일부다. 지금 DDL 은 그 구분 없이 조각째 버린다(미해결, §9).

#### `POST /api/pi/comm-losses` — LoRa 두절 구간

**두절 판정은 Pi 가 한다** (확정 2026-09-17). 서버 스케줄러를 두지 않는다 — 두절 판정은 인터넷 없이도 동작해야 하고, 두 곳에서 판정하면 오판정이 곧 오경보다(계획.md §1.4).

```ts
{
  accident_id:      Uuid;
  detected_at:      Unix;          // 두절로 판정한 시각
  last_lat:         number;        // 마지막으로 받은 부표 위치 — 조인 없이 지도에 찍으려고 복사한 값
  last_lon:         number;
  last_received_at: Unix;          // 그 위치를 받은 시각
  threshold_sec:    Int;           // 판정 당시 기준. 나중에 기준이 바뀌어도 기록은 안 흔들린다
  recovered_at:     Unix | null;   // 복구되면 채워서 다시 보낸다 (upsert)
}
// 멱등 자연키 = (accident_id, detected_at)
// Pi 의 comm_loss_id(INTEGER) · last_buoy_log_id 는 보내지 않는다 —
//   후자는 last_lat/lon/received_at 이 이미 값을 복사해 갖고 있어 서버가 쓸 데가 없다
```

- `threshold_sec` 를 행마다 박제하는 것이 핵심이다. 계획.md 는 두절 임계값 60초를 **임시값**으로 두고 있는데, 나중에 바꿔도 지난 판정의 근거가 남는다.
- `recovered_at` 이 채워져 다시 오면 **같은 행을 갱신한다**(`stale` 아님). 두절 구간은 열렸다 닫히는 하나의 행이다.

#### `POST /api/pi/drift-estimates` — 표류 추정 범위

**계산도 Pi 가 한다.** 인터넷 없이 동작해야 하고, Pi 에 없으면 오프라인 사고의 수색 범위 이력이 사라진다.

```ts
{
  accident_id:         Uuid;
  comm_loss_detected_at: Unix | null;  // 어느 두절 구간에 딸린 추정인가 (comm-losses 자연키로 잇는다)
  base_lat:            number;         // 추정의 출발점 — 마지막으로 받은 부표 위치
  base_lon:            number;
  last_received_at:    Unix;
  elapsed_sec:         Int;            // 그 뒤로 흐른 시간
  center_lat:          number;         // 추정 중심
  center_lon:          number;
  radius_m:            number;         // 추정 반경
  input_current_speed: number | null;  // 계산에 쓴 해양 데이터 스냅샷
  input_current_dir:   number | null;  // 0~360
  input_wind_speed:    number | null;
  input_wind_dir:      number | null;
  input_observed_at:   Unix | null;    // 그 해양 데이터의 관측 시각
  is_current:          0 | 1;          // 지금 유효한 추정인가
  created_at:          Unix;
}
// 멱등 자연키 = (accident_id, created_at)
// Pi 의 estimate_id·comm_loss_id(INTEGER)는 보내지 않는다 (§4.2)
```

- **덮어쓰지 않고 쌓는다.** 갱신될 때마다 새 행이 오고 이전 건은 `is_current = 0` 으로 내려온다. 덮으면 *"그때 어디를 수색 범위로 봤는지"* 가 사라진다. 사고당 `is_current = 1` 은 1건(Pi 에 부분 UNIQUE).
- 🔴 **`input_observed_at` 을 화면에 반드시 같이 띄운다.** `input_*` 이 전부 null 이면 **해양 데이터 없이 추정한 것**이다. 3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 **화면에서 똑같이 생겼다.**
- 🔴 `comm_loss_detected_at` 으로 두절 구간을 잇는 방식은 **서버가 정한 것**이다 — Pi 는 내부 `comm_loss_id`(INTEGER)로 잇고 있어 그 값이 서버에서 뜻이 없다. IoT 확인 필요.

#### `POST /api/pi/imus`

```ts
{
  accident_id:  Uuid;    // 사고 구간만 올린다 — 평시는 링 버퍼(IOT-09)
  imu_position: 'HULL' | 'CAMERA_L' | 'CAMERA_R';
  accel_x:      number | null;   // m/s²
  accel_y:      number | null;
  accel_z:      number | null;
  roll:         Deg;             // 자세각. deg/s 아님
  pitch:        Deg;
  yaw:          Deg;
  heading_deg:  number | null;
  created_at:   Unix;
}
```

30초 단위로 묶어 보낸다(IOT-20). ⚠ `imu_position`·`heading_deg` 서버 컬럼 없음.

#### `POST /api/pi/archives` — 프레임 tar

`multipart/form-data`

| 파트 | 타입 | 내용 |
|---|---|---|
| `meta` | `application/json` | 아래 |
| `file` | `application/x-tar` | JPEG N장, **무압축** — JPEG 는 이미 압축돼 있어 gzip 은 Pi CPU 만 쓴다 |

```ts
// meta
{
  accident_id:       Uuid;
  chunk_seq:         Int;          // 사고 안에서 0부터. 멱등 키 = (accident_id, chunk_seq)
  phase:             'PRE' | 'POST';  // PRE = 사고 전 링 버퍼 150장
  frame_count:       Int;
  first_captured_at: Unix;
  last_captured_at:  Unix;
}
```

- tar 안 파일 이름은 `{seq}.jpg` — `seq` 는 사고 안에서 전역 순번(웹 `frames/{seq}`).
- 같은 `(accident_id, chunk_seq)` 재전송 → 200 `duplicated: 1`. tar 를 다시 풀지 않는다.
- 크기: 30초 × 5fps = 150장. 프레임당 50KB 면 7.5MB, 200KB 면 30MB — **값이 문서마다 달라 미정**(계획.md §9.6).
  - 지금 값 (2026-09-16 설정): Spring `max-file-size: 32MB` · `max-request-size: 34MB`, nginx `client_max_body_size 40m`. **nginx 를 Spring 보다 크게** 둔다 — nginx 가 먼저 끊으면 아래 `MEDIA_TOO_LARGE`(JSON) 대신 nginx 기본 HTML 이 가서 Pi 가 청크를 쪼갤 단서를 못 받는다. 32MB 근거는 150장 × 200KB(`docs/edge/mqtt.md` §5.2) + tar 오버헤드. **프레임 실측 후 두 값을 같이 조정한다.**
  - 🔴 Tomcat `max-swallow-size: -1` 도 같이 설정했다. 기본 2MB 라, 30MB 요청을 413 으로 거부할 때 남은 본문을 삼키지 못해 **연결이 끊기고 Pi 는 응답 대신 타임아웃을 본다.**
  - `MaxUploadSizeExceededException` → `MEDIA_TOO_LARGE` 매핑은 `GlobalExceptionHandler` 에 있다(2026-09-16). 정상 흐름이라 stack trace 없이 warn 만 남긴다 — 자주 찍히면 상한이 낮은 것이다.
  - 넘으면 413 `MEDIA_TOO_LARGE` — 재시도 금지, Pi 가 청크를 쪼갠다(`chunk_seq` 를 새로 매기고 `frame_count` 를 줄인다).
- **Pi 는 R2 자격증명을 갖지 않는다.** R2 에는 EC2 가 올린다. `database/pi.sql` 의 `pi_accident_file.object_key` 주석도 *"R2 업로드 확정 후에 채운다"* 로 같다 — **서버가 키를 돌려주고 Pi 가 받아 적는다**(§8 #11 해소).
- 프레임 전송은 `STOP_MEDIA` 명령 처리 후 · 사고 종결 후 · 사고 후 1시간에서 끝난다.

> 🔴 **이 엔드포인트는 아직 합의 전이다.** Pi 쪽에는 `pi_accident_file` 이 **파일 한 장 = 한 행**으로 있고,
> `ref/mqtt-연동-웹_v2` §11 도 `POST /api/accidents/{id}/files` 로 **장당 1요청**을 제안한다.
>
> | | 이 문서 (tar) | Pi·v2 (장당) |
> |---|---|---|
> | 근거 | 장당 요청이면 오버헤드가 프레임보다 크다(계획.md §9.6) | 묶으면 부분 실패가 지저분해진다 |
> | 멱등키 | `(accident_id, chunk_seq)` | `(accident_id, file_type, sequence_no)` |
> | 분류 | `phase: PRE\|POST` | `file_type: DETECT_SNAPSHOT\|BEFORE\|AFTER` |
> | 카메라 | 없음 | `camera: L\|R` |
>
> Pi 쪽이 `DETECT_SNAPSHOT` 과 `camera` 를 더 갖고 있다 — 감지 스틸컷은 프레임과 성격이 다르고, 카메라가 2대라 좌우 구분이 필요하다. **tar 로 가더라도 `meta` 에 이 둘을 실어야 한다.** 합의 전까지 구현하지 않는다(§8 #20).

#### `PUT /api/pi/device-status` — 제안

```ts
{ ship_id: Uuid, camera_l: 'OK'|'ERROR'|'UNKNOWN', camera_r: ..., camera_dirty: boolean,
  imu: ..., lora: ..., ai: ..., gps: ..., internet: boolean,
  last_buoy_rx_at: Unix | null, measured_at: Unix }
```

- 봉투 없이 **단건**, 최신값으로 덮어쓴다. 이력은 남기지 않는다 — `docs/edge/mqtt.md` 도 저장하지 않는다.
- `is_loaded`(장전 여부)는 받지 않는다 — 계획.md §9.15 에서 뺐다.
- 주기는 Pi 가 정한다. 서버는 `receivedAt` 을 붙여 두고, 화면이 경과 시간으로 "Pi 와 연락 끊김"을 판단한다.

### 4.4 하행 (EC2 → Pi, Pi 폴링)

Pi에 인바운드를 열지 않는다(계획.md §9.9). 하행은 **명령**과 **해양 데이터** 둘이다.

#### `GET /api/pi/ocean?ship_id=&after=` — 해양 데이터 (제안, 2026-09-17 신설)

**왜 필요한가.** 표류 추정을 Pi 가 계산하는데(§4.3 `drift-estimates`) 그 입력인 조류·바람이 Pi 에 있어야 한다. 인터넷이 끊긴 뒤에 계산해야 하므로 **미리 받아 둬야** 한다. `database/pi.sql` 의 `pi_ocean_data` + `sync.direction = 'PULL'` 이 이 경로다.

**왜 Pi 가 직접 공공 API 를 부르지 않나.** API 키가 배에 실린다. `database/pi.sql` 주석도 *"EC2 가 받아 Pi 가 pull 하는 쪽을 권한다(API 키를 배에 두지 않아도 된다)"* 로 같다. 계획.md §9.13 이 키오스크에 대해 쓴 논지와 같다 — 키 노출·쿼터 중복·정규화 로직 중복.

```ts
// 응답 data — pi_ocean_data 행 그대로
{
  ship_id:       Uuid;
  source:        'KHOA' | 'KMA' | 'MOF';
  observed_at:   Unix;           // 관측 시각
  wind_speed:    number | null;  // m/s
  wind_dir:      number | null;  // 0~360
  current_speed: number | null;  // m/s
  current_dir:   number | null;
  wave_height:   number | null;  // m
  water_temp:    number | null;
  fetched_at:    Unix;           // 서버가 받은 시각
}
// Pi 멱등키 = (ship_id, source, observed_at)
```

- **단위는 서버가 정규화해서 준다.** `OceanUnits` 가 cm/s·kn → m/s, 16방위 한글 → deg 를 이미 한다. Pi 가 또 하면 두 벌이 되고, 이건 **틀려도 예외가 안 나서 표류 반경이 조용히 100배가 되는** 종류다.
- `observed_at` 은 `drift-estimates.input_observed_at` 으로 그대로 복사된다 — 화면이 "몇 분 전 데이터로 그린 원인가"를 말할 수 있어야 한다.
- 🔴 **`source` 3종이 서버 수집기 12종과 대응이 안 된다.** 서버는 `roms`·`sea-obs`·`weather-warning` 처럼 소스별로 나뉘어 있고 Pi 는 기관 단위(`KHOA`/`KMA`/`MOF`)다. 표류 입력은 ROMS 단독이므로(계획.md §6) **당장은 `KHOA` 하나로 충분**하지만 매핑을 정해야 한다.
- 🔴 폴링 주기 미정 — 명령(`commands`)과 같은 폴링에 얹을지 따로 둘지. 해양 값은 초 단위 긴급도가 아니다.

#### `GET /api/pi/commands?ship_id=&after=` — 명령

```json
{ "success": true, "message": "OK",
  "data": [ { "command_id": "0192...", "ship_id": "0192...", "accident_id": "0192...",
              "type": "CLOSE_ACCIDENT", "issued_at": 1757821200 } ] }
```

- **`ship_id` 필수** — pi 키가 선박마다 다르지 않아 누가 부르는지 서버가 모른다(§9).
- 아직 ack 되지 않은 명령(`ISSUED`·`DELIVERED`)을 `command_id`(uuid v7 = 시간순) 오름차순으로 준다. `EXPIRED` 는 주지 않는다 — 관제가 이미 재요청했을 수 있어 옛 명령이 뒤늦게 실행되면 안 된다. 처음 내려준 순간 `DELIVERED` + WS `COMMAND_STATE`.
- `after` 는 선택 — 주지 않으면 **미처리 전부**. 커서를 잃어도(재부팅) 명령을 놓치지 않는다.
- 폴링 주기는 IoT 팀과 맞춘다. 종결은 초 단위 긴급도가 아니다.

#### `POST /api/pi/commands/ack`

```json
// 요청
{ "result": "DONE", "error_code": null, "accident_status": "CLOSE", "handled_at": 1757821206 }
```

| 필드 | 규칙 |
|---|---|
| `result` | `DONE` · `REJECTED` |
| `error_code` | `REJECTED` 일 때 — `ALREADY_RESOLVED` · `ALREADY_CANCELLED` · `INVALID_STATE` · `ACCIDENT_NOT_FOUND` |
| `accident_status` | 처리 후(거절이면 현재) Pi 가 아는 상태. 웹이 화면을 실제 상태로 돌린다 |

- 같은 ack 재전송 → 200. 이미 `DONE` 인데 `REJECTED` 가 오면 무시하고 경고 로그. `EXPIRED` 뒤에 온 ack 는 **받는다**(§3.5) — Pi 가 처리한 사실이 만료 표시보다 진실이다.
- 두절 중 쌓인 `CLOSE_ACCIDENT` 가 이미 선내에서 닫힌 사고에 늦게 닿는 것은 **정상 경로**다 — Pi 는 `REJECTED` + `ALREADY_RESOLVED` 로 답한다.
- 오류: `COMMON_NOT_FOUND` 404 (→ `COMMAND_NOT_FOUND` 추가 제안)

### 4.5 명령 상태

| `CommandState` | 언제 | 화면 문구 예 |
|---|---|---|
| `ISSUED` | 웹이 요청 | 종료 요청함 — 선박 전달 대기 |
| `DELIVERED` | Pi 가 가져감 | 선박에 전달됨 — 처리 대기 |
| `DONE` | Pi 가 처리 | 종료됨 |
| `REJECTED` | Pi 가 거절 | `errorCode` 문구 (예: 이미 선내에서 종결됨) |
| `EXPIRED` | 처리 전 `제안` 10분 경과 (§3.5) | 선박이 응답하지 않음 — 다시 요청 가능 |

---

## 5. 해양 공공데이터 API — 구현

**조회 때 외부 API 를 부르지 않는다.** 수집기가 미리 받아 둔 것을 준다(계획.md §6).

kiosk 는 `cloudUrl()`(`packages/shared/src/origins.ts`)로 부른다 — 빌드는 `VITE_CLOUD_ORIGIN` + `/api/ocean/**` 직접 호출(CORS), 개발 서버만 `/cloud` 접두어를 Vite 프록시가 떼어 낸다. **프론트·백엔드 payload 계약은 `apps/kiosk/src/cloud/ocean.ts` 다.**

관제 웹이 해양 API 를 붙일 때는 **`at` 을 넘기거나 키 없이 조회만** 한다 — 웹 번들에는 kiosk 키를 넣지 않는다(§1.1).

### 5.1 `GET /api/ocean/sources`

```json
[ { "source": "weather-warning", "kind": "ADVISORY",
    "observedAt": "2026-09-14T02:00:00Z", "fetchedAt": "2026-09-14T02:10:03Z",
    "ageSec": 4210, "intervalSec": 600,
    "resultCode": "00", "resultMsg": "NORMAL_SERVICE",
    "payload": { } } ]
```

| 필드 | 뜻 |
|---|---|
| `kind` | `OBSERVATION` "30분 전 관측" · `FORECAST` "17시 예측값" · `ADVISORY` "2일 전 발표" — 예보의 `ageSec` 를 신선도로 읽으면 방금 받은 값이 낡아 보인다 |
| `ageSec` | `observedAt` 이후 경과 초. 성공 이력이 없으면 null |
| `payload` | 소스별로 다르다 — `cloud/ocean.ts` 타입 참고 |

- **stale 판정은 서버가 하지 않는다.** 갱신 주기가 3분~주간으로 다섯 자리 차이라 임계를 서버가 정하면 근거 없는 숫자가 된다.
- `source` 오름차순. 수집 설정에 없는 소스도 스냅샷이 있으면 나온다(`kind` null).
- **`lat`·`lon` (선택, 2026-09-15)** — 지점 소스(`sea-obs`·`fishing-ground`·`current-forecast`·`tide-forecast`)의 `payload.stations` 를 이 좌표 반경(`app.ocean.coverage.station-radius-km`, 기본 30km)으로 자르고, 행마다 `distanceKm` 를 붙여 가까운 순으로 준다. `stationCount` 도 자른 수다. 없으면 기본 위치(`app.ocean.coverage`) 기준이다.
  - `current-forecast`(조류예보) 행은 `predcDt`·`currentDirDeg`(16방위 한글을 deg 로)·`currentSpeedMs`, `tide-forecast`(조석예보) 행은 `predcDt`·`tideLevelM` 이다 — **예보라 `predcDt` 는 지금 이후 가장 이른 시각**이다 (2026-09-16).
  - 수집은 **전국 지점**을 저장한다 — 선박이 여러 척이라 수집 때 기준 좌표가 하나가 아니다. 거리를 수집 때 재면 다른 배에게는 틀린 거리다.
  - kiosk 는 본선 좌표를 싣는다. 좌표가 바뀌면 멈춘 뒤 600ms 에 다시 받는다. 커스텀 헤더가 없어 CORS preflight 가 없다.
- `roms` payload 는 해역 대표값이 없다 (2026-09-15) — 타일 현황이다: `tileDeg`·`activeTiles`·`collectedTiles`·`generation`·`refreshedTiles`·`failedTiles`·`baseAt`. 본선 값은 `/current` 로 받는다.

### 5.2 `GET /api/ocean/summary?lat&lon`

```json
{ "headline": "조업 해역 해상 특보 없음", "body": "...",
  "facts": [ "조업 해역(부산앞바다) 해상 특보: 없음",
             "본선 위치 해구 예측(15시 기준): 파고 0.8m · 풍속 5.4m/s · 수온 24.1도" ],
  "generatedAt": "2026-09-18T02:30:00Z", "model": "gpt-4o-mini", "mock": false,
  "lat": 35.0, "lon": 129.1, "shipBased": true }
```

| 파라미터 | 필수 | 뜻 |
|---|---|---|
| `lat` · `lon` | — | 본선 좌표. 주면 그 자리 기준 문장을 받고, **서버의 다음 생성 기준도 그 자리가 된다** |

- **조회는 LLM 을 절대 부르지 않는다.** 키오스크가 60초마다 친다 — 조회에서 부르면 크레딧이 클라이언트 수 × 폴링 주기로 나간다.
- 생성은 `@Scheduled` 한 곳뿐이고 **30분에 1회가 상한**이다 (2026-09-18). 10분마다 갱신 여부만 확인하고, 호출은 상한이 막는다.
- `shipBased: false` 면 기본 위치(`app.ocean.coverage`) 기준이라 **문장 속 지점·거리가 그 배와 무관하다.** 화면이 밝혀야 한다.
- `mock: true` 면 규칙으로 만든 문장이다. **화면이 반드시 밝힌다** — 목이 진짜처럼 읽히면 켜졌는지 구분이 안 된다.
- `facts` 는 요약의 근거 값. 문장만 두면 "그 숫자 어디서 나왔냐"에 답할 수 없다.
- ⚠ **요약은 여전히 하나다.** 선박마다 만들면 LLM 호출이 선박 수만큼 곱해진다. 만들어 둔 문장에서 15km(`SAME_SEA_KM`) 넘게 떨어진 배가 조회하면 **그 배 좌표로 만든 목**을 준다 — 남의 배 기준 문장을 이 배 것처럼 주지 않는다.
- ⚠ 특보는 구역 단위 그대로다. 기상청이 특보구역 경계 좌표를 제공하지 않아(2026-09-14 회신) 본선 좌표로 고를 수 없다. **위치 기반 값은 해구 예측 줄이 진다** — 해구는 좌표 격자라 본선 칸을 정확히 집는다.

### 5.3 좌표 조회 3종 — 공통 규칙

| 파라미터 | 필수 | 뜻 |
|---|---|---|
| `lat` · `lon` | ✅ | 본선 좌표 |

**조회가 곧 관심 표명이다.** 요청 좌표 ±0.1° 에 걸치는 **0.25° ROMS 타일(1~4개)** 에 관심을 찍고, 아직 못 받았거나 옛 예측본이면 수집 스레드로 넘긴다 (2026-09-15, 선박 여러 척 · 백엔드 여러 대).

- 수집 해역 하나를 옮기던 방식은 버렸다 — 배 두 척이면 해역을 서로 빼앗아 둘 다 "해역 밖"이 되고 60초마다 35페이지를 헛불렀다.
- 타일은 좌표만 보고 정해진다(`floor(위도/0.25)` · `floor(경도/0.25)`). 같은 바다의 배는 같은 타일을 나눠 쓴다.
- 매시 새 예측본을 1페이지로 확인하고, 최근 24시간 조회된 옛 예측본 타일만 다시 받는다. 백엔드가 여러 대여도 타일·소스마다 DB 리스로 한 번만 부른다.
- 응답 메시지 이름(`OUTSIDE_AREA`…)은 kiosk 호환으로 유지한다. 뜻은 "본선 주변 타일을 아직 못 받았다"다.

**단 `X-Floaq-Kiosk-Key` 가 맞을 때만 수집을 부른다** (구현 2026-09-15, §1.1). 키가 없거나 틀리면 조회만 한다 — 401 로 막지 않는다. 조회 자체는 공개이고, 막을 것은 수집 유발뿐이다.
`at` 을 넘긴 조회는 키와 무관하게 수집을 부르지 않는다(아래 보관 절).

| 응답 | 뜻 | 화면 |
|---|---|---|
| `200` + 값 | 정상 | |
| `200` + `data: null` + **`message: "OUTSIDE_AREA"`** | 본선 주변 타일을 아직 못 받았다. **오류가 아니다** — 수집을 넘겼고 곧 들어온다(타일 하나 약 24페이지 · 약 5초, 추정) | "받는 중" |
| `200` + `data: null` + **`message: "OUTSIDE_AREA_NOT_MOVED"`** | 못 받았고 **키가 없어 수집을 부르지 않았다.** `OUTSIDE_AREA` 로 주면 화면이 "받는 중"을 거짓으로 띄우고 10초마다 영원히 다시 묻는다 | "수집 해역 밖" — 재조회 안 함 |
| `503 OCEAN_SOURCE_UNAVAILABLE` | **키는 맞는데 ROMS 수집이 꺼져 있거나 인증키가 없다** — 기다려도 안 들어온다 | 마지막 캐시 + 경과 시간 |

> 해역 밖을 503 으로 주면 배가 움직이는 동안 늘 브라우저 콘솔에 오류가 찍히고, 화면이 장애와 구분하지 못한다.

#### 지난 24시간 보관 (결정 2026-09-14)

사고 기록은 통신이 돌아온 뒤에야 동기화될 수 있다. 그때 표류를 다시 계산하려면 **사고 시각의** 유속·바람이 필요하다 — 최신값만 들고 있으면 답이 없다.

| 데이터 | 보관 방식 |
|---|---|
| ROMS (`ocean_roms`) | 지금 이후는 새 예측본으로 교체 · 지금 이전은 24시간 남긴다(같은 격자·시각은 새 값으로 덮음) · 옛 해역의 과거 격자도 남는다 |
| 해구 (`ocean_zone`) | 발효 > 지금은 새 발표본으로 교체 · 발효 ≤ 지금은 24시간 남긴다 |
| 관측 지점 (`ocean_station_obs`) | 수집마다 **전국** 지점을 넣고 24시간 지난 행을 지운다 |

- 삭제는 수집 때 한다. 수집이 멈추면 오래된 행도 안 지워지지만 조회 범위 밖이라 해가 없다.
- 24시간 근거와 Redis 기각 이유는 `OceanRetention.java` 주석.
- **`at` 을 넘긴 조회는 수집을 부르지 않는다** — 지난 사고 지점 타일을 지금 받을 이유가 없다(예측이 과거를 다시 주지도 않는다).

| `at` 조회 응답 | 뜻 |
|---|---|
| `410 OCEAN_OUT_OF_RETENTION` | `at` 이 24시간보다 이르다. 지운 값이다 — 화면은 "그 시각 입력 없음"을 밝힌다 |
| `200` + `data: null` + **`message: "NO_HISTORY"`** | 보관 기간 안이지만 그 시각·좌표 값이 없다 — 그때 그 타일을 받지 않았다 |

#### `GET /api/ocean/current?lat=&lon=&at=`

```json
{ "predcDt": "2026-09-14T04:00:00Z", "lat": 35.07, "lon": 129.08,
  "currentDirDeg": 212.0, "currentSpeedMs": 0.29, "waterTempC": 24.1,
  "distanceKm": 1.2, "neighborSpreadMs": 0.05, "neighborCount": 9 }
```

- `at` — 선택. 사고 시각(ISO). **없으면 지금.** 지난 24시간까지(위 표). 해역을 옮기지 않는다.
- `predcDt` — **예측 시각. 요청 시각(`at` 또는 지금) 이후 가장 이른 것**이다. 요청 시각이 아니다.
- `at` 조회에서 `predcDt` 가 `at` 보다 1시간 넘게 뒤면 값을 주지 않는다(NO_HISTORY) — ROMS 가 1시간 간격이라 그보다 뒤면 그 시각 값이 아니다.
- `currentDirDeg: null` 은 "방위 없음"이다. 0.0(북쪽)이 아니다.
- `neighborSpreadMs` — 한 칸 이내 이웃과의 유속 최대 차이. **표류 범위는 점이 아니라 반경**이고 그 반경이 여기서 나온다. 이웃이 없으면 null — 0 으로 두면 "확실하다"로 읽힌다.
- **값을 주는 기준은 거리가 아니라 받은 타일이다** (수정 2026-09-15). 본선의 최근접 격자와 이웃 한 칸이 걸치는 타일을 **전부** 받았어야 값을 준다 — `current`(at 없음)·`grid`·`series` 공통. 받은 타일 안의 육지 결측 칸은 통과하고 최근접 5km 가 메운다.
  - 이전에는 "최근접 격자 5km 이내"만 봐서, 해역 밖 본선에 **옛 해역 가장자리 칸을 OK 로** 줬다(실측: bbox 서쪽 끝 1.8km 밖 본선에 3.9km 격자). 화면은 엉뚱한 칸을 그리고 "해역 밖" 안내가 뜨지 않았다.
- 최근접 격자가 반경을 넘으면 값을 주지 않는다(OUTSIDE_AREA) — "가장 가까운 것"이 "가까운 것"은 아니다.

#### `GET /api/ocean/grid?lat=&lon=&rings=1&at=`

```json
{ "predcDt": "2026-09-14T04:00:00Z", "latStep": 0.03, "lonStep": 0.03,
  "cells": [ { "lat": 35.07, "lon": 129.08, "currentDirDeg": 212.0,
               "currentSpeedMs": 0.29, "waterTempC": 24.1 } ],
  "times": [ "2026-09-14T04:00:00Z", "2026-09-14T05:00:00Z", "..." ],
  "range": { "speedMin": 0.01, "speedMax": 0.62, "tempMin": 23.8, "tempMax": 26.1 } }
```

| 파라미터 | 뜻 |
|---|---|
| `rings` | 1~12 (1 = 3×3). 육지 칸은 빠져 9개가 안 될 수 있다. 상한 12 = 25×25 칸 — 받은 타일(0.25° ≈ 9×8 칸) 밖은 빈 칸이다 |
| `at` | 선택. 예측 시각(ISO-8601). **없거나 과거면 지금**, 마지막 예측보다 뒤면 마지막 시각으로 물린다 — 시간 슬라이더용 |

| 응답 필드 | 뜻 |
|---|---|
| `predcDt` | 이 칸들이 유효한 예측 시각. `at` 과 다를 수 있다(가장 가까운 이후 시각) |
| `times` | 지금 이후 받을 수 있는 예측 시각 전체, 오름차순. 슬라이더 눈금 |
| `range` | 본선 주변 같은 칸들의 **지금 이후 전 시각** min·max. 화면은 이 범위로 색을 칠한다 — 프레임마다 다시 잡으면 같은 색이 시각마다 다른 값이 된다 |

- 해역 밖 응답(OUTSIDE_AREA)을 받으면 화면은 60초 폴링을 기다리지 않고 **10초 뒤 다시 묻는다.** 서버가 타일 수집을 바로 넘기고, 타일 하나가 약 24페이지 × 0.22초 ≈ 5초다(0.3° 35페이지 약 8초 실측에서 추정).

#### `GET /api/ocean/series?lat=&lon=&hours=48`

```json
{ "lat": 35.07, "lon": 129.08, "distanceKm": 1.2,
  "points": [ { "at": "2026-09-14T04:00:00Z", "currentDirDeg": 212.0,
                "currentSpeedMs": 0.29, "waterTempC": 24.1 } ] }
```

`hours` 6~192. 기본 48 = 조석 반일주기가 네 번 들어와 주기가 눈에 보이는 창.

#### `GET /api/ocean/observations?lat=&lon=&at=&radiusKm=30`

기상청 해양기상종합관측(sea_obs) 지점별 **`at` 이전 가장 최근 관측**. 표류 추정의 바람 입력.

```json
[ { "network": "B", "stn": "22101", "name": "덕적도", "lat": 37.24, "lon": 126.02, "distanceKm": 3.1,
    "observedAt": "2026-09-14T03:00:00Z",
    "waveHeightM": 0.4, "windDirDeg": 40.0, "windSpeedMs": 6.6, "windGustMs": 9.1,
    "waterTempC": 25.4, "airTempC": 24.0, "pressureHpa": 1012.0, "humidityPct": 80.0 } ]
```

| 파라미터 | 뜻 |
|---|---|
| `at` | 선택. 없으면 지금. 지난 24시간까지 — 그보다 이르면 `410 OCEAN_OUT_OF_RETENTION` |
| `radiusKm` | 기본 30, 상한 100. 넘게 주면 100 으로 물린다 — 전국 약 200지점이 한 응답에 실리면 "근처"가 아니다 |

- `distanceKm` 오름차순. **해역이 아니라 요청 좌표 기준**이다 — 사고 지점이 기준.
- `observedAt` 은 `at` 보다 **최대 90분 이르다**. 정시 생산 + 30분 수집 주기라 그만큼 벌어진다. 그보다 오래된 관측은 빠진다.
- 값 `null` 은 결측. 요소마다 나오는 지점이 다르다 — 파고는 파고부이, 바람은 등표. 한 줄로 합치지 않는다.
- 반경 안에 지점이 없으면 빈 배열(200).
- 조회가 수집을 부르지 않는다.

#### `GET /api/ocean/tide?lat=&lon=&hours=48&radiusKm=60` (2026-09-16)

**가장 가까운** KHOA 조석예보 지점의 조위 곡선 + 만조·간조. 항해 탭 "언제 갈까".

```json
{ "stn": "DT_0005", "name": "부산", "lat": 35.09638, "lon": 129.03527, "distanceKm": 8.2,
  "points": [ { "at": "2026-09-16T00:00:00Z", "tideLevelM": 1.05 } ],
  "extremes": [ { "at": "2026-09-16T03:00:00Z", "levelM": 1.52, "kind": "HIGH" } ] }
```

| 파라미터 | 뜻 |
|---|---|
| `hours` | 6~72. 기본 48 — 반일주기가 네 번이라 만조·간조가 각 네 번 들어온다. 예보를 하루치씩 받으므로 그 이상은 없다 |
| `radiusKm` | 기본 **60**, 상한 100. 지점 소스(30km)보다 넓다 — 조석예보 지점이 전국 166곳(연안)뿐이라 30km 면 먼바다에서 늘 빈다 |

- `kind` 는 `HIGH`(만조) · `LOW`(간조). **양 끝 점은 극값으로 보지 않는다** — 창이 거기서 잘린 것이지 꼭대기라는 뜻이 아니다.
- 극값 시각은 **최대 ±30분 어긋난다.** 수집이 1시간 간격(`min=60`)이고 보간하지 않는다 — 원본에 없는 분 단위를 만들지 않는다. 분 단위가 필요하면 KHOA 고조·저조 예보표 API 를 따로 붙여야 한다(미결).
- 조위는 만(灣)마다 다르다. 화면은 `name`·`distanceKm` 를 반드시 함께 보여준다 — 본선 항구 값이 아니다.
- 반경 안에 지점이 없으면 **200 + `data: null`, `message: "NO_STATION"`**. 오류가 아니다 — 먼바다에서는 늘 그렇다.
- `points[].tideLevelM` `null` 은 결측. 0 으로 두면 간조로 읽힌다.
- 조회가 수집을 부르지 않는다 — 조석예보는 전국을 하루 한 번 받아 둔다(ROMS 타일과 다르다). kiosk 키도 필요 없다.

### 5.4 `GET /api/ocean/zones?level=large&at=` — 기상청 해구별 예측

해양포털 "해구별 해양기상정보" 와 같은 원자료(KIM 지역파랑모델 RWW3). 수집기가 발표본(00·12UTC)을 미리 받아 둔다 — 조회가 기상청을 부르지 않는다.

| 파라미터 | 뜻 |
|---|---|
| `level` | `large` 전국 대해구(0.5°, 1,330칸) · `small` **전국 소해구**(1/6°, 대해구 1,330개 = 11,970칸, 2026-09-17부터). 기본 `large`. 그 외 값은 400 |
| `at` | 선택. 발효시각(ISO). **그 시각을 덮는 3시간 구간의 시작**을 고른다 — 없으면 지금. 지난 24시간 보관분까지에서 고르고, 범위 밖은 양끝으로 물린다. 24시간보다 이르면 `410 OCEAN_OUT_OF_RETENTION` |

```json
{ "level": "small", "issuedAt": "2026-09-14T00:00:00Z", "validAt": "2026-09-14T12:00:00Z", "stepDeg": 0.1667,
  "cells": [ { "lzone": 92, "szone": 9, "latMin": 35.0, "latMax": 35.167, "lonMin": 129.333, "lonMax": 129.5,
               "waveHeightM": 0.7, "wavePeriodMaxS": 4.7, "waveDirDeg": 41.8,
               "windSpeedMs": 7.9, "windDirDeg": 41.8,
               "visibilityM": 12360.0, "rainMm": 0.8, "waterTempC": 26.4, "swellLevel": 2 } ],
  "times": [ "2026-09-14T00:00:00Z", "...", "2026-09-17T03:00:00Z" ],
  "range": { "waveMin": 0.0, "waveMax": 2.0, "windMin": 0.5, "windMax": 12.1, "tempMin": 22.2, "tempMax": 28.2 },
  "nextIssuanceAt": null }
```

| 필드 | 뜻 |
|---|---|
| `times` | **최신** 발표본의 발효시각 26개(+0~75시간, 3시간 간격). **발표 시각부터라 과거가 섞인다** — 화면은 지금을 덮는 구간을 "지금"으로 둔다. 24시간 보관분은 싣지 않는다 |
| `range` | 최신 발표본 전 발효시각 min·max. 슬라이더를 넘겨도 같은 색이 같은 값 |
| `issuedAt` | 셀들 중 첫 칸의 발표 시각. 보관분 프레임이면 옛 발표본일 수 있다 — 한 발효시각에는 **그 시각을 가진 가장 새 발표본**의 칸만 준다 |
| `nextIssuanceAt` | 받는 중인 **다음** 발표본. `null` 이면 받는 중이 아니다. 🔴 **`cells` 는 이때도 반쪽이 아니다** — 완결된 직전 발표본이다. 전국 소해구는 약 34분에 걸쳐 받으므로(아래) 화면이 "옛 발표본을 보고 있다"를 알 수 있어야 한다. 모르면 사람이 갱신 안 된 화면을 최신으로 읽는다 |
| 값 `null` | 결측(원자료 -999). 육지에 걸린 칸. **0 이 아니다** |
| `visibilityM`·`rainMm`·`waterTempC`·`swellLevel` | 소해구만. 대해구는 항상 null. 2026-07-01 00UTC 발표본부터 |
| `windDirDeg` | 불어오는 쪽(기상 관례). 화면 화살표는 180° 돌려 불어가는 쪽으로 그린다 |
| `waveDirDeg` | ⚠ 관례가 명세에 없다 — 화살표로 그리지 않는다 |
| `swellLevel` | 너울 위험 1 관심 · 2 주의 · 3 경계 · 4 위험 |

| 응답 | 뜻 |
|---|---|
| `503 OCEAN_SOURCE_UNAVAILABLE` | 그 층의 발표본이 하나도 없다 — 수집 전이거나 막혔다. 소해구는 대해구가 먼저 있어야 고를 수 있다 |

- 수집: 최신 발표본을 확인하고 **이미 받았으면 호출하지 않는다.** 생산 전이면 직전 발표본을 유지한다(12UTC 발표본이 11:19 UTC 에도 없었다, 2026-09-14 실측).
- 오류도 HTTP 200 + 한글 한 줄로 온다 — 수집기가 `#START7777` 표식으로 가른다. 반쪽 발표본(중간 시각 실패)은 저장하지 않는다.

**전국 소해구 수집 (2026-09-17)**

| | 값 |
|---|---|
| 한 발표본 | **884회** = 34묶음 × 26 발효시각. `Lzone` 은 한 번에 40개가 상한이다 |
| 하루 | 1,768회 (발표 00·12UTC) — API허브 한도 20,000건의 **9%**, 용량 152MB 로 5GB 의 **3%** |
| 받는 방식 | **매분 1묶음(26회 ≈ 39초)** 씩. 전량을 한 틱에 받으면 약 54분 동안 다른 소스 수집이 멈춘다 |
| 완료까지 | 약 **34분**. 그동안 조회에는 **직전 발표본**이 그대로 나가고 `nextIssuanceAt` 이 채워진다 |

- `Lzone=0`(전체)은 **소해구에서 거부된다** — `"대해구번호를 입력하세요."`(2026-09-17 실호출). 대해구처럼 1회로 전국을 받는 길이 없어 40개씩 나눠 묻는다.
- 묶음을 더 잘게 쪼개면 **더 비싸다**: 1개 0.75초 · 10개 1.23초 · 40개 3.69초(실측). 호출당 고정 오버헤드가 0.7초쯤이라 40개가 가장 싸다.
- 받는 도중 실패한 묶음은 **그 묶음만** 다시 받는다. 받아 둔 것은 `ocean_zone_pending` 에 남는다 — 일시 오류 하나에 34분이 날아가지 않게.

---

## 6. WebSocket `/ws` — 관제 웹 실시간

REST 가 **진실**이고 WS 는 **변경 알림**이다. WS 는 재생(replay)이 없다 — 끊긴 동안의 이벤트는 사라진다.

> **(재)연결하면 반드시 REST 로 다시 읽는다** (`/api/accidents?status=REPORT` → 상세 → `buoy-positions?after=`). 이 규칙이 없으면 재연결 직후 화면이 끊기기 전 상태에 멈춘다.

### 6.1 연결 · 인증

```
1. new WebSocket("wss://floaq.example.com/ws")
2. 5초 안에 → { "type": "AUTH", "token": "eyJ..." }
3. ← { "type": "AUTH_OK", "user": { "userId": 3, "role": "A" } }
   실패·시간 초과 → close 4401
```

- **토큰을 쿼리스트링에 싣지 않는다.** nginx 액세스 로그가 `$request` 를 남긴다(계획.md §5④) — URL 의 토큰이 로그에 그대로 쌓인다.
- 브라우저 WebSocket 은 `Authorization` 헤더를 붙일 수 없어 첫 메시지로 보낸다.
- 토큰 만료 시 서버가 close `4401` — 클라이언트는 재로그인 후 재연결.
- `A` 만 접속한다. `SA` 은 관제 화면이 없다 → close `4403`.

### 6.2 메시지 형식

```json
{ "type": "BUOY_POS", "at": "2026-09-14T03:31:10Z", "data": { } }
```

`at` = 서버 발행 시각. 측정 시각은 `data` 안에 따로 있다 — **지도에는 측정 시각을 쓴다.**

### 6.3 서버 → 클라이언트

**`A` 은 신고된 사고의 이벤트만 받는다.** 사고가 처음 `REPORT` 가 되는 순간 `ACCIDENT_REPORTED` 가 가고, 그 뒤부터 그 사고의 이벤트가 흐른다. `DETECT`·`WAIT` 단계의 사고는 보이지 않는다(WEB-03).

| type | `data` | 발생 |
|---|---|---|
| `ACCIDENT_REPORTED` | 사고 목록 항목(§3.4) | 사고가 처음 `REPORT` 로 반영됨. 이 전이에는 `ACCIDENT_STATE` 를 따로 보내지 않는다 |
| `ACCIDENT_STATE` | `{ accidentId, status, prevStatus, reason, rescuedAt, changedAt }` | 신고된 사고의 그 뒤 상태 변경 |
| `BUOY_POS` | `{ accidentId, lat, lon, isPressed, measuredAt }` | 부표 위치 수신 (배치당 최신 1건) |
| `BUOY_LOST` | `{ accidentId, lastLat, lastLon, lastMeasuredAt, since }` | 부표 통신 두절 판정 |
| `BUOY_BACK` | `{ accidentId, lat, lon, measuredAt, lostSec }` | 두절 후 재수신 — 추정 범위 표시 해제 |
| `SHIP_POS` | `{ shipId, accidentId, lat, lon, speedKn, headingDeg, measuredAt }` | 사고 구간 선박 위치 `제안` |
| `REPORT_STATUS` | `/reports` 항목 | 채널별 신고 기록 변경 |
| `FRAME` | `{ accidentId, seq, capturedAt, phase }` | 새 프레임 수신 (청크당 마지막 1장) |
| `COMMAND_STATE` | `/commands` 항목 | 명령 상태 변경 |
| `DEVICE_HEALTH` | `{ shipId, ...deviceStatus, receivedAt }` | 장비 이상 탐지 결과 변경 `제안` |
| `PONG` | `{ }` | `PING` 응답 |

- ⚠ **`BUOY_LOST` 판정 주체 미정** — 서버 스케줄러(backend-plan 4단계)냐, Pi 의 `comm-losses` 수신이냐. 판정은 한 곳에서만 한다 — 둘이 하면 서로 다른 시각에 두 번 경보가 뜬다(§9).
- ⚠ 단일 인스턴스 전제. 세션 Set 순회로 브로드캐스트한다 — 다중화 시 Redis Pub/Sub 릴레이 필요.

### 6.4 클라이언트 → 서버

| type | 내용 |
|---|---|
| `AUTH` | §6.1 |
| `PING` | 하트비트 — 브라우저 JS 는 WS ping 프레임에 접근할 수 없어 앱 메시지로 보낸다. 주기 `제안` 미정 |

**그 외는 없다.** 계획.md §1.3 의 `REPORT_CANCEL` · `REPORT_NOW` · `MANUAL_ALERT` · `INCIDENT_RESOLVE` 는 폐기한다:

- 신고 취소·즉시 신고·수동 신고는 **선내 kiosk → Pi MQTT** 로만 한다. 관제 웹에는 권한이 없다(상세기획 §5.5).
- 관제 종료는 **REST `close-requests`** 다. 명령 발행 결과(`commandId`)를 동기 응답으로 받아야 연타·중복을 막을 수 있다.

> 두 부표 신호를 구분한다: `PING`/`PONG` 은 "브라우저 연결이 살아 있나", `BUOY_LOST` 는 "부표가 통신 범위를 벗어났나"다. 섞으면 브라우저가 끊긴 것을 사고 신호로 읽는다(계획.md §1.4).

---

## 7. 에러 코드 (-107)

### 7.1 전체 — `ErrorCode.java` 기준

| code | HTTP | 메시지 | 쓰는 곳 |
|---|---|---|---|
| `COMMON_INVALID_INPUT` | 400 | 잘못된 입력입니다. | 전체 — 검증·형식 실패 |
| `COMMON_UNAUTHORIZED` | 401 | 인증이 필요합니다. | `/api/**` 토큰 없음 |
| `COMMON_FORBIDDEN` | 403 | 권한이 없습니다. | 역할 불일치 |
| `COMMON_NOT_FOUND` | 404 | 리소스를 찾을 수 없습니다. | 명령 (전용 코드 추가 전) |
| `COMMON_INTERNAL_ERROR` | 500 | 서버 오류가 발생했습니다. | 마지막 그물. 내부 메시지 노출 안 함 |
| `AUTH_INVALID_CREDENTIALS` | 401 | 아이디 또는 비밀번호가 올바르지 않습니다. | login |
| `AUTH_INVALID_TOKEN` | 401 | 유효하지 않은 토큰입니다. | 서명 불일치 · 만료 |
| `AUTH_ACCOUNT_PENDING` | 403 | 승인 대기 중인 계정입니다. | login |
| `AUTH_ACCOUNT_REJECTED` | 403 | 반려된 가입 신청입니다. | login — **구현** (V5) |
| `AUTH_ACCOUNT_DELETED` | 403 | 사용할 수 없는 계정입니다. | login · me. 토큰 사용 중 비활성화에도 쓰려면 요청마다 DB 조회가 필요하다(§9) |
| `AUTH_ALREADY_REGISTERED` | 409 | 이미 신청된 계정입니다. | signup |
| `USER_NOT_FOUND` | 404 | 존재하지 않는 계정입니다. | admin users approve · reject — **구현** |
| `PI_UNAUTHORIZED` | 401 | Pi API 인증에 실패했습니다. | `/api/pi/**` — **구현** |
| `PI_STALE_STATE` | 409 | 이미 더 나중 상태가 반영돼 있습니다. | **사용 안 함** — §4.2 `stale` 계수로 대체 (§7.3) |
| `PI_SHIP_UNKNOWN` | 404 | 등록되지 않은 선박입니다. | pi 수신 |
| `SHIP_NOT_FOUND` | 404 | 존재하지 않는 선박입니다. | ships |
| `SHIP_ALREADY_REGISTERED` | 409 | 이미 등록된 선박입니다. | POST ships |
| `ACCIDENT_NOT_FOUND` | 404 | 존재하지 않는 사고입니다. | accidents · 볼 권한 없음 · pi FK |
| `ALREADY_REPORTED` | 409 | 이미 신고가 발신됐습니다. | **kiosk ↔ Pi 전용** (REST 에서 안 씀) |
| `ALREADY_RESOLVED` | 409 | 이미 종결된 사고입니다. | close-requests · pi ack `error_code` |
| `ALREADY_CANCELLED` | 409 | 이미 취소된 사고입니다. | close-requests · pi ack `error_code` |
| `NO_ACTIVE_INCIDENT` | 404 | 진행 중인 사고가 없습니다. | **kiosk ↔ Pi 전용** |
| `INVALID_STATE` | 409 | 지금 상태에서는 할 수 없는 동작입니다. | 명령 중복 · 계정 상태 전이 · pi ack |
| `ACCIDENT_ALREADY_ACTIVE` | 409 | 이미 진행 중인 사고가 있습니다. | pi accidents — **Pi 재시도 대상** |
| `OCEAN_SOURCE_UNAVAILABLE` | 503 | 해양 데이터를 가져올 수 없습니다. | ocean 좌표 조회 — **구현** |
| `OCEAN_SOURCE_UNKNOWN` | 404 | 등록되지 않은 해양 데이터 소스입니다. | 소스 단건 조회 추가 시 |
| `OCEAN_OUT_OF_RETENTION` | 410 | 보관 기간(24시간)이 지난 시각입니다. | ocean `at` 조회 — **구현**. 404 가 아니라 410 — 값이 있었는데 지웠다 |
| `MEDIA_NOT_FOUND` | 404 | 영상을 찾을 수 없습니다. | frames · video |
| `MEDIA_TOO_LARGE` | 413 | 업로드 용량이 제한을 초과했습니다. | pi frames |
| `STORAGE_UNAVAILABLE` | 503 | 저장소에 접근할 수 없습니다. | video (R2) |

⚠ **코드 문자열을 바꾸면 화면이 깨진다.** `ALREADY_REPORTED` · `ALREADY_RESOLVED` · `ALREADY_CANCELLED` · `NO_ACTIVE_INCIDENT` · `INVALID_STATE` 는 kiosk `REJECT_TEXT` 키와 같다.

### 7.2 엔드포인트별

| 엔드포인트 | 나올 수 있는 code |
|---|---|
| POST `/api/auth/login` | `COMMON_INVALID_INPUT` · `AUTH_INVALID_CREDENTIALS` · `AUTH_ACCOUNT_PENDING` · `AUTH_ACCOUNT_REJECTED` · `AUTH_ACCOUNT_DELETED` |
| POST `/api/auth/signup` | `COMMON_INVALID_INPUT` · `AUTH_ALREADY_REGISTERED` |
| `/api/**` 인증 필요 전체 | `COMMON_UNAUTHORIZED` · `AUTH_INVALID_TOKEN` · `AUTH_ACCOUNT_DELETED` · `COMMON_FORBIDDEN` |
| `/api/admin/users/{id}/*` | `USER_NOT_FOUND` · `INVALID_STATE` · `COMMON_FORBIDDEN` |
| `/api/ships/**` | `COMMON_INVALID_INPUT` · `SHIP_NOT_FOUND` · `SHIP_ALREADY_REGISTERED` |
| GET `/api/accidents` | `COMMON_INVALID_INPUT` (잘못된 `status`·날짜) |
| GET `/api/accidents/{id}/**` | `ACCIDENT_NOT_FOUND` |
| POST `close-requests` · `media-stop-requests` | `ACCIDENT_NOT_FOUND` · `ALREADY_RESOLVED` · `ALREADY_CANCELLED` · `INVALID_STATE` |
| GET `frames/{seq}` · `video` | `ACCIDENT_NOT_FOUND` · `MEDIA_NOT_FOUND` · `STORAGE_UNAVAILABLE` |
| `/api/pi/**` 전체 | `PI_UNAUTHORIZED` · `COMMON_INVALID_INPUT` · `PI_UNSUPPORTED_VERSION`(제안) |
| POST `/api/pi/accidents` | + `PI_SHIP_UNKNOWN` · `ACCIDENT_ALREADY_ACTIVE` |
| POST `/api/pi/accident-states` · `reports` · `launches` · `buoys` · `imu` | + `ACCIDENT_NOT_FOUND` |
| POST `/api/pi/archives` | + `ACCIDENT_NOT_FOUND` · `MEDIA_TOO_LARGE` |
| POST `/api/pi/commands/ack` | + `COMMON_NOT_FOUND` |
| GET `/api/ocean/current` · `grid` · `series` | `COMMON_INVALID_INPUT` · `OCEAN_SOURCE_UNAVAILABLE` · `OCEAN_OUT_OF_RETENTION`(`current` 의 `at`) |
| GET `/api/ocean/observations` | `COMMON_INVALID_INPUT` · `OCEAN_OUT_OF_RETENTION` |
| GET `/api/ocean/zones` | `COMMON_INVALID_INPUT` · `OCEAN_SOURCE_UNAVAILABLE` · `OCEAN_OUT_OF_RETENTION` |

### 7.3 변경 제안 — 아직 `ErrorCode.java` 에 반영 안 함

| 제안 | 이유 |
|---|---|
| ~~`USER_NOT_FOUND` 404 추가~~ | **반영(2026-09-15).** 계정 관리에서 `COMMON_NOT_FOUND` 로는 무엇이 없는지 화면이 문구를 못 고른다 |
| `COMMAND_NOT_FOUND` 404 추가 | pi ack 의 잘못된 id — Pi 로그에서 원인이 바로 보이게 |
| `PI_UNSUPPORTED_VERSION` 400 추가 | 봉투 `v` 불일치. 일반 400 과 갈라야 Pi 가 "행 폐기"가 아니라 "전송 중단"으로 대응한다(§4.1) |
| `ErrorResponse` 에 `failed` 필드 추가 (pi 배치 거절 시만) | 배치 중 어느 원소가 거절됐는지 없으면 Pi 가 나머지를 버릴지 다시 보낼지 모른다(§4.1). 웹 응답에서는 항상 생략 |
| `PI_STALE_STATE` 제거 | §4.2 로 쓰이지 않는다. 남겨 두면 누군가 배치 중 한 건에 409 를 던져 두절 복귀 큐를 멈춘다 |

---

## 8. 문서 간 불일치와 이 문서의 선택

| # | 항목 | 어긋난 곳 | 이 문서 | 상태 |
|---|---|---|---|---|
| 1 | 사고 상태 값 | DB·Pi `DETECT/WAIT/REPORT/CANCEL/CLOSE` · 계획.md §1.3 `PENDING/REPORTED/CANCELLED/RESOLVED` · 웹 `types.ts` `live/done/cancel/closed` | **DB 값 그대로.** 웹이 decode | 결정 2026-09-14 |
| 2 | JSON 표기 | `docs/edge/mqtt.md` snake_case · `/api/ocean` camelCase | web camelCase · pi snake_case | 결정 2026-09-14 |
| 3 | 종결 코드 이름 | backend-plan `ACCIDENT_ALREADY_CLOSED` · 코드 `ALREADY_RESOLVED` | 코드 | 코드 기준 |
| 4 | 진행 중 사고 코드 | `docs/edge/mqtt.md` §5.9 `ACCIDENT_IN_PROGRESS` · 코드 `ACCIDENT_ALREADY_ACTIVE` | 코드 (REST) | ⚠ Pi MQTT 응답은 mqtt.md 이름이고 **kiosk `REJECT_TEXT` 에 둘 다 없다** |
| 5 | 종결 기록 컬럼 | 계획.md §9.20 `resolved_at` + `resolved_by` · Pi `rescued_at` + `closed_at` · V1 `closed_at` 만 | `rescued_at` + `closed_at` 수신, 종결 주체는 `accident_state.reason` 으로 | ⚠ **구조됐는지(`rescued_at`)와 누가 닫았는지(`reason`) 둘 다 서버 컬럼이 없다** — §9.20 이 "지워지면 안 된다"고 한 기록. 🔴 pi 초안에 반영(`db/migration/V9__edge.sql`). ⚠ `reason` 8종에 관제 웹 종료·1시간 자동 종결 값이 없다 — 후보 `WEB_CLOSE`·`AUTO_CLOSE` (§9 3 #10) |
| 6 | SA 사고 조회 | 상세기획 §5.5·W-02 "SA 전체 조회" · 계획.md §9.13 "SA 관제 화면 없음" | 계획.md (단일 진실 원천) | ⚠ 팀 확인 필요 |
| 7 | 선박 승인 | WEB-08·W-05 "승인·거절" · `ship` 에 상태 컬럼 없음 | **승인·거절을 둔다** — V8 이 `ship.status` 추가, approve·reject **구현** | ✅ 해소 2026-09-16. ⚠ 등록 경로(kiosk 신청 vs SA 직접)는 아직 정리 안 됨 |
| 8 | 신고 기록 모양 | Pi `pi_report` 채널별 1행 누적 갱신 · 서버 `report` append-only, 채널·횟수 컬럼 없음 | 채널별 upsert | 🔴 pi 초안 반영 (`db/migration/V9__edge.sql`) |
| 9 | Pi 행 PK 타입 | `database/pi.sql` 전부 `INTEGER` 자동 채번 · V1 ⑤ uuid | **서버가 uuid 채번, 멱등은 자연키.** Pi 는 PK 를 안 보낸다 | ✅ 해소 2026-09-17 (§4.2) |
| 10 | pi 상태 수신 | backend-plan `PUT /api/pi/accidents/{id}/state` 단건 · 같은 문서 "전부 배열" | `POST /api/pi/accident-states` 배열 | 이 문서 |
| 11 | 사고 전 150장 업로드 | `docs/edge/mqtt.md` §5.13 "Pi 가 R2 업로드" · 계획.md §9.6 "Pi 는 R2 키 없음, tar → EC2" | 계획.md | IoT 팀에 전달 |
| 12 | 로그인 식별자 | W-01 "이메일" · V1 `login_id` · 상세기획 §10.2 미정 | `loginId` = 기관 이메일 (소문자 저장) | 결정 2026-09-15 |
| 13 | 사고 유형·발생 경로 | Pi `accident_type`·`trigger_source` 있음 · 서버 `accident` 없음 | 필드 설계, 추가 전 null | 🔴 pi 초안 반영 (`db/migration/V9__edge.sql`) |
| 14 | 투하 결과 | Pi `result`·`fail_reason`·`target_lat/lon` 있음 · 서버 `launch` 없음 | 필드 설계 | 🔴 pi 초안 반영 (`db/migration/V9__edge.sql`) |
| 15 | WS 클라→서버 메시지 | 계획.md §1.3 4종 | 폐기 (§6.4) | 이 문서 |
| 16 | 수동 신고 유형 수 | 상세기획 §3.3·S-07 **5개** · `docs/edge/mqtt.md` §4·Pi `enums.py` **10개** | **8종** — SAFETY 2종(`HAZARD`·`ABANDON_SHIP`)만 제외 | ✅ 결정 2026-09-17 (`docs/edge/mqtt.md` §7 #2 가 담당을 웹으로 지정한 항목). 🔴 Pi 전달 필요 |
| 17 | pi 필드명 | `database/pi.sql` 부표 `lat/lon` · V1 `buoy_lat/buoy_lon` | `buoy` 는 V1 이름 유지 + DTO 매핑 · **`ship_position` 은 Pi 이름(`lat/lon`)** | ⚠ 절반. `buoy` 는 V1 이 배포돼 못 바꾼다 — 매핑 실수 자리 1곳 남음 |
| 18 | 평시 선박 위치 | 계획.md §9.13 "평시 항적은 받지 않는다" · `database/pi.sql` `pi_ship_position` 상시 기록 | **평시도 받는다.** 평시 5초 · 사고 중 1초 · 보관 24시간 | 결정 2026-09-17 — 계획.md §9.13 개정 |
| 19 | GPS 발행자 | `docs/edge/mqtt.md` §5.7 `kiosk/sensor/gps`(키오스크) · 계획.md §9.1 토폴로지 "GPS → Pi" | **Pi** — `pi/sensor/gps` | 해소. `docs/edge/mqtt.md` 가 낡음([[260915_kiosk-mqtt-contract]] · `mqtt-연동-웹_v2` §2) |
| 21 | `launch.fail_reason` | 서버 3종 · `database/pi.sql` **4종**(`NO_SOLUTION` 추가) | Pi 4종 | 반영 `V9__edge.sql` ③ (2026-09-17) |
| 22 | `report.first_sent_at` | 서버 `created_at = first_sent_at` NOT NULL 전제 · Pi **NULL 허용** | 미정 | 🔴 아직 못 쏜 채널의 행이 먼저 생긴다 — 서버 PK `(report_id, created_at)` 가 못 들어간다 (`V9__edge.sql` ④) |
| 23 | Pi 에만 있는 컬럼 | `launch.detection_id` · `accident_state.caused_by` · `report.trigger_kind` | 미정 | 받을지 결정. `trigger_kind` 는 Pi 가 이름 충돌을 피해 개명한 것(§8 #16 해소) |
| 20 | 프레임 업로드 | api.md §4.3 `POST /api/pi/archives` tar 묶음 · `ref/mqtt-연동-웹_v2` §11 `POST /api/accidents/{id}/files` **장당 1요청** | 미정 | 🔴 **v2 문서가 어디에도 반영 안 됨**(2026-09-17 발견). 계획.md §9.6 은 "장당 요청이면 오버헤드가 프레임보다 크다"로 tar 를 골랐고 IoT 는 "묶으면 부분 실패가 지저분"으로 반대 — IoT 합의 필요 |

---

## 9. 미결 — 우선순위 순

1. ~~kiosk 의 `/api/ocean` 인증~~ — **결정(2026-09-15): 조회 공개 · 해역 이동만 `X-Floaq-Kiosk-Key` · nginx `limit_req`**(§1.1 · §5.3). **구현 완료(2026-09-15)** — `KioskKey` · `OUTSIDE_AREA_NOT_MOVED` · kiosk `VITE_KIOSK_KEY` 헤더 · nginx 허용 헤더. 남은 것 — EC2 키 배포·nginx 반영 · `limit_req` 한도(7).
2. ~~V8 마이그레이션 범위~~ — **해소 2026-09-17: `db/migration/V9__edge.sql` 로 옮겼다.** 조건이었던 Pi 스키마 대조(`database/pi.sql` 14테이블)가 끝났다. 초안 `docs/edge_draft.sql` 은 삭제. 번호 이력은 V3→V5→V6→V7→V8→**V9** 로 다섯 번 밀렸다 — 초안에 번호를 미리 붙이면 먼저 들어간 사람이 가져가기 때문이다([[260916_migration-renumber]]). ⚠ **이제 체크섬이 걸린다.** 고치면 이미 적용한 DB 가 기동을 거부하므로 바꿀 일이 생기면 새 파일을 만든다. ⚠ 팀원은 앱을 한 번 재기동하면 V9 가 적용된다(V8 다음 번호라 out-of-order 아님). NOT NULL 로 조일 컬럼은 Pi 수신이 실제로 돌고 값이 항상 오는 것이 확인된 뒤 V10 에서 조인다. 제안 테이블 3개(`comm_loss`·`drift_estimate`·`accident_file`)는 여전히 목록만 — `ship_position` 만 DDL 을 썼다.
3. 🔴 **IoT 팀 계약** — 합의 목록. `docs/edge/mqtt.md`(2026-09-09) 와 대조한 상태다.

   **`database/pi.sql` 수령 (2026-09-17) 후 갱신.** 12개 중 6개 해소 · 4개 잔존 · 2개 신규.

   | # | 항목 | 서버 전제 | Pi 쪽 (`database/pi.sql`) | 상태 |
   |---|---|---|---|---|
   | 1 | Pi 스키마 원본 공유 | 컬럼명 대조 | **수령** — 14테이블, SQLite STRICT, 실행 가능한 정본 | ✅ 해소 |
   | 2 | 부표 좌표 컬럼명 | `buoy_lat/buoy_lon` | `lat/lon` | ⚠ 남음. `buoy` 는 V1 배포분이라 DTO 에서 매핑 (§8 #17) |
   | 3 | Pi 행 PK | uuid v7, 재전송 때 같은 값 | **`INTEGER` 자동 채번** (SQLite STRICT rowid 별칭) | ✅ 해소 — 자연키 UNIQUE 로 전환 (§4.2) |
   | 4 | 시각 | Unix 초 (§1.3) | Unix 초 | ✅ |
   | 5 | 전송 순서 | `updated_at` 오름차순 (§4.1) | `ix_*_sync ON (updated_at, pk)` | ✅ |
   | 6 | 상태 변경 재전송 | 같은 행이 `updated_at` 로 다시 옴 | **`(updated_at, pk)` 복합 커서.** 초 단위 시각에서 `>` 는 유실 `>=` 는 중복이라 PK 를 tiebreak 로 | ✅ **해소** — Pi 가 스스로 고쳤다 |
   | 7 | 재시도 표 + `failed` | §4.1 | 스키마 범위 밖 | 합의 필요 |
   | 8 | 사고 전 150장 경로 | Pi tar → EC2, Pi 는 R2 키 없음 | `pi_accident_file.object_key` = "R2 업로드 확정 후 채운다" | ✅ 해소 — Pi 는 R2 키를 갖지 않는다 |
   | 9 | `SAFETY` 사고 미생성 | **폐기** — SAFETY 를 1차 범위에서 뺐다(2026-09-17). 8종 전부 사고를 연다 | `report_type` CHECK 에서 `SAFETY`, `AccidentType` 에서 `HAZARD`·`ABANDON_SHIP` 제거 필요 | ✅ 서버 결정 · 🔴 Pi 전달 |
   | 10 | 종결 사유 | 관제 웹 종료·1시간 자동 종결 | `reason` CHECK 8종에 **여전히 없음** | 🔴 |
   | 11 | 부표 위치 주기 | 1초 행 (V1 주석) | **1초 확정.** `UNIQUE (accident_id, created_at)` 로 초 단위 dedup | ✅ 해소 |
   | 12 | 요청 인증 | **등록 키 + 선박 키 2단**(결정 2026-09-17 · §1.1) | 스키마 범위 밖 | 🔴 Pi 전달 필요 — 등록 응답의 `ship_key` 를 영속 저장해야 한다 |
   | **13** | **하행 해양 데이터** | **없음** | `pi_ocean_data` + `sync.direction = 'PULL'`. 표류 계산을 오프라인에서 하려면 필요 | 🔴 신규 — `GET /api/pi/ocean` |
   | **14** | **영상 청크** | 종결 시 EC2 가 mp4 한 번 (계획.md §9.6, 청크 이어붙이기 **명시적 기각**) | `pi_video` 30초 청크 (IOT-19) | 🔴 신규 |

   덤으로 해소된 것 — `pi_report.report_type` → **`trigger_kind` 개명**(§8 #16 이름 충돌) · IMU `roll/pitch/yaw` **각도(deg)** 주석 명시 · 부표 두절 판정 주체 **Pi**(`threshold_sec` 로 판정 당시 기준 박제, 아래 4 해소).

   3-1. **Pi 요청 HMAC 서명** — IoT 팀 제안, **채택 방향**(2026-09-15). IoT 문서 수령 후 서명 대상·헤더·시각 창 확정. HTTPS 위에서 얻는 것은 **키가 전송되지 않음 · 본문 변조 방지 · 시각 창 밖 재전송 차단**이고, 창 안 중복은 이미 PK 멱등(§4.2)이 막는다. 채택하면 같이 정할 것:
   - 🔴 **시계 오차가 동기화를 멈추지 않게.** 서명 시각이 틀리면 401 → §4.1 표상 전송 중단 → 두절 복귀 큐가 멈춘다. Pi 는 GPS 시각 기준(계획.md §9.5)이지만 실내 시연은 GPS 미수신. → 시각 오류는 401 과 다른 코드(예 `PI_CLOCK_SKEW`) + 응답에 서버 시각 → Pi 가 오프셋 보정 후 재시도. 허용 창은 Pi 시계 오차 실측 후
   - **`frames` 본문 해시** — tar 7.5~30MB 를 검증 전에 버퍼링하지 않게 `meta` 에 tar sha256 을 넣고 meta 만 서명, 수신 후 대조
   - 서명에 `ship_id` 를 넣고 **선박별 키**로 가면 6 도 같이 풀린다
   - 기각: mTLS — 인증서 발급·갱신이 팀 규모·기간 대비 과함. kiosk 해역 이동 키에는 HMAC 이득 없음(키가 번들 안이라 누구나 같은 키로 서명 가능)
3-2. 🔴 **평시 위치 — 두절이 길 때 두 가지가 깨진다** (결정 2026-09-17에 딸림).
   - **2시간 초과**: 1Mb 배치 상한에 안 들어간다(약 80분치 추정). Pi 가 나눠 보내는 규칙 필요
   - **24시간 초과**: 밀린 행이 들어간 직후 보관 스윕에 지워진다. 조용한 손실 — Pi 가 안 보내거나 서버가 `stale` 로 세거나
   - **사고 구간 행이 같이 지워진다**: `drop_chunks` 는 조각째라 `accident_id` 를 안 본다. 사고 기록의 일부인데 24시간 뒤 사라진다.
     후보 — 사고 확정 시 그 구간을 별도 테이블로 복사 · 보관 스윕을 `DELETE ... WHERE accident_id IS NULL` 로(조각 이점 포기) · 사고용/평시용 테이블 분리

3-3. 🔴 **Pi 가 구현하기 전에 정해야 하는 것** (§4.3 작성하며 나온 것들).
   - ~~`SAFETY` 가 사고를 여는가~~ — **해소 2026-09-17: 1차 범위에서 뺐다.** 남은 것은 Pi 에 전달해 `AccidentType` 을 8종으로 줄이는 것 + `ABANDON_SHIP` 등급 오류(`SAFETY`→`DISTRESS`) 정정
   - `reason` 에 `WEB_CLOSE`·`AUTO_CLOSE` 추가 — 서버·Pi CHECK 양쪽
   - `report.created_at` 을 Pi `created_at` 으로 (지금은 `first_sent_at` 매핑인데 null 이 온다)
   - `ship_position.accident_id` 를 누가 채우나 — 서버가 수신 시각으로 붙이는 쪽 제안
   - `drift_estimate` → `comm_loss` 연결키 — 서버가 `comm_loss_detected_at` 으로 제안
   - `GET /api/pi/ocean` 의 `source` 매핑(Pi 기관 3종 ↔ 서버 수집기 12종)과 폴링 주기

4. ~~부표 두절 판정 주체~~ — **해소 2026-09-17: Pi.** `pi_comm_loss` 가 `threshold_sec`(판정 당시 기준)까지 박제한다. 서버는 받아 적기만 — Pi 권위 원칙과 같다. 서버 스케줄러를 두지 않는다.
5. **SA 사고 조회 권한** (§8 #6).
6. ~~pi 키가 선박 공통~~ — **해소 2026-09-17: 등록 키 / 선박 키로 나눴다**(§1.1 · §4.3). 등록 응답으로 선박 전용 키를 주고, 그 뒤 모든 Pi 요청이 그 키다 — **키가 곧 선박 증명**이라 페이로드의 `ship_id` 를 검증할 수 있다. 서버는 해시로만 보관한다.
   - 🔴 **남은 것: 선박 키 재발급 절차.** 한 번만 내려가므로 Pi 가 잃으면 다시 받을 길이 없다. 후보 — SA 가 관제 웹에서 재발급(기존 키 폐기) · 등록 키로 재신청. **누가 무엇을 확인하고 내주는지**가 핵심이다.
7. **JWT 만료 시간** · WS `PING` 주기 · presigned URL 만료 · 페이지 상한 · **명령 만료(§3.5 `제안` 10분)** · `/api/ocean` `limit_req` 한도(§1.1 — kiosk 실제 요청 패턴 측정 후) — 근거 있는 값이 정해지면 넣는다.
8. ~~가입 신청 항목~~ — **결정(2026-09-15): 이름 · 기관 이메일 · 비밀번호만.** 소속·계급·연락처·증빙은 받지 않는다 — 해경 쪽은 신고를 받았는지만 알 수 있고 담당자·처리 기관은 알 수 없다. 사고의 담당 배정도 같은 이유로 없앴다.
9. **1시간 자동 종결 주체** — Pi 권위 원칙이면 Pi. 서버는 받아 적기만.
10. **오종결 재개** — §4.2 순위 가드가 `CLOSE → REPORT` 를 막는다. 재개를 허용하면 가드와 `uq_accident_active` 둘 다 손봐야 하고, A 조회 범위(§3.4) 전제도 같이 본다(계획.md 미결).
11. **선박 중복 판정 기준** — MMSI · 등록번호 UNIQUE 제약 없음.
12. ~~계정 상태 3개의 한계~~ — **결정(2026-09-15): `REJECTED` 추가**(`V5__users_rejected.sql`). 반려는 `REJECTED`, 비활성화는 `DELETED`. 남은 것: 비활성화를 되돌릴 상태(`INACTIVE`)는 비활성화 기능을 만들 때 정한다. 번호는 V5 다 — 2026-09-16 팀원과 교환. 해양이 V6·V7 을 쓰므로 pi 스키마는 V8 로 간다(§9 2). 순서 위반 위험이 없어졌다.
13. **비활성화된 계정의 살아 있는 토큰** — 만료까지 허용(무상태) vs 요청마다 `users` 조회(§7.1 `AUTH_ACCOUNT_DELETED`). 계정이 몇 개 안 되니 조회 비용은 문제가 아니고, "해임된 계정이 몇 시간 더 관제를 본다"를 받아들일지의 문제다.

> ~~Swagger 운영 노출~~ — **이미 닫혀 있다.** `application-prod.yml` 이 `springdoc.api-docs.enabled: false` · `swagger-ui.enabled: false`. 계획.md·backend-plan 의 미결 목록이 이를 반영하지 못했다.

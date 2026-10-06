# Pi ↔ EC2

정본은 **[`api.json`](api.json)** 이다 — 서버 코드에서 뽑은 OpenAPI 3.1 이라 문서와
구현이 갈라질 여지가 없다. 이 문서는 그 위에서 **Pi 가 무엇을 어떻게 하는지**만 적는다.

> 🔴 **`api.md` 는 폐기다.** 경로(`/api/edge/**`)·헤더 이름·필수 필드가 전부 다르다.
> 그걸 보고 짜면 401 이 난다.

---

## 1. 인증 — 두 단계, 헤더 두 개

```
① POST /api/pi/ships          X-Ship-Register-Key   공용 등록 키. ship_id 없음
②③ 그 밖의 전부               X-Ship-Secret-Key     등록으로 받은 선박 키
```

| | 어디서 | 만료 |
|---|---|---|
| **등록 키** | 웹 팀이 만들어 전달. `.env` 의 `FLOAQ_SHIP_REGISTER_KEY` | 없음 |
| **선박 키** | 등록 응답. `pi_credential.ship_key` | 없음 |

🔴 **등록 키는 등록이 끝나면 지운다.** 남겨 두면 공용 키의 유출 표면만 늘고, 그 키를
회전할 때 이미 등록된 배를 전부 건드려야 한다. `EdgeClient.use_ship_key()` 가
`X-Ship-Register-Key` 를 헤더에서 뺀다.

🔴 **키를 로그에 찍지 않는다.** 선박 키는 서버가 해시로만 보관해 **다시 안 준다.**

---

## 2. 선박 등록 — `ship_id` 를 받는 유일한 경로

```
키오스크 ──POST /api/ship──▶ Pi        name · registration_no · mmsi · has_buoy
                              │ 202. 파일에 적고 즉시 반환
                              ▼
        [EC2] POST /api/pi/ships       X-Ship-Register-Key
               └─ 200 { ship_id, ship_key, status: "WAIT" }
                              │ 🔴 받는 즉시 DB. 로그는 그다음
                              ▼
        [EC2] GET /api/pi/ships/{id}   X-Ship-Secret-Key. 60초 간격
               └─ status 가 ACTIVE 가 될 때까지
```

`floaq/enroll.py` 가 별도 데몬 스레드로 돈다.

### 왜 `POST /api/ship` 이 EC2 를 안 부르나

인터넷이 없으면 그 요청이 타임아웃까지 멈추고, 키오스크 화면이 "저장 중" 에서
20초를 선다. 받아서 파일에 쓰고 202 를 돌려준 뒤, 등록 루프가 되는 대로 올린다.

### 🔴 `ship_id` 를 받기 전에는 `pi_ship` 행을 만들지 않는다

임시 uuid 로 먼저 만들고 나중에 서버 값으로 바꾸면 둘이 동시에 깨진다.

- `pi_accident.ship_id` 가 FK 다. 그 사이 생긴 사고가 전부 고아가 된다
- MQTT 토픽이 전부 `ship/{ship_id}/…` 다. 키오스크·Jetson 구독이 통째로 어긋난다

그래서 대기 값은 DB 가 아니라 **파일**(`floaq.db.pending-ship.json`)에 둔다.
`pi_ship` 은 PK 가 NOT NULL 이라 애초에 담을 수 없고, 담으려고 컬럼을 NULL 허용으로
풀면 위 FK 가 같이 풀린다.

### 🔴 `pi_credential` 은 `sync` 대상이 아니다

`pi_ship` 의 컬럼으로 넣으면 "행을 그대로 보낸다"는 전제 때문에 키가 매 요청 본문에
실려 서버로 되돌아간다. 서버가 이미 아는 값이라 얻는 것도 없다.
`assert_schema_matches()` 가 `sync` 에 이름이 들어가 있으면 **기동을 거부한다.**

계약(`floaq/contracts/`)에도 모델로 만들지 않는다 — 거기 들어가면 Pi 가 공개로
서빙하는 `/contract.json` 에 스키마가 나간다.

### 멱등

`registration_no` 가 자연키다. 응답이 유실돼 다시 보내도 **같은 `ship_id`** 가 온다.
어선 인터넷에서 응답 유실은 정상 경로라 이게 없으면 재시도마다 배가 늘어난다.

⚠ **시연 범위에 키 재발급은 없다.** 잃으면 다시 등록해야 한다.

---

## 3. 전송 펌프 — `floaq/sync.py`

```
for 테이블 in FK 순서:
    (synced_at, synced_pk) 이후 행을 LIMIT 만큼 읽는다
    api.json 이 요구하는 컬럼만 골라 봉투에 담아 POST
    2xx 를 받은 뒤에만 커서를 전진시킨다
```

### 순서가 곧 FK 순서다

```
ship-positions   (사고와 무관. 가볍고 자주 생겨 앞에)
  → accidents
  → accident-states · launches
  → buoys · imus · comm-losses · drift-estimates
  → reports        (마지막. 사고 행이 있어야 붙는다)
```

사고 행 없이 자식을 먼저 올리면 서버에서 FK 위반으로 배치가 통째로 롤백된다.

### 봉투

```jsonc
{ "request_id": "01a0…",   // uuid v7. 서버 로그 상관용
  "v": 1,                  // 스키마 버전
  "ts": 1789622400,        // Pi 발행 시각 (Unix 초)
  "data": [ {…}, {…} ] }   // 항상 배열. 단건도 길이 1
```

`/api/pi/ships` 와 `/api/pi/archives` 만 봉투를 안 쓴다.

### 🔴 2xx 전에는 커서를 안 옮긴다

전송 시점이 아니라 **저장 확정 시점**이다(`database/pi.sql` `sync`). 먼저 옮기면 서버가
못 받은 행이 영영 재전송 대상에서 빠지고, 그 손실은 아무 로그도 남기지 않는다.

### 응답 해석 — 전부 "재시도"로 뭉개면 안 된다

| 응답 | 동작 | 왜 |
|---|---|---|
| 2xx | **커서 전진** | |
| 400 `COMMON_INVALID_INPUT` · 413 | **커서 전진** + 로그 | 형식 오류는 몇 번 보내도 같다. 붙들면 그 배치가 큐를 영원히 막고 뒤의 사고 기록까지 멈춘다 |
| 400 `EDGE_UNSUPPORTED_VERSION` | 전송 중단. 행은 안 버림 | 서버·Pi 버전 불일치. 사람이 풀어야 한다 |
| 403 `EDGE_SHIP_NOT_APPROVED` | 백오프 후 재시도 | **오류가 아니라 상태다.** 사람이 승인하면 풀린다 |
| 404 `ACCIDENT_NOT_FOUND` | 그 테이블만 건너뜀 | 순서 문제. 다음 회차에 사고가 먼저 올라간다 |
| 404 `EDGE_SHIP_UNKNOWN` | 전송 중단 | `ship_id` 설정 문제. 재시도해도 안 풀린다 |
| 409 `ACCIDENT_ALREADY_ACTIVE` | 백오프 후 재시도 | 앞 사고의 종결이 아직 안 올라왔다 |
| 401 | 전송 중단 | 키 문제. 좁은 상향 대역과 로그만 태운다 |
| 5xx · 타임아웃 · 연결 실패 | 백오프 후 재시도 | 서버 사정. **같은 PK 로 보내므로 안전하다** |

"전송 중단" 은 큐를 비우는 것이 아니다 — 쌓아 두고 원인이 풀리면 이어 보낸다.

### 승인 전에는 아무것도 안 보낸다

`WAIT` 인 선박의 데이터는 서버가 거절한다. 보내봐야 403 만 쌓이므로 펌프가 큐를 쥐고
`ACTIVE` 를 기다린다. **데이터를 잃지 않는다** — 승인이 늦어도 사고 기록은 남는다.

### 보내지 않는 것

| | 왜 |
|---|---|
| `updated_at` | 서버가 자기 값으로 채운다 |
| INTEGER PK (`report_id`·`buoy_log_id`·`position_id`…) | Pi 안에서만 뜻이 있다. 서버는 uuid 를 채번하고 **중복은 자연키가 막는다** |
| `pi_accident_state.reason` · `caused_by` | `api.json` 이 안 받는다 (자연키 3개만) |

예외는 `accident_id` 와 `ship_id` 둘 — 둘 다 TEXT uuid 다. `accident_id` 는 Pi 가
인터넷 없이 발급해야 해서 uuid v7 이다.

### 타입

SQLite 에 boolean 이 없어 `is_pressed`·`is_current` 가 0/1 로 들어 있다. `api.json` 은
boolean 을 요구하므로 전송 직전에 바꾼다 — 그대로 보내면 400 이다.
⚠ `None` 에 변환을 걸면 `False` 가 된다. 그건 "값 없음"과 다른 뜻이라 건너뛴다.

---

## 4. 타르볼 — `POST /api/pi/archives`

```
multipart/form-data
  accident_id      01a0…
  archive          (tar) — manifest.json + 이미지 + 영상 청크
  archive_sha256   64자리 16진
  created_at       1789622400
```

**멱등은 타르볼이 아니라 항목별이다.**

```
이미지  (accident_id, file_type, sequence_no, camera)   pi_accident_file UNIQUE 와 같다
영상    video_name                                       pi_video PK 와 같다
```

응답의 `files[].duplicated` 가 장마다 온다. 같은 타르볼을 두 번 올려도
`stored: 0 · duplicated: N` 이고 행이 안 는다. 그래서 `chunk_seq` 가 없다 —
타르볼 자체는 상태가 없다.

🔴 **`object_key` 는 서버가 돌려주고 Pi 가 받아 적는다.** `pi_accident_file.object_key`
가 NULL 인 것이 곧 업로드 대기열이다. **Pi 는 R2 자격증명을 갖지 않는다** — 어선에
실린 물리 장비라 분해·도난을 전제한다.

---

## 5. 해양 데이터 — 인증 없음

`/api/ocean/**` 여덟 개는 EC2 에서 `security: -` 다. Pi 가 그냥 부르면 된다.
별도 `GET /api/pi/ocean` 은 필요 없었다.

| | |
|---|---|
| `current` | 최근접 ROMS 격자 + 이웃 산포 |
| `grid` · `series` · `observations` · `tide` · `zones` | |
| `summary` · `sources` | |

`IRomsPointView` 가 `currentSpeedMs`·`currentDirDeg`·`waterTempC` 를 **이미 정규화된
m/s·도** 로 준다. Pi 가 다시 변환하면 두 벌이 되고, 이건 틀려도 예외가 안 나서
표류 반경이 조용히 100배가 되는 종류다.

`neighborSpreadMs`(이웃 유속 산포)가 있어 `pi_drift_estimate.radius_m` 의 불확실도
근거로 쓸 수 있다.

**키오스크는 Pi 를 통해 받는다** — [architecture.md §4.5](architecture.md).
`x-floaq-kiosk-key` 는 Pi 가 서버 쪽에서 붙인다.

---

## 6. 하행 — Pi 가 폴링한다

엣지에 인바운드를 열지 않는다.

```
GET  /api/pi/commands?after=&limit=      미처리 명령
POST /api/pi/commands/ack                { request_id, state, reason, acked_at }
```

명령 이름이 키오스크 명령과 같은 어휘다 — `cancel` · `close` · `report_manual` 등.
`pi_command_log` 가 중복을 막으므로 같은 `request_id` 가 두 번 와도 한 번만 실행된다.

⚠ 두절 중 쌓인 `close` 가 이미 선내에서 닫힌 사고에 늦게 닿는 것은 **정상 경로**다.
Pi 는 `REJECTED` 로 답한다.

---

## 7. 아직 없는 것

| | |
|---|---|
| `device-status` | `pi/device/status` MQTT 는 있는데 EC2 경로가 없다. 원래 미정이었다 |
| 타르볼 업로드 구현 | 클라이언트는 있고 `object_key IS NULL` 대기열 소비가 없다 |
| HMAC 서명 | 채택 방향. 서명 대상·시각 창 미확정 |

### 🔴 지금 401 이다

```
POST /api/pi/ships
  X-Ship-Register-Key: 0c5e…
→ 401 {"code":"COMMON_UNAUTHORIZED","message":"인증이 필요합니다."}
```

`EDGE_UNAUTHORIZED` 가 아니라 **`COMMON_UNAUTHORIZED`** 인 게 단서다 — 전용 필터가
아니라 공통 인증 필터가 잡고 있다. 웹 팀에 확인할 것 셋:

1. `/api/pi/**` 가 실제 배포됐는지 (`api.json` 이 설계일 수도)
2. 헤더 이름이 `X-Ship-Register-Key` 맞는지
3. 우리가 받은 키가 그 값 맞는지 — 이름이 `FLOAQ_EDGE_KEY` 에서 바뀌었다

키가 없으면 등록 루프를 안 띄우고 경고만 남긴다. **선내 동작은 그대로 돈다** —
사고 판정·투하·조난 신고는 인터넷과 무관하다.

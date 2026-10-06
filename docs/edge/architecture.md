# IoT 구성과 전송 경로

누가 무엇을 들고 있고, 무엇이 어디로 흐르는지 한 장에 모은다.
세부는 각 문서가 맡는다 — [mqtt.md](mqtt.md) · [lora.md](lora.md) ·
[distress.md](distress.md) · [mqtt-연동-웹.md](mqtt-연동-웹.md)

---

## 1. 노드

선내에 보드가 **둘**, 부표에 **하나**다. 키오스크는 노드가 아니라 화면이다.

```
                          선박
  ┌───────────────────────────────────────────────────────┐
  │                                                       │
  │   [Jetson]                     [Raspberry Pi 5]       │
  │   AI 추론                       오케스트레이터          │
  │   카메라 L/R                    mosquitto  1883 / 9001 │
  │   조준 해 계산                   FastAPI    8000        │
  │        │                        SQLite                 │
  │        └────── MQTT ──────────────┤                    │
  │                                   │                    │
  │                            ┌──────┴──────┐             │
  │                            │             │             │
  │                     [키오스크]      발사기 · GPS · IMU   │
  │                     브라우저         LoRa · VHF          │
  │                     ws://…:9001                        │
  └───────────────────────────────────────────────────────┘
                                   ╎ LoRa 1Hz
                              [부표] MCU + GPS + LoRa
```

| 노드 | 하드웨어 | 역할 | 상태 |
|---|---|---|---|
| **Pi** | Raspberry Pi 5 | 오케스트레이터. 상태머신·저장·발사·신고·브로커·웹서버 | 구현 중 |
| **Jetson** | Jetson | 카메라 추론, 익수자 탐지, 조준 해 계산 | `iot/jetson/` 껍데기만 |
| **부표** | MCU + GPS + LoRa | 투하 후 1Hz 위치 송신 | 미착수 |
| 키오스크 | 태블릿 브라우저 | 화면·조작 | 개발용 `tools/kiosk.html` |

### 🔴 Pi 가 서버다

키오스크는 별도 서버를 두지 않는다. **Pi 가 페이지를 내려주고 Pi 의 브로커에 붙는다.**

```
브라우저 → http://<pi>:8000/kiosk/kiosk.html   페이지를 Pi 가 내려줌
브라우저 → ws://<pi>:9001                      Pi 의 mosquitto (MQTT over WebSocket)

페이지를 Pi 가 내려주므로 브라우저의 `location.hostname` 이 곧 Pi 주소다.
키오스크가 별도 컴퓨터여도 **설정할 것이 없다** — 주소만 치면 된다.
```

⚠ 브라우저는 raw TCP 소켓을 못 연다. 1883 이 아니라 **9001** 이어야 한다.
그래서 `mosquitto.conf` 에 리스너가 둘이다.

⚠ 키오스크가 죽어도 사고 처리는 계속된다. Pi 가 자기 시계로 판단해 신고한다.
화면은 관측자이지 판단 주체가 아니다.

---

## 2. 전송 수단이 네 가지인 이유

한 가지로 통일하지 않는다. 구간마다 제약이 다르다.

| 구간 | 수단 | 왜 |
|---|---|---|
| Jetson → Pi (이벤트) | **MQTT** 1883 | 작고 잦다. retained 로 상태가 남는다 |
| Jetson → Pi (프레임) | **HTTP PUT** 8000 | 크고 드물다. 125장을 MQTT 로 밀면 1Hz 가 밀린다 |
| Jetson → 화면 (라이브) | **MJPEG** 8080 | 지금 무엇을 보는지. 기록이 아니다 |
| Pi ↔ 키오스크 | **MQTT over WS** 9001 | 브라우저 제약 |
| 부표 → Pi | **LoRa** 920MHz | 수 km 해상. 인터넷·와이파이 없음 |
| Pi → 해상 | **VHF DSC / AIS** | GMDSS 규격. 해경·주변 선박이 받는 유일한 수단 |
| Pi → 키오스크 (이미지) | **HTTP** 8000 | 브라우저가 `<img>` 로 바로 먹음 |
| Pi → EC2 | **HTTPS REST** `/api/pi/**` | 인터넷. MQTT 를 쓰지 않는다 |
| 키오스크 → 해양 데이터 | **Pi 중계** 8000 | 키오스크는 EC2 를 직접 부르지 않는다 (§4.5) |

### 전송별 한계

| | 대역 | 지연 | 끊김 |
|---|---|---|---|
| MQTT (선내 랜) | 충분 | ms | 거의 없음 |
| LoRa | **19바이트/초** | 51ms | 자주 |
| VHF DSC | 심볼 스트림 | 초 | 거리 의존 |
| 인터넷 | 좁음 | 초 | **자주 끊김** |

LoRa 와 인터넷이 병목이다. 설계가 그 둘을 중심으로 갈린다.

---

## 3. 사고 한 건의 흐름

```
 ① Jetson  익수자 탐지
           └─MQTT─▶ jetson/detection  (조준 해 포함)

 ② Pi      사고 생성 · 각도 검증 · 발사
           ├─MQTT─▶ pi/accident/state   DETECT   retained
           ├─────── 발사기 구동
           ├─MQTT─▶ pi/launch/result             retained
           └─MQTT─▶ pi/accident/state   WAIT     retained + report_due_at

 ③ 키오스크 30초 카운트다운 표시
           취소하면 ─MQTT─▶ kiosk/command/cancel

 ④ Pi      30초 만료 → 자동 신고
           ├─MQTT─▶ pi/accident/state   REPORT   retained
           ├─UDP──▶ DSC 조난 경보 + AIS-MOB + AIS-SART
           └─MQTT─▶ pi/report/status             retained

 ⑤ 해안국  조난 확인응답 (수동 조작)
           └─▶ Pi 가 DSC 만 중지. AIS 는 계속

 ⑥ 부표    LoRa 1Hz 위치 송신
           └─MQTT─▶ pi/buoy/position  (QoS 0)

 ⑦ 구조    ─MQTT─▶ kiosk/command/rescue
           └─▶ 전 채널 중지 · CLOSE · retained 정리
```

⚠ ④ 는 키오스크가 살아있든 아니든 일어난다. Pi 가 혼자 판단한다.

---

## 4. 이미지·영상 경로

**MQTT 로 실물을 나르지 않는다.** 크기와 성격이 다른 둘로 나뉜다.

```
 [Jetson] ──HTTP PUT──▶ [Pi 로컬 저장]
                              │
              ┌───────────────┼────────────────┐
              │               │                │
        MQTT base64      HTTP 8000       HTTPS multipart
        스냅샷 1장        프레임 125장     인터넷 될 때만
              │               │                │
              ▼               ▼                ▼
          [키오스크]      [키오스크]         [EC2] ──▶ [R2]
```

| 대상 | 수단 | 근거 |
|---|---|---|
| 탐지 스냅샷 1장 | MQTT `jetson/snapshot` base64, retained | 사고당 1회 300KB. retained 라 접속만 해도 뜬다 |
| 사고 전후 프레임 125장 | Pi 로컬 HTTP | `<img src>` 로 바로. 브라우저 캐싱·지연 로딩 공짜 |
| 위 전부 | EC2 `POST /api/pi/archives` tar → R2 | 인터넷 될 때만 |
| 라이브 화면 | Jetson `:8080` MJPEG | 기록이 아니다. 지금 카메라가 보는 것 |

**프레임 창 `확정` 2026-09-17 — 앞 15초 · 뒤 10초.** 5fps 로 75 + 50 = **125장**,
200KB 로 잡으면 사고당 25MB 다. 이전 값은 앞 30초(150장)였다.
앞 구간은 Jetson 이 링 버퍼로 상시 들고 있다가 탐지 순간에 쏟아낸다 —
**사고가 난 뒤에는 그 전 장면을 다시 만들 수 없다.**

### Jetson → Pi 업로드 규약

```
PUT /api/detections/{detection_id}/files/{file_type}/{sequence_no}
Content-Type: image/jpeg
X-Camera: L

  (raw JPEG bytes)

201 { "file_id": 1, "accident_id": "01a0…", "url": "/files/01a0…/BEFORE/0001.jpg" }
```

🔴 **Jetson 은 `accident_id` 를 모른다.** 탐지 시점엔 사고가 아직 없고 Pi 가
`jetson/detection` 을 받고 나서 만들기 때문이다. 그래서 자기가 만든 `detection_id`
로 올리고 Pi 가 `pi_launch` 를 통해 풀어준다.

⚠ 업로드가 탐지 발행보다 먼저 도착하면 404 다. 재시도하면 붙는다.

⚠ PUT 인 이유는 멱등해서다. 응답을 못 받고 재전송해도 같은 자리에 덮어쓰고
`pi_accident_file` 의 UNIQUE 가 새 행을 막는다. POST 면 프레임이 두 배가 된다.

⚠ multipart 가 아니라 raw 본문이다. 메타데이터는 경로와 헤더로 충분하다.
(EC2 구간은 multipart 다 — 거긴 필드가 많고 Spring 이 받는다.)

### 키오스크 조회

```
GET /api/accidents/{accident_id}/files        목록. sequence_no 순
GET /files/{accident_id}/{file_type}/0001.jpg  이미지 한 장
```

`FileResponse` 가 `Range`·`ETag`·`Last-Modified` 를 처리한다. 125장을 다시 받지 않는다.

### 🔴 키오스크는 R2 를 보지 않는다

선내 화면이 인터넷에 의존하게 된다. 사고 상황에서 인터넷이 가장 먼저 끊긴다.
`pi_accident_file` 에 `file_path`(Pi 로컬)와 `object_key`(R2)가 따로 있는 이유다.

```
키오스크 → Pi 로컬 HTTP    항상 된다
웹/앱   → R2              육상
```

### 업로드는 대기열이 따로 없다

```sql
pi_accident_file(file_path TEXT NOT NULL, object_key TEXT, ...)
```

`WHERE object_key IS NULL` 이 그대로 미업로드 목록이다. 인터넷이 없으면 행이 쌓이고
복구되면 비운다. 백오프·재시도 횟수·데드레터를 만들지 않는다.

**인터넷이 없으면 아무것도 하지 않는다** `확정`. 연결 확인도 따로 없다 — 업로드 요청이
실패하면 그게 곧 "인터넷 없음"이다.

### EC2 업로드 규약

```
POST /api/pi/archives
X-Ship-Secret-Key: <선박 키>
Content-Type: multipart/form-data

  accident_id      01a0…
  archive          (tar 바이너리) — manifest.json + 이미지 + 영상 청크
  archive_sha256   64자리 16진. 전송 무결성 대조
  created_at       1789456675

200 { "received": 126, "stored": 126, "duplicated": 0, "failed": 0,
      "files":  [ { "file_type": "BEFORE", "sequence_no": 1, "camera": "L",
                    "object_key": "accidents/…/BEFORE/0001.jpg", "etag": "…",
                    "duplicated": false } ],
      "videos": [ … ] }
```

**한 사고를 타르볼 하나로 묶는다** (`api.json` 2026-09-17). 장당 요청이면 125번이고
오버헤드가 프레임보다 커진다. 서버가 풀어서 R2 에 직접 PUT 한다.

🔴 **멱등은 타르볼이 아니라 항목별이다.** `IPiFileStored.duplicated` 가 장마다 온다.

```
이미지  (accident_id, file_type, sequence_no, camera)   pi_accident_file UNIQUE 와 같다
영상    video_name                                       pi_video PK 와 같다
```

같은 타르볼을 두 번 올려도 `stored: 0 · duplicated: N` 이고 행이 안 는다. 그래서
`chunk_seq` 같은 게 없다 — 타르볼 자체는 상태가 없다.

🔴 **`object_key` 는 서버가 돌려주고 Pi 가 받아 적는다.** `pi_accident_file.object_key`
가 NULL 인 것이 곧 업로드 대기열이다(아래).

### 왜 R2 에 직접 올리지 않는가

presigned URL 방식도 가능하나 이쪽을 택했다.

| | presigned | multipart → EC2 |
|---|---|---|
| Pi 자격증명 | 임시 URL 보관 | **아예 없음** |
| 왕복 | 3회 (발급·PUT·보고) | **1회** |
| 실패 처리 | 단계마다 다름 | 성공/실패 하나 |
| 키 결정·DB 기록 | 나뉨 | EC2 한 곳 |

125장 × 200KB = 25MB. EC2 를 거치는 대역 낭비가 이 규모에서는 의미가 없다.
presigned 는 훨씬 큰 규모에서만 이긴다.

Pi 는 어선에 실린 물리 장비다. 분해·도난을 전제하면 **자격증명을 두지 않는 쪽**이 맞다.

### 4.5 해양 데이터 — 키오스크는 EC2 를 직접 부르지 않는다 `확정` 2026-09-17

```
키오스크 ──GET http://<pi>:8000/api/ocean/current?lat=&lon=──▶ [Pi]
                                                                │ 중계 + 캐시
                                                                ▼
                                                   [EC2] GET /api/ocean/current
```

얻는 것이 셋이다.

| | |
|---|---|
| 키오스크 설정이 줄어든다 | Pi 주소만 알면 된다. EC2 주소·키를 안 들고 있는다 |
| 키가 번들에 안 들어간다 | `x-floaq-kiosk-key` 를 Pi 가 서버 쪽에서 붙인다 |
| 끊겨도 마지막 값이 있다 | 캐시에서 주되 **`fresh: false`** 를 같이 싣는다 |

🔴 **인터넷이 끊겼을 때 빈 200 을 주지 않는다.** 화면이 "조류 0.0 m/s" 로 그리고 그건
"잔잔하다"로 읽힌다. 그 값으로 표류 반경을 그리면 수색 범위가 거짓이 된다.
캐시도 없으면 **503** 이다 — "값 없음"과 "수집 안 됨"을 가른다.

`/api/ocean/**` 는 EC2 에서 인증이 없다(`api.json`). 해역 이동으로 새 타일 수집을
부르는 것만 kiosk 키를 요구한다.

---

## 4.6 Jetson SDK

AI 팀은 배관을 몰라야 한다. **함수 둘이면 끝난다** — [JetSon/README.md](../../iot/jetson/README.md).

```python
from floaq_jetson import Floaq

fq = Floaq(pi="192.168.0.10")     # ship_id 는 Pi /health 에서
fq.start()

fq.frame(jpeg, camera="L")        # ① 매 프레임
fq.detected(lat=…, lon=…, distance_m=…, confidence=…,
            yaw=…, pitch=…, target_lat=…, target_lon=…)   # ② 탐지되면
```

`detected()` 한 번이 `detection_id` 발급 · pydantic 검증 · MQTT 발행 · 링 버퍼
쏟아내기 · AFTER 모드 전환을 전부 한다. `AFTER` 는 뒤 10초가 지나거나 Pi 가 사고를
`CLOSE`/`CANCEL` 하면 자동으로 꺼진다.

⚠ 기존 `jetson_client.py`(468줄 시연 스크립트)와 Jetson 쪽 Flask 카메라 서버는
**버렸다.** SDK 가 대신한다.

### 카메라 라이브 — Jetson `:8080`

```
http://<jetson>:8080/                       좌우 카메라 확인 페이지
http://<jetson>:8080/stream.mjpg?camera=L   <img src> 에 그대로
http://<jetson>:8080/snapshot.jpg?camera=R  최근 한 장
```

**기록이 아니라 보기용이다.** 기록은 Pi 로 올라가는 쪽이다. 최신 한 장만 들고 있어서
보는 쪽이 느려도 프레임이 쌓이지 않는다 — 쌓으면 그 클라이언트가 Jetson 메모리를
채우고 화면은 점점 과거를 보여준다.

---

## 4.7 선박 등록 — 키오스크가 Pi 를 통해 신청한다

```
키오스크 ──POST http://<pi>:8000/api/ship──▶ [Pi]     name·registration_no·mmsi
                                              │ 202. 파일에 적고 즉시 반환
                                              ▼
                       [EC2] POST /api/pi/ships    X-Ship-Register-Key (공용 등록 키)
                              └─ 200 { ship_id, ship_key, status: "WAIT" }
                                              │
                       [EC2] GET /api/pi/ships/{id}  X-Ship-Secret-Key. 60초 간격
                              └─ status 가 ACTIVE 가 될 때까지
```

🔴 **`ship_key` 는 등록 응답에 한 번만 온다.** 서버가 해시로만 보관해 다시 못 준다.
받는 즉시 `pi_credential` 에 쓴다 — `pi_ship` INSERT 와 **같은 트랜잭션**이다.

🔴 **`ship_id` 를 받기 전에는 `pi_ship` 행을 만들지 않는다.** 임시 uuid 로 먼저 만들고
나중에 바꾸면 `pi_accident.ship_id` FK 가 고아가 되고 MQTT 토픽(`ship/{ship_id}/…`)이
통째로 어긋난다. 대기 값은 DB 가 아니라 파일에 둔다.

🔴 **`pi_credential` 은 `sync` 대상이 아니다.** 컬럼으로 `pi_ship` 에 넣으면 "행을 그대로
보낸다"는 전제 때문에 키가 매 요청 본문에 실려 서버로 되돌아간다. `assert_schema_matches`
가 `sync` 에 이름이 들어가면 기동을 거부한다.

**승인 전에는 아무것도 안 올린다.** `WAIT` 인 선박의 데이터는 서버가 거절하므로,
전송 펌프가 큐를 쥐고 `ACTIVE` 를 기다린다. 승인은 관제 웹에서 사람이 누른다
(`POST /api/admin/ships/{shipId}/approve`).

---

## 5. 구현 현황

### MQTT — 사고 경로는 끝, 텔레메트리는 비어 있음

| 토픽 | 방향 | 상태 |
|---|---|---|
| `jetson/detection` | 수신 | ✅ |
| `kiosk/command/*` (5종) | 수신 | ✅ |
| `pi/accident/state` | 발행 | ✅ retained |
| `pi/launch/result` | 발행 | ✅ retained |
| `pi/command/response` | 발행 | ✅ |
| `pi/online` | 발행 | ✅ LWT |
| `pi/report/status` | 발행 | ✅ retained. `pi_report` 도 같이 쓴다 |
| `pi/sensor/gps` | 발행 | ✅ 1Hz. 배 NMEA `$xxRMC` |
| `pi/sensor/imu` | 발행 | ❌ IMU 어댑터 없음 |
| `pi/buoy/position` | 발행 | ❌ LoRa 어댑터 없음 |
| `pi/buoy/drift` | 발행 | ❌ 표류 추정 없음 |
| `pi/device/status` | 발행 | ❌ 장비 감시 없음 |
| `jetson/snapshot`·`jetson/status` | 수신 | ❌ 구독 미연결 |

⚠ `clear_retained` 는 `pi/buoy/drift`·`pi/report/status` 를 지우지만 발행한 적이 없다.
무해하나 짝이 안 맞는다.

⚠ `DEVICE_STATUS_SEC` · `DRIFT_PUBLISH_SEC` 는 아직 돌지 않는다. GPS 는 돈다 —
  발행 1Hz, DB 기록은 평시 5초 · 사고 중 1초로 **주기가 다르다**.

### HTTP (FastAPI 8000)

| 경로 | 용도 | 상태 |
|---|---|---|
| `GET /health` | 배선 확인 | ✅ |
| `GET /kiosk/…` | 키오스크 페이지 | ✅ |
| `GET /contract.json` | MQTT 계약. 요청마다 파이썬에서 생성 | ✅ |
| `GET /openapi.json` · `/docs` | 스펙. 웹 팀에 그대로 준다 | ✅ |
| `PUT /api/detections/{id}/files/…` | Jetson 프레임 업로드 | ✅ |
| `GET /api/accidents/{id}/files` | 파일 목록 | ✅ |
| `GET /files/{id}/{type}/{n}.jpg` | 이미지 한 장 | ✅ |
| `POST /api/ship` · `GET /api/ship` | 선박 등록 신청·상태 (§4.7) | ✅ |
| `GET /api/ocean/{path}` | 해양 데이터 중계 (§4.5) | ✅ |
| Pi → EC2 행 전송 | `sync` 커서 → 배치 POST | ✅ `floaq/sync.py` |
| Pi → EC2 타르볼 | `object_key IS NULL` 대기열 소비 | ❌ |

⚠ **HTTP 가 죽어도 사고 처리는 돈다.** `main.py` 가 오케스트레이터 뒤에 띄우고
기동 실패해도 죽이지 않는다. 화면이 없어도 Pi 는 혼자 신고한다.

🔴 **블로킹 호출을 `async def` 안에서 그대로 부르지 않는다.** SQLite 와 파일 I/O 는
전부 블로킹이라 이벤트 루프에서 직접 부르면 모든 요청이 같이 선다.
`run_in_threadpool` 로 넘긴다 — 첫 구현에서 실제로 밟았다.

### 규격 계층

| | 상태 |
|---|---|
| ITU-R M.493 (DSC) | ✅ 심볼 프레임까지 — [distress.md](distress.md) |
| ITU-R M.1371 (AIS) | ✅ 메시지 + 링크 계층 |
| LoRa 프레임 19바이트 | ✅ 코덱 + 수신 어댑터 — [lora.md](lora.md) |
| NMEA 0183 직렬화 | ✅ `$CDDSC` · `$CDDSE` · `!AIVDM` |

### 어댑터

| | 상태 |
|---|---|
| `adapters/mqtt.py` | ✅ |
| `adapters/sqlite.py` | ✅ |
| `adapters/report.py` | ✅ UDP. 실물 무전기는 없음 |
| `adapters/nmea.py` | ✅ |
| `web/app.py` · `web/files.py` | ✅ FastAPI |
| `web/ocean.py` | ✅ 해양 중계 + 캐시 |
| `adapters/gps.py` | ✅ `$xxRMC`. 배 NMEA 에 붙는다 |
| `adapters/ec2.py` | ✅ `/api/pi/**` 클라이언트 |
| `provision.py` · `enroll.py` | ✅ 선박 등록·승인 |
| `sync.py` | ✅ EC2 전송 펌프 |
| `adapters/lora.py` | ✅ 부표 수신. 실링크 미검증 (부표 펌웨어 미착수) |
| `adapters/gpio.py` | ❌ 발사기 |
| IMU | ❌ |

---

## 6. 포트

| 포트 | 무엇 | 비고 |
|---|---|---|
| 1883 | MQTT (TCP) | Jetson, 오케스트레이터 |
| 9001 | MQTT over WebSocket | **키오스크 전용.** 브라우저 제약 |
| 8000 | **FastAPI** | 키오스크 페이지·이미지·Jetson 업로드·`contract.json`·OpenAPI |
| 10110 | NMEA 0183 over UDP | 조난 신고 송출. IETF 할당 포트 |
| 10111 | 부표 LoRa over UDP | `--lora udp` 전용. 라디오 없이 상류만 시험한다 |
| 8080 | **Jetson MJPEG** | 카메라 라이브. Jetson 이 연다 (§4.6) |

⚠ 이미지 HTTP 서버를 붙일 때 **9001 을 피할 것.** mosquitto 가 쓴다.

---

## 7. 미정

| 항목 | 내용 |
|---|---|
| MQTT 인증 | 지금 `allow_anonymous true`. **선내 폐쇄망 전제**라 연기했다 — 외부 노출이 생기면 반드시 닫는다 |
| `ship_id` 발급 | 선박 등록(부록 C) 절차 미확정. 실행할 때마다 새로 발급된다 |
| MMSI 발급 | 조난 신고에 필요. 해양경찰청 등록 사항 |
| 부표 MCU | 미확정 |
| 파일 보관 정책 | `pi_accident_file` 삭제 규칙이 없다. 프로토타입 범위라 연기 |
| `synchronous=NORMAL` | 정전 시 최근 커밋이 날아갈 수 있다. 프로토타입 범위라 연기 |
| `pi/accident/file` 토픽 | 파일 준비 알림. 계약에 아직 없다 |

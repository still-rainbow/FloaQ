# 키오스크 ↔ Pi

> **AI 에게 시킬 때는 이 파일을 통째로 주세요.** 아래 §A 가 지시문이고, 그 뒤가
> 근거와 세부입니다. 잘라서 주면 함정(§9)을 빠뜨립니다.

---

## A. AI 에게 주는 지시

FloaQ 선내 키오스크 화면을 만든다. **선박 한 척, 사고 한 건**을 다루는 전용 단말이다.
익수자가 물에 빠진 순간부터 구조까지를 선원이 보고 조작한다.

### 환경

- 선내 독립 컴퓨터의 브라우저. 인터넷이 없을 수 있다
- 페이지를 Pi 가 내려준다 → **Pi 주소를 하드코딩하지 말고 `location.hostname` 을 쓴다**
- MQTT 는 `mqtt.js` 로 `ws://<pi>:9001`
- 프레임워크는 자유. 빌드가 필요하면 산출물을 Pi 의 `tools/` 에 놓는다

### 화면 넷

| | 언제 | 무엇 |
|---|---|---|
| **등록** | `GET /api/ship` 이 `NONE`·`PENDING`·`WAIT`·`REJECTED` | 선박 등록 폼 / 승인 대기 |
| **대기** | 진행 중 사고 없음 | 선박 위치·장비 상태·카메라 라이브 |
| **경보** | `DETECT` · `WAIT` | 큰 카운트다운 + 취소/즉시신고 버튼 + 스냅샷 |
| **신고 중** | `REPORT` | 채널 3종 상태 + 부표 위치 + 구조/종료 버튼 |

`CANCEL`·`CLOSE` 는 대기 화면으로 돌아간다.

### 반드시 지킬 것

1. **카운트다운은 `report_due_at`(Unix 초, 절대 시각)에서 매 프레임 다시 계산한다.**
   `setInterval` 로 30 부터 세지 않는다. 메시지가 3초 늦으면 화면은 33초를 세는데
   Pi 는 30초에 신고를 쏜다 — 화면에 7초 남았는데 이미 나간 상태가 된다.
   ```js
   const left = Math.max(0, state.report_due_at - Math.floor(Date.now()/1000));
   ```

2. **버튼을 상태로 막는다.** 취소·즉시신고는 `WAIT` 에서만 보인다. `REPORT` 에서는
   구조·종료만. 눌리고 거부되면 사용자에게 고장난 버튼으로 보인다.

3. **재시도는 같은 `request_id` 로 1회만.** 새로 만들면 Pi 의 중복 방어가 무력해지고
   **신고가 두 번 나간다.**

4. **빈 페이로드를 먼저 거른다.** retained 삭제가 길이 0 으로 온다. `JSON.parse("")`
   가 던지면 그 뒤로 메시지가 하나도 안 온다 — 조용히 죽는다.
   ```js
   client.on("message", (topic, buf) => { if (!buf.length) return; ... });
   ```

5. **구독은 QoS 1**, 재접속마다 **다시 구독**한다. QoS 0 이면 retained 를 못 받아
   첫 화면이 빈다. clean session 이라 브로커가 구독을 안 들고 있다.

6. **사진은 Pi 로컬에서** 받는다(`/files/...`). R2·EC2 를 직접 부르지 않는다.

7. **해양 데이터의 `fresh: false` 를 화면에 표시한다.** 3시간 전 조류와 3분 전 조류는
   화면에서 똑같이 생겼다. `503` 이면 빈 값을 0 으로 그리지 않는다.

8. **키오스크는 판단하지 않는다.** 화면이 꺼져 있어도 Pi 가 30초 뒤 신고한다.
   상태는 항상 Pi 가 보낸 것을 그린다.

### 절대 하지 말 것

- 자체 30초 타이머
- `accident_id` 를 키오스크가 만들기
- EC2·R2 직접 호출
- `ship_id` 하드코딩
- 포트 1883 (브라우저는 raw TCP 를 못 연다. **9001**)
- 응답이 없다고 새 `request_id` 로 재시도

### 붙일 곳

```
ws://<pi>:9001                       MQTT over WebSocket
http://<pi>:8000/api/ship            선박 등록 (GET 상태 / POST 신청)
http://<pi>:8000/api/accidents/{id}/files
http://<pi>:8000/files/{id}/{type}/{n}.jpg
http://<pi>:8000/api/ocean/{path}    해양 데이터 (Pi 가 EC2 중계)
http://<pi>:8000/contract.json       토픽·QoS·retain 정본
http://<jetson>:8080/stream.mjpg?camera=L   카메라 라이브 (Pi 아님)
```

토픽·페이로드·오류 코드·명령 목록은 아래 §1~§9 에 전부 있다. `ship_id` 는
`GET /api/ship` 의 `ship_id` 또는 `GET /health` 의 `ship_id` 로 받는다.

---

## B. 배경과 세부

키오스크는 **선내 독립 컴퓨터**입니다. Pi 가 페이지를 내려주고 Pi 의 브로커에 붙습니다.
그래서 설정할 것이 없습니다 — Pi 주소만 알면 됩니다.

```
브라우저 → http://<pi>:8000/kiosk/       페이지를 Pi 가 내려줌
         → ws://<pi>:9001                Pi 의 mosquitto (MQTT over WebSocket)
         → http://<pi>:8000/api/...      사진·해양·선박 등록
```

페이지를 Pi 가 내려주므로 `location.hostname` 이 곧 Pi 주소입니다. 하드코딩하지 마세요.

> 🔴 **EC2 를 직접 부르지 않습니다.** 해양 데이터까지 Pi 가 중계합니다 — 인터넷이
> 끊겨도 화면이 살아야 하고, 키가 브라우저 번들에 들어가면 안 됩니다.

---

## 0. 왜 MQTT 와 HTTP 를 섞나

| | 쓸 것 |
|---|---|
| 답이 **즉시** 필요하고 일회성 | **HTTP** |
| **상태**가 변하고, 재접속 때 복구돼야 함 | **MQTT retained** |

retained 가 핵심입니다. 키오스크가 죽었다 살아나도 **구독하는 순간** 현재 사고·신고
상태가 옵니다. 폴링도, "지금 뭐가 진행 중이지?" 를 묻는 API 도 필요 없습니다.

⚠ 브라우저는 raw TCP 를 못 엽니다. **1883 이 아니라 9001** 입니다.

---

## 1. 토픽

모든 토픽 앞에 `ship/{ship_id}/` 가 붙습니다.

### 구독 (Pi → 키오스크)

| 토픽 | retain | 내용 |
|---|---|---|
| `pi/accident/state` | ✅ | **사고 상태.** 화면의 중심 |
| `pi/launch/result` | ✅ | 투하 결과 (성공/실패 + 사유) |
| `pi/report/status` | ✅ | 신고 채널 3종의 발신 상태 |
| `pi/command/response` | — | 내 명령의 결과. 거부도 옵니다 |
| `pi/buoy/position` | — | 부표 위치 1Hz (QoS 0) |
| `pi/buoy/drift` | ✅ | 표류 추정 범위 |
| `pi/sensor/gps` | ✅ | 선박 위치 1Hz |
| `pi/device/status` | ✅ | 장비 상태 |
| `pi/online` | ✅ | Pi 생사 (LWT) |
| `jetson/snapshot` | ✅ | 탐지 스틸컷 (base64) |

### 발행 (키오스크 → Pi)

| 토픽 | 언제 |
|---|---|
| `kiosk/command/cancel` | 오인신고. **`WAIT` 에서만** |
| `kiosk/command/report_now` | 즉시 신고. **`WAIT` 에서만** |
| `kiosk/command/report_manual` | 수동 긴급 신고. 진행 중 사고가 없을 때 |
| `kiosk/command/rescue` | 구조 확정 |
| `kiosk/command/close` | 사고 종료 |
| `kiosk/online` | LWT. 접속할 때 `true` retained, 유언은 `false` |

전부 QoS 1 입니다.

### 봉투

```jsonc
{ "request_id": "01a0...",   // UUID v7. 중복 판정 + 응답 상관에 씁니다
  "v": 1,
  "ts": 1789622400,          // Unix 초
  "data": [ { ... } ] }      // 항상 배열. 단건도 길이 1
```

---

## 2. 사고 한 건의 시나리오

```
 ① Jetson 탐지
      pi/accident/state   status=DETECT   reason=AI_DETECT
      ─▶ 화면: 경보 띄우기. 소리·색

 ② Pi 가 부표 투하
      pi/launch/result    result=SUCCESS 또는 FAILED + fail_reason
      ─▶ 화면: 투하 결과 표시. 실패해도 사고는 계속됩니다

 ③ 30초 카운트다운
      pi/accident/state   status=WAIT   report_due_at=<절대 시각>
      ─▶ 화면: report_due_at - 지금 을 매 프레임 다시 계산

      사람이 개입할 창이 여기입니다.
        오인이면  kiosk/command/cancel      → CANCEL
        진짜면    kiosk/command/report_now  → REPORT (즉시)
        안 누르면 30초 뒤 Pi 가 알아서      → REPORT

 ④ 신고 발신
      pi/accident/state   status=REPORT
      pi/report/status    채널 3종 × SENDING
      ─▶ 화면: "신고 중" + 채널별 상태

 ⑤ 구조 / 종료
      kiosk/command/rescue  또는  close
      pi/accident/state   status=CLOSE
```

### 🔴 `report_due_at` 을 반드시 쓰세요

**자체 30초 타이머를 돌리면 안 됩니다.**

- 메시지가 3초 늦게 도착하면 키오스크는 33초를 셉니다. Pi 는 30초에 신고를 쏩니다.
  **화면에 7초 남았는데 이미 신고가 나간 상태**가 됩니다.
- 카운트다운 중 재접속하면 남은 시간을 알 방법이 없습니다. `report_due_at` 이 있으면
  retained `pi/accident/state` 하나로 복구됩니다.

```js
const left = Math.max(0, state.report_due_at - Math.floor(Date.now() / 1000));
```

### 🔴 `CANCEL` 은 `WAIT` 에서만 됩니다

| 상태 | 취소 | 왜 |
|---|---|---|
| `DETECT` | ❌ | 투하 중. 카운트다운 전 |
| `WAIT` | ✅ | 신고 전이라 되돌릴 수 있습니다 |
| `REPORT` | ❌ | **이미 전파가 나갔습니다.** 회수가 안 됩니다 |

`REPORT` 에서는 `rescue`(구조 확정) · `close`(종료)만 있습니다. 화면에서 취소 버튼을
**상태에 따라 감추거나 비활성**하세요 — 눌리면 Pi 가 거부하고 그건 사용자에게
"고장난 버튼"으로 보입니다.

### ⚠ 키오스크가 꺼져 있어도 신고는 나갑니다

Pi 가 자기 시계로 판단합니다. 화면은 관측자이지 판단 주체가 아닙니다.

---

## 3. 명령 보내기

```js
const requestId = uuidv7();
publish(`ship/${shipId}/kiosk/command/cancel`, envelope({ accident_id }), { qos: 1 });
```

응답은 `pi/command/response` 로 옵니다. **같은 `request_id`** 로 상관시키세요.

```jsonc
{ "request_id": "01a0...",       // 내가 보낸 것
  "command": "cancel",
  "ok": false,
  "error": { "code": "INVALID_STATE", "message": "..." },
  "accident_id": "01a0...",
  "status": "REPORT" }           // 거부 뒤의 현재 상태
```

### 🔴 거부도 응답입니다

무효한 명령을 Pi 가 조용히 버리지 않습니다. 응답이 없으면 키오스크가 2초 뒤 재시도하고
사용자는 버튼을 연타합니다.

**재시도는 같은 `request_id` 로 1회만.** QoS 1 은 at-least-once 라 같은 명령이 두 번
도착할 수 있는데, Pi 가 `pi_command_log` 로 중복을 막습니다. `request_id` 를 새로
만들면 그 방어가 무력해지고 **신고가 두 번 나갑니다.**

| `error.code` | 뜻 |
|---|---|
| `INVALID_STATE` | 지금 상태에서 못 하는 명령 |
| `ACCIDENT_NOT_FOUND` | 그 사고가 없습니다 |
| `ACCIDENT_IN_PROGRESS` | 진행 중 사고가 있어 새로 못 엽니다 |
| `DEVICE_ERROR` | 장치 문제 |

---

## 4. 선박 등록

일생에 한 번입니다. 신청도 상태도 **HTTP** 입니다.

⚠ 상태는 `pi/ship/status` retained 가 맞지만 아직 없습니다(§11). 지금은 `GET /api/ship`
을 폴링하세요 — 승인 대기 화면에서 10초 간격이면 충분합니다.

```
POST http://<pi>:8000/api/ship
{ "name": "제7금양호", "registration_no": "1234567-6261102",
  "mmsi": "440123456", "has_buoy": true }

202 { "pending": true, "name": "제7금양호" }   받아뒀고 서버 등록 대기
409                                            이미 등록된 배가 있습니다
400                                            형식 오류 (message 에 사유)
```

- **세 값 다 필수입니다.** `registration_no` 는 서버 멱등의 자연키, `mmsi` 는 DSC·AIS 가
  전파에 싣는 자기 식별자의 원본입니다.

> 🔴 **등록번호는 매번 새 값이어야 합니다.** 서버는 같은 `registration_no` 로 다시
> 등록하면 같은 `ship_id` 를 주되 **선박 키는 `null`** 로 줍니다 — 키는 한 번만
> 내려갑니다(실측 2026-09-17). Pi 의 DB 를 지우면 키도 같이 지워지므로, 같은 번호를
> 다시 넣은 배는 **영영 EC2 에 못 붙습니다.**
>
> 재등록·초기화 뒤에는 화면이 새 번호를 만들어 주거나, 사용자에게 그 사실을
> 알려야 합니다.
- `mmsi` 는 숫자 9자리입니다.

상태는 `GET http://<pi>:8000/api/ship` 으로 봅니다.

```jsonc
{ "state": "NONE" }                              // 아직 아무것도 안 넣음
{ "state": "PENDING", "name": "제7금양호" }       // Pi 가 들고 있고 서버 등록 대기
{ "state": "WAIT", "ship_id": "…", "name": "…" }  // 등록됨. 관제 승인 대기
{ "state": "ACTIVE", … }                          // 승인 완료
{ "state": "REJECTED", … }                        // 반려. 고쳐서 다시 신청
```

- `WAIT` 동안 화면에 **"승인 대기"** 를 띄우세요. 승인은 관제 웹에서 사람이 누릅니다 —
  몇 분에서 몇 시간 걸립니다.
- `REJECTED` 는 자동 재시도로 안 풀립니다. 사람이 고쳐서 다시 신청해야 합니다.
- ⚠ 응답에 선박 키는 **절대 안 실립니다.** 서버가 한 번만 주는 값이라 나가는 경로를
  아예 만들지 않았습니다.

> 🔴 **등록 전에는 사고를 못 엽니다.** `ship_id` 가 없으면 MQTT 토픽 경로 자체가
> 성립하지 않습니다. 첫 화면이 등록 화면이어야 합니다.

---

## 5. 사진

```
GET /api/accidents/{accident_id}/files          목록. sequence_no 순
GET /files/{accident_id}/{file_type}/0001.jpg   한 장
```

`file_type` 은 `DETECT_SNAPSHOT` · `BEFORE` · `AFTER` 셋입니다.

| | 장수 | 언제 |
|---|---|---|
| `DETECT_SNAPSHOT` | 1 | 탐지 순간. 화면 대표 이미지 |
| `BEFORE` | 75 | 탐지 **전** 15초 (5fps) |
| `AFTER` | 50 | 탐지 **후** 10초 |

```html
<img src="/files/01a0.../BEFORE/0001.jpg">
```

`FileResponse` 가 `ETag`·`Last-Modified` 를 처리하므로 125장을 다시 받지 않습니다.
지연 로딩(`loading="lazy"`)을 쓰세요.

🔴 **R2 를 보지 마세요.** 선내 화면이 인터넷에 의존하면 사고 상황에서 가장 먼저
끊깁니다. Pi 로컬에서 받으세요.

⚠ 탐지 직후에는 아직 안 올라온 장이 있습니다. 목록을 다시 부르거나, 사고가 `CLOSE`
된 뒤에 재생하세요.

---

## 6. 해양 데이터 — Pi 가 중계합니다

```
GET http://<pi>:8000/api/ocean/current?lat=35.05&lon=129.1
```

중계 경로 여덟: `current` `grid` `series` `observations` `tide` `zones` `summary` `sources`.

```jsonc
{ "success": true, "data": { "currentSpeedMs": 0.42, "currentDirDeg": 137, ... },
  "cached_at": 1789622400,   // 이 값을 받은 시각
  "fresh": true }            // false 면 인터넷이 끊겨 옛 값을 준 것
```

🔴 **`fresh: false` 를 화면에 반드시 표시하세요.** 3시간 전 조류로 그린 원과 3분 전
조류로 그린 원은 **화면에서 똑같이 생겼습니다.**

**503** 이면 인터넷도 캐시도 없는 것입니다. 빈 값을 0 으로 그리지 마세요 —
"조류 0.0 m/s" 는 "잔잔하다"로 읽힙니다.

---

## 7. 카메라 라이브 (Jetson)

```html
<img src="http://<jetson>:8080/stream.mjpg?camera=L">
<img src="http://<jetson>:8080/stream.mjpg?camera=R">
```

MJPEG 이라 `<img>` 하나로 끝입니다. **Pi 가 아니라 Jetson 주소**입니다.

```
GET http://<jetson>:8080/health
{ "ok": false, "size_mismatch": false,
  "cameras": { "L": { "frames": 1204, "age_sec": 0.2, "live": true,  "size": "1280x720" },
               "R": { "frames": 0,    "age_sec": null, "live": false, "size": null } } }
```

`live: false` 인 카메라가 있으면 화면에 알려주세요. 스테레오 거리가 둘 다 필요해서,
한쪽만 도는 상태는 조준 해가 **조용히** 나빠지는 것입니다.

---

## 8. 재접속 복구

```
1. ws://<pi>:9001 접속
2. ship/{ship_id}/pi/#  구독          ← retained 가 바로 옵니다
3. pi/accident/state 를 보고 화면을 고릅니다
     없음 · CANCEL · CLOSE  →  대기 화면
     DETECT · WAIT          →  경보 화면 (report_due_at 으로 카운트다운 재계산)
     REPORT                 →  신고 중 화면
4. GET /api/ship 으로 등록 상태 확인
```

자체 타이머를 돌리고 있었다면 재접속 시점에 남은 시간을 알 방법이 없습니다.
**`report_due_at` 으로 매번 다시 계산**하는 것이 이 절차의 핵심입니다.

---

## 9. 자주 밟는 것

| 증상 | 원인 |
|---|---|
| **아무것도 안 옴. 에러도 없음** | `ship_id` 가 틀렸습니다. 브로커는 아무 말도 안 해줍니다 — 그냥 다른 방에 말하는 셈입니다 |
| 붙지도 못함 | 1883 으로 붙었습니다. 브라우저는 **9001** 입니다 |
| 첫 접속에 화면이 비어 있음 | QoS 0 으로 구독했습니다. retained 를 받으려면 **QoS 1** |
| 재접속 뒤로 조용함 | 재접속마다 **다시 구독**해야 합니다. clean session 이면 브로커가 구독을 안 들고 있습니다 |
| 메시지 파싱에서 죽고 그 뒤 조용함 | **빈 페이로드는 retained 삭제**입니다. `JSON.parse("")` 가 던지고 핸들러가 죽습니다. 길이 0 이면 그냥 무시하세요 |
| 버튼이 안 먹음 | 그 상태에서 못 하는 명령입니다. `pi/command/response` 의 `error.code` 를 보세요 |
| 신고가 두 번 나감 | 재시도에 **새 `request_id`** 를 만들었습니다. 같은 값으로 1회만 |
| 카운트다운이 어긋남 | 자체 타이머를 돌리고 있습니다. `report_due_at` 을 쓰세요 |

---

## 10. 계약은 손으로 옮겨 적지 마세요

```
GET http://<pi>:8000/contract.json
```

토픽·QoS·retain·유효 명령이 전부 들어 있습니다. **요청할 때마다 파이썬이 만듭니다** —
파일로 굳혀두면 코드와 갈라집니다.

```
GET http://<pi>:8000/docs          OpenAPI (HTTP 쪽)
```

페이로드 필드는 [mqtt.md](mqtt.md) 가 정본입니다.

---

## 11. 아직 없는 것

| | 대안 |
|---|---|
| `GET /api/accidents` 목록·이력 | 지금은 retained 로 **현재 사고 하나**만 볼 수 있습니다 |
| `GET /api/accidents/{id}/timeline` | 〃 |
| `pi/ship/status` retained | `GET /api/ship` 폴링으로 대신합니다 |

필요하면 말해주세요. 만들 수 있습니다.

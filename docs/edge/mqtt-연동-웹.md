# 웹 팀 MQTT 연동 안내

Pi 오케스트레이터에 붙어서 사고 상태를 받고 명령을 보내는 방법을 정리한다.

전체 토픽·페이로드 규격은 [mqtt.md](mqtt.md)가 정본이다. 이 문서는 **연결해서 화면을
띄우는 데 필요한 것만** 추린다. LoRa 구간은 [lora.md](lora.md)로 따로 있다.

---

## 1. 접속 정보

| 항목 | 값 |
|---|---|
| 호스트 | 개발 PC의 LAN 주소 (담당자에게 확인) |
| MQTT (TCP) | `1883` — 서버 사이드, Node/Python |
| **MQTT over WebSocket** | **`9001`** — 브라우저는 이것만 가능 |
| **HTTP** | **`8000`** — 이미지·계약·OpenAPI |
| 프로토콜 | MQTT 3.1.1 |
| 인증 | 없음. **선내 폐쇄망 전제** — 외부 노출이 생기면 닫는다 |
| `SHIP_ID` | 실행할 때마다 새로 발급된다. 담당자에게 확인 |

포트가 둘로 나뉘는 게 어색하지만 프로세스가 다르다 — `9001` 은 mosquitto,
`8000` 은 FastAPI. `1883` 과 `9001` 은 **같은 브로커의 입구 둘**이고 토픽도
메시지도 동일하다. 브라우저가 raw TCP 를 못 열어서 WebSocket 입구가 따로 있는 것뿐이다.

### 브라우저에서

```js
// mqtt.js (npm: mqtt)
const client = mqtt.connect('ws://<호스트>:9001')
```

> 🔴 **브라우저는 raw TCP 소켓을 못 연다.** `1883`으로 붙으려 하면 실패한다.
> 반드시 `ws://호스트:9001`을 쓴다.

### 연결이 안 될 때

1. 브로커가 떠 있는지 — 담당자에게 확인
2. 방화벽 — Windows 인바운드가 기본 차단이다. 1883/9001 허용 규칙이 필요하다
3. 같은 네트워크인지 — 사내망 밖에서는 안 된다

---

## 2. 토픽 구조

```
ship/{ship_id}/{발행자}/{주제}
```

발행자는 `pi` · `jetson` · `kiosk` 셋이다. **자기가 발행하는 세그먼트에만 쓴다.**
웹/키오스크는 `kiosk/**`에만 발행하고 `pi/**`·`jetson/**`은 구독만 한다.

이 규약은 나중에 브로커 ACL로 강제할 예정이다. 지금 어겨도 동작하지만,
ACL이 켜지는 순간 조용히 막힌다.

### 구독할 것

| 토픽 | 내용 | QoS | retained |
|---|---|---|---|
| `pi/accident/state` | **사고 상태.** 화면의 중심 | 1 | O |
| `pi/launch/result` | 부표 투하 결과 | 1 | O |
| `pi/buoy/position` | 부표 위치 (1Hz) | 0 | X |
| `pi/buoy/drift` | 통신 두절 시 표류 추정 범위 | 1 | O |
| `pi/sensor/gps` | 선박 위치 (1Hz) | 0 | O |
| `pi/sensor/imu` | 선박 자세 | 0 | X |
| `pi/device/status` | 장비 상태 | 1 | O |
| `pi/report/status` | 신고 채널별 상태 | 1 | O |
| `pi/command/response` | 내가 보낸 명령의 응답 | 1 | X |
| `pi/online` | Pi 생존 여부 (LWT) | 1 | O |
| `jetson/snapshot` | 사고 영상 스냅샷 | 1 | O |
| `jetson/status` | Jetson 상태 | 1 | O |

한 번에 받으려면 `ship/{ship_id}/pi/#`와 `ship/{ship_id}/jetson/#`를 구독한다.

### retained가 왜 중요한가

`retained`가 O인 토픽은 **구독하는 순간 마지막 값이 즉시 온다.** 화면을 새로고침해도
현재 사고 상태를 바로 그릴 수 있다. 별도의 "현재 상태 조회 API"가 필요 없다.

retained가 X인 토픽은 다음 발행을 기다려야 한다.

---

## 3. 봉투 (Envelope)

`pi/online`·`kiosk/online`을 제외한 **모든** 페이로드는 이 봉투에 담긴다.

```ts
interface Envelope<T> {
  request_id: string   // UUID v7
  v: number            // 스키마 버전. 현재 1
  ts: number           // Unix epoch **초** (밀리초 아님)
  data: T[]            // 🔴 항상 배열
}
```

> 🔴 **`data`는 언제나 배열이다.** 원소가 하나여도 배열로 감싼다.
> 객체를 그대로 넣으면 Pi가 `Input should be a valid array`로 거부하고
> **응답도 주지 않는다.** 실제로 밟기 쉬운 곳이다.

명령의 응답만 모양이 다르다.

```ts
interface CommandAck<T> {
  request_id: string   // 내가 보낸 명령의 request_id 를 그대로 되돌려준다
  v: number
  ts: number
  is_success: boolean
  data: T              // 🔴 이쪽은 배열이 아니다
  error?: { code: string, message: string }
}
```

### 봉투를 쓰지 않는 예외

`pi/online`과 `kiosk/online`은 LWT(Last Will and Testament)라 페이로드가 접속
시점에 고정된다. `request_id`·`ts`를 의미 있게 채울 수 없어 날것으로 보낸다.

```json
{ "online": true, "ts": 1789456675 }
```

수신 측에서 이 둘만 따로 처리해야 한다. 봉투로 파싱하려 들면 깨진다.

### 🔴 빈 페이로드를 반드시 걸러낼 것

사고가 끝나면 Pi 가 **0바이트를 retain 으로 발행**해 `pi/accident/state` 등의
retained 를 지운다. 그게 구독자에게 **빈 메시지**로 도착한다.

```js
client.on('message', (topic, payload) => {
  if (payload.length === 0) return        // retained 삭제. 반드시 먼저
  const env = JSON.parse(payload)
  ...
})
```

거르지 않으면 `JSON.parse('')` 가 던지고, **그 예외가 메시지 핸들러를 죽여서
이후 모든 메시지를 못 받는다.** 화면이 조용히 멈춘다.

실제로 참조 클라이언트에서 밟았다.

---

## 4. 사고 상태 — 화면의 중심

`ship/{ship_id}/pi/accident/state` (retained)

```ts
interface AccidentState {
  accident_id: string
  status: 'DETECT' | 'WAIT' | 'REPORT' | 'CANCEL' | 'CLOSE'
  prev_status: string | null
  reason: 'AI_DETECT' | 'COUNTDOWN_START' | 'TIMEOUT'
         | 'TABLET_CANCEL' | 'TABLET_REPORT_NOW' | 'TABLET_MANUAL'
         | 'TABLET_RESCUE' | 'TABLET_CLOSE'
  accident_type: 'MOB' | 'FIRE' | 'FLOODING' | ...
  report_type: 'DISTRESS' | 'URGENCY'      // SAFETY 제거 2026-09-17. AccidentType 은 8종
  lat: number | null
  lon: number | null
  wait_sec: number
  report_due_at: number | null   // WAIT 일 때 반드시 있다
  created_at: number
}
```

### 상태 흐름

```
        AI 탐지                   30초 만료
 (없음) ──────→ DETECT ──────→ WAIT ──────────→ REPORT ──→ CLOSE
                              │                   ↑
                              │ 취소               │ 즉시 신고
                              ↓                   │
                            CANCEL                └── 수동 신고 (DETECT 안 거침)
```

### 카운트다운 그리는 법

🔴 **프런트에서 30초를 세지 않는다.** `report_due_at`(Unix 초)에서 현재 시각을 빼서
매 프레임 다시 계산한다.

```js
const remain = Math.max(0, state.report_due_at - Math.floor(Date.now() / 1000))
```

이유: 화면을 새로 열거나 탭이 백그라운드로 갔다 와도 정확한 남은 시간이 나온다.
프런트 타이머로 세면 그 순간 어긋나고, **Pi는 자기 시계로 신고를 쏘기 때문에**
화면과 실제가 달라진다.

> Pi는 키오스크가 살아 있든 아니든 혼자 판단해 신고한다. 화면은 관측자일 뿐
> 판단 주체가 아니다.

---

## 5. 명령 보내기

`ship/{ship_id}/kiosk/command/{명령}` · QoS 1 · **retain 금지**

| 명령 | 페이로드 `data[0]` | 유효 상태 |
|---|---|---|
| `cancel` | `{ accident_id }` | DETECT, WAIT |
| `report_now` | `{ accident_id }` | DETECT, WAIT |
| `rescue` | `{ accident_id }` | REPORT |
| `close` | `{ accident_id }` | REPORT |
| `report_manual` | `{ accident_id, accident_type, lat, lon }` | 진행 중 사고 없을 때 |

```js
client.publish(`ship/${shipId}/kiosk/command/close`, JSON.stringify({
  request_id: crypto.randomUUID(),
  v: 1,
  ts: Math.floor(Date.now() / 1000),
  data: [{ accident_id: accidentId }],     // 배열
}), { qos: 1, retain: false })
```

> 🔴 **`kiosk/command/*`에 retain을 걸지 않는다.** 걸면 Pi가 재접속할 때마다
> 30분 전의 [즉시 신고]가 되살아난다.

### 응답 처리

`ship/{ship_id}/pi/command/response`를 구독하고 `request_id`로 짝을 맞춘다.

```json
{
  "request_id": "...",
  "v": 1, "ts": 1789456675,
  "is_success": true,
  "data": { "accident_id": "...", "command": "close", "status": "CLOSE" }
}
```

거부될 때도 응답이 온다. 침묵이 아니다.

```json
{
  "is_success": false,
  "data": { "accident_id": "...", "command": "rescue", "status": "WAIT" },
  "error": { "code": "INVALID_STATE", "message": "..." }
}
```

`data.status`에 **현재 상태**가 실려 오므로 화면을 그 상태로 되돌리면 된다.

주요 에러 코드: `INVALID_STATE` · `ACCIDENT_IN_PROGRESS` · `NOT_FOUND` · `BAD_REQUEST`

### 재시도

QoS 1은 at-least-once다. 2초 안에 응답이 없으면 **같은 `request_id`로** 다시 발행한다.

> 🔴 **새 `request_id`로 보내지 않는다.** Pi는 `request_id`로 중복을 거른다.
> 새 ID면 별개 명령으로 처리되어 신고가 두 번 나간다.

같은 `request_id`로 다시 보내면 Pi는 실행은 건너뛰고 응답만 다시 준다.

---

## 6. 연결 상태 판정

`ship/{ship_id}/pi/online` (retained, LWT)

```json
{ "online": true, "ts": 1789456675 }
```

Pi가 죽으면 브로커가 대신 `{"online": false, "ts": 0}`을 발행한다.

> ⚠ **약 22초 늦는다.** Keep Alive 15초 × 1.5 = 22.5초가 지나야 브로커가 LWT를
> 발행한다. 30초 카운트다운과 같은 스케일이라, "Pi가 죽었다"를 화면에 띄울 때
> 이 지연을 감안해야 한다. 끊긴 직후 22초 동안은 아직 `online: true`로 보인다.

정상 종료일 때는 Pi가 직접 `online: false`를 발행하므로 즉시 반영된다.

---

## 7. 계약 파일 — 손으로 옮겨 적지 말 것

타입을 직접 다시 쓰면 반드시 갈라진다. **파이썬이 정본**이고 JSON Schema로 뽑아 쓴다.

```bash
cd iot/pi
python -m floaq.contracts -o tools/contract.json
```

`contract.json`에 들어 있는 것:

- 토픽별 페이로드 JSON Schema, QoS, retain 기본값
- enum 전체 (`AccidentStatus`, `AccidentType`, `ReportType`, `ErrorCode` …)
- `accident_routing` — 사고 유형 → (신고 등급, DSC 코드)
- `valid_command_states` — 상태별로 활성화할 버튼
- `transitions` — (현재 상태, 사유) → 다음 상태

TS 타입 생성:
```bash
npx json-schema-to-typescript contract.json > contract.d.ts
```

> `valid_command_states`는 **버튼 활성화 힌트로만** 쓴다. 실제 거부는 Pi가 한다.
> 프런트에서 막았다고 Pi 응답을 안 봐도 되는 게 아니다.

---

## 8. 바로 해보기

### 브라우저에서

개발용 키오스크가 이미 있다. 그대로 열거나 참고 구현으로 봐도 된다.

```powershell
cd IoT\PI
.\scripts\dev.ps1 kiosk        # http://localhost:8765/kiosk.html
```

`iot/pi/tools/kiosk.html` — `contract.json`을 읽어 토픽·유효 명령을 채우고,
카운트다운을 `report_due_at`에서 200ms마다 다시 계산한다. `*/online`을 봉투 없이
처리하는 부분도 들어 있다.

### 가짜 사고 만들기

Jetson 없이 탐지를 흉내낸다.

```powershell
.\scripts\dev.ps1 detect                  # 정상 탐지 → 투하 성공 → WAIT
.\scripts\dev.ps1 detect --no-solution    # 조준 해 없음 → NO_SOLUTION
.\scripts\dev.ps1 detect --bad-angle      # 범위 밖 각도 → OUT_OF_RANGE
.\scripts\dev.ps1 detect --bad-profile    # 미등록 프로파일 → OUT_OF_RANGE
.\scripts\dev.ps1 detect --stale          # 묵은 조준 해 → OUT_OF_RANGE
```

거부 경로도 화면이 감당해야 하므로 넷 다 한 번씩 돌려볼 것.

### 전체 메시지 덤프

```powershell
.\scripts\dev.ps1 sub
```

### Postman

Postman은 MQTT를 지원한다. `mqtt://<호스트>:1883`으로 새 MQTT Request를 만들고
`ship/{ship_id}/#`을 구독하면 전부 보인다. 브라우저가 아니므로 9001이 아니라
1883으로 붙는다.

---

## 9. 자주 밟는 것

| 증상 | 원인 |
|---|---|
| 브라우저에서 연결 실패 | `1883`으로 붙었다. `ws://호스트:9001`을 써야 한다 |
| 명령을 보내도 응답이 없다 | `data`를 배열로 안 감쌌다. Pi가 조용히 버린다 |
| `pi/online` 파싱 실패 | LWT 토픽은 봉투를 쓰지 않는다. 따로 처리 |
| 새로고침하면 화면이 빈다 | retained 토픽을 구독하지 않았다 |
| 카운트다운이 어긋난다 | 프런트에서 세고 있다. `report_due_at`으로 계산 |
| 신고가 두 번 나갔다 | 재시도에서 `request_id`를 새로 만들었다 |
| 30분 전 명령이 되살아난다 | `kiosk/command/*`에 retain을 걸었다 |
| 타임스탬프가 1970년 | `ts`는 **초**다. 밀리초를 넣었다 |
| 사고 종료 후 클라이언트가 먹통 | **retained 삭제가 빈 페이로드로 온다.** `JSON.parse('')` 가 던지고, 그 예외가 메시지 핸들러를 죽인다 |
| 외부에서 접속이 안 된다 | Windows 방화벽 인바운드 차단. 1883/9001 허용 필요 |

---

## 10. 조난 신고 상태

`ship/{ship_id}/pi/report/status` (retained, 채널당 1건)

```ts
interface ReportStatus {
  accident_id: string
  report_id: number
  channel: 'AIS_MOB' | 'AIS_SART' | 'DSC'
  status: 'SENDING' | 'ACKED' | 'STOPPED' | 'FAILED'
  sent_count: number
  first_sent_at: number | null
  last_sent_at: number | null
  acked_at: number | null      // DSC 만 값이 들어온다
  acked_by: string | null      // 확인응답을 보낸 해안국 MMSI 9자리
  fail_reason: 'NO_INTERNET' | 'NO_RECEIVER' | 'TIMEOUT' | null
}
```

**채널이 셋이고 동작이 서로 다르다.**

| 채널 | 주기 | 중지 |
|---|---|---|
| `AIS_MOB` | 1분 8회 + 4분마다 문구 | 수동만 |
| `AIS_SART` | 동일 | 수동만 |
| `DSC` | 연속 5회, 3.5~4.5분 무작위 간격 | **확인응답 시 자동** |

> 🔴 **`ACKED` 는 DSC 에만 온다.** AIS 는 단방향 브로드캐스트라 확인응답이 없다.
> `acked_at`/`acked_by` 가 AIS 채널에 채워지면 그건 버그다 — DB 도
> `CHECK (acked_at IS NULL OR channel = 'DSC')` 로 막고 있다.

> ⚠ **DSC 가 `ACKED` 여도 구조가 끝난 게 아니다.** 해안국이 신고를 접수했다는
> 뜻일 뿐이고 AIS 두 채널은 계속 나간다. 화면에 "신고 접수"와 "구조 완료"를
> 구분해서 써야 한다.

> ⚠ 확인응답은 해안국 운용자가 **수동으로** 보낸다(ITU-R M.541 §3.3). 언제 올지
> 모르고, 무선전화로 대신 응답하면 영영 안 온다. `SENDING` 이 오래 지속되는 것이
> 정상이다 — 오류로 표시하지 말 것.

### 실제로 나가는 것 (참고)

웹이 받을 필요는 없다. 검증·시연용이다.

```
10110/udp    NMEA 0183 over UDP (IETF 할당 포트)

  $CDDSC + $CDDSE        DSC 조난 경보
  !AIVDM (MMSI 972…)     AIS-MOB
  !AIVDM (MMSI 970…)     AIS-SART
```

**포트는 하나다.** 채널은 문장 종류와 MMSI 접두로 구분된다.

OpenCPN 에 붙여 보려면 `Options > Connections > Add > Network > UDP`,
주소 `0.0.0.0`, 포트 `10110`. 자세한 건 [distress.md](distress.md).

> 🔴 시뮬레이션이다. 실제 전파가 나가지 않으며 형식 승인된 GMDSS 장비를 대신할 수 없다.

---

## 11. 이미지·영상

**MQTT 로 실물 파일을 받지 않는다.** 크기와 성격이 다른 둘로 나뉜다.

| 대상 | 어디서 | 수단 |
|---|---|---|
| 탐지 스냅샷 1장 | Pi | MQTT `jetson/snapshot` base64, retained |
| 사고 전후 프레임 125장 | Pi | HTTP `http://<pi>:8000/files/...` |
| 위 전부 | R2 | EC2 가 올린다 |

### 선내 화면은 R2 를 보지 않는다

키오스크는 **Pi 로컬 HTTP** 에서 받는다. R2 를 보면 선내 화면이 인터넷에 의존하게
되고, 사고 상황에서 인터넷이 가장 먼저 끊긴다.

웹/앱(육상)은 R2 에서 받는다.

### Pi → EC2 업로드 규약

인터넷이 될 때만 올린다. 안 되면 아무것도 하지 않고 Pi 에 쌓아 둔다.

```
POST /api/accidents/{accident_id}/files
Content-Type: multipart/form-data

  file         (binary)
  file_type    DETECT_SNAPSHOT | BEFORE | AFTER
  sequence_no  0001
  camera       L | R
  captured_at  1789456675

200 { "object_key": "accidents/{id}/BEFORE/0001.jpg" }
```

**파일 하나당 요청 하나.** 여러 장을 묶으면 부분 실패가 지저분해진다.

> 🔴 **멱등키는 `(accident_id, file_type, sequence_no)`.**
> 응답이 유실돼 Pi 가 재전송해도 새 행을 만들면 안 된다. upsert 하고 기존
> `object_key` 를 그대로 돌려줄 것. Pi 는 그 값을 받아야 업로드 완료로 표시한다.

EC2 가 R2 에 올리고 키를 돌려준다. Pi 에는 R2 자격증명을 두지 않는다 —
어선에 실린 물리 장비라 분해·도난을 전제한다.

### 아직 없는 것

`pi/accident/file` 토픽이 계약에 없다. 파일이 준비됐다는 알림을 웹이 받을 길이
아직 없다는 뜻이다. 필요하면 요청할 것.

---

## 12. 최근 변경

### 2026-09-17 — `SAFETY` 등급과 `HAZARD` 유형 제거 `확정`

```
ReportType     DISTRESS | URGENCY | SAFETY   ->  DISTRESS | URGENCY
AccidentType   10종                           ->  8종 (HAZARD·ABANDON_SHIP 삭제)
```

SAFETY 는 항행경보 수준이라 익수자 구조 시스템에서 쓸 일이 없었다. `HAZARD` 는
SAFETY 가 사라지면서 갈 곳이 없어졌고, `ABANDON_SHIP` 은 1차 범위에서 뺐다.
결과 8종은 EC2 `api.json` 의 `IPiAccident.accident_type` 과 **글자까지 같다.**

> `ABANDON_SHIP` 을 되살릴 때는 `DISTRESS` + dsc `108` 이다. 구 설계의 `SAFETY` 는
> 오류였다 — DSC 의 **category** 108(safety)과 **nature of distress** 108
> (abandoning ship)은 다른 표이고, 퇴선은 조난이다.

사고 유형은 10개 -> 8개다. 화면 선택지에서 "위험물 발견"과 "퇴함"을 빼면 된다.

---

### 2026-09-17 — 프레임 구간 `확정` 앞 15초 · 뒤 10초

```
이전   앞 30초 150장
지금   앞 15초 75장 + 뒤 10초 50장 + 스틸컷 1장 = 125장
```

5fps 기준이고 200KB 로 잡으면 사고당 25MB 다. 화면에서 바뀌는 것은 재생 길이뿐이다 —
경로(`GET /files/{accident_id}/{file_type}/{n}.jpg`)와 `file_type` 3종은 그대로다.

---

### 2026-09-17 — 해양 데이터는 Pi 가 중계한다 `확정`

**키오스크는 EC2 를 직접 부르지 않는다.**

```
이전   키오스크 ──▶ EC2 /api/ocean/current      (VITE_KIOSK_KEY 를 번들에)
지금   키오스크 ──▶ Pi  :8000/api/ocean/current  ──▶ EC2
```

| | |
|---|---|
| 키오스크 설정 | Pi 주소 하나. EC2 주소·키를 안 들고 있는다 |
| `x-floaq-kiosk-key` | **Pi 가 서버 쪽에서 붙인다.** 브라우저 번들에 안 들어간다 |
| 인터넷 끊김 | Pi 캐시에서 준다. 본문에 `cached_at` · `fresh: false` 가 붙는다 |

🔴 **`fresh: false` 를 화면에 반드시 표시할 것.** 3시간 전 조류로 그린 원과 3분 전
조류로 그린 원은 **화면에서 똑같이 생겼다.** 캐시도 없으면 **503** 이다 —
빈 200 을 주면 "조류 0.0 m/s" 가 "잔잔하다"로 읽힌다.

```jsonc
// GET http://<pi>:8000/api/ocean/current?lat=35.05&lon=129.1
{ "success": true, "data": { "currentSpeedMs": 0.42, ... },
  "cached_at": 1789622400,   // 이 값을 받은 시각
  "fresh": true }            // false 면 인터넷이 끊겨 옛 값을 준 것
```

중계하는 경로는 여덟이다 — `current` `grid` `series` `observations` `tide` `zones`
`summary` `sources`.

---

### 2026-09-17 — 선박 등록은 키오스크가 Pi 로 보낸다 `확정`

```
키오스크 ──POST http://<pi>:8000/api/ship──▶ Pi ──▶ EC2 POST /api/pi/ships
                                                      └─ ship_id · ship_key · status
```

```jsonc
// 요청 — 셋 다 필수
{ "name": "제7금양호", "registration_no": "1234567-6261102",
  "mmsi": "440123456", "has_buoy": true }

// 202 — 받아뒀고 서버 등록 대기
{ "pending": true, "name": "제7금양호" }
// 409 — 이미 등록된 배가 있다
```

상태는 `GET http://<pi>:8000/api/ship` 으로 본다.

```jsonc
{ "state": "NONE" }                              // 아직 아무것도 안 넣음
{ "state": "PENDING", "name": "제7금양호" }        // Pi 가 들고 있고 서버 등록 대기
{ "state": "WAIT", "ship_id": "…", "name": "…" }  // 등록됨. 관제 승인 대기
{ "state": "ACTIVE", … }                          // 승인 완료
{ "state": "REJECTED", … }                        // 반려. 사람이 고쳐 다시 신청
```

- **`registration_no` 와 `mmsi` 가 필수다.** 등록번호는 서버 멱등의 자연키고, MMSI 는
  DSC·AIS 가 전파에 싣는 자기 식별자의 원본이다.
- `WAIT` 동안 화면에 "승인 대기"를 띄운다. 승인은 관제 웹에서 사람이 누른다.
- ⚠ `ship_key` 는 **응답에 절대 안 실린다.** 서버가 한 번만 주는 값이라 나가는 경로를
  아예 만들지 않았다.

---

### 2026-09-17 — Jetson SDK · 카메라 라이브 `:8080`

Jetson 쪽 Flask 카메라 서버와 `jetson_client.py` 는 **버렸다.** SDK 가 대신한다.

```
http://<jetson>:8080/                       좌우 카메라 확인 페이지
http://<jetson>:8080/stream.mjpg?camera=L   <img src> 에 그대로 넣는다
http://<jetson>:8080/snapshot.jpg?camera=R  최근 한 장
```

```html
<img src="http://<jetson>:8080/stream.mjpg?camera=L">
```

**기록이 아니라 보기용이다.** 사고 기록은 Pi 로 올라가는 쪽이고, 여기는 지금 카메라가
무엇을 보는지 확인하는 화면이다.

---

## 13. 지금 미정인 것

| 항목 | 내용 |
|---|---|
| 인증 | 개발 중 익명이다. 키오스크가 브라우저라 자격증명을 숨길 곳이 없다. 익명 / 전용계정+ACL / 클라이언트 인증서 중 선택 (`mqtt.md` §7) |
| `SHIP_ID` 발급 절차 | 선박 등록(부록 C)이 확정되지 않았다. 지금은 실행할 때마다 새로 발급된다 |
| 브로커 주소 | 개발 PC에서 돈다. Pi에 올라가면 주소가 바뀐다 |

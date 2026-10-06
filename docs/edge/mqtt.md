# MQTT 통신 규격 — Raspberry Pi (브로커) ↔ Jetson · 키오스크

> 상세 기획 §7.2 를 구현 가능한 수준으로 확정한 문서.
> 페이로드는 **TypeScript interface 표기**를 씁니다 (JSON Schema 아님).

| `확정` | 기획서에서 결정됨 |
| --- | --- |
| `제안`⚠️ | 이 문서에서 제안. 승인 필요 |
| `미정`⚠️ | 결정 필요. **개발 막힘** |

## 이 문서가 다루는 구간

```
  카메라 2대 ──▶  Jetson  (AI 추론 전용)
                    │
                    │  MQTT  jetson/detection · jetson/snapshot · jetson/status
                    │  HTTP  프레임 125장 PUT   (§5.13)
                    ▼
              Raspberry Pi  ──▶ 발사 장치
                ├─ MQTT broker (mosquitto)   ← 브로커가 여기 있다
                ├─ SQLite (pi_*)
                ├─ IMU
                ├─ LoRa RX  ◀── 구조 부표
                └─ UDP TX   ──▶ AIS 수신처 (신고)
                    │
                    │  MQTT  pi/*  ⇅  kiosk/*
                    ▼
                 키오스크
                    │
                    │  선박 GPS 원본이 여기 (기획서 §2.2)
                    │  → kiosk/sensor/gps 를 Pi 와 Jetson 이 구독
                    │
     [HTTPS REST]   ← 이 문서 범위 밖
          ▼
         EC2  ──▶ R2 (영상·이미지)
```

**Pi 가 브로커입니다.** Jetson 과 키오스크는 둘 다 클라이언트로 붙습니다.

| 구간 | 이 문서 | 비고 |
| --- | --- | --- |
| Jetson ↔ Pi | ✅ MQTT | 대용량 프레임만 HTTP (§5.13) |
| Pi ↔ 키오스크 | ✅ MQTT | |
| Jetson ↔ 키오스크 | ✅ MQTT | 중계 없이 직접 (§1.3) |
| Pi ↔ EC2 | ❌ | **HTTPS REST + 폴링** `확정` (2026-09-11) — §0.3 |
| Pi ↔ 구조 부표 | ❌ | LoRa 20바이트 바이너리 |
| Pi → AIS 수신처 | ❌ | UDP |

---

## 0. 범위와 표기 규약

### 0.3 MQTT 는 선박 안에서만 씁니다 `확정` (2026-09-11)

**MQTT 3자 = Pi · Jetson · 키오스크.** 전부 선박 내부이고 인터넷이 필요 없습니다.

**Pi ↔ EC2 는 MQTT 를 쓰지 않습니다.** HTTPS REST 를 쓰고, 관제 웹은 EC2 에 폴링합니다. 방향은 두 갈래입니다.

| 방향 | 내용 |
| --- | --- |
| Pi → EC2 (push) | 사고·부표·IMU·영상 동기화 (IOT-18), R2 업로드 |
| Pi ← EC2 (pull) | **해양 공공데이터 캐시** — 조류·풍속. 인터넷 있을 때 받아 `pi_ocean_data` 에 저장하고, 끊기면 마지막 값으로 표류를 계산 (§5.14) |

이유는 두 가지입니다.

1. **인터넷 없이도 선박 기능이 전부 돌아야 합니다.** 브로커가 Pi 에 있으므로 탐지·투하·경보·부표추적·신고가 EC2 와 무관하게 동작합니다. EC2 로 가는 링크는 끊겨도 되는 경로입니다 (기획서 §9.1).
2. **재전송 책임이 이미 Pi 에 있습니다.** Pi 가 SQLite 동기화 큐를 갖고 있어서(IOT-18) 브로커 측 세션 큐·QoS 는 중복입니다. 끊김이 잦은 링크에 상시 연결을 유지할 이유도 없습니다.

> 🔴 **EC2 에 있는 mosquitto 는 이 결정으로 불필요해집니다.** `infra/docker-compose.yml`·`docker-compose.prod.yml` 의 `mosquitto` 서비스, `infra/mosquitto/mosquitto.conf`, `backend/build.gradle` 의 `spring-integration-mqtt` 가 대상입니다. 공인 EC2 에 평문 1883 을 `allow_anonymous true` 로 열어둔 상태라 **지우면 보안 이슈도 같이 닫힙니다.**

## 0. 표기 규약

문서 전체에서 아래 별칭을 씁니다. 페이로드 정의보다 먼저 읽으세요.

```ts
type Int  = number;   // 정수만. §0.1 참고 — STRICT 가 전부 막아주지는 않습니다
type Unix = number;   // Int. Unix epoch "초". 밀리초 아님
type Uuid = string;   // UUID v7 문자열. 36자, 하이픈 포함
type Deg  = number;   // 도(°). 각속도(deg/s) 아님
```

규칙 네 가지:

1. **`?` 와 `| null` 은 다릅니다.** `?`는 키 자체를 생략해도 됨, `| null`은 키는 반드시 있고 값이 `null`일 수 있음. 파서가 달라지니 구분해서 쓰세요.
2. **범위·단위는 주석으로 답니다.** TS 타입으로는 `100 ~ 110`, `0 ~ 1` 을 표현할 수 없습니다.
3. **필드명은 전부 snake_case.** DB 컬럼명과 동일하게 둔 것이라 변환 계층이 없습니다 (§3.5).
4. **`lng` 금지, `lon` 으로 통일** (기획서 §6.4).

### 0.1 와이어 포맷 `제안`⚠️

TS interface 는 **표기**일 뿐이고, 실제로 선을 타는 건 아래 규격입니다.

| 항목 | 규격 |
| --- | --- |
| 인코딩 | **UTF-8 JSON**. 최상위는 항상 객체 (배열·스칼라 금지) |
| 숫자 | JSON number. **`NaN` / `Infinity` 금지** — JSON 표준 밖이라 파서가 터집니다 |
| 정수 | `Int`/`Unix` 는 소수점 없이. `1757000000.0` 은 보내지 마세요 — ⚠️ **SQLite STRICT 는 이걸 막지 않습니다.** INTEGER 컬럼은 무손실 변환이 되는 실수를 조용히 정수로 바꿔 넣습니다. `1.5` 만 실패해요. 이 규칙은 **앱에서 검증**해야 합니다 |
| 불린 | `is_pressed` 만 `0 | 1` (LoRa·SQLite 와 맞춤). 나머지는 `true`/`false` |
| 바이너리 | base64 표준 알파벳, 패딩 포함, **개행 없음**. `data:` 접두사 없음 |
| 최대 크기 | `jetson/snapshot` 300KB, **그 외 모든 토픽 4KB** |
| 알 수 없는 필드 | **무시하고 진행.** 에러로 처리하지 마세요 (§0.2) |

### 0.2 버전 규약 `제안`⚠️

Envelope 에 `v` 를 둡니다 (§3).

| 변경 | `v` |
| --- | --- |
| 필드 **추가** | 유지 — 수신 측이 모르는 필드를 무시하면 되니까 |
| 필드 **제거**, 의미·단위 변경, enum 값 제거 | **증가** |

수신 측은 **모르는 `v` 가 오면 그 메시지를 버리고 로그만 남깁니다.** 이게 없으면 키오스크만 업데이트한 상태에서 Pi 가 옛 페이로드를 계속 보낼 때 조용히 오작동합니다.

지금은 전부 `v: 1` 입니다.

---

## 1. 브로커

| 항목 | 값 | 상태 |
| --- | --- | --- |
| 위치 | **Pi 로컬 mosquitto** | `제안`⚠️ |
| 포트 | **1883** raw MQTT · **9001** WebSocket — §1.0 | `제안`⚠️ |
| 인증 | username/password + ACL (§1.2) | `미정`⚠️ |
| Clean Session | **true** (셋 다) | `제안`⚠️ |
| Keep Alive | 15초 | `제안`⚠️ |

### 1.0 리스너가 2개인 이유 — 키오스크는 브라우저입니다 🔴

**브라우저는 raw TCP 소켓을 열 수 없습니다.** 키오스크(`apps/kiosk`, React)는 1883 에 직접 붙지 못하므로 **MQTT over WebSocket** 으로 받아야 합니다. 프로토콜은 동일하고 전송 계층만 다르므로 §2~§5 계약은 그대로 적용됩니다.

```conf
listener 1883
protocol mqtt                  # Jetson, orchestrator

listener 9001
protocol websockets            # 키오스크 (브라우저)
```

같은 브로커라 Jetson 이 1883 에 발행한 메시지가 키오스크에 9001 로 그대로 전달됩니다. retained·LWT·QoS·ACL 전부 동일하게 동작합니다.

```ts
// 키오스크
const client = mqtt.connect(`ws://floaq.local:9001`, { clientId: `kiosk-${shipId}` });
```

**확인할 것 2가지.**

1. **mosquitto 빌드에 websockets 가 들어있어야 합니다.** 모든 바이너리에 있는 게 아닙니다. `ldd $(which mosquitto) | grep -i websockets` 로 확인하고, 없으면 로그에 `Websockets support not available` 이 찍히며 리스너가 안 열립니다. 그 경우 EC2 에서 쓰는 `eclipse-mosquitto:2` 도커 이미지를 Pi 에도 그대로 쓰면 됩니다.
2. **`listener` 를 하나라도 명시하면 기본 리스너가 꺼집니다.** 1883 도 위처럼 같이 적어야 합니다.

> ⚠️ **인증을 켜면 자격증명이 키오스크 JS 번들에 노출됩니다.** 키오스크는 로그인이 없는 단말이라(권한 매트릭스) 숨길 곳이 없습니다. §1 의 인증 항목이 `미정`⚠️ 인 실질적인 이유가 이것이고, 선택지는 세 가지입니다 (§7-6).
>
> | 안 | 내용 |
> | --- | --- |
> | 익명 허용 | 폐쇄망 전제. 가장 간단하지만 같은 Wi-Fi 에 붙은 누구나 발행 가능 |
> | 키오스크 전용 계정 | 번들에 노출되나 ACL 로 `kiosk/#` write 만 허용 → 피해 범위 제한 |
> | 클라이언트 인증서 | 가장 안전하나 키오스크 배포·갱신 부담 |

### 1.1 클라이언트 3개

| 역할 | clientId | 전송 | 하는 일 |
| --- | --- | --- | --- |
| **Pi** | `pi-{ship_id}` | localhost:1883 | 브로커 겸 클라이언트. 사고 판정·투하·부표추적·신고·DB |
| **Jetson** | `jetson-{ship_id}` | TCP:1883 | AI 추론 결과·조준 해·스틸컷 발행 |
| **키오스크** | `kiosk-{ship_id}` | **WS:9001** | 화면 표시 + 사람의 명령 발행 + 선박 GPS 발행 |

**브로커를 Pi에 두는 이유.** 키오스크가 죽어도 Pi는 탐지·투하·부표추적을 계속해야 합니다. 브로커를 키오스크에 두면 키오스크가 꺼질 때 **Jetson↔Pi 통신까지 같이 끊깁니다.** 조타실 키오스크는 사람이 만지는 물건이라 더 잘 죽습니다.

**Clean Session을 true로 두는 이유.** 재접속했을 때 필요한 건 "끊긴 동안 쌓인 IMU 300개"가 아니라 **"지금 사고가 어떤 상태인가"** 입니다. 그건 세션 큐가 아니라 **retained 메시지**로 받습니다 (§2.1).

### 1.2 3자 통신에서 가장 중요한 것 — 토픽에 발행자를 넣습니다 🔴

2자였을 때는 "발행/구독" 열로 버틸 수 있었지만, **3자가 되면 토픽만 보고 누가 보낸 건지 알 수 없으면 반드시 사고납니다.** 그래서 토픽 두 번째 세그먼트에 발행자를 박습니다.

```
ship/{ship_id}/{발행자}/{주제}
                 ↑
          pi | jetson | kiosk   ← 이 세그먼트에 쓸 수 있는 건 자기 자신뿐
```

얻는 것 세 가지:

**1. 구독이 한 줄로 끝납니다.**

```
키오스크 :  ship/{id}/pi/#      +  ship/{id}/jetson/#
Pi      :  ship/{id}/kiosk/#   +  ship/{id}/jetson/#
Jetson  :  ship/{id}/pi/accident/state   +  ship/{id}/kiosk/sensor/gps
```

**2. mosquitto ACL로 그대로 표현됩니다.** 각 클라이언트가 자기 prefix 밖으로 쓰는 걸 브로커가 막습니다. 키오스크 코드 버그가 Pi 인 척 상태를 발행하는 사고를 원천 차단합니다.

```
user kiosk-{ship_id}
topic write ship/{ship_id}/kiosk/#
topic read  ship/{ship_id}/pi/#
topic read  ship/{ship_id}/jetson/#
```

**3. 로그를 보면 바로 압니다.** `ship/X/jetson/snapshot` 이 왔으면 Jetson 이 보낸 겁니다. 추적할 필요가 없습니다.

### 1.3 중계하지 마세요

MQTT 를 쓰는 이유가 이겁니다. **Jetson 이 스틸컷을 한 번 발행하면 Pi(저장)와 키오스크(표시)가 동시에 받습니다.**

```
                 ┌─▶ Pi        pi_accident_file 에 저장 + R2 업로드
Jetson ──발행──┤
                 └─▶ 키오스크   S-02 경보 화면에 표시
```

Pi 가 받아서 키오스크로 다시 보내는 구조로 만들면 지연이 두 배가 되고, 중계 코드와 그 코드의 버그가 생깁니다. **같은 브로커에 붙어 있으니 양쪽이 그냥 구독하면 됩니다.**

### 1.4 LWT (Last Will) `제안`⚠️

**Pi 와 키오스크 둘 다** LWT 를 등록합니다. Jetson 은 `jetson/status` 주기 발행으로 대체합니다.

```
Pi        topic: ship/{ship_id}/pi/online       payload: {"online": false, "ts": 0}
키오스크   topic: ship/{ship_id}/kiosk/online    payload: {"online": false, "ts": 0}
          QoS 1, retain true
```

접속 직후 각자 같은 토픽에 `{"online": true, "ts": <현재>}` 를 retain 으로 덮어씁니다.

**키오스크 LWT 가 필요한 이유.** Pi 는 "경보를 띄울 화면이 살아있는지" 알아야 합니다. 키오스크가 죽은 채로 사고가 나면 **아무도 30초 카운트다운을 못 봅니다** — 그때 Pi 는 자동 신고로 직행해야 하고, 그 판단에 이 값이 필요합니다.

> 🔴 **LWT 는 즉시 오지 않습니다.** 브로커는 Keep Alive 의 1.5배가 지나야 유언을 발행합니다 — 15초 설정이면 **약 22.5초**입니다. 30초 카운트다운과 같은 스케일이라 실전에서 겹칩니다.
>
> ```
> 키오스크 사망 -> 5초 뒤 사고 발생 -> Pi 는 online=true 로 보고 30초 대기
>                                  -> 17초 뒤에야 LWT 도착. 아무도 화면을 못 본 채 30초가 감
> ```
>
> 그래서 **사고 발생 시점의 값만 보면 안 됩니다.** 카운트다운이 도는 중에 `kiosk/online: false` 가 오면 그 시점에 즉시 신고로 당기세요. `제안`⚠️ — 오탐이었을 때 취소 기회가 사라지므로 팀 승인이 필요합니다 (§7).

> LWT 페이로드는 접속 시점에 고정되므로 `ts` 에 의미 있는 값을 넣을 수 없습니다. `0` 으로 두고 `online` 만 보세요.

---

## 2. 토픽 목록

`{ship_id}` 는 UUID v7 (부록 C 선박 등록에서 발급). 토픽 접두사는 전부 `ship/{ship_id}/` 라서 아래 표에서는 생략했습니다.

### Jetson 이 발행 → Pi · 키오스크가 구독

| 토픽 | Pi | 키오스크 | QoS | retain | 주기 |
| --- | --- | --- | --- | --- | --- |
| `jetson/detection` | ✅ | ✅ | 1 | ❌ | 이벤트 |
| `jetson/snapshot` | ✅ | ✅ | 1 | ✅ | 이벤트 (1회) |
| `jetson/status` | ✅ | ✅ | 1 | ✅ | 5초 |

### Pi 가 발행 → 키오스크 · (일부) Jetson 이 구독

| 토픽 | 키오스크 | Jetson | QoS | retain | 주기 |
| --- | --- | --- | --- | --- | --- |
| `pi/accident/state` | ✅ | ✅ | 1 | ✅ | 이벤트 |
| `pi/launch/result` | ✅ | — | 1 | ✅ | 이벤트 (1회) |
| `pi/buoy/position` | ✅ | — | 0 | ❌ | **1초** ⚠️ |
| `pi/buoy/drift` | ✅ | — | 1 | ✅ | 두절 판정 직후 + **10초** `제안`⚠️ |
| `pi/report/status` | ✅ | — | 1 | ✅ | 채널별 상태 변화 |
| `pi/sensor/imu` | ✅ | — | 0 | ❌ | `미정`⚠️ |
| `pi/device/status` | ✅ | — | 1 | ✅ | 5초 + 변화 시 |
| `pi/command/response` | ✅ | — | 1 | ❌ | 명령마다 1회 |
| `pi/online` | ✅ | ✅ | 1 | ✅ | 접속·두절 (LWT) |

### 키오스크가 발행 → Pi · (일부) Jetson 이 구독

| 토픽 | Pi | Jetson | QoS | retain | 주기 |
| --- | --- | --- | --- | --- | --- |
| `kiosk/command/cancel` | ✅ | — | 1 | ❌ | 이벤트 |
| `kiosk/command/report_now` | ✅ | — | 1 | ❌ | 이벤트 |
| `kiosk/command/report_manual` | ✅ | — | 1 | ❌ | 이벤트 |
| `kiosk/command/rescue` | ✅ | — | 1 | ❌ | 이벤트 |
| `kiosk/command/close` | ✅ | — | 1 | ❌ | 이벤트 |
| `kiosk/sensor/gps` | ✅ | **✅** | 0 | ✅ | 1초 `제안`⚠️ |
| `kiosk/online` | ✅ | — | 1 | ✅ | 접속·두절 (LWT) |

### MQTT 를 안 쓰는 구간

| 구간 | 방식 | 이유 |
| --- | --- | --- |
| Jetson → Pi (사고 전후 125장) | **HTTP PUT** (§5.13) | 25MB. 브로커에 통과시키면 경보 메시지가 뒤로 밀림 |
| Pi → EC2 | **HTTPS REST + 폴링** | 인터넷 없이도 선박 기능이 돌아야 하고, 재전송 큐가 이미 Pi 에 있음 (§0.3) |
| Pi → AIS 수신처 | **UDP** | 신고 (§5.11) |
| Pi ↔ 구조 부표 | **LoRa** | 20바이트 바이너리 패킷 |

### 기획서 §7.2 에서 바뀐 것

| 변경 | 이유 |
| --- | --- |
| **토픽에 발행자 세그먼트 추가** | 3자 통신이라 필수. §1.2 |
| `accident/detected` → **`jetson/detection`** | 탐지는 Jetson 이 발행합니다. Pi 는 그걸 받아 사고를 *판정*하고 `pi/accident/state` 로 알립니다 — 발행 주체가 다르니 토픽도 다릅니다 |
| `command/delete` → **`command/cancel`** | 상태값이 `CANCEL` 인데 토픽만 `delete` 라 혼동. DB·UI·토픽 전부 CANCEL 로 통일 |
| **`command/report_manual` 추가** | §3.3 수동 긴급 신고를 보낼 토픽이 §7.2 에 **없었음**. 사고 유형을 실어야 하므로 `report_now` 로 대체 불가 |
| **`pi/online` · `kiosk/online` 추가** | LWT 전용. `device/status` 를 LWT 로 쓰면 정적 페이로드라 나머지 필드가 전부 거짓말이 됨 |
| **`report/status` 추가** | 신고가 실제로 나갔는지 알릴 토픽이 §7.2 에 **없었음**. S-03 "신고 상태", S-05 "신고 기록 — 채널별 전송 시각·횟수" |
| **`command/response` 추가** | 공통 Response Envelope(`is_success`/`error`)을 실을 토픽 (§3.1) |
| **`jetson/status` 추가** | AI-06 카메라 이물질, 추론 FPS, 모델 버전. APP-15 장비 상태에 AI 칸이 있는데 채울 소스가 없었음 |
| **`jetson/detection` 에 `launch` 추가** | **조준 해는 Jetson 이 낸다** `확정` (2026-09-11). 기획서 AI-04 담당과 일치. 이전 초안은 Pi 가 투하 계산을 하는 것으로 적혀 있었으나 [DES-38 §5](IoT_REVIEW_DES-38_각도제어구조.md) 와 충돌했음 |
| **신고 발신 주체 = Pi** | `확정` (2026-09-11). 기획서가 **스스로 갈라져 있었음** — §3.2⑥·§7.1 은 `[Backend]`, §4.2 IOT-11/12/13 은 IoT. Pi 가 보내야 인터넷 두절을 Pi 가 직접 알고 `pi/report/status.fail_reason: 'NO_INTERNET'` 을 띄울 수 있음 (§5.10). **기획서 §3.2⑥·§7.1 수정 필요** |

### 🔴 `kiosk/sensor/gps` — Jetson 도 구독해야 합니다

기획서 §2.2 가 **"선박 GPS = 키오스크 GPS 사용"** 으로 확정이라, 선박 위치·방위의 원본은 키오스크입니다. 그런데 §3.2 ③ 추락 위치 계산(스테레오 거리 + **선박 GPS** + **선박 방위**)은 Jetson 이 합니다.

**즉 키오스크 → Jetson 경로가 반드시 있어야 합니다.** 3자 MQTT 라서 중계 없이 Jetson 이 직접 구독하면 끝입니다 (§1.3). 이 토픽이 끊기면 AI 가 좌표를 못 냅니다.

> ⚠️ 제가 앞서 토폴로지 그림에 GPS 를 Pi 쪽에 그렸는데 그건 실수입니다. 기획서 §2.2 가 `확정` 이므로 **GPS 는 키오스크**입니다. Pi 에 별도 GPS 모듈을 달 계획이면 알려주세요 — 그러면 이 토픽이 `pi/sensor/gps` 로 바뀌고 키오스크는 발행에서 빠집니다.

### 2.1 retain 규칙 — 명령에는 절대 걸지 마세요 🔴

`kiosk/command/*` 에 `retain: true` 를 걸면 **Pi가 재접속할 때마다 브로커가 그 명령을 다시 배달합니다.** 30분 전에 누른 [즉시 신고]가 재부팅 때 되살아납니다. 반드시 `retain: false`.

retain 을 거는 건 **"지금 상태가 무엇인가"** 를 나타내는 것들입니다.

| retain ✅ | 이유 |
| --- | --- |
| `pi/accident/state` | 진행 중 사고와 그 상태. **재접속 복구의 기준점** |
| `pi/device/status` | 장비 상태 (APP-15) |
| `pi/online` | Pi 생존 여부 (LWT) |
| `kiosk/sensor/gps` | 마지막 선박 위치 |
| `jetson/snapshot` | 사고당 1회 이벤트라 다시 안 옴 (§2.2) |
| `pi/launch/result` | 사고당 1회 이벤트라 다시 안 옴 (§2.2) |
| `pi/report/status` | 채널별 신고 진행 상황 |
| `pi/buoy/drift` | 두절 중 **현재 수색 범위**. 재접속하면 바로 원을 그려야 함 (§5.14) |

| retain ❌ | 이유 |
| --- | --- |
| `kiosk/command/*` | **재접속 때 옛 명령이 되살아남** |
| `jetson/detection` | `pi/accident/state` 가 같은 정보를 retained 로 갖고 있음 |
| `pi/buoy/position`, `pi/sensor/imu` | 1초마다 다음 값이 옴 |

### 2.2 🔴 `snapshot` · `pi/launch/result` 에 retain 을 걸어야 합니다

**기획서 §7.2 대로 이 둘을 retain 없이 두면 키오스크가 재접속했을 때 복구가 안 됩니다.** 사고당 1회만 발행되는 이벤트라 다시 오지 않기 때문입니다.

| 놓치는 것 | 결과 |
| --- | --- |
| `jetson/snapshot` | S-02 사고 경보 화면의 **감지 스틸컷이 빈칸**. §11 우선순위 3위가 "없으면 대기·삭제 판단 불가"라고 명시한 그 화면입니다 |
| `pi/launch/result` | **E5 발사 실패 알림을 놓칩니다.** 부표가 안 나갔는데 키오스크는 모릅니다 |

키오스크는 조타실에서 사람이 만지는 기기라 재시작·화면잠금·Wi-Fi 재연결이 실제로 자주 일어납니다. 하필 탐지 순간에 끊겨 있으면 그 사고 내내 스냅샷을 못 봅니다.

#### 사고가 끝나면 retained 를 비우세요

retain 을 걸면 사고 종료 후에도 옛 스냅샷이 브로커에 남습니다. 재접속한 키오스크가 이미 끝난 사고의 스틸컷을 받게 됩니다.

MQTT 표준 방식은 **같은 토픽에 0바이트 페이로드를 retain 으로 발행**하는 것입니다. 그러면 retained 메시지가 삭제됩니다.

**🔴 지우는 주체는 발행자입니다.** §1.2 ACL 이 각 클라이언트를 자기 prefix 안에 가두므로 **Pi 는 `jetson/snapshot` 을 지울 수 없습니다.** 브로커가 막습니다.

```
사고가 CLOSE / CANCEL 되면

  Pi 가 빈 페이로드를 retain 발행:
    ship/{ship_id}/pi/launch/result
    ship/{ship_id}/pi/report/status      (채널당 1개씩)
    ship/{ship_id}/pi/buoy/drift         (LoRa 복구 시에도 지움)
    ship/{ship_id}/pi/accident/state     <- 반드시 맨 마지막

  Jetson 이 pi/accident/state 에서 CLOSE / CANCEL 을 보고 자기 것을 지움:
    ship/{ship_id}/jetson/snapshot
```

Jetson 은 이미 `pi/accident/state` 를 구독하고 있으므로(§2.4) 추가 배관이 없습니다. 자기 토픽이라 ACL 도 자연스럽습니다.

**`pi/accident/state` 를 맨 마지막에 지우는 이유.** 먼저 지우면 그 틈에 재접속한 키오스크가 "진행 중 사고 없음"으로 보면서 아직 안 지워진 `launch/result` 를 함께 받습니다. 대조할 기준이 사라진 상태예요.

수신 측 방어책도 같이 두세요.

- **retained 로 받은 `accident_id` 가 `pi/accident/state` 의 것과 다르면 버립니다.**
- **`pi/accident/state` 자체가 없으면 사고에 딸린 retained 를 전부 버립니다.** Jetson 이 죽어 있으면 스냅샷이 안 지워진 채 남기 때문입니다.

`pi/accident/state` 가 현재 사고의 유일한 진실입니다.

### 2.3 QoS 0 을 쓰는 곳

`pi/buoy/position`, `pi/sensor/imu`, `kiosk/sensor/gps` 는 QoS 0 입니다. 1초 주기로 계속 오는 값이라 한 개 유실돼도 다음 게 옵니다. QoS 1로 하면 재전송 큐가 쌓여서 오히려 최신값이 늦게 도착합니다.

대신 `pi/buoy/position` 에는 **`seq`** 를 넣어 유실을 감지합니다 (§7.3 LoRa 패킷과 동일 값).

> ⚠️ **`seq` 의 비트 폭과 롤오버 규칙이 없습니다.** LoRa 패킷이 20바이트라 큰 폭을 주기 어려운데, 8비트면 1초 주기에서 **256초(4분 16초)마다 감깁니다.** 사고가 4분을 넘기면 반드시 발생합니다. 폭을 정하고, 수신 측은 `(seq - prev) mod 2^N` 으로 증가분을 계산하세요. `미정`⚠️ (§7)

### 2.4 재접속 복구 절차 `제안`⚠️

Clean Session 이라 끊긴 동안의 메시지는 안 옵니다. 대신 **접속하면 retained 가 즉시 밀려들어옵니다.** 도착 순서는 보장되지 않으니 아래처럼 처리하세요.

#### 키오스크가 재접속했을 때

```
1. ship/{id}/pi/#  +  ship/{id}/jetson/#  구독
2. retained 가 한꺼번에 도착 (순서 무보장)
3. 전부 모은 뒤 아래 순서로 판단:

   pi/online          online=false  →  "Pi 연결 끊김" 표시하고 여기서 멈춤
   pi/accident/state  없음          →  진행 중 사고 없음 → S-01 평상시 화면
                      있음          →  status 로 화면 결정 (아래)
   pi/device/status                 →  장비 상태 표시 (APP-15)
   jetson/status                    →  AI·카메라 상태 표시
   pi/report/status                 →  채널별 신고 진행 상황 (REPORT 인 경우)
   jetson/snapshot                  →  S-02 스틸컷 (accident_id 대조 후)
   pi/launch/result                 →  발사 성공/실패 (accident_id 대조 후)

4. 화면 결정:
   DETECT / WAIT  →  S-02 경보 (report_due_at - now 로 카운트다운 재계산)
   REPORT         →  S-03 사고 진행
   없음/CANCEL/CLOSE → S-01 평상시
```

**`pi/accident/state` 가 유일한 진실입니다.** `jetson/snapshot` 과 `pi/launch/result` 는 retained 라서 **이미 끝난 사고의 것이 남아 있을 수 있습니다.** 반드시 `accident_id` 를 대조해서 다르면 버리세요 (§2.2).

**`report_due_at` 으로 카운트다운을 다시 계산하는 게 이 절차의 핵심입니다.** 자체 타이머를 돌리고 있었다면 재접속 시점에 남은 시간을 알 방법이 없습니다.

#### Pi 가 재접속했을 때 (재부팅)

```
1. ship/{id}/kiosk/#  +  ship/{id}/jetson/#  구독
2. kiosk/sensor/gps (retained)  →  마지막 선박 위치 확보
3. kiosk/online                 →  경보를 띄울 화면이 살아있는지 (§1.4)
4. 진행 중 사고는 MQTT 가 아니라 로컬 SQLite 에서 복구:
     SELECT * FROM pi_accident WHERE status IN ('DETECT','WAIT','REPORT')
   → WAIT 인데 report_due_at 이 이미 지났으면 즉시 신고로 전이
5. 복구한 상태를 pi/accident/state 로 retain 재발행
```

**Pi 의 상태 원본은 브로커가 아니라 자기 DB 입니다.** retained 메시지는 브로커(=Pi 자신)에 있으니 재부팅하면 mosquitto 설정에 따라 날아갈 수 있습니다 — `persistence true` 를 켜두더라도 **DB 를 진실로 삼고 retained 를 다시 발행하는 쪽**이 맞습니다.

> ⚠️ 4번에서 "이미 지난 `report_due_at`" 을 어떻게 처리할지 정해야 합니다. 재부팅에 40초가 걸렸다면 카운트다운이 만료된 상태로 깨어납니다. **즉시 신고** 가 안전한 기본값으로 보이지만, 오탐이었다면 취소 기회가 사라집니다. `미정`⚠️

#### Jetson 이 재접속했을 때

```
1. ship/{id}/pi/accident/state  +  ship/{id}/kiosk/sensor/gps  구독
2. 진행 중 사고가 있으면 새 탐지 발행을 억제 (AI-05)
3. GPS 가 안 오면 jetson/status.gps_received = false 로 알림
```

---

## 3. 공통 Envelope

모든 페이로드는 **봉투로 감싸고, 실제 내용은 `data` 에 넣습니다.** §5 의 인터페이스들이 `data` 의 원소 타입 `T` 입니다. 봉투는 두 가지이고, 다른 점은 **`data` 가 배열이냐 단건이냐**와 `is_success`/`error` 유무뿐입니다.

```ts
/** 단방향 — 텔레메트리·이벤트·명령. 응답이 오는지는 봉투가 아니라 토픽이 정한다 */
interface Envelope<T> {
  request_id: string;  // UUID v7. 로그 상관 + 명령일 때는 응답 상관에도 쓴다
  v:          1;       // 페이로드 스키마 버전 (§0.2)  [제안]
  ts:         Unix;    // 발행 시각                    [제안]
  data:       T[];     // 항상 배열. 단건도 길이 1 (§3.2)
}

/** kiosk/command/* 의 응답 전용 */
interface CommandAck<T> {
  request_id: string;            // 요청의 request_id 를 그대로 반사
  v:          1;
  ts:         Unix;
  is_success: boolean;
  error:      ErrorInfo | null;
  data:       T;                 // 언제나 1건. 배열이 아니다
}

interface ErrorInfo {
  code:    ErrorCode;  // string 아님 — 키오스크가 화면 분기에 쓴다
  message: string;     // 로그용. 영어라 화면에 그대로 띄우지 말 것
}

type ErrorCode =
  | 'INVALID_STATE'        // 그 상태에서 쓸 수 없는 명령 (§5.9)
  | 'ACCIDENT_NOT_FOUND'   // accident_id 가 없음
  | 'ACCIDENT_IN_PROGRESS' // report_manual 인데 진행 중 사고가 이미 있음 (E1)
  | 'DEVICE_ERROR';        // 장비 문제로 처리 불가
```

**이름을 `Request`/`Response` 로 두지 않은 이유.** 둘은 짝이 아닙니다. 트래픽의 대부분이 단방향이고 대응하는 응답이 영영 오지 않는데, `Request<SensorImu>` 처럼 1초마다 나가는 텔레메트리가 "요청"으로 읽힙니다. 실제 요청-응답 쌍은 `kiosk/command/*` 하나뿐입니다.

> `request_id` 는 단방향에도 그대로 둡니다. 응답 유무와 무관한 **추적 ID 관례**이고(이 프로젝트 nginx 도 `X-Request-Id` 를 응답에 붙입니다), 지금 단방향인 토픽이 나중에 응답을 갖게 돼도 이름을 안 바꿔도 됩니다.

> `CommandAck.data` 만 단건인 이유: 명령 응답은 언제나 1건입니다. 배열로 두면 모든 호출부가 `data[0]` 을 쓰는데, TS strict 에서 그 값이 `T | undefined` 가 되어 **절대 일어나지 않는 케이스에 매번 null 체크**를 하게 됩니다.

### 3.1 어느 토픽이 어느 것을 쓰나

| 방향 | Envelope | 토픽 |
| --- | --- | --- |
| Pi → 키오스크 (텔레메트리·이벤트) | `Envelope<T>` | `pi/accident/state`, `pi/launch/result`, `pi/buoy/position`, `pi/sensor/imu`, `pi/report/status`, `pi/device/status`, `pi/online` |
| 키오스크 → Pi (센서) | `Envelope<T>` | `kiosk/sensor/gps` |
| 키오스크 → Pi (명령) | `Envelope<T>` | `kiosk/command/*` |
| Pi → 키오스크 (명령 결과) | **`CommandAck<T>`** | `pi/command/response` |

**응답은 명령에만 있습니다.** 텔레메트리에 `is_success` 를 붙이면 채울 값이 없습니다.

### 3.2 `data` 를 항상 배열로 두면 좋은 점

**§5.5 의 "부표 1초 vs 10초" 문제가 인터페이스 변경 없이 풀립니다.** 10초로 묶기로 하면 `data` 에 원소 10개를 넣으면 끝입니다. 단건이면 길이 1.

```json
{ "request_id": "0192...", "v": 1, "ts": 1757000010,
  "data": [ { "buoy_log_id": 1, "seq": 1, "lat": 35.1, "lon": 129.0, ... } ] }
```

### 3.3 `request_id` 가 하는 일 두 가지

**1. 중복 제거.** QoS 1 은 *at-least-once* 라서 **같은 메시지가 두 번 옵니다.** 명령이 중복되면 신고가 두 번 나가고 사고가 두 개 생깁니다. 수신 측은 최근 `request_id` 100개를 기억했다가 중복이면 버리세요.

> **dedup 은 `kiosk/command/*` 에만 적용합니다.** `pi/buoy/position`·`pi/sensor/imu`·`kiosk/sensor/gps` 는 QoS 0 이라 애초에 중복이 생기지 않습니다. 1초 주기로 UUID v7 을 만들고 100개 테이블을 돌리는 건 순수 낭비입니다. `jetson/detection` 은 `detection_id` 로 따로 막습니다 (§5.1).

**2. 응답 상관관계.** `pi/command/response` 의 `request_id` 로 "내가 보낸 그 명령의 결과"를 찾습니다.

### 3.4 `ts` 와 측정 시각은 다릅니다

`ts` 는 "발행한 순간", `data` 원소 안의 `measured_at`/`captured_at`/`detected_at` 은 "그 값이 실제로 측정된 순간"입니다. LoRa 지연이나 큐 대기 때문에 둘은 몇 초씩 벌어집니다. **지도에 찍을 때는 측정 시각을 쓰세요.**

### 3.5 확정 사항 `확정`

| # | 항목 | 결정 |
| --- | --- | --- |
| 1 | 상태 필드명 | **`is_success`** (오타 `is_sucess` 정정). 성공 여부 |
| 2 | 네이밍 | **전부 snake_case.** Envelope·`data` 원소 전부 |
| 3 | MQTT 버전 | `request_id` 를 **페이로드에 넣는 방식** 으로 고정. 3.1.1·5 양쪽에서 동작 |

**snake_case 로 통일한 결과 — 변환 계층이 사라집니다.**

```
MQTT 필드 :  accident_id, ship_id, accident_type, report_due_at, is_pressed
DB 컬럼   :  accident_id, ship_id, accident_type, report_due_at, is_pressed
              ↑ 완전히 동일. 매핑 함수 불필요
```

기획서 §6.4 가 요구한 *"변환 함수 한 곳에 모을 것"* 은 **변환 자체를 없앴으니 해결된 것으로 봅니다.** unixtime ↔ `timestamptz` 변환은 서버 동기화 지점에 여전히 필요합니다.

> `clientId` 만 예외입니다 (§1). 이건 우리 필드가 아니라 MQTT 프로토콜의 연결 파라미터 이름입니다.

---

## 4. 공통 enum

```ts
type AccidentStatus = 'DETECT' | 'WAIT' | 'REPORT' | 'CANCEL' | 'CLOSE';
type ReportType     = 'DISTRESS' | 'URGENCY';   // SAFETY 제거 `확정` 2026-09-17
type TriggerSource  = 'AI' | 'MANUAL';
type ImuPosition    = 'HULL' | 'CAMERA_L' | 'CAMERA_R';
type DeviceHealth   = 'OK' | 'ERROR' | 'UNKNOWN';

/** 8종 `확정` 2026-09-17. EC2 `api.json` 의 IPiAccident 와 글자까지 같다. DSC 코드는 §4.1 대응표 참고 */
type AccidentType =
  | 'MOB'              // 인명 추락        DISTRESS  dsc 110 → AIS-MOB
  | 'FIRE'             // 선박 화재        DISTRESS  dsc 100
  | 'FLOODING'         // 침수/전복 위험    DISTRESS  dsc 101 | 104 (IMU 자동 결정)
  | 'COLLISION'        // 충돌            DISTRESS  dsc 102
  | 'GROUNDING'        // 좌초            DISTRESS  dsc 103
  | 'ENGINE_FAILURE'   // 기관 고장        DISTRESS  dsc 106
  | 'OTHER_DISTRESS'   // 기타 조난        DISTRESS  dsc 107
  | 'MEDICAL';         // 응급 환자        URGENCY   dsc 없음
```

기획서 "사고 유형" 표에서 **`HAZARD`(위험물 발견)·`ABANDON_SHIP`(퇴함) 두 개를 뺐습니다** `확정` 2026-09-17. `SAFETY` 등급을 없애면서 `HAZARD` 는 갈 곳이 없어졌고, `ABANDON_SHIP` 은 1차 범위에서 제외했습니다.

> `ABANDON_SHIP` 을 되살릴 때는 **`DISTRESS` + dsc `108`** 입니다. 구 설계는 `SAFETY` 로 잡고 있었는데 그건 오류입니다 — DSC 의 **category** `108`(safety)과 **nature of distress** `108`(abandoning ship)은 다른 표이고, 퇴선은 조난입니다.

> ⚠️ **기획서 안에서 모순이 있었습니다.** §3.3② 와 S-07 화면은 수동 신고 선택지를 **5개**(기관고장/좌초/충돌/침수/기타)라고 하는데, "사고 유형" 표에는 **10개**가 있었습니다. `확정` 2026-09-17 — **8개**로 줄여 EC2 `api.json` 과 맞췄습니다. 여전히 5개는 아니므로 **S-07 레이아웃은 8개 기준으로 잡아야 합니다** — 5개로 두면 `MOB`·`FIRE`·`MEDICAL` 을 수동으로 아예 못 보냅니다.

### 4.1 accident_type → report_type / dsc 대응

이 매핑은 **Pi와 Backend 양쪽에 중복 구현하지 말고 한 곳(상수 파일)에** 두세요 (기획서 §8 지침).

`FLOODING`만 IMU 기울기로 `101`(침수) / `104`(전복 위험)이 갈립니다. 나머지는 고정입니다.

---

## 5. 페이로드

### 5.1 `jetson/detection` — 사람 탐지 (Jetson → Pi · 키오스크)

**Jetson 은 "사람을 봤고, 쏜다면 이 각도다"까지 말합니다. "사고다"라고 판정하는 건 Pi 입니다.** `확정` (2026-09-11)

**조준 해(`launch`)는 Jetson 이 냅니다.** 스테레오 거리(AI-03)·선박 GPS·침로가 전부 Jetson 에 모여 있고(§2 🔴), Pi 로 원시값을 넘겨 다시 계산하면 왕복 지연만 늘어납니다. 기획서 AI-04 담당과도 일치합니다.

그래도 이 페이로드에 `accident_id` 는 없습니다. Jetson 은 사고 번호를 모릅니다 — Pi 가 이 메시지를 받아 AI-05(중복 사고 방지)를 통과시킨 뒤 `accident_id` 를 발급하고 `pi/accident/state` 로 알립니다. **각도를 보냈다고 발사가 확정되는 것도 아닙니다. Pi 가 거부하면 그대로 버려집니다(아래 거부 조건).**

```ts
interface JetsonDetection {
  detection_id:  Uuid;    // UUID v7. Jetson 이 발급. 중복 수신 판정용
  ship_id:       Uuid;

  lat:           number;  // -90 ~ 90.   추락 추정 위치
  lon:           number;  // -180 ~ 180
  distance_m:    number;  // 스테레오 거리 (AI-03)

  confidence:    number;  // 0 ~ 1
  frame_count:   Int;     // 연속 탐지 프레임 수 (AI-02 근거)
  model_version: string;  // 오탐 분석용
  camera:        'L' | 'R';
  bbox:          [Int, Int, Int, Int] | null;  // x, y, w, h
  detected_at:   Unix;    // 프레임이 찍힌 시각

  /** 조준 해. 낼 수 없으면 null — 탐지는 유효하지만 발사 불가 (GPS 미수신 등) */
  launch:        LaunchSolution | null;
}

interface LaunchSolution {
  target_yaw_deg:   Deg;     // 선수 기준. 명목 -45 ~ +45 (DES-38 §1). 보정 범위 밖이면 Pi 가 거부
  target_pitch_deg: Deg;     // 수평 기준. 명목 0 ~ 45 (DES-38 §1). 보정 범위 밖이면 Pi 가 거부
  launch_profile:   string;  // 등록된 프로파일만. 미등록이면 Pi 가 거부
  target_lat:       number;  // -90 ~ 90.   계산된 착수 목표 위치
  target_lon:       number;  // -180 ~ 180
  solved_at:        Unix;    // 해를 계산한 시각. 만료 판정 기준 (아래 거부 조건)
}
```

> `launch` 를 별도 토픽으로 빼지 않은 이유: MQTT 는 **토픽이 다르면 도착 순서를 보장하지 않습니다.** 분리하면 조준 해가 탐지보다 먼저 도착하는 경우를 Pi 가 버퍼링해서 맞춰야 하고, 그 상태 관리가 통째로 생깁니다. 한 메시지에 담으면 그 문제가 사라집니다. 실제로 새로 늘어나는 필드도 조준 3개 + 목표 좌표 2개뿐이고(`confidence` 는 이미 있음), 조준 해는 언제나 탐지에 동반되지 독립 이벤트가 아닙니다. 키오스크는 이 블록을 안 써도 되지만 4KB 상한 안이라 무해합니다.

`distance_m` 과 `bbox` 는 Pi 가 저장하지 않아도 **키오스크가 화면에 근거를 보여주는 데** 씁니다 (S-02 감지 정보). 오탐 분석에도 필요하니 `pi_accident.model_version` 옆에 컬럼을 더할지는 나중에 결정하세요.

#### Pi 가 이 메시지를 받아서 하는 일

```
1. AI-02 임계값 통과?           ← 기준 미정 ⚠ (AI팀)
2. 진행 중 사고 있음?  ─ 있으면 → 무시 (AI-05 / E1)
                       └ 없으면 → accident_id 발급 (UUID v7)
3. pi_accident INSERT   status=DETECT, trigger_source=AI, accident_type=MOB
                        report_type=DISTRESS, report_dsc=110
4. pi/accident/state 발행  status=DETECT, reason=AI_DETECT
5. launch 검증  ─ 통과 → 그 각도로 발사 → pi/launch/result (SUCCESS)
                 └ 거부 → 발사 안 함  → pi/launch/result (FAILED + fail_reason)
6. status=WAIT 로 전이 + report_due_at 설정 → pi/accident/state 재발행
```

**2번을 DB 가 한 번 더 막아줍니다** — `uq_pi_accident_active` 부분 UNIQUE 인덱스가 걸려 있어서, Pi 코드가 놓쳐도 두 번째 사고 INSERT 가 실패합니다.

#### `launch` 거부 조건 — [DES-38](IoT_REVIEW_DES-38_각도제어구조.md) §6 이 정본

**Pi 는 받은 각도를 그대로 믿지 않습니다.** 아래 중 하나라도 걸리면 발사하지 않고 `pi/launch/result` 에 `FAILED` 를 발행합니다.

| 조건 | `fail_reason` |
| --- | --- |
| `launch` 가 `null` | `NO_SOLUTION` — 탐지는 유효, 조준만 불가 |
| `target_yaw_deg`·`target_pitch_deg` 가 보정 범위 밖 | `OUT_OF_RANGE` |
| `launch_profile` 이 미등록 | `OUT_OF_RANGE` |
| `solved_at` 만료 (`제안`⚠️ 3초) | `OUT_OF_RANGE` |
| 장전 안 됨 (IOT-04 물리 스위치) | `NOT_LOADED` |
| 서보 전압 저하·과열·걸림, 잠금 핀 상태 불일치 | `DEVICE_ERROR` |
| `detection_id` 중복 | 거부가 아니라 **무시** (이미 처리한 탐지) |

**AI 가 임의의 힘 값을 모터 출력으로 직접 전달하지 않습니다.** Pi 는 실물 시험으로 승인된 `launch_profile` 만 고릅니다. 각도–거리 보정표와 안전 상태 머신(`SAFE→AIMING→ARMED→READY→RELEASED`+`FAULT`)은 DES-38 이 정본이고, MQTT 에는 **결과만** 드러납니다.

> ⚠️ `solved_at` 만료 기준 `미정`⚠️. 배가 10노트면 1초에 약 5m 이동하므로 해가 오래될수록 목표점이 그만큼 어긋납니다. 탐지→계산→발사→착수까지의 실측 지연을 잰 뒤 확정하세요 (§7).

**`report_due_at`을 반드시 쓰세요 — 키오스크가 자체 30초 타이머를 돌리면 안 됩니다.** 이유:

- 메시지가 3초 늦게 도착하면 키오스크는 33초를 셉니다. Pi는 30초에 신고를 쏩니다. **화면에 7초 남았는데 이미 신고가 나간 상태**가 됩니다.
- 카운트다운 중 키오스크가 재접속하면 남은 시간을 알 수 없습니다. `report_due_at`이 있으면 retained `pi/accident/state` 하나로 복구됩니다.

키오스크는 `report_due_at - 현재시각` 을 매 프레임 다시 계산해서 표시하세요.

> ⚠️ 키오스크와 Pi의 시계가 어긋나면 이 방식도 틀어집니다. 선박 Wi-Fi 폐쇄망이라 NTP가 없을 수 있습니다. **시각 동기화 방법 `미정`⚠️** — Pi를 NTP 서버로 쓰거나, 키오스크가 `ts`와 자기 시계 차이를 오프셋으로 보정하는 방법이 있습니다.

### 5.2 `jetson/snapshot` — 감지 스틸컷 (Jetson → Pi · 키오스크, retained)

기획서 §11 우선순위 3위. 없으면 대기·취소 판단이 불가능합니다.

```ts
interface AccidentSnapshot {
  accident_id: Uuid;
  format:      'jpeg';
  width:       Int;                          // px
  height:      Int;
  bytes:       Int;                          // base64 디코드 후 크기
  data:        string;                       // base64 (data: 접두사 없음)
  captured_at: Unix;                         // 프레임이 찍힌 시각
  confidence:  number;                       // 0 ~ 1
  bbox:        [Int, Int, Int, Int] | null;  // x, y, w, h — 화면에 박스 표시용
  camera:      'L' | 'R';
}
```

**크기 상한 `제안`⚠️ — 원본 JPEG 200KB (base64 후 약 267KB).**

- 부록 A "AI팀 7. 감지 스냅샷 해상도·용량"이 미정으로 남아 있는데, MQTT로 보내는 이상 상한을 먼저 못 박아야 합니다.
- 640×480 JPEG q80 이 대략 40~60KB 입니다. 200KB면 1280×720까지 여유가 있습니다.
- 선박 Wi-Fi 로컬 구간이라 267KB는 문제 없습니다. **`message_size_limit` 을 명시적으로 설정하세요 (`제안`⚠️ 512KB).** mosquitto 기본값은 `0` = 무제한이라, 걸려서 끊기는 게 아니라 **폭주 페이로드를 막을 게 없는** 쪽이 위험합니다. 클라이언트 라이브러리 상한도 같이 확인하세요.
- 그래도 크면 **HTTP로 빼는 게 정석**입니다 (Pi에 작은 파일 서버 + MQTT엔 URL만). 지금 규모면 base64 인라인으로 충분합니다.

### 5.3 `pi/accident/state` — 상태 변경 (Pi → 키오스크, retained)

```ts
interface AccidentState {
  accident_id: Uuid;
  status:      AccidentStatus;
  prev_status: AccidentStatus | null;  // 최초 생성이면 null
  reason:
    | 'AI_DETECT'          // → DETECT
    | 'COUNTDOWN_START'    // → WAIT
    | 'TIMEOUT'            // → REPORT (30초 만료)
    | 'TABLET_CANCEL'      // → CANCEL
    | 'TABLET_REPORT_NOW'  // → REPORT
    | 'TABLET_MANUAL'      // → REPORT (수동 신고)
    | 'TABLET_RESCUE'      // → CLOSE  (구조 확정)
    | 'TABLET_CLOSE';      // → CLOSE  (사고 종료)
  caused_by:     string | null;  // 이 변경을 유발한 command 의 request_id
  report_due_at: Unix | null;    // WAIT 일 때만 값 있음
  changed_at:    Unix;
}
```

`caused_by` 는 **감사 목적**입니다 — S-05 타임라인에서 "이 상태 변경이 어느 명령 때문이었나"를 추적합니다. `TIMEOUT`(30초 만료)이나 `AI_DETECT` 처럼 명령 없이 일어난 변경은 `null` 입니다.

> 명령 도달 확인은 이 필드가 아니라 **`pi/command/response` 가 담당합니다** (§3.1, §5.9). 공통 Response Envelope 에 `is_success`/`error` 가 있어서 거부 사유를 `error.code` 로 구분할 수 있기 때문입니다.

### 5.4 `pi/launch/result` — 투하 결과 (Pi → 키오스크, retained)

```ts
interface LaunchResult {
  accident_id: Uuid;
  detection_id: Uuid;      // 어느 탐지의 조준 해로 쐈는지 (§5.1)
  result:      'SUCCESS' | 'FAILED';
  fail_reason: 'NOT_LOADED' | 'DEVICE_ERROR' | 'OUT_OF_RANGE' | 'NO_SOLUTION' | null;

  launch_lat:       number;         // 발사 시점 선박 위치
  launch_lon:       number;
  target_lat:       number;         // Jetson 이 계산한 목표 착수 위치 (§5.1 launch)
  target_lon:       number;
  horizontal_angle: Deg;            // 실제 명령한 yaw.  소프트 리밋에 걸리면 target_yaw_deg 와 다를 수 있음
  vertical_angle:   Deg;            // 실제 명령한 pitch. 위와 같음
  confidence_score: number | null;  // 0 ~ 1
  launched_at:      Unix;
}
```

E5(발사 실패)는 **재발사 없음**이므로 `result: 'FAILED'` 는 키오스크에 알림만 띄우고 사고는 그대로 진행됩니다 (부표 없이 신고까지 감).

> `target_lat`/`target_lon`/`result`/`fail_reason` 은 **`schema.sql` 에 반영 완료**입니다 (§8, `pi_launch` 11컬럼). 위 초안의 "컬럼이 없습니다" 주석은 반영 전에 쓰인 것이라 정정했습니다.
>
> ⚠️ 다만 **`detection_id` 는 아직 없습니다.** 조준 해를 Jetson 이 내는 구조가 되면서 "어느 탐지로 쐈는지"를 남겨야 오탐 분석이 됩니다. `pi_launch` 에 컬럼 추가가 필요합니다 (§7).

### 5.5 `pi/buoy/position` — 부표 위치 (Pi → 키오스크)

```ts
interface BuoyPosition {
  accident_id: Uuid;
  buoy_log_id: Int;
  seq:         Int;            // 부표가 매긴 순번. 유실 감지용 (§7.3)
  lat:         number;
  lon:         number;         // ← lng 아님
  is_pressed:  0 | 1;          // 사람이 부표를 잡음 (APP-08)
  measured_at: Unix;           // 부표 GPS 측정 시각
  received_at: Unix;           // Pi가 LoRa로 수신한 시각
  rssi:        number | null;  // dBm. 통신 품질 확인용
}
```

> 🔴 **주기가 문서 안에서 충돌합니다.** §7.1·§8 은 **1초**, §7.2 토픽 주석은 **10초**입니다.
> LoRa 수신은 1초인데 MQTT 재발행만 10초로 묶겠다는 뜻이라면 그렇게 명시해야 하고, 그 경우 페이로드를 **배열로 10개씩** 보내는 게 맞습니다. 지금 정의는 **1초 · 1건** 기준입니다. **결정 필요.**

`is_pressed`를 `boolean`이 아니라 `0 | 1`로 둔 것은 LoRa 패킷(§7.3)과 SQLite 컬럼이 둘 다 정수라 변환 지점을 줄이기 위해서입니다.

> 이 토픽이 **끊긴 구간**은 [`pi/buoy/drift`](#514-pibuoydrift--표류-예상-범위-pi--키오스크-retained) 가 메웁니다 (§5.14).

### 5.6 `pi/sensor/imu` — IMU (Pi → 키오스크)

```ts
interface SensorImu {
  accident_id:  Uuid | null;    // 평상시는 null
  imu_position: ImuPosition;    // 어느 IMU 인지. ⚠️ 실제로는 1개만 씁니다 (아래 주석)
  accel_x:      number | null;  // m/s^2
  accel_y:      number | null;
  accel_z:      number | null;
  roll:         Deg;            // 자세. deg/s 아님
  pitch:        Deg;
  yaw:          Deg;
  heading_deg:  number | null;  // 0 ~ 360. GPS로 보정한 방위
  measured_at:  Unix;
}
```

> ⚠️ **ERD의 `roll`/`pitch`/`yaw` 주석이 `deg/s`로 되어 있는데 잘못입니다.** S-01 화면이 "자세(roll·pitch)"를 표시한다고 되어 있으니 **각도(deg)** 가 맞습니다. 자이로 원시값(deg/s)을 따로 저장할 거면 `gyro_x/Y/Z` 를 별도 필드로 추가하세요. 지금은 각도로 정의했습니다.

> **발행 주기 `미정`⚠️.** IMU를 키오스크에 1초마다 3개(HULL/CAMERA_L/CAMERA_R) 보내면 초당 3메시지입니다. S-01이 표시하는 건 자세 하나뿐이니 **선택된 IMU 1개만 1초 주기**로 보내면 충분합니다. 기획서 §2.2 "3개 중 좋은 거 하나 쓸 거임"과도 맞습니다. 나머지 2개는 링버퍼(IOT-09)에만 남기세요.

### 5.7 `kiosk/sensor/gps` — 선박 위치 (**키오스크 → Pi**, retained)

⚠️ **이 토픽만 방향이 반대입니다.** 기획서 §2.2 에서 선박 GPS를 키오스크 GPS로 쓰기로 했기 때문입니다.

```ts
interface SensorGps {
  lat:         number;
  lon:         number;
  speed_kn:    number;         // knot. ETA 계산용
  heading_deg: number;         // 0 ~ 360. 진북 기준
  accuracy_m:  number | null;  // GPS 오차 반경(m)
  measured_at: Unix;
}
```

Pi가 이걸 구독해야 §3.2 ③ **추락 위치 계산**(스테레오 거리 + 선박 GPS + 선박 방위)이 됩니다. 이 토픽이 끊기면 AI는 좌표를 못 냅니다 — `pi/device/status.gps` 에 그 상태가 드러나야 합니다.

> §9.2 4번 "선박 속도 — 임의 지정값 `미정`⚠️" 이 여기 `speed_kn` 입니다.

### 5.8 `pi/device/status` — 장비 상태 (Pi → 키오스크, retained)

```ts
interface DeviceStatus {
  is_loaded:       boolean;       // 투하 장치 장전 여부 (IOT-04 물리 스위치)
  camera_l:        DeviceHealth;
  camera_r:        DeviceHealth;
  camera_dirty:    boolean;       // AI-06 이물질 감지
  imu:             DeviceHealth;
  lora:            DeviceHealth;
  ai:              DeviceHealth;
  gps:             DeviceHealth;  // 키오스크 GPS 수신 여부 (Pi 관점)
  internet:        boolean;       // 신고 가능 여부와 직결 (§9.1)
  last_buoy_rx_at: Unix | null;   // 마지막 LoRa 수신 시각. null이면 미수신
}
```

APP-15(장비 상태 표시)와 E4(장전 안 됨 알림)가 이 하나로 해결됩니다. **변화가 있을 때 + 5초마다** 발행하세요. 변화 시에만 보내면 키오스크가 "값이 안 오는 것"과 "Pi가 죽은 것"을 구분 못 합니다.

`internet: false` 면 키오스크는 §9.1대로 **"신고 불가"를 화면에 명시**해야 합니다. 이게 없으면 사용자는 신고가 나간 줄 압니다.

### 5.9 `kiosk/command/*` — 키오스크 → Pi

```ts
interface CommandBase {
  accident_id: Uuid;
  issued_by:   'TABLET';
}

/** kiosk/command/cancel      — 자동 신고 취소 (APP-04). WAIT 상태에서만 유효 */
type CommandCancel    = CommandBase;

/** kiosk/command/report_now  — 즉시 신고 (APP-05). WAIT 상태에서만 유효 */
type CommandReportNow = CommandBase;

/** kiosk/command/rescue      — 구조 확정 (APP-10). 신고 중지 + CLOSE */
type CommandRescue    = CommandBase;

/** kiosk/command/close       — 사고 종료 (APP-11). 구조 실패 시 */
type CommandClose     = CommandBase;

/** kiosk/command/report_manual — 수동 긴급 신고 (APP-06). 사고를 새로 만든다 */
interface CommandReportManual {
  accident_id:   Uuid;          // 키오스크가 UUID v7 로 생성
  accident_type: AccidentType;
  lat:           number;        // 신고에 담길 좌표
  lon:           number;
  issued_by:     'TABLET';
}
```

**`report_manual`만 `accident_id`를 키오스크가 만듭니다.** 나머지 명령은 이미 존재하는 사고를 가리킵니다. 키오스크가 UUID v7을 생성하므로 재전송해도 같은 ID → 사고가 중복 생성되지 않습니다 (멱등).

#### 상태별 유효 명령 `제안`⚠️

Pi 는 아래 조합만 받아들이고, 나머지는 거부합니다. 각 명령이 나오는 화면과 1:1로 대응합니다.

| 명령 | 유효 상태 | 화면 · 버튼 |
| --- | --- | --- |
| `kiosk/command/cancel` | `WAIT` | S-02 `[자동 신고 취소]` (APP-04) |
| `kiosk/command/report_now` | `WAIT` | S-02 `[즉시 신고]` (APP-05) |
| `kiosk/command/rescue` | `REPORT` | S-03 `[구조 확정]` (APP-10) |
| `kiosk/command/close` | `REPORT` | S-03 `[사고 종료]` (APP-11) |
| `kiosk/command/report_manual` | **진행 중 사고 없음** | S-01 `[긴급 신고]` (APP-06) |

`DETECT` 중에는 취소·신고 버튼이 아직 안 뜹니다 (부표 투하 진행 중). `CANCEL`·`CLOSE` 는 종료 상태라 어떤 명령도 받지 않습니다.

`report_manual` 은 진행 중 사고가 있으면 거부됩니다 — **DB 의 `uq_pi_accident_active` 인덱스가 같은 규칙을 강제**하고 있어서, 앱이 놓쳐도 INSERT 가 실패합니다 (동시 사고 1건, E1).

**Pi 는 무효한 명령을 조용히 무시하지 말고 거부를 알려야 합니다.** `pi/command/response` 에 `is_success: false` 와 사유를 실어 보냅니다.

#### `pi/command/response` — 명령 결과 (Pi → 키오스크)

`CommandAck<CommandResult>` 형태입니다 (§3).

```ts
interface CommandResult {
  accident_id: Uuid;
  command:     'cancel' | 'report_now' | 'report_manual' | 'rescue' | 'close';
  status:      AccidentStatus;                                                  // 처리 후(또는 거부 시 현재) 사고 상태
}
```

```json
{ "request_id": "0192...", "v": 1, "ts": 1757000031,
  "is_success": true, "error": null,
  "data": { "accident_id": "0192...", "command": "report_now", "status": "REPORT" } }
```

거부:

```json
{ "request_id": "0192...", "v": 1, "ts": 1757000031,
  "is_success": false,
  "error": { "code": "INVALID_STATE", "message": "cancel is only valid in WAIT (current: REPORT)" },
  "data": { "accident_id": "0192...", "command": "cancel", "status": "REPORT" } }
```

`error.code` 는 §3 의 `ErrorCode` union 이 정본입니다 `제안`⚠️

| code | 뜻 |
| --- | --- |
| `INVALID_STATE` | 그 상태에서 쓸 수 없는 명령 (위 표 참고) |
| `ACCIDENT_NOT_FOUND` | `accident_id` 가 없음 |
| `ACCIDENT_IN_PROGRESS` | `report_manual` 인데 진행 중 사고가 이미 있음 (E1) |
| `DEVICE_ERROR` | 장비 문제로 처리 불가 |

> 초안은 §3 주석이 `NOT_FOUND`, 이 표가 `ACCIDENT_NOT_FOUND` 로 **이미 갈라져 있었습니다.** `string` 이라 양쪽 다 통과했고요. union 으로 바꿔 한 곳에서만 정의합니다.

**거부일 때도 `data` 에 현재 `status` 를 실어주세요.** 키오스크가 화면을 실제 상태로 되돌릴 수 있습니다 — 거부 사유만 받으면 뭘 보여줄지 모릅니다.

#### 명령 재시도 정책 `제안`⚠️

```
1. QoS 1 로 발행 (request_id = R)
2. 2초 안에 pi/command/response 에 request_id == R 이 오는지 대기
3. 안 오면 같은 request_id(R) 로 1회 재발행
4. 다시 2초 무응답이면 "명령 전달 실패" 표시하고 버튼 재활성화
```

**재시도할 때 `request_id` 를 바꾸지 마세요.** 같은 값을 쓰면 Pi 가 중복으로 판정해 실행은 건너뛰고 `pi/command/response` 만 다시 보냅니다 (§3.3). 새 `request_id` 로 보내면 Pi 가 **별개 명령으로 처리해서 신고가 두 번 나갑니다.**

응답을 기다리는 동안 버튼은 비활성화합니다. 안 그러면 사용자가 연타하고, QoS 1 중복과 겹쳐서 같은 명령이 여러 번 처리됩니다.

> `pi/command/response` 는 **retain 하지 않습니다.** 지난 명령의 결과가 재접속 때 되살아나면 키오스크가 이미 끝난 일에 반응합니다. 재접속 후의 진실은 retained `pi/accident/state` 입니다 (§2.1).

### 5.10 `pi/report/status` — 신고 상태 (Pi → 키오스크, retained)

S-03 "신고 상태", S-05·W-03 "신고 기록 — 채널별 전송 시각·횟수" 를 위한 토픽입니다.
**채널마다 1개씩** 발행합니다 (3채널이면 retained 메시지 3개).

```ts
type ReportChannel = 'AIS_MOB' | 'AIS_SART' | 'DSC';

interface ReportStatus {
  accident_id: Uuid;
  report_id:   Int;
  channel:     ReportChannel;
  status:
    | 'SENDING'    // 반복 전송 중
    | 'ACKED'      // 수신처가 ACK. DSC 에서만 발생 가능
    | 'STOPPED'    // 구조 확정 · 사고 종료로 수동 중지
    | 'FAILED';    // 전송 불가

  sent_count:    Int;   // 지금까지 보낸 횟수 (누적)
  first_sent_at: Unix;
  last_sent_at:  Unix;

  acked_at: Unix | null;    // ⚠️ DSC 만 값이 들어올 수 있음. §5.11 참고
  acked_by: string | null;  // ACK 을 보낸 국의 MMSI

  fail_reason: 'NO_INTERNET' | 'NO_RECEIVER' | 'TIMEOUT' | null;
}
```

`NO_INTERNET` 은 §9.1 의 "인터넷 두절 시 신고 불가"가 실제로 발생한 경우입니다. **키오스크는 이걸 반드시 화면에 띄워야 합니다** — 안 그러면 사용자는 신고가 나간 줄 압니다.

### 5.11 채널별 ACK 규격 🔴

> **세 채널의 ACK 동작이 서로 다릅니다.** 현재 기획서 §7.5 는 AIS-SART 규격("1분에 8회")을 세 채널에 똑같이 적용하고, 중지 조건도 "구조 확정 또는 사고 종료" 하나로 통일해 두었습니다. **DSC는 둘 다 다릅니다.**

| 채널 | 실제 규격의 ACK | 반복 주기 | 중지 조건 |
| --- | --- | --- | --- |
| **AIS-MOB** | **없음.** AIS는 단방향 브로드캐스트 | 1분에 8회 버스트 | 배터리 소진 / 수동 정지 |
| **AIS-SART** | **없음.** 동일 | 1분에 8회 버스트 | 배터리 소진 / 수동 정지 |
| **DSC** | **있음.** DSC Distress Acknowledgement | 응답 없으면 **3.5~4.5분** 간격 재송 | **ACK 수신 시 자동 중지** + 수동 정지 |

핵심은 **DSC ACK 이 단순 수신확인이 아니라 종료 신호**라는 점입니다. 받는 즉시 조난경보 재송이 멈춥니다.

**누가 ACK 을 보내는가.** GMDSS 절차상 VHF DSC 조난경보는 **해안국이 ACK** 하고, 주변 선박은 DSC 가 아니라 Ch16 음성으로 응답합니다. 선박이 DSC 로 ACK 해버리면 조난선의 재송이 멈춰서 정작 해안국이 경보를 못 받기 때문입니다.
§1.3 에서 **관제 웹이 해경 역할**을 맡기로 했으므로, **ACK 주체는 관제 웹**이 맞습니다.

#### §7.6 결정에 따라 달라지는 것

| §7.6 안 | DSC ACK | `acked_at` | 구현 |
| --- | --- | --- | --- |
| **A** 백엔드 UDP 리스너 | ✅ 가능 | 값 들어옴 | 관제 웹에서 해경이 "접수" 누르면 ACK UDP 회신 → `status: ACKED` |
| **B** 별도 노트북 수신 데모 | ✅ 가능 | 값 들어옴 | 데모 앱이 ACK 회신. 시연 임팩트는 A보다 큼 |
| **C** 수신처 없음 | ❌ 불가 | 항상 `null` | `status` 는 `SENDING` → `STOPPED` 만 |

**A안을 권합니다.** 실제 절차(해안국이 ACK)와 구조가 맞고, "왜 이렇게 했나"(§9) 질문에 답하기 좋습니다. 발표에서 **경보 → 해경 접수 → 재송 자동 중지**가 화면에 보이는 것이 시연 포인트가 됩니다.

#### ACK 패킷 `제안`⚠️

§7.4 신고 패킷의 응답입니다. 같은 UDP 소켓으로 회신합니다.

```ts
interface DscAck {
  ack_of_report_id: Int;     // 원본 report_id (MQTT 의 request_id 와 무관)
  channel:          'DSC';   // AIS 채널은 ACK 없음
  acked_by:         string;  // 해안국 MMSI
  acked_at:         Unix;
  accident_id:      Uuid;
}
```

#### 구현 시 주의

1. **중지 조건이 채널마다 다릅니다.** `AIS_MOB`/`AIS_SART` 는 수동 정지만, `DSC` 는 ACK 자동 정지 + 수동 정지. 하나의 반복 루프에서 세 채널을 돌리면 이 분기를 빠뜨리기 쉽습니다.
2. **DSC 반복 주기도 다릅니다.** 1분에 8회가 아니라 3.5~4.5분 간격입니다. 기획서 §7.5 를 실제 규격대로 갈지, 시연 편의상 1분 8회로 통일할지 **결정하고 문서에 근거를 남기세요.** §9.2 표에 한 줄 추가하면 됩니다.
3. **ACK 을 구현하면 `pi_report.acked_at` 이 필요해집니다** (기획서 §6.1 🟡 마지막 줄이 정확히 이 조건부 항목입니다). §8 참고.
4. **위 반복 주기 수치는 실제 무선 규격(ITU-R M.541) 기준입니다.** 발표에서 인용할 거면 원문 확인을 권합니다.

> 💡 이 표가 §7.5 의 **"3채널 → 1채널 축소 권고"** 를 다시 뒷받침합니다. ACK 이 있는 건 DSC 하나뿐이므로, DSC 만 남기면 반복 주기·중지 조건 분기가 통째로 사라집니다.

### 5.12 `jetson/status` — AI 상태 (Jetson → Pi · 키오스크, retained)

APP-15 장비 상태에 AI·카메라 칸이 있는데 채울 소스가 없었습니다. Jetson 은 LWT 를 안 쓰고 **이걸 5초마다 발행하는 것으로 생존 신호를 겸합니다** — 마지막 수신 후 15초가 지나면 죽은 것으로 봅니다.

```ts
interface JetsonStatus {
  model_version:  string;         // 오탐 분석 · 재현용
  inference_fps:  number;         // 실측 추론 FPS
  camera_l:       DeviceHealth;   // OK / ERROR / UNKNOWN
  camera_r:       DeviceHealth;
  camera_dirty:   boolean;        // AI-06 이물질 감지
  gps_received:   boolean;        // kiosk/sensor/gps 를 받고 있는가
  uptime_sec:     Int;
}
```

**`gps_received` 가 중요합니다.** Jetson 은 추락 위치 계산에 키오스크 GPS 가 필요한데(§2 마지막 항목), 그게 안 오면 좌표를 못 냅니다. 이 값이 `false` 면 **탐지는 되지만 위치가 안 나오는 상태**이므로 키오스크가 경고를 띄워야 합니다. 이 필드가 없으면 사고 순간에야 알게 됩니다.

`camera_dirty` 가 `true` 면 S-01 상단에 배너를 띄우세요 — 렌즈에 물방울이 맺힌 채로 사고가 나면 탐지가 안 됩니다.

### 5.13 사고 전후 프레임 — Jetson 이 Pi 로 **PUT** 합니다 `확정` 2026-09-17

> **이전 판(HTTP pull)은 폐기됐습니다.** 방향이 반대로 바뀌었고, 구간도 앞 30초에서
> **앞 15초 · 뒤 10초**로 바뀌었습니다. 아래가 실제 구현입니다.

링버퍼(IOT-09)는 카메라가 달린 **Jetson RAM** 에 있습니다. 탐지 순간 그 장면을 Pi 로
올립니다 — 사고가 난 뒤에는 그 전 장면을 다시 만들 수 없습니다.

**MQTT 로 보내지 않습니다.** 25MB 를 브로커에 통과시키면 같은 브로커를 쓰는
**경보·카운트다운 메시지가 그 뒤로 밀립니다.** 이 문서가 QoS 와 retain 을 공들여 정한
이유가 30초 안에 화면이 뜨게 하는 것인데, 그걸 스스로 깨는 셈입니다.

```
PUT http://<pi>:8000/api/detections/{detection_id}/files/{file_type}/{sequence_no}
Content-Type: image/jpeg
X-Camera: L

  (raw JPEG bytes)

201 { "file_id": 1, "accident_id": "01a0…", "url": "/files/01a0…/BEFORE/0001.jpg" }
```

| 구간 | 초 | 5fps | `file_type` |
| --- | --- | --- | --- |
| 탐지 전 | **15초** | 75장 | `BEFORE` |
| 탐지 스틸컷 | — | 1장 | `DETECT_SNAPSHOT` |
| 탐지 후 | **10초** | 50장 | `AFTER` |

| 판단 | 이유 |
| --- | --- |
| **키는 `detection_id`** | Pi 가 `accident_id` 를 발급하기 *전에* 프레임이 존재합니다. Jetson 은 자기가 아는 ID 로만 이름 지을 수 있고, Pi 가 `pi_launch` 로 풀어줍니다 |
| **push (Jetson 이 올림)** | pull 이면 Pi 가 사고로 판정한 뒤에 받는데, 그 사이 링버퍼가 덮어써집니다. **MQTT 가 끊겨 있어도 프레임은 올립니다** — 탐지는 QoS 1 이라 재접속 때 나가고, 그때 장면이 이미 없으면 소용이 없습니다 |
| **PUT · 장당 1요청** | 멱등합니다. 응답을 못 받고 재전송해도 같은 자리에 덮어쓰고 `pi_accident_file` 의 UNIQUE 가 새 행을 막습니다. POST 면 프레임이 두 배가 됩니다 |
| **raw 본문** | 메타데이터는 경로와 헤더로 충분합니다. multipart 는 EC2 구간에서만 씁니다 |

**⚠ 업로드가 탐지 발행보다 먼저 도착할 수 있습니다.**

| 응답 | 뜻 | Jetson 동작 |
| --- | --- | --- |
| `404` | 아직 사고에 안 붙었다. Jetson 이 Pi 보다 빨랐다 | **재시도하면 붙습니다** |
| `409` | 진행 중 사고가 있어 이 탐지가 E1 으로 거부됐다 | **영구 실패.** 재시도하면 시간만 태웁니다 |

둘을 404 로 뭉뚱그리면 Jetson 이 헛되이 재시도합니다 — 실제로 40초를 버렸습니다.

**큐가 차면 `AFTER` 부터 버립니다.** 셋의 가치가 다릅니다.

```
DETECT_SNAPSHOT   사고당 1장. 화면 대표 이미지     -> 절대 안 버립니다
BEFORE            탐지 전 장면. 다시 못 만듭니다    -> 안 버립니다
AFTER             계속 생기고 뒤쪽이 더 유용합니다   -> 오래된 것부터 버립니다
```

> ⚠️ **오탐(CANCEL)이면** Pi 가 `pi/accident/state` 로 알리고 Jetson 이 `AFTER` 수집을
> 멈춥니다. 이미 올라간 `BEFORE` 는 그 사고에 남습니다 — 오탐 분석에 그게 근거입니다.

**이 구간은 [Jetson SDK](../../iot/jetson/README.md) 가 전부 처리합니다.** AI 팀은 `frame()` 과
`detected()` 만 부르면 됩니다.

---

### 5.14 `pi/buoy/drift` — 표류 예상 범위 (Pi → 키오스크, retained)

APP-09 · S-03 "표류 예상 범위". 기획서 §11 우선순위 **5위 — 서비스 차별점**입니다.

LoRa 가 1분간 미수신이면 두절로 판정하고(§8 정책값), 마지막 위치에서 조류·바람으로 표류 범위를 추정해 발행합니다. **반경이 시간에 따라 커지는 것이 화면에 보이는 것**이 이 기능의 요지라 주기적으로 갱신합니다.

```ts
interface BuoyDrift {
  accident_id:  Uuid;
  estimate_id:  Int;

  base_lat:     number;  // -90 ~ 90.   마지막 LoRa 수신 위치
  base_lon:     number;  // -180 ~ 180
  last_received_at: Unix;  // 마지막 수신 시각
  elapsed_sec:  Int;     // 두절 후 경과

  center_lat:   number;  // -90 ~ 90.   표류 예상 중심
  center_lon:   number;  // -180 ~ 180
  radius_m:     number;  // 예상 반경(m). 시간에 따라 커짐

  /** 계산에 쓴 해양 데이터 스냅샷. 전부 null 이면 해양 데이터 없이 추정한 것 (§9.1) */
  input_current_speed: number | null;  // m/s
  input_current_dir:   Deg    | null;  // 0 ~ 360. 진북 기준
  input_wind_speed:    number | null;  // m/s
  input_wind_dir:      Deg    | null;  // 0 ~ 360
  input_observed_at:   Unix   | null;  // 그 해양 데이터의 관측 시각

  estimated_at: Unix;
}
```

계산식은 기획서 §8.1 `제안`⚠️ 입니다 — 드리프트 = 유속 + 풍속 × 0.03, 반경 = 50 + 드리프트 × 경과초 × 0.5.

#### 🔴 `input_observed_at` 을 반드시 실으세요

**Pi 가 계산한다**는 것은 인터넷이 끊긴 동안 **캐시된 해양 데이터로 계산한다**는 뜻입니다. 3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 신뢰도가 완전히 다른데, 화면에서는 똑같이 생겼습니다.

키오스크는 이 값으로 "○○ 전 해양 데이터 기준"을 원 옆에 같이 표시해야 합니다. `packages/shared` 의 `formatAge()` 가 그 용도입니다. `input_*` 이 전부 `null` 이면 **"해양 데이터 없이 추정"** 을 명시하세요.

> 정확도를 주장하지 말고 **"추정 범위"** 로 표시합니다 (기획서 §8.1).

#### 뺀 필드 2개

| 필드 | 이유 |
| --- | --- |
| `is_current` | DB 는 이력을 쌓지만(기획서 §6.2) MQTT 는 retained 라 마지막 것만 남습니다. 중복 |
| `comm_loss_id` | Pi 내부 PK. 키오스크가 쓸 일이 없습니다. 대신 `last_received_at`·`elapsed_sec` 으로 "N분 전 마지막 수신"을 그립니다 |

#### `pi_comm_loss` 는 토픽을 따로 만들지 않습니다

두절 사실은 `pi/device/status` 의 `lora`·`last_buoy_rx_at` 로 이미 알 수 있고, 위 페이로드가 `last_received_at`·`elapsed_sec` 을 싣습니다. 토픽 하나로 충분합니다.

#### LoRa 가 복구되면

`pi/buoy/drift` 에 0바이트 retain 을 발행해 지웁니다. 그러면 키오스크가 원을 걷고 `pi/buoy/position` 실시간 표시로 돌아갑니다.

---

## 6. 페이로드 ↔ Pi DB 매핑

필드명이 DB 컬럼명과 동일하므로 **이름 변환이 없습니다.** 아래는 어느 토픽이 어느 테이블로 가는가만 나타냅니다.

> ✅ **`schema.sql` 에 전부 반영 완료** (2026-09-09). 아래 매핑이 실제 컬럼과 1:1로 맞습니다.
> ERDCloud 반영은 `erd-changes.md` (`./erd-changes.md`, 공개 사본 미포함) 참고.

| 토픽 | 필드 | 테이블 · 컬럼 |
| --- | --- | --- |
| `jetson/detection` | `lat`, `lon` | `pi_accident.accident_lat` / `accident_lon` |
| | `detected_at` | `pi_accident.created_at` |
| | `model_version` | `pi_accident.model_version` |
| | `launch.target_lat` / `target_lon` | `pi_launch.target_lat` / `target_lon` |
| | `launch.target_yaw_deg` / `target_pitch_deg` | `pi_launch.horizontal_angle` / `vertical_angle` (소프트 리밋 적용 후 값) |
| | `detection_id` | `pi_launch.detection_id` — **컬럼 추가 필요** 🟡 (§7-15) |
| | `distance_m`, `confidence`, `frame_count`, `bbox`, `camera`, `launch.launch_profile`, `launch.solved_at` | **저장 안 함.** 오탐 분석용으로 남기려면 컬럼 추가 필요 🟡 |
| ↑ **Pi 가 채우는 컬럼** | `accident_id`(Pi 발급), `ship_id`, `status`, `accident_type`, `trigger_source`, `report_type`, `report_dsc`, `wait_sec`, `report_due_at` | `pi_accident` — **Jetson 이 보내는 값이 아닙니다.** 초안 표가 이 둘을 섞어놔 Jetson 이 채워야 하는 것처럼 읽혔습니다 (§5.1) |
| `jetson/snapshot` | `captured_at`, `width`, `height`, `bytes`, `camera` | `pi_accident_file` (`file_type = 'DETECT_SNAPSHOT'`) |
| | `data` (base64) | **DB 에 저장 안 함.** 디스크에 쓰고 `file_path` 만 기록 |
| `jetson/status` | 전체 | 저장 안 함 (retained 메시지로 충분) |
| `pi/accident/state` | `accident_id`, `status`, `prev_status`, `reason` | `pi_accident_state` |
| | `changed_at` | `created_at` |
| | `caused_by` | `pi_accident_state` — **저장 안 함.** 감사용이면 컬럼 추가 필요 |
| `pi/launch/result` | `result`, `fail_reason`, `target_lat`, `target_lon`, `launch_lat`, `launch_lon`, `horizontal_angle`, `vertical_angle`, `confidence_score` | `pi_launch` |
| | `launched_at` | `created_at` |
| `pi/buoy/position` | `buoy_log_id`, `accident_id`, `seq`, `is_pressed`, `lat`, `lon`, `rssi`, `received_at` | `pi_buoy` |
| | `measured_at` | `created_at` |
| `pi/sensor/imu` | `accel_x/y/z`, `roll`, `pitch`, `yaw`, `heading_deg`, `imu_position`, `accident_id` | `pi_imu` |
| | `measured_at` | `created_at` |
| `kiosk/sensor/gps` | `lat`, `lon`, `speed_kn`, `heading_deg`, `accuracy_m`, `measured_at` | `pi_ship_position` |
| `pi/report/status` | `report_id`, `accident_id`, `channel`, `status`, `sent_count`, `first_sent_at`, `last_sent_at`, `acked_at`, `acked_by`, `fail_reason` | `pi_report` |
| `pi/buoy/drift` | `estimate_id`, `accident_id`, `base_lat/lon`, `elapsed_sec`, `center_lat/lon`, `radius_m`, `input_*` | `pi_drift_estimate` |
| | `estimated_at` | `created_at` |
| | `is_current` | **페이로드에 없음.** DB 에서만 이력 관리 (§5.14) |
| `pi/device/status` | 전체 | 저장 안 함 (retained 메시지로 충분) |
| `kiosk/command/*` | — | 저장 안 함. 결과가 `pi_accident_state` 에 남음 |

### 스키마가 강제하는 것 — 코드에서 또 검사하지 마세요

`schema.sql` 의 CHECK 제약이 아래를 DB 레벨에서 거부합니다. 검증 로직을 앱에 중복 구현하면 두 곳이 어긋납니다.

| 규칙 | 제약 |
| --- | --- |
| AIS 채널에는 ACK 이 올 수 없다 | `ck_pi_report_ack_channel` — `acked_at IS NULL OR channel = 'DSC'` |
| `status = 'ACKED'` 와 `acked_at` 은 항상 같이 | `ck_pi_report_ack_status` |
| `acked_by` 는 9자리 MMSI | `ck_pi_report_acked_by` |
| AI 감지는 `MOB` 만 만든다 | `ck_pi_accident_ai_type` |
| `result = 'SUCCESS'` 면 `fail_reason` 은 NULL | `ck_pi_launch_fail_reason` |
| 같은 사고·유형에 `sequence_no` 중복 불가 | `uq_pi_accident_file_seq` |
| `CLOSE` 가 아니면 종료 시각 없음 | `ck_pi_accident_closed` |

---

## 7. 결정 필요 — 이거 없으면 구현 못 합니다 🔴

| # | 항목 | 담당 | 막히는 것 |
| --- | --- | --- | --- |
| 1 | **부표 위치 주기 1초 vs 10초** (§7.1/§8 ↔ §7.2 충돌) | IoT | 페이로드가 단건인지 배열인지 결정됨 |
| 2 | ~~**수동 신고 유형 5개 vs 10개**~~ | 웹 | **해소 2026-09-17 — 8종 확정** (EC2 `api.json` 과 동일). 남은 건 S-07 레이아웃뿐 |
| 3 | **감지 스냅샷 해상도·용량 상한** | AI | 브로커·클라이언트 최대 페이로드 설정 |
| 4 | **IMU 발행 주기와 대상**(3개 전부 vs 선택 1개) | IoT | 키오스크 처리량 |
| 5 | **Pi ↔ 키오스크 시각 동기화** (NTP 없는 폐쇄망) | IoT | `report_due_at` 카운트다운 정확도 |
| 6 | **브로커 인증 방식** | IoT | 접속 코드. ⚠️ 키오스크가 브라우저라 자격증명이 JS 번들에 노출됨 — 익명 / 전용계정+ACL / 클라이언트 인증서 중 선택 (§1.0) |
| 7 | **`ship_id` 를 Pi·키오스크에 넣는 절차** (부록 C) | 웹 | 모든 토픽 경로 |
| 8 | **§7.6 UDP 수신처 A/B/C** | 별도 담당 | **DSC ACK 구현 여부**. C안이면 `acked_at` 자체가 무의미 (§5.11) |
| 9 | **DSC 반복 주기** — 실제 규격(3.5~4.5분) vs 시연 편의(1분 8회) | IoT | 채널별 반복 루프 분기 |
| 10 | **AI-02 사고 판단 기준** (연속 프레임 수 · confidence 임계값) | AI | Pi 가 `jetson/detection` 을 사고로 승격하는 조건 (§5.1) |
| 11 | **재부팅 중 `report_due_at` 만료 시 처리** | 팀 | 즉시 신고 vs 취소 기회 부여 (§2.4) |
| 12 | **Jetson 프레임 보관 건수** | AI | `제안` N=5 (§5.13) |
| 13 | **`solved_at` 만료 기준** — 조준 해의 유효 시간 | IoT + AI | Pi 의 발사 거부 판정 (§5.1). 탐지→발사→착수 실측 지연을 재야 정할 수 있음 |
| 14 | **조준 해 입력에 선체 자세(IMU)를 넣을지** | IoT + AI | 넣으면 `pi/sensor/imu` 를 Jetson 이 구독해야 함 (§2 표 변경). 선박 속도·침로는 이미 `kiosk/sensor/gps` 로 전달 중 |
| 15 | **`pi_launch.detection_id` 컬럼 추가** | IoT | 어느 탐지의 해로 쐈는지 추적 불가 → 오탐 분석 불가 (§5.4) |
| 16 | **`seq` 비트 폭과 롤오버 규칙** | IoT | 8비트면 4분 16초마다 감김. 사고가 길어지면 유실 감지가 거짓말이 됨 (§2.3, §7.3) |
| 17 | **카운트다운 중 키오스크 두절 시 즉시 신고할지** | 팀 | LWT 가 22.5초 늦게 오므로 "사고 시점의 online 값"만으로는 부족 (§1.4). 당기면 오탐의 취소 기회가 사라짐 |
| 18 | **`pi_ocean_data` 테이블 신설** | IoT | 표류 계산을 Pi 가 하기로 했으므로(§5.14) 해양 데이터 캐시가 Pi 에 필요. §8 은 현재 13 테이블이고 이게 없음 |
| 19 | **해양 데이터를 Pi 가 직접 받나, EC2 가 받아 Pi 로 내려주나** | IoT + 웹 | API 키를 배에 뿌릴지가 갈림. `app.ocean.collect-cron` 이 백엔드에 있으니 **EC2 수집 → Pi pull** 이 구조에 맞음 |
| 20 | **해양 데이터 수집 주기** | 웹 | 기획서 §8 은 3분, `application.yml` 은 10분. ⚠️ 10분이면 144회/일인데 주석의 "개발계정 50회/일 제한"을 이미 넘습니다 — 재확인 필요 |
| 21 | **표류 추정 발행 주기** | IoT | `제안` 10초 (§5.14). 반경이 커지는 게 보여야 하는 시연 포인트 |

### 🟡 문서에서 제안한 것 — 승인 필요

**3자 통신 구조 (이번에 추가)**

1. **토픽에 발행자 세그먼트** — `ship/{ship_id}/{pi|jetson|kiosk}/...` (§1.2)
2. **mosquitto ACL** — 각 클라이언트는 자기 prefix 에만 write (§1.2)
3. **중계 금지** — Jetson 발행을 Pi·키오스크가 각자 구독 (§1.3)
4. **키오스크도 LWT 등록** — Pi 가 "경보 띄울 화면이 살아있는지" 판단 (§1.4)
5. **`jetson/detection` 에 `accident_id` 없음** — 사고 판정은 Pi 가 하고 ID 도 Pi 가 발급 (§5.1)
6. **`jetson/status` 신설** — APP-15 의 AI·카메라 칸 소스. LWT 대신 5초 주기로 생존 신호 겸용 (§5.12)
7. **125장은 HTTP PUT** — Jetson 이 `detection_id` 로 Pi 에 올림 (§5.13). pull 은 폐기
8. **재접속 복구 절차** — retained 도착 순서 무보장 전제, `pi/accident/state` 를 유일한 진실로 (§2.4)

**기존 제안**

9. `command/delete` → `kiosk/command/cancel` 개명
10. `kiosk/command/report_manual` 신설
11. `pi/online` LWT 토픽 신설
12. `kiosk/sensor/gps` — **Jetson 도 구독** (추락 위치 계산 입력)
13. retain 정책 (§2.1) — 특히 **command 에 retain 금지**
14. `pi/command/response` 토픽 + 공통 Response Envelope
15. 스냅샷 상한 200KB
16. `pi/report/status` 토픽 신설 (채널별 retained 1개씩)
17. **DSC ACK 주체 = 관제 웹**, §7.6 **A안** 채택 (§5.11)
18. DSC 만 ACK 자동 중지, AIS 2채널은 수동 중지

---

## 8. Pi DB 반영 현황 ✅

`schema.sql` 반영 완료 (2026-09-09). **13 테이블 / STRICT 13 / CHECK 67 / FK 13 / 인덱스 37 / 트리거 0**, 실행·제약 검증 통과.

모든 테이블에 `updated_at` 이 있습니다 (`sync` 제외). 동기화는 이걸 기준으로 합니다 — `created_at` 은 `pi_buoy`·`pi_imu`·`pi_ship_position` 에서 **측정 시각**이라 LoRa 지연 시 워터마크보다 이전 값이 될 수 있고, 그러면 그 행이 영원히 안 올라갑니다.

```sql
SELECT * FROM <table> WHERE updated_at > :synced_at ORDER BY updated_at;
```

**갱신은 ORM 에서 합니다.** 트리거는 쓰지 않습니다 — 이유는 `erd-changes.md` (`./erd-changes.md`, 공개 사본 미포함) §3 참고.

```python
updated_at: Mapped[int] = mapped_column(Integer, default=_now, onupdate=_now)
```

| 테이블 | 컬럼 | 비고 |
| --- | --- | --- |
| `pi_ship` | 8 | `mmsi` `TEXT` + 9자리 GLOB CHECK |
| `pi_accident` | 15 | `accident_type`, `trigger_source`, `wait_sec`, `report_due_at`, `model_version`, `rescued_at`, `closed_at` 추가 |
| `pi_accident_state` | 6 | `prev_status`, `reason` 추가 |
| `pi_launch` | 11 | `result`, `fail_reason`, `target_lat/lon` 추가 |
| `pi_buoy` | 9 | `seq`, `received_at`, `rssi` 추가. `lng` → `lon` |
| `pi_report` | 17 | 채널별 전송 추적 + DSC ACK (`acked_at`, `acked_by`) |
| `pi_imu` | 11 | `heading_deg`, `imu_position` 추가. `accident_id2` → `accident_id` |
| `pi_video` | 5 | `object_key` 추가 (R2) |
| **`pi_ship_position`** | 8 | 신규 — `kiosk/sensor/gps` 수신분. APP-01 항적·ETA |
| **`pi_accident_file`** | 12 | 신규 — 감지 스틸컷 + 사고 전후 125장. `file_type`, `sequence_no`, `camera` |
| **`pi_comm_loss`** | 9 | 신규 — LoRa 두절 구간 |
| **`pi_drift_estimate`** | 15 | 신규 — 표류 예상 범위 (이력 누적) |
| `sync` | 2 | 단일 행 CHECK |

### 설계 판단 3개

**1. `pi_imu` 에 `seq` 를 넣지 않았습니다.** `imu_id` 가 Pi 에서 순차 발급되므로 `ORDER BY created_at, imu_id` 로 초 내부 순서가 잡힙니다. 초 단위 타임스탬프의 한계를 컬럼 추가 없이 해결합니다.

**2. 이미지·영상 바이너리는 DB 에 넣지 않습니다.** `pi_accident_file` 은 `file_path` + `object_key` 만 갖습니다. 사고 전후 125장 × 200KB = **25MB/사고** 를 SQLite BLOB 에 넣으면 SD카드 수명에 불리하고, 동기화할 때 한 행이 통째로 커집니다. **스냅샷 용량이 확정되면 재검토** (§7 항목 3).

**3. `pi_comm_loss` / `pi_drift_estimate` 를 Pi 에도 뒀습니다.** §6.2 는 `timestamptz`/`jsonb` 로 정의해 서버 전용처럼 읽히지만, 두절 판정과 표류 계산은 **오프라인에서도 동작**하고(§9.1) 인터넷 복구 후 EC2 로 올려야 합니다. Pi 에 없으면 오프라인 사고의 수색 범위 이력이 사라집니다.

### 아직 남은 것

| 항목 | 상태 |
| --- | --- |
| `pi_report.report_type` 이름 충돌 | `pi_accident.report_type`(DISTRESS/URGENCY) 과 이름은 같고 의미는 다름(AUTO/MANUAL/RESCUE). §6.3 표기를 따랐으나 **개명 검토 필요** |
| `pi_ship_position` 보관 기간 | 1Hz 로 무한 누적. **정책 미정** |
| ~~`sync` 워터마크가 UPDATE 를 놓침~~ | **해결됨.** 위 §8 본문의 `updated_at` 기준 동기화(`WHERE updated_at > :synced_at`)가 정확히 이 문제를 닫습니다. `created_at` 기준으로 남아 있는 코드가 있으면 그것만 고치세요 |

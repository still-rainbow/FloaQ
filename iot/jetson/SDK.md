# FloaQ Jetson SDK

Pi 와 말하는 SDK와 카메라 미리보기용 추론 옵션이 들어 있습니다. 사고 판단에 쓰는
AI 추론 루프는 별도로 연동합니다.

환경 구축은 [README.md](README.md) 를 따르세요. 이 문서는 그 위에서 SDK 쓰는 법만
적습니다.

---

## 1. 준비

별도 설치가 없습니다. `floaq_jetson/` 이 `iot/jetson` 안에 있어서 그 디렉터리에서
바로 `import` 됩니다.

```bash
cd iot/jetson
source .venv/bin/activate
python -c "import floaq_jetson; print('ok')"
```

쓰는 의존성은 셋입니다 — `paho-mqtt`, `pydantic`, `requests`. 셋 다
`pyproject.toml` 에 들어 있으므로 `uv sync` 가 챙깁니다.

## 2. 쓰는 법 — 함수 둘

```python
from floaq_jetson import Floaq

fq = Floaq(pi="192.168.0.10")        # ship_id 는 Pi 가 알려줍니다
fq.start()

while True:
    frame = camera.read()
    jpeg = encode(frame)

    fq.frame(jpeg, camera="L")                      # ① 매 프레임

    if p := model.detect(frame):                    # ② 탐지되면 한 줄
        fq.detected(
            lat=p.lat, lon=p.lon,
            distance_m=p.distance,                  # 스테레오 거리
            confidence=p.conf,
            camera="L", bbox=(x, y, w, h),
            snapshot=jpeg,                          # 화면 대표 이미지
            yaw=aim.yaw, pitch=aim.pitch,           # 조준 해. 없으면 생략
            target_lat=aim.lat, target_lon=aim.lon,
        )
```

끝입니다. `accident_id`·`detection_id`·MQTT 토픽·업로드 순번·재시도는 안 보입니다.

### `detected()` 한 번이 하는 일

```
1. detection_id 발급 (UUID v7 — 문자열 정렬이 곧 시간순)
2. 페이로드 검증 (pydantic)         틀리면 즉시 예외
3. jetson/detection 발행 (QoS 1)
4. 링 버퍼 -> 업로드 큐  BEFORE      앞 15초
5. snapshot -> 업로드 큐  DETECT_SNAPSHOT
6. AFTER 모드 ON                    이후 frame() 이 자동 업로드, 뒤 10초
```

`AFTER` 는 **자동으로 꺼집니다** — 뒤 10초가 지나거나, Pi 가 사고를 `CLOSE`/`CANCEL`
하면. 종료 시점을 신경 쓸 필요가 없습니다.

---

## 3. 카메라 라이브 — `:8080`

키오스크에 검출 상자가 그려진 영상을 보여주려면 Jetson에서 모델을 지정해 실행합니다.
기존 `/stream.mjpg?camera=L`·`/stream.mjpg?camera=R` 주소는 그대로 씁니다.

```bash
python -m floaq_jetson --stream-only --camera 0,1 \
  --weights /path/to/best.pt --device 0
```

`--weights` 를 생략하면 기존 원본 스트림입니다. 모델 추론은 촬영 스레드와 분리하고
카메라별 최신 프레임만 처리합니다. 추론 속도가 촬영 속도보다 느리면 중간 프레임은
버리므로 화면 지연이 계속 쌓이지 않습니다. Jetson에서 모델과 추론 장치가 실제로
동작하는지는 해당 보드에서 확인해야 합니다.

`start()` 하면 자동으로 뜹니다. `frame()` 으로 들어온 프레임이 그대로 흐릅니다.

| 경로 | 내용 |
| --- | --- |
| `http://<jetson>:8080/` | 좌우 카메라 확인 페이지 |
| `/stream.mjpg?camera=L` | MJPEG 스트림. `<img src>` 에 그대로 넣습니다 |
| `/snapshot.jpg?camera=R` | 가장 최근 한 장 |
| `/health` | 카메라 둘의 생사 |

Pi 와 같은 FastAPI 입니다. 기기는 다르지만 프레임워크가 하나여야 둘을 따로 배우지
않습니다. 버린 Flask 카메라 서버가 있던 자리입니다.

`camera` 는 `L` 과 `R` 만 받습니다. 다른 값은 **422** 입니다 — 조용히 빈 스트림이
나가면 카메라가 안 붙은 건지 오타인지 구분이 안 됩니다.

```jsonc
// GET /health
{ "ok": false,                                  // 둘 다 살아 있어야 true
  "cameras": {
    "L": { "frames": 1204, "age_sec": 0.2,  "live": true  },
    "R": { "frames": 0,    "age_sec": null, "live": false } } }   // R 이 죽었다
```

🔴 **카메라 둘이 항상 나옵니다.** 프레임이 온 것만 나열하면 R 고장과 카메라 한 대를
구분할 수 없습니다. 스테레오 거리(AI-03)가 둘 다 필요해서, 한쪽만 도는 상태는 조준
해가 **조용히** 나빠지는 것입니다 — 예외도 로그도 안 납니다. `age_sec` 이 3초를
넘으면 `live: false` 이고, 그게 "잠깐 끊김"과 "고장"을 가릅니다.

**기록이 아니라 보기용입니다.** 사고 기록은 Pi 로 올라가는 쪽이고, 여기는 지금 무엇을
보고 있는지 확인하는 화면입니다.

끄려면 `Floaq(pi=..., stream_port=None)`.

> 🔴 최신 한 장만 들고 있습니다. 보는 쪽이 느려도 프레임을 쌓지 않습니다 — 쌓으면 그
> 클라이언트가 Jetson 메모리를 채우고, 화면은 점점 과거를 보여줍니다.

---

## 4. 배선 확인

AI 코드를 붙이기 **전에** 이걸 돌리세요. 카메라도 모델도 없이 경로만 확인합니다.

```bash
python -m floaq_jetson --pi 192.168.0.10
```

```
ship_id  01a0a3ed-01fd-7a09-b3cf-ba5910c52950
링 버퍼 채우는 중 (앞 15초)
  보유 75장
탐지 발행  01a0ae93-e27b-77e3-a6ef-656b96ce8cab  published=True
뒤 10초 프레임 보내는 중
   {'mqtt': 'connected', 'phase': 'AFTER', 'sent': 126, 'failed': 0, ...}

[성공] 경로가 살아 있다
```

여기서 안 되면 원인이 우리 쪽이고, 여기서 되면 AI 쪽입니다.

| 옵션 | |
| --- | --- |
| `--no-aim` | 조준 해 없이 (Pi 가 `NO_SOLUTION` 으로 기록하는지 확인) |
| `--watch` | 탐지 없이 상태만 지켜보기 |
| `--ship-id` | Pi `/health` 를 안 쓰고 직접 지정 |
| `--stream-only` | Pi·카메라 없이 `:8080` 만. 네트워크 경로 확인용 |

### 스크립트

`scripts/` 에 하나씩 있습니다. 전부 `iot/jetson` 어디서 불러도 됩니다.

| | 하는 일 |
| --- | --- |
| `./scripts/check.sh` | `uv sync` + JetPack 검증 + SDK import. **제일 먼저 이것** |
| `./scripts/live.sh <pi>` | 실제 카메라 + 추론 + Pi 업로드. **시연용** |
| `./scripts/test.sh` | 단위 시험. 브로커도 Pi 도 없이 돕니다 |
| `./scripts/stream.sh` | `:8080` 만 띄웁니다. 카메라 붙이기 전 네트워크 확인 |
| `./scripts/selftest.sh <pi>` | 탐지 한 번 + 프레임. **Pi 에 사고가 하나 생깁니다** |
| `./scripts/watch.sh <pi>` | 붙어만 있고 상태를 봅니다. 탐지를 안 만듭니다 |

Pi 주소는 인자 · `FLOAQ_PI` 환경변수 · `.env` 순으로 찾습니다.

---

## 5. 규칙 셋

### 🔴 모든 호출이 논블로킹입니다

추론 루프가 5fps 로 도는데 우리 때문에 프레임이 밀리면 안 됩니다. MQTT 발행과 HTTP
업로드는 전부 워커 스레드가 합니다. `frame()`·`detected()` 는 즉시 돌아옵니다.

### 🔴 예외는 **호출이 틀렸을 때만** 납니다

```python
fq.detected(lat=200, ...)
# InvalidCall: lat: Input should be less than or equal to 90
```

이건 AI 쪽 버그라 크게 터져야 합니다. 반대로 **Pi 가 죽었거나 랜이 끊긴 것은 정상
경로**라 조용히 큐에 쌓입니다. 그 상태는 `stats()` 로 봅니다.

```python
fq.stats()
# {'mqtt': 'connected', 'phase': 'IDLE', 'accident_id': None,
#  'ring': 75, 'ring_bytes': 15360000,
#  'queued': 0, 'sent': 1204, 'failed': 0, 'dropped': 0,
#  'stream': 'http://0.0.0.0:8080/'}
```

### 🔴 사고 판정은 Pi 가 합니다

이 SDK 어디에도 `accident_id` 를 만드는 곳이 없습니다. 탐지를 보내면 Pi 가
중복(E1)을 거르고 사고를 열어 `accident_id` 를 발급합니다. 30초 카운트다운과
오인신고 취소도 Pi·키오스크 쪽 일입니다.

**각도를 보냈다고 발사가 확정되는 것도 아닙니다.** Pi 가 범위·만료·장전 상태를
검증하고 거부하면 그대로 버려집니다 — 그건 오류가 아니라 설계입니다.

---

## 6. 알아 두면 좋은 것

### 프레임 창

| | 초 | 5fps 기준 |
| --- | --- | --- |
| `BEFORE` | 앞 15초 | 75장 |
| `AFTER` | 뒤 10초 | 50장 |

앞 구간은 링 버퍼에 상시로 들고 있다가 탐지 순간에 쏟아냅니다 — **사고가 난 뒤에는
그 전 장면을 다시 만들 수 없습니다.** 링 버퍼는 상한이 있어 그 이상 커지지 않습니다.

### 큐가 차면 `AFTER` 부터 버립니다

```
DETECT_SNAPSHOT   사고당 1장. 화면 대표 이미지      -> 절대 안 버립니다
BEFORE            탐지 전 장면. 다시 못 만듭니다     -> 안 버립니다
AFTER             계속 생기고 뒤쪽이 더 유용합니다    -> 오래된 것부터 버립니다
```

버린 수는 `stats()['dropped']` 에 셉니다.

### 조준 해는 전부 주거나 전부 생략

`yaw`·`pitch`·`target_lat`·`target_lon` 넷입니다. 절반만 주면 예외가 납니다 —
조용히 `NO_SOLUTION` 으로 떨어지면 왜 발사가 안 되는지 시연 날까지 모릅니다.

### 계약이 갈라지면 경고만 합니다

`start()` 가 Pi 의 `/contract.json` 과 필드를 대조합니다. 다르면 로그에 남기고
**계속 보냅니다** — 필드 하나 때문에 탐지를 막으면 사람을 못 건집니다.

```
WARNING 계약 불일치: Pi 가 요구하는데 SDK 에 없는 필드: ['새필드']
```

이 경고가 보이면 알려주세요. 양쪽 스키마를 맞춰야 합니다.

---

## 7. 문제가 생기면

| 증상 | 볼 곳 |
| --- | --- |
| `InvalidCall: Pi 의 /health 에서 ship_id 를 못 받았다` | Pi 의 `:8000` 이 떠 있는지. 방화벽 |
| `InvalidCall: Pi 가 ship_id 를 안 준다` | 선박 등록이 아직 안 됐습니다. 키오스크에서 등록 |
| `stats()['mqtt'] == 'disconnected'` | 브로커 `:1883`. 재접속은 자동이라 잠깐이면 정상 |
| `sent` 가 안 오름 | Pi `:8000` 의 업로드 경로. `queued` 가 쌓이면 Pi 쪽 |
| `failed` 가 오름 | Pi 로그를 보세요. 409 는 진행 중 사고가 있어 거부된 것(정상) |
| 스트림이 안 뜸 | `:8080` 이 이미 쓰이는지. 기동 로그에 경고가 남습니다 |
| `/health` 가 `ok:false` | 어느 카메라가 `live:false` 인지 보세요. 그쪽이 안 붙었거나 죽었습니다 |

---

## 8. 구조

```
floaq_jetson/
    __init__.py     공개 API 재수출만
    _client.py      Floaq 구현
    _models.py      pydantic 스키마 + 계약 대조
    _mqtt.py        paho 래핑 (재접속마다 재구독)
    _ring.py        링 버퍼
    _upload.py      업로드 워커 + 우선순위 큐
    _stream.py      :8080 MJPEG
    ids.py          UUID v7
```

밑줄로 시작하는 것은 내부입니다. 직접 쓰면 `AttributeError` 가 납니다 — 내부 구조를
바꿀 수 있게 하려는 것이니, 필요한 게 있으면 말해주세요. 공개 API 로 뺍니다.

```python
>>> fq.Uploader
AttributeError: floaq_jetson.Uploader 은 공개 API 가 아니다.
               쓸 수 있는 것: Floaq, Detection, InvalidCall, ...
```

시험은 `python -m pytest tests/` 입니다. 브로커도 Pi 도 없이 돕니다.

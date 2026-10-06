# 실시간 영상 촬영 (IOT-01)

- Jira: floaq-18 · 에픽 floaq-1
- 대상 보드: **Jetson Orin Nano** (DES-31 §1 — 영상 수집·추론은 Jetson, Pi 5 는 제어 전담)
- 상태: 합성 소스로 전 구간 검증 완료 · 실물 카메라 미검증

선박 후방 스테레오 카메라에서 프레임을 수집해 AI 탐지 모듈로 넘긴다.

## 저장소 배치

이 폴더의 `camera/` 와 `tests/` 를 저장소의 `iot/jetson/` 아래로 옮긴다.

```text
iot/jetson/
├── camera/
│   ├── __init__.py
│   ├── config.py       설정 (해상도·fps·엔드포인트)
│   ├── frame.py        Frame · StereoPair 와 헤더 정의
│   ├── source.py       CameraSource · V4l2Source · SyntheticSource
│   ├── capture.py      카메라별 수집 스레드 · 최신 프레임 슬롯 · 재연결
│   ├── stereo.py       좌우 타임스탬프 페어링
│   ├── publisher.py    JPEG 인코딩 · ZMQ PUB
│   ├── subscriber.py   수신측 파서 (AI·링버퍼 공용)
│   ├── service.py      조립 · 통계 · 신호 처리
│   └── __main__.py     CLI
└── tests/test_camera.py
```

의존성은 `pyzmq` 하나뿐이고 이미 `iot/jetson/pyproject.toml` 에 있다.
`cv2` 는 JetPack 시스템 패키지라 uv 로 설치하지 않는다(그래서 지연 임포트한다).
`numpy` 도 이미 들어 있다. **추가할 패키지 없음.**

## 실행

```bash
cd iot/jetson
source .venv/bin/activate

# 장치 확인
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext

# 실물 스테레오
python -m camera --left /dev/video0 --right /dev/video2

# 카메라 없이 파이프라인만
python -m camera --left synthetic --right synthetic --seconds 10

# 다른 터미널에서 수신 확인
python -m camera.subscriber --seconds 10
```

주요 인자: `--width --height --capture-fps --publish-fps --quality --endpoint --max-skew-ms`
환경변수 `FLOAQ_CAM_LEFT` · `FLOAQ_CAM_RIGHT` · `FLOAQ_FRAME_ENDPOINT` · `FLOAQ_PUBLISH_FPS` 로도 덮어쓴다(systemd 용).

```bash
python -m unittest discover -s tests -v     # 26 tests, cv2·zmq 없이도 통과
```

> **venv 는 반드시 `--system-site-packages` 로 만든다.** `cv2` 는 JetPack 시스템
> 패키지라 uv 가 만드는 기본 venv 에서는 보이지 않고, `uv sync` 가 venv 를
> 다시 만들면서 이 설정을 날린다. 서비스 시작 시 `_preflight()` 가 확인해
> 없으면 즉시 죽는다.
>
> ```bash
> uv venv --python /usr/bin/python3.10 --system-site-packages
> uv sync --locked --inexact --python /usr/bin/python3.10
> uv run python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"
> ```
>
> cv2 가 보이기 시작한 뒤 `compiled using NumPy 1.x cannot be run in NumPy 2.x`
> 가 뜨면, JetPack cv2 가 numpy 1.x 로 빌드됐는데 프로젝트가 `numpy==2.2.6` 을
> 깔아 시스템 numpy 를 가린 것이다. numpy 를 1.26.4 로 내리는 쪽이
> cv2 를 새로 빌드하는 것보다 싸다. lock 이 바뀌므로 재락 전에
> `[[tool.uv.index]]` 의 `pytorch-cpu` 에 `explicit = true` 를 먼저 넣는다
> (없으면 certifi 부터 해석이 깨진다).

## 설계 결정

**시계는 IMU 링버퍼와 같은 규칙을 쓴다.** `mono_ns` 로 순서·페어링·구간 길이를 계산하고
`wall_ns` 는 기록·조회에만 쓴다. Jetson 은 chrony makestep 이 켜져 있어 wall clock 점프가
실제로 일어나므로(floaq-178), 두 시계를 섞으면 30초 창과 페어링이 동시에 틀어진다.
`imu_ringbuffer.py` 의 `ImuSample` 과 필드 규칙이 같아서 -146 에서 바로 정렬할 수 있다.

**타임스탬프는 `grab()` 직후에 찍는다.** OpenCV `read()` 는 grab+retrieve 를 묶어버려
디코드 시간이 시각에 섞인다. 스테레오에서는 이게 그대로 skew 오차가 된다.

**카메라마다 스레드를 하나씩 둔다.** 한 스레드에서 grab-grab-retrieve-retrieve 로 묶으면
skew 는 더 줄지만 한쪽이 멈출 때 양쪽이 같이 멈춘다. 해상에서 USB 한 대가 빠지는 건
정상 시나리오로 봐야 하므로 독립 스레드로 가고, 대신 skew 를 재서 헤더에 실어 보낸다.

**허용 오차를 넘은 좌우 조합은 쌍으로 인정하지 않는다.** 억지로 붙인 쌍은 스테레오
거리 계산에서 조용히 틀린 값을 만든다. mono 로 떨어뜨리고 `mono_fallback` 을 센다.

**프레임을 큐에 쌓지 않는다.** 소비자가 느리면 지연이 누적되므로 최신 한 장만 들고
오래된 것은 버린다. 버린 개수는 `dropped` 로 노출한다. ZMQ PUB 도 같은 이유로
HWM 에서 버리게 두었다(`CONFLATE` 는 멀티파트에서 동작하지 않아 쓰지 않는다).

**수집 fps 와 송신 fps 를 분리한다.** 저장은 5 fps 로 확정돼 있지만(DES-31 C-8)
탐지는 더 높은 fps 가 유리하다. 카메라를 5 fps 로 낮추면 탐지 쪽 여지가 사라진다.

## 메시지 형식

ZMQ PUB 멀티파트. 구독자가 이미지를 디코드하지 않고도 시각·번호만 보고
버릴지 정할 수 있게 헤더를 분리했다.

| # | 내용 |
|---|---|
| 0 | 토픽 `b"frame"` |
| 1 | 헤더 JSON (utf-8) |
| 2 | 왼쪽 JPEG |
| 3 | 오른쪽 JPEG (stereo 일 때만) |

```json
{
  "pair_id": 1421, "pub_seq": 474,
  "mono_ns": 812740155293, "wall_ns": 1789351102882441000, "created_at": 1789351102,
  "width": 1280, "height": 720,
  "stereo": true, "skew_ms": 0.24,
  "left_seq": 1421, "right_seq": 1420,
  "encoding": "jpeg", "quality": 85,
  "left_bytes": 11504, "right_bytes": 11498,
  "encode_ms": 2.34, "capture_age_ms": 4.1
}
```

`pair_id` 는 수집한 쌍 번호라 솎아내기 때문에 연속하지 않는다.
`pub_seq` 는 실제로 내보낸 메시지 번호라 연속해야 정상이고, 끊기면 전송 유실이다.
둘을 나눠 둬야 "일부러 안 보낸 것"과 "중간에 잃은 것"을 구분할 수 있다.

AI 쪽은 `ai/docs/interface.md` 의 detection contract 에 `pair_id` 를 그대로 실어
돌려주면 원본 프레임을 다시 찾을 수 있다.

## 커밋 단위

`feature/iot-18-camera-capture` 브랜치에서 아래 순서로 나눠 커밋한다.
각 커밋은 그 시점에 테스트가 통과하는 상태다.

| # | 커밋 | 파일 |
|---|---|---|
| 1 | `feat(iot): 프레임 데이터 모델과 촬영 설정 정의` | `frame.py` `config.py` |
| 2 | `feat(iot): 카메라 소스 추상화와 V4L2·합성 구현` | `source.py` |
| 3 | `feat(iot): 카메라별 수집 스레드와 장치 재연결` | `capture.py` |
| 4 | `feat(iot): 스테레오 타임스탬프 페어링` | `stereo.py` |
| 5 | `feat(iot): ZMQ 프레임 퍼블리셔와 수신 파서` | `publisher.py` `subscriber.py` |
| 6 | `feat(iot): 촬영 서비스 조립과 CLI` | `service.py` `__main__.py` `__init__.py` `README` |
| 7 | `test(iot): 촬영 파이프라인 시험` | `tests/test_camera.py` |
| 8 | `fix(iot): cv2 미검출 시 시작 거부와 인코딩 실패 로깅` | `service.py` `publisher.py` |

MR 템플릿의 "전달 사항"에 넣을 것:
**AI** — 메시지 형식과 `pair_id` 회신 규칙. **Web** — 없음.

## 합성 소스 실측 (640×480, 수집 15 fps → 송신 5 fps)

| 항목 | 값 |
|---|---|
| 수집 fps | 14.99 (양쪽) |
| 페어링 성공률 | 1.00 · skew 평균 0.27 ms / 최대 2.09 ms |
| 송신 fps | 5.00 · 전송 유실 0 |
| 프레임 드롭 | 0 |
| JPEG 인코딩 | 2.3 ms/장 · 11.5 KB/장 |

합성 소스는 CPU 부하와 USB 대역이 빠진 값이다. 실물 수치가 아니다.

## 실물 카메라 도착 후 확인할 것

DES-31 §5 #5(카메라 대역)의 측정 절차가 된다. `--verbose` 로 돌리면
`actual_settings()` 가 드라이버가 실제로 받아들인 값을 남긴다.

1. `v4l2-ctl --list-formats-ext` 로 MJPG 지원과 해상도별 fps 확인.
   MJPG 가 없으면 YUYV 로 떨어져 720p 2스트림은 대역이 안 나온다.
2. 요청 해상도·fps 와 `actual_settings()` 결과가 같은지. 드라이버가 조용히
   낮추는 경우가 흔하다.
3. 두 카메라를 **다른 USB 컨트롤러**에 꽂았을 때와 같은 허브에 꽂았을 때
   `grabbed` · `dropped` · `grab_errors` 비교.
4. `skew_max_ms` 가 `--max-skew-ms` 안에 드는지. 넘으면 값을 넓히지 말고
   `mono_fallback` 이 왜 나는지 먼저 본다.
5. 자동 노출·화이트밸런스가 좌우에서 따로 노는지 육안 확인.
   스테레오 캘리브레이션은 두 카메라의 노출이 같다고 가정한다.
   따로 논다면 `v4l2-ctl -c exposure_auto=1` 로 고정해야 한다.
6. `kb_per_frame` 실측. DES-31 C-8 의 장당 100 KB 가정을 여기서 확정한다.

## 남은 것 (이 이슈 범위 밖)

- 스테레오 캘리브레이션·거리 계산 — AI 쪽 planned extension
- 흔들림 보정 — IMU(-23) 와 묶어야 한다
- 링버퍼 적재 — floaq-146.
  JPEG 바이트를 그대로 보관하는 편이 메모리에 유리하다(디코드하지 않아도 되게
  `subscriber.py` 가 헤더와 이미지를 분리해 둔 이유다)
- 렌즈 오염·초점 이상 판정 — floaq-20.
  이 모듈은 장치·수집 계층만 보고 `service.health()` 로 내보낸다
- NVJPG 하드웨어 인코딩 오프로드 — DES-31 §5 #6. 지금은 CPU 인코딩이고
  `encode_ms` 통계가 판단 근거가 된다

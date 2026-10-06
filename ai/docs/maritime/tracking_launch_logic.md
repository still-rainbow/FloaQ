# 물속 사람 추적 및 부표 투하 판단 로직

작성일: 2026-09-18

대상: v33 YOLO11n 탐지 결과를 받아 tracking과 투하 후보 판단을 수행하는 Python 코드

## 1. 목적과 범위

이 문서는 모델 학습 이후의 영상 처리 로직을 정의한다. 목표는 한 프레임에서 물속 사람을 놓친 경우를 여러 프레임의 탐지 결과로 보완하면서, 배 위 사람에게 부표를 투하하지 않는 것이다.

Python 모듈의 책임은 다음과 같다.

1. YOLO의 낮은 confidence 후보를 보존한다.
2. 같은 대상을 여러 프레임에 걸쳐 추적한다.
3. track별 클래스 근거를 누적해 물속 사람과 배 위 사람을 구분한다.
4. 일시적인 미탐에도 track을 일정 시간 유지한다.
5. 투하 가능 여부와 사유를 구조화된 결과로 반환한다.
6. 사건 단위 Recall과 배 위 사람 오투하율을 계산할 수 있는 로그를 남긴다.

실제 모터 제어, 발사 장치 통신, 거리 보정 및 탄도 계산은 별도 모듈의 책임이다. 이 모듈은 장치를 직접 동작시키기보다 `launch_ready` 판단과 목표 정보를 전달한다.

## 2. 모델과 클래스 의미

최종 해상 후보는 다음 가중치다.

- 파일: `experiments/maritime/models/production/maritime_v33_yolo11n_seed44_best.pt`
- SHA256: `891bf2e3b6980f4232e6ea55d4add03fa68b2dc020c596a2122b715af434e7ad`
- 모델: YOLO11n
- 입력 크기: 640
- 클래스 순서: `0 animal`, `1 float`, `2 person`, `3 person_with_float`

가중치 호환성을 위해 모델의 클래스 이름과 ID를 변경하지 않는다. 애플리케이션에서는 다음 의미로 해석한다.

| 모델 클래스 | 애플리케이션 의미 | 투하 대상 |
|---|---|---|
| `animal` | 동물 | 아니오 |
| `float` | 부유물 또는 사람과 혼동되는 물체 | 아니오 |
| `person` | 물에 빠진 사람 | **예** |
| `person_with_float` | 이름과 달리 사실상 배에 타고 있는 사람 | **아니오** |

코드에서는 `person_with_float`를 `person_on_boat` 의미의 별칭으로 사용해도 된다. 모델 출력의 원본 `class_id=3`, `class_name=person_with_float`도 로그에 보존한다.

두 사람 클래스를 합쳐 Recall을 계산하지 않는다. 구조 임무의 Recall은 물속 `person` 정답 중 투하 대상으로 확정된 비율이다.

## 3. 현재 성능과 threshold

v33 test 248장, 물속 `person` 정답 203개에서 seed44 결과는 다음과 같다.

| Confidence | Recall | Precision | TP | FP | FN |
|---:|---:|---:|---:|---:|---:|
| 0.25 | 79.31% | 75.59% | 161 | 52 | 42 |
| 0.22 | 80.79% | 73.54% | 164 | 59 | 39 |
| 0.19 | 80.79% | 71.30% | 164 | 66 | 39 |
| 0.10 | 83.74% | 62.73% | 170 | 101 | 33 |
| 0.05 | 85.22% | 52.74% | 173 | 155 | 30 |
| 0.03 | 86.70% | 45.24% | 176 | 213 | 27 |
| 0.01 | 88.18% | 29.54% | 179 | 427 | 24 |

`0.22`는 한 프레임의 균형형 기준이다. tracking 입력을 0.22로 제한하면 그 아래 점수의 물속 사람을 이후 로직에서 복구할 수 없다. 탐지 후보 기준과 최종 투하 기준을 분리한다.

- 후보 탐지 기준: `candidate_confidence=0.03~0.05`
- 강한 단일 탐지 기준: `strong_confidence=0.22`
- NMS IoU: `0.70`
- 최종 투하: 한 프레임 confidence가 아니라 track 누적 근거로 결정

0.03과 0.05 중 어느 값을 사용할지는 새 시연 영상의 사건 단위 Recall과 배 위 사람 오투하율로 정한다.

## 4. Detection 입력 계약

```python
@dataclass(frozen=True)
class Detection:
    frame_id: int
    timestamp_s: float
    xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
```

- 좌표는 현재 프레임 픽셀 기준 `x1, y1, x2, y2`다.
- timestamp는 단조 증가해야 한다.
- `confidence < candidate_confidence`인 탐지는 tracking에 전달하지 않는다.
- 원본 클래스 ID와 이름을 임의로 바꾸지 않는다.
- 프레임 누락, 지연 또는 순서 역전을 로그에 남긴다.

## 5. Track 상태

```python
@dataclass
class TargetTrack:
    track_id: int
    first_seen_s: float
    last_seen_s: float
    age_frames: int
    detected_frames: int
    missed_frames: int
    recent_hits: deque[bool]
    class_evidence: dict[str, float]
    confidence_history: deque[float]
    center_history: deque[tuple[float, float]]
    latest_xyxy: tuple[float, float, float, float]
    state: str
    launch_requested: bool
```

`class_evidence`는 마지막 프레임의 클래스만 사용하지 않고 track 기간의 점수를 누적한다. 최근 프레임에 더 큰 가중치를 주는 지수이동평균을 사용할 수 있다.

```text
SEARCHING → CANDIDATE → CONFIRMED_TARGET → LAUNCH_READY
                      ↘ BLOCKED_ON_BOAT
모든 활성 상태 → LOST
```

- `CANDIDATE`: 낮은 confidence를 포함한 물속 사람 후보
- `CONFIRMED_TARGET`: 여러 프레임의 누적 근거가 물속 사람 조건을 만족
- `BLOCKED_ON_BOAT`: 배 위 사람 근거가 우세해 투하 차단
- `LAUNCH_READY`: 위치, 시간 및 장치 전제 조건까지 만족
- `LOST`: 허용된 누락 프레임 또는 시간 초과

## 6. 다중 프레임 초기 설정

값은 코드 상수가 아니라 설정 파일에서 관리한다.

```yaml
candidate_confidence: 0.05
strong_confidence: 0.22
confirmation_window_frames: 5
minimum_hits_in_window: 2
maximum_missed_frames: 10
minimum_track_age_frames: 3
class_evidence_decay: 0.85
```

권장 동작:

1. confidence 0.03~0.05 이상의 관련 탐지를 tracker에 입력한다.
2. 최근 5프레임 중 최소 2회 물속 `person` 근거가 있으면 후보를 유지한다.
3. 한두 프레임에서 탐지가 사라져도 track을 바로 삭제하지 않는다.
4. confidence 0.22 이상의 강한 탐지는 더 큰 가중치를 줄 수 있다.
5. `person_with_float` 근거가 반복되면 배 위 사람으로 차단한다.
6. 클래스가 프레임마다 바뀌면 마지막 결과가 아니라 누적 근거로 판단한다.

`5프레임 중 2회`는 시작값이다. 카메라 FPS가 다르면 최근 0.5초 동안 2회처럼 시간 기준으로 설정한다.

## 7. 투하 승인과 차단

`launch_ready=True`가 되려면 다음 조건을 모두 만족해야 한다.

1. 물속 `person` 누적 근거가 설정 기준 이상이다.
2. `person_with_float`, 즉 배 위 사람 근거가 차단 기준보다 낮다.
3. 최소 확인 시간 또는 hit 수를 만족한다.
4. 대상 위치가 여러 프레임에서 안정적이다.
5. 거리 또는 좌표 변환 결과가 유효 범위에 있다.
6. 프레임과 위치 정보가 오래되지 않았다.
7. 같은 track에 이미 투하 요청을 보내지 않았다.
8. 장치 제어 계층이 준비 상태다.

다음 상황에서는 투하를 차단한다.

- 배 위 사람 근거가 우세함
- animal 또는 float와 지속해서 혼동됨
- 대상 위치가 급격히 변하거나 track ID가 불안정함
- 거리 계산 실패 또는 사거리 밖
- 영상 정지, timestamp 역전, 과도한 처리 지연
- 같은 track에 이미 투하 요청 완료

## 8. 판단 결과 계약

```python
@dataclass(frozen=True)
class LaunchDecision:
    frame_id: int
    timestamp_s: float
    track_id: int
    state: str
    launch_ready: bool
    reason_code: str
    target_xy: tuple[float, float] | None
    predicted_xy: tuple[float, float] | None
    target_confidence: float
    on_boat_confidence: float
    evidence_frames: int
    model_sha256: str
```

권장 `reason_code`:

- `TARGET_CONFIRMED`
- `INSUFFICIENT_HISTORY`
- `BLOCKED_ON_BOAT`
- `TARGET_LOST`
- `UNSTABLE_POSITION`
- `INVALID_DISTANCE`
- `STALE_FRAME`
- `ALREADY_REQUESTED`

장치 제어 모듈은 `launch_ready`뿐 아니라 reason, timestamp, track ID와 위치 유효성을 함께 확인한다.

## 9. 위치 예측

탐지 시점과 실제 투하 시점 사이의 지연을 고려한다. 최근 center history에서 속도를 추정해 투하 예정 시점의 위치를 예측한다. 초기 구현은 일정 속도 모델 또는 Kalman Filter를 사용할 수 있다.

위치 예측은 Recall을 높이는 기능이 아니라 탐지된 대상에 부표를 정확히 전달하기 위한 기능이다. 예측 위치가 불안정하면 현재 위치로 무조건 투하하지 않고 `UNSTABLE_POSITION`으로 차단한다.

## 10. 로그

JSON Lines 또는 구조화된 CSV로 다음 정보를 남긴다.

- 실행 ID와 Git commit
- 모델 경로와 SHA256
- threshold 및 tracking 설정 전체
- 영상 ID, frame ID, timestamp
- 원본 detection 전체
- detection과 track 연결 결과
- track별 클래스 누적 근거
- 상태 전이와 reason code
- 목표 및 예측 좌표
- 투하 요청 및 중복 차단 여부
- 프레임 처리 시간과 누락 프레임 수

특정 투하 또는 미투하 결정이 왜 발생했는지 로그만으로 재현할 수 있어야 한다.

## 11. 평가 지표

| 지표 | 정의 |
|---|---|
| Target event Recall | 물속 사람 사건 중 제한 시간 안에 `CONFIRMED_TARGET`이 된 비율 |
| Launch-ready Recall | 물속 사람 사건 중 위치 조건까지 만족해 `LAUNCH_READY`가 된 비율 |
| On-boat false-launch rate | 배 위 사람 사건 중 `LAUNCH_READY`가 잘못 발생한 비율 |
| Background false alerts | 빈 바다·파도·반사광에서 발생한 confirmed target 수 |
| Time to confirmation | 첫 등장부터 `CONFIRMED_TARGET`까지 걸린 시간 |
| Duplicate request rate | 같은 실제 사람에게 둘 이상의 투하 요청이 발생한 비율 |
| Track fragmentation | 한 사람을 여러 track으로 분리한 횟수 |

frame 기준 Recall 80.79%를 시스템 구조 성공률로 해석하지 않는다. 같은 사람이 여러 프레임에 나타나므로 event Recall은 높아질 수 있지만, 역광·가림·초소형 객체처럼 연속으로 놓치는 장면은 tracking만으로 복구되지 않는다.

## 12. 검증 영상

1. 물속 사람만 존재
2. 배 위 사람만 존재
3. 물속 사람과 배 위 사람이 동시에 존재
4. 사람이 배 바로 옆 물속에 존재
5. 사람 일부만 수면 위에 보임
6. 멀리 있는 작은 사람
7. 파도, 역광, 반사광, 야간 또는 저조도
8. 동물과 부유물만 존재
9. 빈 바다와 빈 배
10. 일시적인 가림과 카메라 흔들림

영상은 원본 촬영 단위로 train/validation/test와 분리한다. 같은 영상의 인접 프레임이 서로 다른 split에 들어가면 사건 단위 성능이 과대평가될 수 있다.

## 13. 권장 Python 모듈 구조

```text
src/
├─ detector.py          # YOLO 로딩과 낮은 confidence detection 생성
├─ tracker.py           # ByteTrack/BoT-SORT 연결과 track 갱신
├─ target_policy.py     # 클래스 누적, 상태 전이, 투하 승인/차단
├─ trajectory.py        # 좌표 안정성, 속도 및 미래 위치 예측
├─ launch_interface.py  # 장치 계층으로 LaunchDecision 전달
└─ event_metrics.py     # 사건 Recall, 오투하율, 확인 시간 계산
```

실제 파일명은 현재 구현에 맞출 수 있다. YOLO 추론, tracking, 투하 정책과 실제 장치 호출은 함수 또는 클래스로 분리해 녹화 영상 테스트에서 장치 호출을 가짜 구현으로 교체할 수 있어야 한다.

## 14. 의사코드

```python
for frame_id, timestamp_s, frame in video_stream:
    detections = detector.predict(frame, conf=settings.candidate_confidence)
    tracks = tracker.update(detections, timestamp_s)

    for track in tracks:
        policy.update_evidence(track)
        decision = policy.decide(track, frame_id, timestamp_s)
        audit_log.write(detections, track, decision)

        if not decision.launch_ready:
            continue

        predicted = trajectory.predict(track, settings.launch_latency_s)
        final_decision = policy.with_position(decision, predicted)

        if final_decision.launch_ready:
            launch_interface.request_once(final_decision)
```

## 15. 완료 기준

- 저장 영상에서 실제 장치 없이 전체 파이프라인 재생 가능
- 모든 결정에 reason code와 재현 가능한 로그 기록
- 한두 프레임 미탐에도 track 유지
- 배 위 사람 track을 `BLOCKED_ON_BOAT`로 차단
- 같은 track에 투하 요청이 한 번만 발생
- threshold와 tracking 값을 설정에서 변경 가능
- 사건 단위 Recall, 배 위 사람 오투하율, 확인 시간 보고
- 모델 SHA256과 설정을 결과에 함께 저장

초기 목표는 물속 사람 event Recall 95% 이상, 평가된 배 위 사람 영상의 오투하 0건, 중복 투하 요청 0건이다. 새 영상의 기준선을 측정한 뒤 장치 요구사항에 따라 조정한다.

## 16. 관련 자료

- 전체 데이터 및 실험 기록: `EXPERIMENT_HISTORY.md`
- 최종 모델 선정: `docs/model_selection.md`
- threshold 설정: `configs/maritime/inference_thresholds.yaml`
- 모델 후보 비교: `experiments/maritime/reports/local/final_candidate_test_20260918_093554_638471/report.html`

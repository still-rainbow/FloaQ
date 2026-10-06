# 최종 모델 선정 — 2026-09-18

전체 데이터 버전과 실험 흐름은 `experiment_history.md`에 정리했다.

## 결론

해상 구조용 최종 후보는 `maritime_v33_yolo11n_seed44_best.pt`다.

운용상 `person`은 물에 빠진 부표 투하 대상이고, `person_with_float`는 이름과 달리 사실상 배에 타고 있는 사람을 뜻하는 투하 비대상이다. 부표 투하 판단에서는 `person` Recall을 우선하고 두 사람 클래스를 합산하지 않는다. 가중치 호환성을 위해 클래스 ID와 이름은 유지하고 애플리케이션에서 `person_with_float → person_on_boat`로 해석한다.

- 데이터: A208 v33
- 클래스 ID: 0 animal, 1 float, 2 person, 3 person_with_float
- 학습: YOLO11n, 640px, 50 epoch, batch 16, SGD, lr0 0.005, Mosaic 1.0, seed 44
- 가중치 SHA256: `891bf2e3b6980f4232e6ea55d4add03fa68b2dc020c596a2122b715af434e7ad`
- 원본 실행: `v33_sgd_lr_0p005_seed44_20260917_132134_407967`

fish가 필요한 시연용 최종 후보는 `demo_v8_yolo11s_seed42_best.pt`다. 두 모델은 데이터와 클래스가 다르므로 점수로 직접 순위를 매기지 않는다.

- 데이터: A208 Demo v8
- 클래스 ID: 0 animal, 1 fish, 2 float, 3 person
- 학습: YOLO11s, 960px, 50 epoch, batch 16, optimizer auto, seed 42
- 가중치 SHA256: `7ecc66fc8111f33b01279bb4db9c54966a1264ad0000e0841f47b322f564215c`
- 원본 실행: `demo_v8_20260916_150822_444036`

## 해상 구조용 모델 선정 근거

### 1. 모델과 해상도

동일한 v25 validation에서 YOLO11n의 person AP50은 82.91%였다. YOLO11s 75.89%, YOLO26n 77.83%, YOLO26s 80.09%보다 높았고 가중치도 5.47MB로 작았다. YOLO11n의 960px 결과는 person AP50 71.78%로 640px보다 낮아 640px를 선택했다.

### 2. 증강과 optimizer

Mosaic OFF의 person AP50은 76.45%로 기준 실행보다 낮아 Mosaic 1.0을 유지했다. seed 43·44 평균에서 AdamW 대비 SGD가 전체 mAP50을 38.45%에서 43.17%로 높였으며 person AP50은 76.69%에서 77.07%로 비슷했다. 같은 Recall 약 80%에서 SGD가 두 seed 모두 FP가 적었다.

### 3. SGD 학습률

v25 seed 43·44 평균은 다음과 같다.

| lr0 | 전체 mAP50 | person AP50 | person AP50-95 | person_with_float AP50 |
|---:|---:|---:|---:|---:|
| 0.00125 | 43.17% | 77.07% | 39.38% | 10.48% |
| 0.005 | **43.99%** | **82.16%** | 43.33% | **17.93%** |
| 0.01 | 38.54% | 80.06% | **43.46%** | 8.63% |

person AP50, 전체 성능, person_with_float를 함께 고려해 lr0 0.005를 선택했다.

### 4. v33 반복 재현성

v33은 person_with_float 학습 객체가 v25의 51개에서 132개로 증가했다. 같은 설정에서 seed만 바꾼 validation 결과는 다음과 같다.

| Seed | 전체 mAP50 | person AP50 | person AP50-95 | person_with_float AP50 | person_with_float AP50-95 |
|---:|---:|---:|---:|---:|---:|
| 43 | 65.73% | 82.72% | 44.78% | 79.06% | 51.89% |
| 44 | **69.22%** | **85.85%** | **45.10%** | **86.05%** | 56.60% |
| 45 | 65.99% | 79.67% | 43.68% | 85.09% | **58.27%** |

seed 44는 전체·person·person_with_float AP50의 균형이 가장 좋아 validation의 1차 후보로 선택했다.

### 5. 동일 test에서 최종 후보 비교

최종 결정일에는 지금까지의 유효 후보 8개를 같은 v33 test 248장, 442개 객체, 640px 조건으로 다시 평가했다. 최초 비교는 `person mAP50`, `person mAP50-95`, `person_with_float mAP50`, 전체 mAP50 순으로 정리했다. 구조 안전 검토에서는 실제 사람을 놓치는 FN의 비용을 가장 크게 보고 person Recall을 우선 확인했다.

| 후보 | 전체 mAP50 | person mAP50 | person mAP50-95 | person_with_float mAP50 | CPU 추론/장 |
|---|---:|---:|---:|---:|---:|
| v33 11n SGD 0.005 seed44 | 74.03% | **81.30%** | **41.91%** | 79.41% | 15.52ms |
| v33 11n SGD 0.005 seed45 | **74.68%** | 78.43% | 38.62% | **84.92%** | 15.74ms |
| v33 11n SGD 0.005 seed43 | 74.44% | 77.16% | 38.70% | 82.81% | 15.86ms |
| v25 11n SGD 0.005 seed44 | 55.42% | 77.54% | 36.79% | 38.33% | 15.01ms |
| v25 11n SGD 0.005 seed43 | 52.67% | 76.98% | 38.81% | 23.29% | 16.16ms |
| v25 26s auto seed42 | 54.59% | 73.74% | 34.19% | 33.99% | 37.70ms |
| v25 11n AdamW seed42 | 48.53% | 71.06% | 34.05% | 16.41% | 15.51ms |
| v25 11s auto seed42 | 49.17% | 71.06% | 35.53% | 21.10% | 37.59ms |

seed 44는 핵심 클래스인 person에서 mAP50과 mAP50-95가 모두 가장 높고, 평가 운용점의 person Recall도 후보 중 가장 높은 77.83%다. seed 45는 전체와 person_with_float에서 더 높지만 person Recall이 65.02%다. 따라서 Recall 우선으로 다시 검토해도 사람 구조용 최종 모델은 seed 44다. 전체 비교 원본은 `experiments/maritime/reports/local/final_candidate_test_20260918_093554_638471/report.html`과 같은 폴더의 `comparison.csv`에 보관했다.

클래스 의미를 반영한 추가 test 점검에서도 confidence 0.22, IoU 0.5 기준 배 위 사람 정답 54개를 `person`으로 잘못 탐지한 사례는 0개였고, 물속 person 정답 203개를 배 위 사람 클래스로 탐지한 사례도 0개였다. 현재 test에서 주된 한계는 두 사람 클래스의 상호 혼동이 아니라 물속 person의 미탐이다.

이번 비교로 v33 test를 모델 선택에 사용했으므로 이 split은 더 이상 완전히 독립적인 최종 평가셋이 아니다. 이후 일반화 성능을 주장할 때는 새 촬영 영상 또는 새 holdout을 한 번만 평가한다.

### 6. 선택 모델의 test 결과

v33 test 248장, 442개 객체에서 다음 결과를 얻었다.

| 클래스 | mAP50 | mAP50-95 |
|---|---:|---:|
| 전체 | 74.03% | 42.02% |
| animal | 68.17% | 35.76% |
| float | 67.22% | 36.39% |
| person | 81.30% | 41.91% |
| person_with_float | 79.41% | 54.01% |

Validation에서 선택한 confidence를 그대로 적용한 고정 IoU 0.5 결과다.

| 클래스 | confidence | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| person | 0.19 | 164 | 66 | 39 | 71.30% | 80.79% |
| person_with_float | 0.68 | 41 | 15 | 13 | 73.21% | 75.93% |

Validation Recall은 person 86.03%, person_with_float 88.89%였고 test에서는 각각 80.79%, 75.93%로 낮아졌다. 이 차이는 최종 성능의 한계로 기록하며 test에 맞춰 confidence를 다시 조정하지 않는다.

### 7. Recall 우선 운용 검토

AP는 confidence 전 구간을 요약하므로 모델 비교에는 유용하지만 구조 현장의 FN 위험을 직접 나타내지 않는다. 운용 시에는 물에 빠진 `person`의 목표 Recall을 먼저 정하고 이를 만족하는 confidence 중 FP가 가장 적은 값을 고른다. `person_with_float`는 배 위 사람에게 투하하지 않도록 구분하는 보조 클래스이며, 두 클래스를 합산한 Recall은 투하 성공 지표로 사용하지 않는다.

저장된 validation 예측에서 person Recall 90%를 목표로 분석하면 confidence 0.03에서 TP 123, FP 173, FN 13, Precision 41.55%, Recall 90.44%다. person_with_float는 confidence 0.16에서 TP 33, FP 26, FN 3, Precision 55.93%, Recall 91.67%다. 기존 균형형 confidence 0.19와 0.68보다 Recall은 높지만 FP가 늘어난다.

현재 val/test에는 빈 바다 배경이 없으므로 이 고Recall 기준을 바로 기본값으로 바꾸지 않는다. 새 빈 바다·파도·반사광 영상과 배 위 사람 영상에서 오투하율을 측정한다. 여러 프레임 연속 탐지나 추적을 이용해 FP를 줄인 뒤 구조 모드의 기준으로 확정한다. 배 위 사람이 v33에서 `person`으로 잘못 라벨링된 경우는 먼저 수정한다.

## 시연용 모델 검증

Demo v8 test는 100장, 178개 객체이며 21장은 모든 클래스의 빈 배경이다.

| 클래스 | mAP50 | mAP50-95 |
|---|---:|---:|
| 전체 | 90.45% | 61.32% |
| animal | 91.98% | 56.55% |
| fish | 98.79% | 79.45% |
| float | 81.91% | 50.61% |
| person | 89.10% | 58.67% |

confidence 0.25, IoU 0.5에서 person은 TP 49, FP 13, FN 7로 Precision 79.03%, Recall 87.50%였다. 화면 단위 사람 존재 판정은 TP 55, FP 1, FN 1, TN 43으로 Precision과 Recall이 각각 98.21%였다. 화면 단위 수치는 박스 위치와 클래스 혼동을 확인하지 않으므로 박스 지표와 함께 사용한다.

## 알려진 한계

- v33의 train/validation/test 사이에 동일 원본명과 유사·좌우 반전 장면 후보가 있다. 독립 장면 성능이 과대평가될 가능성이 있다.
- v33 validation과 test에는 빈 배경 이미지가 없어 빈 바다에서의 오경보율을 측정하지 못했다.
- 일부 person_with_float 정답은 배 전체를 감싸며 라벨 기준을 다시 확인할 필요가 있다.
- v25와 v33은 라벨 및 평가 이미지가 달라 버전 간 점수를 직접적인 성능 향상량으로 해석하지 않는다.
- 저장된 처리 속도는 해당 서버의 GPU 또는 CPU 측정값이며 실제 엣지 장치 FPS가 아니다.

## 사용 원칙

- 두 가중치의 클래스 순서를 바꾸지 않는다.
- 해상 모델의 person과 person_with_float는 별도 클래스로 유지한다.
- 해상 모델은 `inference_thresholds.yaml`의 클래스별 confidence를 적용한다.
- 시연용 모델은 confidence 0.25를 초기값으로 사용한다.
- 배포 전 새 촬영 영상, 빈 바다, 파도, 배, 동물, 역광, 소형 사람 장면을 확인한다.
- 원본 데이터와 test 결과가 바뀌면 모델 SHA256과 평가 기록을 함께 갱신한다.

# Architecture

## Baseline flow

`person/animal/float dataset YAML → preprocessing (optional) → 3-class YOLO detector → person 중심 evaluation → failure analysis`

Detector는 세 클래스를 모두 구분한다. 현재 제품 관점의 1차 판단 대상은 `person`이며, evaluation은 전체 클래스 metric과 함께 person의 precision, recall, 미탐, 오탐을 우선 확인한다.

Detection 결과는 box coordinates, confidence, class id를 보존하여 이후 tracker 입력으로 사용할 수 있게 한다.

## Planned extensions

- Tracking: frame 간 person identity와 trajectory 유지
- Stereo: calibration 기반 거리 추정, 출력 단위 명시
- Low-light: baseline과 독립적으로 활성화하고 동일 test set에서 효과 비교

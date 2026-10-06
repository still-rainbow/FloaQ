# 검증된 실험 기법

현재 실험 이력에서 반복 사용할 가치가 확인된 항목이다.

- 데이터셋 fingerprint와 manifest를 실행마다 저장한다.
- train/validation/test 간 파일명, 유사 장면 및 증강 누수를 split audit로 확인한다.
- 모델 비교 시 데이터 fingerprint, split, image size와 평가 조건을 고정한다.
- seed 반복으로 단일 실행의 우연성을 확인한다.
- 구조용 모델은 전체 mAP보다 `person` recall과 false negative를 먼저 검토한다.
- confidence는 모델 비교용 AP와 실제 운용점을 분리해 validation에서 결정한다.
- 빈 바다·파도·역광 영상은 객체 데이터셋과 별도로 false alert 평가에 사용한다.
- 재사용되는 batch runner, 후보 비교, threshold 분석 로직은 Notebook에 복제하지 않고 `src/`로 승격한다.

수치와 선택 근거는 `docs/experiment_history.md`와 `docs/model_selection.md`를 따른다.

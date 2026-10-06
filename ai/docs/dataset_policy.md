# Dataset Policy

- 데이터와 영상은 Git에 commit하지 않는다.
- train/validation/test split을 고정하고 누수를 점검한다.
- 데이터 버전, class 정의, 수집 출처와 라이선스를 기록한다.
- 클래스는 `person`, `animal`, `float`로 관리하고 dataset YAML의 class id 순서를 고정한다.
- 1차 탐지 목표는 `person`이며, 사람의 가림, 소형 객체, 역광 사례와 `animal`/`float`로 잘못 분류된 사례를 문서화한다.
- 데이터 경로는 환경별 dataset YAML에서 관리한다.

# FloaQ AI

사람·동물·부유체 3개 클래스를 탐지하는 학습·평가 모듈과
추적, 목표 선택, 스테레오 거리 추정 및 조준 계산 모듈입니다.
주요 평가는 person 클래스의 미탐·오탐을 우선합니다.

Python 3.11과 uv를 사용합니다. GPU 환경에 맞는 PyTorch 인덱스를
`pyproject.toml`에서 확인한 뒤 설치합니다. 기본 cu126 설정은 기존 GPU 환경을 위한 설정입니다.

```bash
uv sync --locked
uv run python -m src.train --help
uv run python -m src.evaluate --help
uv run python -m src.predict --help
uv run python -m pytest tests
```

학습 전에 `configs/baseline.yaml`의 데이터 경로, GPU 및 출력 경로를 자기 환경에 맞춥니다.
학습 데이터, 모델 weight, 실험 결과와 개인 notebook은 공개 사본에 포함하지 않습니다.
기존 `models/README.md`의 로컬 모델 파일은 별도로 준비해야 합니다.

- [인터페이스](docs/interface.md)
- [데이터 정책](docs/dataset_policy.md)
- [스테레오·조준](docs/stereo_targeting.md)

카메라 교정과 발사 속도가 확인되지 않으면 해당 계산을 실제 장치 명령에 사용하지 않습니다.

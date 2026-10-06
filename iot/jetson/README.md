# NVIDIA Jetson IoT

Jetson은 시스템 Python 3.10.12와 시스템 패키지를 상속하는 가상환경을 사용하며, Python 의존성은 이 폴더의 독립적인 uv 프로젝트로 관리합니다.

대상 환경(사용자 제공): Jetson Orin Nano 8GB Super (p3767-0005), JetPack 6.2.1 / L4T 36.4.7 / CUDA 12.6 / cuDNN 9.3 / TensorRT 10.3.

Pi 와 통신하는 부분은 `floaq_jetson` 패키지가 담당합니다. 쓰는 법은
[SDK.md](SDK.md) 를 보세요.

## 패키지 소스

| 패키지 | 설치 소스 |
| --- | --- |
| torch 2.8.0 / torchvision 0.23.0 | `https://pypi.jetson-ai-lab.io/jp6/cu126` 전용 인덱스 |
| onnxruntime-gpu 1.24.0 | `wheels/onnxruntime_gpu-1.24.0-cp310-cp310-linux_aarch64.whl` |
| TensorRT / OpenCV 등 JetPack 패키지 | 시스템 Python 패키지 상속 |
| 기타 Python 패키지 | 기본 PyPI |

전용 인덱스는 `explicit = true`로 지정하고 torch와 torchvision만 연결했습니다. ONNX Runtime은 사용자가 Jetson에 존재한다고 확인한 파일 경로를 그대로 사용합니다. 해당 파일은 lock 생성과 설치 때 모두 필요합니다.

제공한 원본의 CPU torch 2.13.0+cpu / torchvision 0.28.0 대신, 제시된 GPU 조합인 2.8.0 / 0.23.0을 지정했습니다. 전용 인덱스에 두 버전의 cp310/linux_aarch64 wheel이 있는 것은 확인했으나, 실제 GPU 동작은 보드에서 검증해야 합니다.

시스템 OpenCV를 사용하기 위해 pip OpenCV 배포판은 전이 의존성까지 `exclude-dependencies`로 제외합니다. **NumPy 2.2.6은 제공한 버전을 유지했습니다. 시스템 OpenCV가 NumPy 1.x ABI로 빌드되었다면 충돌할 수 있으므로 설치 후 반드시 검증해야 합니다.** 시스템 OpenCV가 애플리케이션의 요구 버전을 충족하는지도 확인합니다. 이 설정은 그 호환성을 보증하지 않습니다.

## 1. uv와 시스템 Python 준비

uv가 없다면 Linux 설치 명령을 실행하고 터미널을 다시 엽니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

저장소 루트에서 시작합니다.

```bash
cd iot/jetson
uv --version
uname -m
/usr/bin/python3.10 --version
test -f wheels/onnxruntime_gpu-1.24.0-cp310-cp310-linux_aarch64.whl
/usr/bin/python3.10 -c "import tensorrt, cv2; print(tensorrt.__version__); print(cv2.__version__, cv2.__file__)"
```

아키텍처는 aarch64, Python은 3.10.12인지 확인합니다. 위 명령 중 하나라도 실패하면 해당 원인을 해결한 뒤 진행합니다. 시스템 Python을 교체하거나 다운그레이드하지 않습니다.

`pyproject.toml`은 Python 자동 다운로드를 차단하고 시스템 Python만 선택하도록 설정했습니다. 아래 명령에서도 JetPack 인터프리터 경로를 명시합니다.

## 2. 가상환경 생성

**새 환경에서만** 다음 생성 명령을 실행합니다. 기존 `.venv`가 있다면 먼저 `pyvenv.cfg`와 실행 파일을 확인합니다. 다른 Python 또는 Windows에서 만든 환경이면 별도 이름으로 백업하고 새로 생성합니다. 기존 환경에 생성 명령을 반복 실행하지 않습니다.

```bash
uv venv --python /usr/bin/python3.10 --system-site-packages .venv
source .venv/bin/activate
python -c "import sys; print(sys.executable); print(sys.version); print(sys.base_prefix)"
cat .venv/pyvenv.cfg
```

`include-system-site-packages = true`인지 확인합니다. 생성된 가상환경을 장치 간에 복사하지 않습니다.

## 3. 최초 lock 생성 및 설치 — Jetson에서 실행

uv.lock은 포함되어 있습니다. 먼저 장치용 wheel을 위 경로에 준비하세요. 공개 사본에서 wheel 경로를 상대 경로로 변경했으므로 실제 Jetson에서 아래 명령으로 lock과 보드 환경의 정합성을 확인해야 합니다.

가상환경 준비 후 실제 wheel이 있는 Jetson에서 실행합니다.

```bash
uv lock --python /usr/bin/python3.10
```

성공하면 `uv.lock`이 생성됩니다. 이어서 실행합니다.

```bash
uv sync --locked --inexact --python /usr/bin/python3.10
python verify_environment.py
```

`--locked`는 lock을 임의로 갱신하지 않습니다. `--inexact`는 lock에 없는 수동 설치 패키지를 유지하지만, lock에 선언된 패키지의 버전 변경까지 막지는 않습니다. torch/torchvision/ONNX Runtime은 선언한 소스로 관리됩니다. 시스템 apt 패키지와 CUDA 라이브러리 버전은 uv.lock에 기록되지 않습니다.

lock 생성 중 패키지 버전 부재, Python 3.10 비호환, 인덱스 접속 오류 또는 의존성 충돌이 발생하면 해당 오류를 해결한 뒤 다시 생성합니다. 원본의 나머지 버전은 임의로 변경하지 않았습니다. 기존 설치 목록이 전체 의존성 해결에 성공한다는 보장은 없습니다.

## 4. 일상 작업

lock 생성 이후 새 터미널에서 실행합니다.

```bash
cd iot/jetson
source .venv/bin/activate
uv sync --locked --inexact --python /usr/bin/python3.10
python verify_environment.py
python main.py
```

패키지 추가는 이 폴더에서 `uv add --no-sync <package-name>`으로 수행하고, 위 동기화와 검증을 반복합니다. `--no-sync`를 지정해 먼저 의존성과 lock 변경을 검토합니다. 일반 패키지를 추가하면서 GPU 소스 설정을 제거하지 않습니다.

`verify_environment.py`는 Linux/aarch64, Python 버전, 시스템 패키지 상속, 주요 import, PyTorch CUDA 연산 및 ONNX Runtime GPU provider 등록을 확인합니다. 실패하면 종료 코드 1을 반환합니다. 실제 모델의 TensorRT/ONNX Runtime GPU 추론은 추가로 검증해야 합니다.

## 스테레오 조준

`scripts/live.sh`에 모드를 붙인다.

| 모드 | 하는 일 |
|---|---|
| `--aim` | 사람을 따라 `jetson/aim`만 보낸다. 사고·사진·신고를 만들지 않는다 |
| `--aim-detect` | 위 조준에 탐지·사진·신고까지 한 실행으로 붙인다. 시연용 |

```bash
./scripts/live.sh <PI_IP> --aim          # 조준만
./scripts/live.sh <PI_IP> --aim-detect   # 시연
```

⚠ **여기 인자는 발사를 막지 못한다.** 발사는 Pi 가 정한다 — `--servos`면 쏘고,
`--no-fire`(시험, `./scripts/dev.sh aim`)면 안 쏜다.

**카메라 좌우는 `--camera L=2,R=0`이다** (`live.sh` 기본값). 2026-09-23 에 발사관
뒤에서 오른쪽 렌즈를 가렸더니 video0 화면이 가려졌다 — video0 이 오른쪽 카메라다.
반대로 두면 두 시선이 앞에서 벌어져 미리보기에 `no stereo intersection`이 뜬다.

**계산 방식** (`floaq_jetson/_stereo_aiming.py`) — 좌우 각 영상에서 사람 상자의
가운데 한 점을 보는 방향으로 선을 긋고, 두 선이 만나는 곳을 목표로 본다.
체스보드 캘리브레이션이나 디스패리티는 쓰지 않는다. 카메라 위치·각도는
`configs/stereo_targeting.yaml`의 값(2026-09-21 수기 측정: 왼쪽 렌즈 x=−17.0cm, 오른쪽
렌즈 x=+18.5cm·안쪽 8.5°, 오른쪽 5.5°, 화각 52°)을 그대로 쓴다.

- **좌우 둘 다 사람을 잡아야** 조준을 보낸다. 한쪽만 보이면 거리를 모르므로 안
  보낸다(미리보기에 `person missing in L/R`). 단안 추정은 쓰지 않는다
- 목표에서 발사관 위치를 빼서 yaw·pitch·거리(발사관 기준 수평거리)를 낸다
- pitch 는 **포물선으로 푼다** — yaml `ballistics` 의 두 거리: `near_m`(아래 끝 −10°로
  쐈을 때 떨어지는 곳, 실측 20cm)과 `far_m`(위 끝 25°, 임시 45cm). 둘로 속도·높이를 풀고
  목표 거리에 떨어지는 발사각을 곡선 그대로 구한다. near 보다 가까우면 −10°, far 보다
  멀면 25°. 짧게 떨어지면 `far_m` 을 줄이고, 넘어가면 늘린다. 0°(수평)가 Pi 의 CH1 140 이다(09-23 실측).
  범위 밖이라고 버리지 않는다 — 버리면 좌우 조준까지 멈춘다
- 거리 3.0m 를 넘으면 버린다(`range rejected`). 좌우 2쌍이 안정돼야 보낸다
- 5초 상태줄의 `본것 {'L': …, 'R': …}`로 좌우가 무엇을 봤는지 본다(사람 = 3)

⚠ **로그의 `range=`는 발사관 회전축 기준**이다. 배 중심(원점)에서 잰 거리보다
27cm 짧게 나오는 게 정상이다(`launcher.position_m` z=0.270). 2026-09-23 에 배 중심
기준 두 점(0.60m·0.45m)으로 카메라 앞뒤 위치를 14.5cm 고쳤다(yaml 주석). 선미에서 잰
거리와 비교해서 카메라 각도를 잘못 고쳤다가 되돌린 적이 있다 — 기준점을 꼭 맞춘다.
거리는 카메라 안쪽 각도에 민감하다 — 카메라가 각각 1° 만 틀어져도 2m 가 2.59m 로
읽힌다. 카메라를 건드렸으면 알려진 거리에서 `range~`를 다시 본다. 거리가 틀려도 yaw·pitch 는 거의 안
틀어진다(같은 1° 오차에서 yaw 0.1°, pitch 1.1°) — 카메라와 발사관이 가까워서다.

`floaq_jetson/stereo_calibrate.py`(체스보드)는 지금 조준 경로가 쓰지 않는다.
`configs/stereo_calibration_*backup.npz`는 1280x720 으로 만든 것이라 640x480 만
내는 지금 카메라로는 쓸 수 없다.

Pi 에서는 `./scripts/dev.sh aim`(시험, 조준만)이나 `./scripts/dev.sh pi --servos`(실전,
발사)로 받는다.
수동 서보 도구(`2servo.py`)와 동시에 돌리지 않는다.

## 관리 파일

- `pyproject.toml`: 현재 의존성과 소스의 기준 파일
- `.python-version`: Python 3.10.12 지정
- `uv.lock`: Jetson에서 생성 후 pyproject.toml과 함께 커밋
- `requirements.snapshot.txt`: 사용자가 제공한 원본 57개 항목, 참고용
- `requirements.txt`: 이전 pip 방식의 후보 목록, 참고용이며 현재 설치에 사용하지 않음
- `.venv`, wheel 파일: Git 제외

다른 Jetson에서도 같은 절대 경로에 ONNX Runtime wheel이 필요합니다. 경로를 바꾸면 소스 설정을 수정하고 lock을 다시 생성합니다.

## 참고

- [uv 패키지별 소스 설정](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources)
- [uv 설정: Python 선택 및 의존성 제외](https://docs.astral.sh/uv/reference/settings/)
- [uv lock 및 sync](https://docs.astral.sh/uv/concepts/projects/sync/)

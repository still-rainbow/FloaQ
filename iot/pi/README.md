# Raspberry Pi IoT

Python 3.13.5 기반 Raspberry Pi 애플리케이션입니다. 제공된 41개 의존성을 `pyproject.toml`에 지정했으며 원본은 `requirements.snapshot.txt`에 보존합니다. Pi5 Neopixel 패키지는 Python 3.11 이상이 필요하므로 Jetson의 Python 3.10.12 환경과 분리합니다.

아래 명령은 Raspberry Pi의 Linux에서 이 폴더로 이동한 뒤 실행합니다. GPIO 관련 패키지는 Windows 실행 대상이 아닙니다.

```bash
uv sync --locked
uv run python --version
uv run python main.py
```

`uv.lock` 생성과 설정 일치 검증을 완료했습니다. `uv sync --locked`는 커밋된 lock을 변경하지 않고 설치합니다.

`uv run python --version` 결과가 `Python 3.13.5`인지 확인합니다. 기존 3.10.12 가상환경이 있으면 재생성이 필요하며, 가상환경에만 설치해 둔 패키지는 먼저 기록합니다.

네이티브 확장 빌드 또는 GPIO/I2C 접근 오류는 해당 보드의 빌드 도구, 라이브러리 및 장치 권한을 확인합니다. lock 생성 성공만으로 하드웨어 동작을 보증하지 않습니다.

## 실장비 조준·발사와 발사 없는 시험

`--servos`(옛 이름 `--aim-only-servos`)는 PCA9685의 CH0 yaw와 CH1 pitch를 구동하고
**기본으로 발사합니다** — 조준이 `--fire-stable-count`회(기본 1회) 연속 안정되면
0.3초(`--fire-settle-seconds`) 뒤 CH2를 정방향으로 1.3초 돌려 부표를 발사하고,
중립 0.5초 뒤 역방향으로 1.0초 감은 다음 중립으로 멈춥니다.
정방향 시간은 `--ch2-max-seconds`로 바꿀 수 있습니다. 켜자마자 왼쪽·아래
(CH0 120, CH1 150 — `2servo.py`와 같은 명령값)를 봅니다(`--start-ch0`/`--start-ch1`,
이 자세로는 쏘지 않음). 시험으로
조준만 볼 때는 `--no-fire`를 붙입니다(CH2를 열지 않음). 서보 규약은 `2servo.py`와 같습니다:
주소 `0x60`, 50Hz, 명령값 0~180 → 500~2500µs (`floaq/adapters/servokit.py`의
`POSITION_PULSE_US`). yaw 기본 보정은 `-15°→101.25`, `0°→90`, `+15°→78.75`이며
명령값 90 초과가 왼쪽입니다 (2026-09-23 실측, 발사관 뒤에서 봄).

```bash
uv run python main.py \
  --ship-id <SHIP_UUID> \
  --db floaq.db \
  --servos --no-fire
```

방향을 의심하면 코드를 보지 말고 Jetson 을 끈 채 `jetson/aim`에 각도를 직접 보내
확인한다. yaw 가 보정 범위 **밖**이면 서보가 움직이지 않아(예외) 반대로 도는 것과
구분이 안 되므로 범위 안 각도로 본다. 방향이 반대로 확인되면 양 끝 명령값을
맞바꾼다(`--yaw-cal=-15:78.75 --yaw-cal=0:90 --yaw-cal=15:101.25`). 더 넓게
움직이려면 보정점을 `--yaw-cal=<YAW_DEG>:<SERVO_COMMAND>` 형식으로 두 개 이상 준다.

실행 중 Pi 터미널에는 계산된 yaw/pitch와 CH0/CH1에 실제로 쓴 서보 명령값이 함께
표시된다. 예: `yaw=+5.00°→CH0 86.2, pitch=+10.00°→CH1 103.3`.

브로커와 자동 조준 모드는 각각 별도 터미널에서 실행한다.

```bash
./scripts/dev.sh broker
./scripts/dev.sh aim
```

`aim`은 기존 수동 서보 스크립트처럼 명령값을 직접 입력하는 대신 Jetson의
`jetson/aim`을 받아 CH0/CH1을 자동으로 움직인다(`--no-fire`, 발사 안 함).
`./scripts/dev.sh pi`는 기본이 `--fake-hw`이고, `--servos`를 주면 실제 서보를 쓰고
발사까지 한다.

pitch 기본 보정은 `floaq/config.py`의 `PITCH_CAL`: `-10°→148.9`, `0°→140`, `25°→117.8`
입니다. **`0°→140`(수평)만 2026-09-23 실측**이고 나머지는 전 표의 기울기를 빌린
임시값입니다. 전 표(`2.5°→110`, `25°→90`, 09-18)는 재장착 뒤 영점이 약 28 밀려
안 맞았습니다 — CH1 110 은 실제로 위를 봅니다. Jetson 이 계산한 pitch 를
포물선으로 풀어 −10°~25° 에 붙여서 보내므로 위아래도 목표를 따라갑니다. Pi 의 소프트 리밋
(`floaq/config.py` `PITCH_MIN_DEG`/`PITCH_MAX_DEG`)과 Jetson 의
`configs/stereo_targeting.yaml`이 이 범위와 같이 움직여야 합니다. 다른 값을 쓰려면
`--pitch-cal=<PITCH_DEG>:<SERVO_COMMAND>`를 두 번 이상 전달합니다. 보정 범위 밖의
각도는 외삽하지 않고 거부합니다(서보가 움직이지 않는다). 발사 파워 변경 후 사거리를 다시 측정하기 전에는
자동 발사 경로를 사용하지 않습니다.

전체 설정 방법은 상위 README (`../README.md`, 공개 사본 미포함)를 참고합니다.

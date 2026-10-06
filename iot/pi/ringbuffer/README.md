# MPU6050 IMU 링버퍼 하드웨어 실험

이 폴더는 Git 저장소 밖에서 Jira 146번(영상·IMU RAM 링버퍼)을 시험하기 위한
독립 코드다. Jetson 영상은 ZMQ JPEG 스트림을 구독하고 Pi IMU는 I2C에서 읽는다.
두 프로세스 모두 같은 `event <Unix ns>` 값으로 사고 전 30초·후 5초를 잘라낸다.

**현재 저장소 운영 설정은 영상 전 15초·후 10초이지만 Jira 146 설명은 전 30초다.**
이 실험 도구는 Jira 기준으로 전 30초를 기본값으로 두었으며 `--before`와
`--after`로 운영 설정을 시험할 수도 있다.

## 배선

| MPU6050 | Raspberry Pi 5 |
|---|---|
| VCC | 3.3V, 물리 1번 핀 |
| GND | GND, 물리 6번 핀 |
| SDA | GPIO2/SDA1, 물리 3번 핀 |
| SCL | GPIO3/SCL1, 물리 5번 핀 |
| AD0 | GND (`0x68`) |
| INT | 미사용 |
| XDA/XCL | 미사용 |

같은 I2C 버스에 PCA9685 `0x60`을 함께 연결할 수 있다. 정상적인 스캔 결과는
`0x60`과 `0x68`이다. E22 LoRa는 UART 장치라 이 목록에 나오지 않는다.

## 설치

```bash
sudo raspi-config nonint do_i2c 0
sudo apt-get update
sudo apt-get install -y i2c-tools python3-venv

i2cdetect -y 1

cd ~/imu_ringbuffer_lab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. 연결 확인

```bash
python3 run_imu.py --check
```

성공하면 `WHO_AM_I=0x68`과 가속도·자이로 원시값 10개를 출력한다. 센서를 가만히
놓았을 때 가속도 벡터 크기는 약 `9.81 m/s²`, 자이로는 `0 deg/s` 근처여야 한다.

## 2. 링버퍼 실험

```bash
python3 run_imu.py --addr 0x68 --hz 50 --before 30 --after 5
```

시작할 때 3초 동안 자이로 영점을 보정한다. 이때 센서를 움직이면 안 된다.

- `Enter`: 현재 시점을 사고 이벤트로 기록한다.
- `event <Unix ns>`: Jetson 영상과 같은 사고 시각으로 기록한다.
- 이후 5초를 더 수집한 다음 사고 전 30초와 사고 후 5초를 저장한다.
- `q` + `Enter`: 종료한다.
- 결과: `captures/imu_날짜_시각.jsonl`과 `.meta.json`

실행 직후 Enter를 누르면 사고 전 30초가 아직 채워지지 않아 메타데이터의
`truncated`가 `true`가 된다. 최소 30초 기다린 뒤 눌러야 전체 구간이 저장된다.

## 값의 의미

| 필드 | 단위 | 의미 |
|---|---|---|
| `accel_x/y/z` | m/s² | 3축 가속도 |
| `gyro_x/y/z` | deg/s | 3축 회전 속도 |
| `roll/pitch` | deg | 가속도와 자이로를 결합한 기울기 |
| `yaw` | deg | 자이로 적분 상대각 |

MPU6050에는 지자기 센서가 없으므로 `yaw`는 절대 방위가 아니며 시간이 지나면
드리프트한다. 절대 선수 방향은 GPS heading 또는 지자기 센서와 결합해야 한다.

## 하드웨어 없이 흐름 확인

```bash
python3 run_imu.py --source synthetic --before 5 --after 2 --calibrate 0
```

## Jetson 영상 링버퍼

기본 입력은 운영 FastAPI 카메라 서버의 L/R MJPEG 스트림이다. 기존 서버와
카메라를 그대로 실행한 상태에서 이 도구만 별도 터미널에 띄운다.

Jetson에서 이 폴더를 복사한 후:

```bash
python3 run_video.py --source fastapi --base-url http://127.0.0.1:8080 \
  --before 30 --after 5
```

L/R 프레임 수가 증가해야 한다. `Enter`를 누르면 현재 Unix 나노초가
표시된다. 그 값을 Pi의 `run_imu.py` 콘솔에서
`event <Unix ns>`로 입력하면 같은 사고 시각 기준으로 양쪽 데이터를 저장한다.
반대로 Pi에서 먼저 Enter를 누르고 Jetson에 같은 값을 넣어도 된다.

시험용 `jetson_camera` ZMQ 퍼블리셔로 검증할 때만 다음 명령을 사용한다.

```bash
pip install pyzmq
python3 run_video.py --source zmq --endpoint ipc:///tmp/floaq_frames
```

영상은 `captures/event_.../video/` 아래 JPEG와 `index.json`으로 저장된다.
IMU는 `captures/imu_....jsonl` 및 `.meta.json`으로 저장된다. 평상시에는
둘 다 RAM에만 보관하며, 이벤트가 있을 때만 디스크에 쓴다.

서로 다른 장치의 시계를 같은 기준으로 쓰므로 Pi와 Jetson의 시간 동기화 상태를
`chronyc tracking`으로 확인해야 한다. 시각 차이가 5fps의 한 프레임 간격
(약 200ms)을 넘으면 영상의 `truncated`가 `true`가 될 수 있다.

FastAPI MJPEG는 원래 촬영 시각을 보내지 않는다. 이 도구는 **Jetson에서 JPEG를
받은 시각**으로 기록한다. 따라서 전 30초 보관과 파일 추출은 확인할 수 있지만,
실제 촬영 시각 기준 밀리초 단위 동기화의 증거로 사용하면 안 된다. 운영 통합
때는 `floaq_jetson`의 원본 프레임 콜백에서 촬영 시각과 JPEG를 버퍼에 직접 넣는
것이 맞다.

영상 기본 메모리 상한은 128MiB다. 실제 JPEG 크기 때문에 전 30초가 남지 않으면
`--max-mb`를 늘리고 상태 출력의 보관 시간을 확인한다.

"""MPU6050 어댑터. 배 바닥(`ImuPosition.HULL`)에 붙은 6축을 읽는다.

`adapters/gps.py` 와 같은 구조다 — 스레드가 계속 읽고, 최신 값만 상자에 둔다.
부르는 쪽은 언제든 `read()` 로 지금 값을 가져간다.

    from floaq.adapters.imu import Mpu6050, Tilt
    imu = Mpu6050(zero=Tilt.load(path))
    imu.start()
    ...
    s = imu.read()          # None 이면 아직 못 읽었다

── 왜 각도를 여기서 만드나 ─────────────────────────────────────────
계약(`contracts/pi.py SensorImu`)이 `roll`·`pitch` 를 **각도(deg)** 로 받는다.
가속도 3축은 `accel_*` 에 그대로 싣는다 — 둘 다 자리가 있다.

    accel_x/y/z   생값 그대로 (m/s²). 사후에 "센서가 뭘 봤나" 를 되짚는 값
    roll/pitch    설치 오프셋을 뺀 **배 기준** 각도

🔴 **설치 오프셋을 빼지 않으면 값이 뜻이 없다.** 센서 좌표계와 배 좌표계는
   다르다. 실측에서 보드가 21도 기울어 붙어 있었다 — 그 상태의 생값을 그대로
   쓰면 평상시가 이미 "기울어짐" 이다.

🔴 **영점이 없으면 `roll`·`pitch` 를 안 준다(None).** 0 을 주면 화면이 "수평"
   으로 읽는다. 이 프로젝트가 계속 경계하는 그 패턴이다 —
   "조류 0.0 = 잔잔하다" 와 같은 종류의 거짓말이다.

── yaw ─────────────────────────────────────────────────────────────
⚠ **MPU6050 으로는 yaw 를 못 구한다.** 자력계가 없다(9250 에는 있다). 중력은
  연직이라 수평 회전을 알려주지 않는다. 자이로 적분은 몇 분이면 표류한다.
  `SensorImu.heading_deg` 주석이 "GPS 로 보정한 방위" 라고 적어둔 이유다 —
  방위는 GPS 진행방향에서 가져온다. 여기서는 만들지 않는다.

── 스케일 오차 ─────────────────────────────────────────────────────
⚠ 실측에서 정지 상태 |a| 가 0.90g 였다(1.00 이어야 한다). 자세를 세 번 바꿔도
  같아서 **회전으로 설명이 안 되는** 스케일 오차다. 억지로 1.0 으로 늘리지
  않는다 — 배가 흔들리면 중력 외 가속이 더해져 1.0 을 넘는데 그게 정보다.
  각도는 `atan2` 의 비율이라 이 오차가 대부분 상쇄된다.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: `linux/i2c-dev.h`. 이 ioctl 로 파일 핸들이 말 걸 주소를 정한다
I2C_SLAVE = 0x0703

#: MPU6050 기본. AD0 이 HIGH 면 0x69
DEFAULT_ADDR = 0x68
DEFAULT_BUS = 1

WHO_AM_I = 0x75
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

#: ±2g 설정에서. `AFS_SEL` 을 바꾸면 이 값도 바뀐다
LSB_PER_G = 16384.0
#: 표준 중력. 계약이 accel_* 를 m/s² 로 받는다
G_MS2 = 9.80665

#: 읽는 주기. 기울기 판정(침수·전복)에 초 단위면 충분하고, I2C 를 덜 태운다
PERIOD_SEC = 0.2

#: 영점을 잡을 때 요구하는 |a| 범위(g).
#:
#: 🔴 파도 위나 움직이는 중에 잡으면 **엉뚱한 기준이 박힌다.** 그러면 진짜
#:    침수가 나도 roll 이 0 으로 보여 판정이 통째로 죽는다.
#: ⚠ 아래가 0.80 인 것은 이 칩의 스케일 오차(0.90g) 때문이다. 1.0 근처만
#:   받으면 멀쩡한 칩이 영원히 영점을 못 잡는다.
ZERO_MIN_G = 0.80
ZERO_MAX_G = 1.20


def roll_pitch(ax: float, ay: float, az: float) -> tuple[float, float]:
    """가속도 3축 -> `(roll, pitch)` 도. 단위는 무엇이든 된다 — 비율만 쓴다.

    roll  은 좌우 기울기, pitch 는 앞뒤 기울기다.
    ⚠ 부호 규약: 보드의 +X 가 뱃머리, +Z 가 위를 향한다고 본다. 반대로 붙이면
      "선수가 들림" 과 "선미가 들림" 이 바뀐다.
    """
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
    return roll, pitch


@dataclass(frozen=True, slots=True)
class Tilt:
    """설치 오프셋. 배가 수평일 때 센서가 내는 각도다.

    ⚠ 파일로 남긴다. 부팅마다 다시 잡으면 그때 배가 기울어 있던 각도가 기준이
      되어버린다 — 사람이 한 번 명시적으로 잡는다(`tools/imu_zero.py`).
    """

    roll: float
    pitch: float

    def apply(self, roll: float, pitch: float) -> tuple[float, float]:
        return roll - self.roll, pitch - self.pitch

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps({"roll": self.roll, "pitch": self.pitch}), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "Tilt | None":
        """없으면 None. **그때는 각도를 발행하지 않는다.**"""
        p = Path(path)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return Tilt(roll=float(d["roll"]), pitch=float(d["pitch"]))
        except (ValueError, KeyError, OSError) as e:
            # 🔴 깨진 영점을 0 으로 대신하지 않는다. 없는 것으로 친다
            log.warning("IMU 영점 파일을 못 읽었다 (%s). 각도를 발행하지 않는다", e)
            return None


@dataclass(frozen=True, slots=True)
class Sample:
    """한 번 읽은 것. `contracts.SensorImu` 로 바로 옮길 수 있는 모양이다."""

    #: m/s². 생값이다 — 오프셋을 안 뺐다
    accel_x: float
    accel_y: float
    accel_z: float
    #: 배 기준 각도. **영점이 없으면 None** — 0 을 주지 않는다
    roll: float | None
    pitch: float | None
    #: 중력 크기(g). 1.0 에서 많이 벗어나면 움직이는 중이거나 센서가 이상하다
    magnitude_g: float
    measured_at: int


class _I2C:
    """`/dev/i2c-N` 을 파일로 연다. smbus2 같은 패키지가 없어도 된다."""

    def __init__(self, bus: int, addr: int) -> None:
        import fcntl                      # ⚠ 리눅스 전용. 시험은 Fake 를 쓴다

        self.f = open(f"/dev/i2c-{bus}", "r+b", buffering=0)
        fcntl.ioctl(self.f, I2C_SLAVE, addr)

    def read(self, reg: int, n: int = 1) -> bytes:
        self.f.write(bytes([reg]))
        return self.f.read(n)

    def write(self, reg: int, val: int) -> None:
        self.f.write(bytes([reg, val]))

    def close(self) -> None:
        self.f.close()


class Mpu6050:
    """`ports` 에 없는 보조 장치라 Protocol 을 두지 않는다. main 이 직접 엮는다."""

    def __init__(self, *, bus: int = DEFAULT_BUS, addr: int = DEFAULT_ADDR,
                 zero: Tilt | None = None, period: float = PERIOD_SEC) -> None:
        self.bus, self.addr = bus, addr
        self.zero = zero
        self.period = period
        self._dev: _I2C | None = None
        self._lock = threading.Lock()
        self._last: Sample | None = None
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        #: 연속 읽기 실패. 선이 빠지면 여기가 오른다
        self.fails = 0

    # ── 수명주기 ─────────────────────────────────────────────────────
    def open(self) -> None:
        """버스를 열고 칩을 깨운다.

        🔴 MPU6050 은 기본이 **잠자기**다. 안 깨우면 전부 0 이 나오고, 그게
           "안 움직인다" 처럼 보인다.
        """
        self._dev = _I2C(self.bus, self.addr)
        who = self._dev.read(WHO_AM_I)[0]
        if who != 0x68:
            # 같은 주소를 쓰는 다른 칩일 수 있다. 죽이지 않고 경고만 한다
            log.warning("IMU WHO_AM_I=0x%02X — MPU6050(0x68) 이 아니다", who)
        self._dev.write(PWR_MGMT_1, 0x00)
        time.sleep(0.1)
        if self.zero is None:
            log.warning("IMU 영점이 없다. roll·pitch 를 발행하지 않는다 "
                        "— tools/imu_zero.py 로 한 번 잡을 것")

    def start(self) -> None:
        if self._dev is None:
            self.open()
        self._thread = threading.Thread(target=self._run, name="imu", daemon=True)
        self._thread.start()
        log.info("IMU 시작  i2c-%d 0x%02X", self.bus, self.addr)

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                s = self.sample()
            except OSError as e:
                # ⚠ 선이 흔들리면 흔한 일이다. 죽지 않고 다음 주기에 다시 본다
                self.fails += 1
                if self.fails in (1, 10, 100):
                    log.warning("IMU 읽기 실패 %d회: %s", self.fails, e)
                s = None
            if s is not None:
                self.fails = 0
                with self._lock:
                    self._last = s
            self._stopping.wait(self.period)

    # ── 읽기 ─────────────────────────────────────────────────────────
    def sample(self) -> Sample:
        """한 번 읽는다. 스레드 없이 쓰고 싶을 때도 부를 수 있다."""
        if self._dev is None:
            raise RuntimeError("open() 을 먼저 부른다")
        raw = self._dev.read(ACCEL_XOUT_H, 6)
        # ⚠ 빅엔디안 16비트 셋이다. 리틀엔디안으로 읽으면 값이 통째로 엉뚱해진다
        gx, gy, gz = struct.unpack(">hhh", raw)
        ax, ay, az = gx / LSB_PER_G, gy / LSB_PER_G, gz / LSB_PER_G

        roll, pitch = roll_pitch(ax, ay, az)
        if self.zero is not None:
            roll, pitch = self.zero.apply(roll, pitch)
        else:
            roll = pitch = None            # type: ignore[assignment]

        return Sample(
            # 계약이 m/s² 로 받는다 (`contracts/pi.py SensorImu`)
            accel_x=ax * G_MS2, accel_y=ay * G_MS2, accel_z=az * G_MS2,
            roll=roll, pitch=pitch,
            magnitude_g=math.sqrt(ax * ax + ay * ay + az * az),
            measured_at=int(time.time()),
        )

    def read(self) -> Sample | None:
        """마지막으로 읽은 것. 아직 없으면 None."""
        with self._lock:
            return self._last


class FakeImu:
    """시험·`--fake-hw` 용. I2C 없이 같은 모양을 돌려준다."""

    def __init__(self, *, roll: float = 0.0, pitch: float = 0.0,
                 zero: Tilt | None = None) -> None:
        self.roll, self.pitch = roll, pitch
        self.zero = zero
        self.fails = 0

    def open(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...

    def sample(self) -> Sample:
        """⚠ 진짜와 같은 규칙이다 — `zero` 가 없으면 각도를 None 으로 준다.
        가짜만 항상 값을 주면 "영점 없음" 경로가 시험에서 안 밟힌다."""
        if self.zero is None:
            r = p = None
        else:
            r, p = self.zero.apply(self.roll, self.pitch)
        return Sample(accel_x=0.0, accel_y=0.0, accel_z=G_MS2,
                      roll=r, pitch=p, magnitude_g=1.0,
                      measured_at=int(time.time()))

    def read(self) -> Sample | None:
        return self.sample()

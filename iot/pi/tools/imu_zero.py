"""IMU 설치 영점을 잡는다. **배가 수평일 때 한 번만.**

    uv run python tools/imu_zero.py                  # 잡아서 파일로 저장
    uv run python tools/imu_zero.py --show           # 지금 저장된 값만 본다
    uv run python tools/imu_zero.py --clear          # 지운다

🔴 **아무 때나 잡으면 안 된다.** 이 값이 "수평" 의 기준이 된다. 배가 이미 기울어
   있을 때 잡으면 그 기울기가 수평으로 박히고, 진짜 침수가 나도 roll 이 0 으로
   보여 `core/state.py` 의 FLOODING 판정(101 침수 / 104 전복)이 통째로 죽는다.

   조건:
     · 배가 수평이고 정박 중일 것 (파도 위에서 잡지 말 것)
     · IMU 를 **최종 위치에 고정한 뒤**. 임시로 올려둔 상태면 다시 잡아야 한다
     · 보드의 +X 가 뱃머리, +Z 가 위를 향할 것

⚠ 여러 표본의 평균을 쓴다. 한 번만 읽으면 그 순간의 잡음이 기준이 된다.
⚠ 표본이 흔들리면 **거부한다** — 움직이는 중이라는 뜻이고, 그 상태의 평균은
  수평이 아니다.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters.imu import (  # noqa: E402
    DEFAULT_ADDR, DEFAULT_BUS, ZERO_MAX_G, ZERO_MIN_G, Mpu6050, Tilt,
)

#: 기본 저장 위치. DB 옆에 둔다 — 같이 백업되고 같이 지워진다
DEFAULT_PATH = "floaq.imu-zero.json"

#: 몇 개를 평균낼지. 1Hz 가 아니라 빠르게 읽으므로 몇 초면 끝난다
SAMPLES = 40
SAMPLE_GAP = 0.05

#: 표본 표준편차가 이보다 크면 움직이는 중으로 본다(도).
#:
#: ⚠ 실측에서 고정된 보드는 0.01도 수준이었다. 0.5도면 넉넉하다 —
#:   너무 조이면 사람 손이 스치기만 해도 거부한다
STEADY_MAX_DEG = 0.5


def capture(dev: Mpu6050) -> Tilt | None:
    rolls: list[float] = []
    pitches: list[float] = []
    mags: list[float] = []

    print(f"{SAMPLES}개 읽는다...")
    for _ in range(SAMPLES):
        s = dev.sample()
        # 🔴 영점을 잡는 중이므로 기존 오프셋이 끼면 안 된다. 생각도를 다시 만든다
        from floaq.adapters.imu import G_MS2, roll_pitch
        r, p = roll_pitch(s.accel_x / G_MS2, s.accel_y / G_MS2, s.accel_z / G_MS2)
        rolls.append(r)
        pitches.append(p)
        mags.append(s.magnitude_g)
        time.sleep(SAMPLE_GAP)

    mag = statistics.fmean(mags)
    sd_r = statistics.pstdev(rolls)
    sd_p = statistics.pstdev(pitches)
    roll = statistics.fmean(rolls)
    pitch = statistics.fmean(pitches)

    print(f"  |a| {mag:.3f}g   roll {roll:+.2f}° (±{sd_r:.2f})   "
          f"pitch {pitch:+.2f}° (±{sd_p:.2f})")

    if not ZERO_MIN_G <= mag <= ZERO_MAX_G:
        print(f"  거부: |a| 가 {ZERO_MIN_G}~{ZERO_MAX_G}g 밖이다. "
              "움직이는 중이거나 센서가 이상하다")
        return None
    if sd_r > STEADY_MAX_DEG or sd_p > STEADY_MAX_DEG:
        print(f"  거부: 값이 흔들린다(허용 ±{STEADY_MAX_DEG}°). "
              "정박하고 손을 뗀 뒤 다시 할 것")
        return None
    return Tilt(roll=roll, pitch=pitch)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--bus", type=int, default=DEFAULT_BUS)
    p.add_argument("--addr", default=hex(DEFAULT_ADDR))
    p.add_argument("--show", action="store_true", help="저장된 값만 본다")
    p.add_argument("--clear", action="store_true", help="지운다")
    args = p.parse_args()

    path = Path(args.path)

    if args.show:
        z = Tilt.load(path)
        print(f"{path}: {z if z else '없다 — 각도를 발행하지 않는 상태'}")
        return 0

    if args.clear:
        if path.exists():
            path.unlink()
            print(f"{path} 지웠다. 이제 roll·pitch 를 발행하지 않는다")
        else:
            print("이미 없다")
        return 0

    print("🔴 배가 수평이고 정박 중이어야 한다. IMU 가 최종 위치에 고정됐는지 확인할 것")
    dev = Mpu6050(bus=args.bus, addr=int(args.addr, 0))
    try:
        dev.open()
    except OSError as e:
        print(f"IMU 를 못 열었다: {e}")
        print("  tools/imu_probe.py 로 먼저 확인할 것")
        return 1

    try:
        z = capture(dev)
    finally:
        dev.stop()

    if z is None:
        return 1

    z.save(path)
    print(f"\n저장했다: {path}")
    print(f"  설치 오프셋  roll {z.roll:+.2f}°  pitch {z.pitch:+.2f}°")
    print("  이제 이 자세가 '수평' 이다. IMU 를 옮기면 다시 잡을 것")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

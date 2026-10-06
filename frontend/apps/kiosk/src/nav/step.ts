import type { LngLat } from '@floaq/shared';

/**
 * 가상 항해 한 걸음. 순수 함수 — `test/nav-check.mjs` 가 이 파일을 검증한다.
 */

/**
 * 1노트를 위도 도/초로. 1kn = 1해리/시이고 해리 1개가 위도 1분이다.
 *
 * ⚠ km 를 거치지 않는다. 1.852 를 곱하면 1.852배 빨라진다 — 처음 그렇게 짜서 틀렸다.
 */
export const KN_TO_DEG_LAT_PER_SEC = 1 / (60 * 3600);

/**
 * 바깥 고리(점선 ~ 테두리)의 시연 배속.
 *
 * 실제 속력으로는 화면에서 안 움직인다 — 8kn 은 4.1m/s 이고 zoom 13 에서 1픽셀이 약 19m 라
 * 10초에 2픽셀이다. 격자 한 칸(3km)을 지나는 데 12분이 걸린다.
 *
 * 100배면 8kn 이 초당 411m 라 격자 한 칸을 약 7초에 지난다.
 * 안쪽 고리는 배속 없이 실제 속력이라, 둘을 오가며 "이게 진짜 속력"을 보여줄 수 있다.
 */
export const FAST_SCALE = 100;

/**
 * 점선 고리의 반지름(스틱 반지름 대비).
 *
 * CSS 와 맞춰야 한다 — `.joy-pad` 84px, `.joy-ring { inset:10px }` 이므로
 * 점선 반지름 32px / 스틱 반지름 42px = 0.762.
 */
export const INNER_RATIO = 32 / 42;

/** 스틱을 끝까지 밀었을 때. 어선 순항(6~8kn)의 위쪽 */
export const MAX_KN = 8;

/** 이 안에서는 움직이지 않는다. 손이 살짝 떨릴 때 배가 흐르는 것을 막는다 */
export const DEADZONE = 0.12;

/** 스틱 기울기(-1~1)에 해당하는 속력. 안쪽 고리 안에서 0~8kn 로 비례한다 */
export function speedKn(vx: number, vy: number): number {
  const len = Math.min(1, Math.hypot(vx, vy));
  if (len <= DEADZONE) {
    return 0;
  }
  return len <= INNER_RATIO ? (MAX_KN * len) / INNER_RATIO : MAX_KN;
}

/** 안쪽 고리는 실제 속력, 바깥 고리는 시연 배속 */
export function timeScale(vx: number, vy: number): number {
  return Math.min(1, Math.hypot(vx, vy)) <= INNER_RATIO ? 1 : FAST_SCALE;
}

/**
 * @param vx 스틱 기울기. 오른쪽이 +
 * @param vy 스틱 기울기. **화면 기준이라 아래가 +** — 위도와 부호가 반대다
 * @return 움직이지 않으면 null
 */
export function step(at: LngLat, vx: number, vy: number, dtSec: number): LngLat | null {
  const len = Math.min(1, Math.hypot(vx, vy));
  const kn = speedKn(vx, vy);
  if (kn === 0 || dtSec <= 0) {
    return null;
  }
  const [lon, lat] = at;
  const deg = kn * KN_TO_DEG_LAT_PER_SEC * timeScale(vx, vy) * dtSec;
  // 경도는 위도에 따라 좁아진다. 보정 없이 더하면 고위도에서 동서로 빨라진다
  const lonScale = Math.cos((lat * Math.PI) / 180);
  return [
    lon + ((vx / len) * deg) / (lonScale || 1),
    lat - (vy / len) * deg,
  ];
}

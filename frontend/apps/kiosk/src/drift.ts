/**
 * 표류 추정 범위를 화면 문구로. 지도(`MapPane`)와 통신 패널(`Comms`)이 같이 쓴다.
 *
 * 값 자체는 Pi 가 계산한다 (`iot/pi/floaq/drift.py`). 여기서는 읽는 방법만 정한다.
 */

import { RING_K } from '@floaq/shared';
import type { BuoyState } from '@floaq/shared';

/**
 * 지도가 고리에 칠하는 색 (`floaq-map.js` BAND_RAMP). 안쪽부터다.
 *
 * ⚠ 지도와 범례가 따로 적고 있어서, 지도 색을 고치면 여기도 고쳐야 한다.
 *   안 고치면 범례가 거짓말을 한다.
 */
export const BAND_COLORS = {
  buoy: [['50%', '#d94040'], ['75%', '#e2643a'], ['95%', '#f2c14e']],
  person: [['50%', '#c02a2a'], ['75%', '#d94040'], ['95%', '#d94040']],
} as const;

/**
 * 축 방향 네 가지. 「북동-남서로 길다」가 「방위 42°」보다 빨리 읽힌다.
 * 타원은 180° 대칭이라 방향이 아니라 **축**이다 — 그래서 여덟이 아니라 넷이다.
 */
const COMPASS = ['남북', '북동-남서', '동서', '북서-남동'] as const;

/**
 * 장축의 방위를 축 이름으로. 입력은 0~180 이다.
 *
 * ⚠ 180 은 0 과 같은 축이다. 반올림이 4 를 내므로 나머지로 되돌린다 —
 *   Pi 가 0~180 을 보내지만 값이 180 바로 아래면 여기서 4 가 나온다.
 */
export function axisName(bearingDeg: number): string {
  const i = Math.round(bearingDeg / 45) % COMPASS.length;
  return COMPASS[i] ?? COMPASS[0];
}

/**
 * 두절 배너에 쓸 범위 문구. 95% 고리 기준이다.
 *
 * 🔴 **원이 아니라 타원이다.** 지름 하나만 적으면 어느 쪽으로 긴지를 지우는데,
 *    수색선이 어느 방향으로 훑어야 하는지가 바로 그 값에 들어 있다.
 *
 * ⚠ 축이 없으면(갱신 전 Pi 가 남긴 retained) 반경만 적는다 — 없는 방향을 지어내지 않는다.
 */
export function driftSize(b: BuoyState): string {
  const e = b.driftEllipse;
  if (!e) return `추정 범위 ${b.estimatedRadiusM ?? '—'} m`;
  const long = Math.round(e.majorM * RING_K.p95);
  const short = Math.round(e.minorM * RING_K.p95);
  return `추정 범위 ${long}×${short} m · ${axisName(e.bearingDeg)}으로 길다`;
}

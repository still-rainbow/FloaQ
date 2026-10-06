import { FloaqMap } from '@floaq/shared';
import type { LngLat } from '@floaq/shared';
import { SWEEP_R, toLocal } from './searchGrid';

/**
 * 해상 수색 패턴 — IAMSAR 매뉴얼 제2권의 기본 패턴 세 가지.
 *
 *   섹터 탐색(VS)  위치가 거의 정확할 때. 추정점을 세 번 지나며 부채꼴을 훑는다.
 *   확대 사각(SS)  위치를 좁은 범위로 알 때. 추정점에서 시작해 사각형을 넓혀 간다.
 *   평행 탐색(PS)  범위가 넓을 때. 표류 방향으로 긴 줄을 간격을 두고 왕복한다.
 *
 * 경로는 **물에 붙어 흘러간다.** 조난자가 밀리는 만큼 패턴 전체가 같이 밀린다 —
 * 바다에 고정된 선을 따라가면 배가 도착했을 때 사람은 이미 그 선 밖에 있다.
 * 그래서 경로를 추정점(datum) 기준 오프셋으로 들고, 그릴 때마다 지금 추정점에 붙인다.
 */

export type PatternKind = 'sector' | 'square' | 'parallel';

export const PATTERN_LABEL: Record<PatternKind, string> = {
  sector: '섹터 탐색',
  square: '확대 사각',
  parallel: '평행 탐색',
};

/** 줄 간격(track spacing). 한 번 지나며 양옆 SWEEP_R 을 훑으므로 그 두 배다. */
export const TRACK_S = SWEEP_R * 2;

/** 추정점 기준 오프셋(m). u = 표류 방향(장축), v = 그 오른쪽 90° */
export type Offset = [number, number];

export interface Pattern {
  kind: PatternKind;
  /** 표류 방향(°). 오프셋의 u 축이다 */
  bearing: number;
  points: Offset[];
}

/**
 * IAMSAR 의 선택 기준을 단순화했다 — 위치 오차(95% 장축 반경, m)로 고른다.
 * 기준값은 소형 경비정 한 척이 한 패턴을 30분 안팎에 도는 크기에서 잡았다.
 */
export function pickPattern(a95: number): PatternKind {
  if (a95 <= 250) return 'sector';
  if (a95 <= 800) return 'square';
  return 'parallel';
}

const rad = (d: number) => (d * Math.PI) / 180;
/** u 축에서 시계방향(오른쪽)으로 deg 만큼 돈 방향으로 r 만큼 */
const polar = (r: number, deg: number): Offset => [r * Math.cos(rad(deg)), r * Math.sin(rad(deg))];

/**
 * 섹터 탐색 — 한 변 r 의 정삼각형 셋. 늘 오른쪽으로 120° 돌고, 추정점을 세 번 지난다.
 * 2차에는 30° 돌려서 1차 선 사이를 훑는다(IAMSAR 의 두 번째 섹터).
 */
function sector(r: number, rot: number): Offset[] {
  const o: Offset = [0, 0];
  const p = (deg: number) => polar(r, deg + rot);
  return [o, p(0), p(60), o, p(240), p(300), o, p(120), p(180), o];
}

/** 확대 사각 — S, S, 2S, 2S, 3S … 로 늘려 가며 오른쪽으로 90°씩 돈다. */
function square(reach: number, s: number): Offset[] {
  const dirs: Offset[] = [[1, 0], [0, 1], [-1, 0], [0, -1]];
  const pts: Offset[] = [[0, 0]];
  let u = 0;
  let v = 0;
  for (let k = 0; ; k += 1) {
    const len = (Math.floor(k / 2) + 1) * s;
    if (len > reach * 2 + s) break;
    const [du, dv] = dirs[k % 4]!;
    u += du * len;
    v += dv * len;
    pts.push([u, v]);
  }
  return pts;
}

/**
 * 평행 탐색 — 표류 방향으로 줄을 긋고 간격 S 로 왕복한다.
 * 타원 밖으로 나가는 줄 끝은 잘라낸다(있을 가능성이 없는 바다를 도는 시간을 뺀다).
 * 시작점(CSP)은 배에서 가장 가까운 모서리다.
 */
function parallel(a: number, b: number, s: number, from: Offset): Offset[] {
  const n = Math.max(1, Math.ceil((2 * b) / s));
  const lanes: number[] = [];
  for (let k = 0; k < n; k += 1) lanes.push(-b + s / 2 + k * s);
  if (from[1] > 0) lanes.reverse();
  // 배가 뒤쪽(-u)에 있으면 +u 방향으로 먼저 간다
  let forward = from[0] <= 0;
  const pts: Offset[] = [];
  for (const v of lanes) {
    const half = Math.max(s / 2, a * Math.sqrt(Math.max(0, 1 - (v / b) ** 2)));
    pts.push(forward ? [-half, v] : [half, v], forward ? [half, v] : [-half, v]);
    forward = !forward;
  }
  return pts;
}

/**
 * @param a  덮을 장축 반경(m)
 * @param b  덮을 단축 반경(m)
 * @param from  배 위치(추정점 기준 오프셋). 평행 탐색의 시작 모서리를 고른다
 * @param round  1차/2차. 섹터는 2차에 30° 돌린다
 */
export function buildPattern(
  kind: PatternKind, a: number, b: number, bearing: number, from: Offset, round: 1 | 2 = 1,
): Pattern {
  const s = TRACK_S;
  const points = kind === 'sector'
    ? sector(Math.max(a, s * 2), round === 2 ? 30 : 0)
    : kind === 'square'
      ? square(Math.max(a, s), s)
      : parallel(Math.max(a, s), Math.max(b, s / 2), s, from);
  return { kind, bearing, points };
}

/** 오프셋을 지금 추정점에 붙여 지도 좌표로 만든다. */
export function toGeo(datum: LngLat, bearing: number, [u, v]: Offset): LngLat {
  return FloaqMap.offset(FloaqMap.offset(datum, Math.abs(u), u >= 0 ? bearing : bearing + 180),
                         Math.abs(v), v >= 0 ? bearing + 90 : bearing - 90);
}

/** 지도 좌표를 추정점 기준 오프셋으로 옮긴다. */
export function toOffset(datum: LngLat, bearing: number, p: LngLat): Offset {
  const r = rad(bearing);
  const [dx, dy] = toLocal(datum, p);
  return [dx * Math.sin(r) + dy * Math.cos(r), dx * Math.cos(r) - dy * Math.sin(r)];
}

/** i 번째 지점부터 끝까지의 경로 길이(m) */
export function lengthFrom(points: Offset[], i: number): number {
  let m = 0;
  for (let k = Math.max(i, 0) + 1; k < points.length; k += 1) {
    const [u1, v1] = points[k - 1]!;
    const [u2, v2] = points[k]!;
    m += Math.hypot(u2 - u1, v2 - v1);
  }
  return m;
}

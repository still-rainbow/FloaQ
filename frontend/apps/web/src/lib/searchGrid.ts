import { FloaqMap } from '@floaq/shared';
import { isLand } from './land';
import type { LngLat } from '@floaq/shared';
import { drift } from './drift';
import type { Leeway, Sea } from './drift';
import type { Uncertainty } from '../types';

/**
 * 수색 구역 분할(신규 11).
 *
 * 추정 불확실 범위를 원(타원)으로만 주면 "그래서 어디부터?"가 남는다.
 * 범위를 격자로 자르고, 훑은 칸을 지워 나가는 도구로 만든다.
 *
 * 이건 **출동한 배에서 쓰는 도구**다. 상황실이 전체를 조망하는 화면과 성격이 다르다 —
 * 지금 어디를 훑고 있고 다음에 어디로 갈지만 알면 된다.
 */

/** 한 칸의 변 길이(m). 100m 는 소형 구조정이 한 번 지나며 훑는 폭에 맞춘 값이다. */
export const CELL_M = 100;

/** 구조정이 지나가며 실제로 훑었다고 볼 반경(m). 육안 수색 기준으로 잡았다. */
export const SWEEP_R = 70;

export type CellState = 'todo' | 'done' | 'stale';

export interface Cell {
  id: string;
  /** 시계방향 4점 */
  poly: LngLat[];
  center: LngLat;
  /** 존재 가능성 농도 0~1 (중심을 1 로 정규화) */
  density: number;
  state: CellState;
}

/** 칸을 훑은 기록. 값은 훑은 시각(초). */
export type Searched = Record<string, number>;

/**
 * 훑은 기록이 몇 초 뒤에 만료되는가.
 *
 * **표류 속도로 한 칸(변 100m)을 벗어나는 데 걸리는 시간**이다.
 * 그만큼 지나면 그때 그 칸에 없었다는 사실이 지금은 아무것도 보장하지 않는다 —
 * 조난자가 그 사이에 흘러 들어왔을 수 있다. 그래서 다시 훑어야 한다.
 *
 * 이 값이 짧게 나오는 게 이 화면의 요점이다. 수색은 빨라야 한다.
 */
export function staleAfterSec(sea: Sea, leeway: Leeway, cellM = CELL_M) {
  const v = drift(sea, leeway).speed;
  return v > 0.01 ? cellM / v : Infinity;
}

/**
 * 타원 범위를 격자로 자른다.
 *
 * 축을 타원의 장·단축에 맞춰 돌려 놓는다. 정북 기준 격자로 자르면
 * 흘러가는 방향과 칸이 어긋나서 "조류 따라 훑는다"는 실제 수색 방식과 맞지 않는다.
 *
 * 농도는 2차원 정규분포를 쓴다. a·b 를 95% 등확률 반경으로 보므로
 * σ = r95 / 2.4477 이다(r95 = σ√(−2 ln 0.05)).
 */
export function buildGrid(
  center: LngLat,
  band: Uncertainty,
  searched: Searched,
  nowSec = 0,
  staleAfter = Infinity,
  cellM = CELL_M,
  /**
   * 칸을 고정할 기준점. 조난자 추정(center)은 시간이 지나면 흘러가지만 칸은 바다에 붙어 있어야 한다 —
   * 칸이 같이 흘러가면 "이 칸을 훑었다"는 기록이 엉뚱한 바다를 가리키게 된다.
   * 넘기지 않으면 center 와 같아서 예전과 똑같이 동작한다.
   */
  origin: LngLat = center,
): Cell[] {
  const { a, b, bearing } = band;
  const sigU = a / 2.4477;
  const sigV = b / 2.4477;
  const half = cellM / 2;

  // 축 방향으로 두 번 밀면 회전 격자가 된다. 삼각함수를 직접 쓰는 것보다 읽기 쉽다.
  const at = (u: number, v: number): LngLat =>
    FloaqMap.offset(FloaqMap.offset(origin, Math.abs(u), u >= 0 ? bearing : bearing + 180),
                    Math.abs(v), v >= 0 ? bearing + 90 : bearing - 90);

  // 지금 추정 중심을 격자 좌표로 옮긴다. u = 장축(bearing) 방향, v = 그 오른쪽 90°.
  const r = (bearing * Math.PI) / 180;
  const [dx, dy] = toLocal(origin, center);
  const u0 = dx * Math.sin(r) + dy * Math.cos(r);
  const v0 = dx * Math.cos(r) - dy * Math.sin(r);

  const cells: Cell[] = [];
  const iMin = Math.floor((u0 - a) / cellM);
  const iMax = Math.ceil((u0 + a) / cellM);
  const jMin = Math.floor((v0 - b) / cellM);
  const jMax = Math.ceil((v0 + b) / cellM);

  for (let i = iMin; i <= iMax; i += 1) {
    for (let j = jMin; j <= jMax; j += 1) {
      const u = i * cellM;
      const v = j * cellM;
      const du = u - u0;
      const dv = v - v0;
      // 칸 중심이 타원 밖이면 버린다. 모서리까지 따지면 칸이 들쭉날쭉해 세기 어렵다.
      if ((du / a) ** 2 + (dv / b) ** 2 > 1) continue;

      /*
       * 🔴 <b>육지 칸은 만들지 않는다.</b> 사람이 거기 있을 수 없는데 칸을 깔면
       * 수색 진도가 그만큼 부풀고, 배를 못 가는 곳으로 보낸다(2026-09-18).
       *
       * ⚠ 버리기만 하고 그 몫을 바다 칸으로 <b>재배분하지는 않는다.</b> 실제 수색구조 모델은
       *   육지에 걸린 확률을 남은 칸에 나눠 준다 — 그게 맞지만, 지금은 density 가 표시용
       *   농도일 뿐이라 합이 1 이라는 전제가 애초에 없다. 확률로 쓰기 시작하면 그때 고친다.
       */
      const c = at(u, v);
      if (isLand(c[0], c[1])) continue;

      const id = `${i}:${j}`;
      const doneAt = searched[id];
      const state: CellState = doneAt === undefined
        ? 'todo'
        : nowSec - doneAt > staleAfter ? 'stale' : 'done';

      cells.push({
        id,
        center: c,
        poly: [
          at(u - half, v - half), at(u + half, v - half),
          at(u + half, v + half), at(u - half, v + half),
        ],
        density: Math.exp(-0.5 * ((du / sigU) ** 2 + (dv / sigV) ** 2)),
        state,
      });
    }
  }
  return cells;
}

export interface GridStats {
  total: number;
  todo: number;
  done: number;
  stale: number;
  /** 아직 훑어야 할 면적 (km²) — 미수색 + 재수색 */
  leftKm2: number;
}

export function gridStats(cells: Cell[], cellM = CELL_M): GridStats {
  const todo = cells.filter((c) => c.state === 'todo').length;
  const stale = cells.filter((c) => c.state === 'stale').length;
  return {
    total: cells.length,
    todo,
    stale,
    done: cells.filter((c) => c.state === 'done').length,
    leftKm2: ((todo + stale) * cellM * cellM) / 1e6,
  };
}

/** origin 에서 p 까지의 동·북 거리(m). 이 범위에서는 평면 근사로 충분하다. */
export function toLocal([lng0, lat0]: LngLat, [lng, lat]: LngLat): [number, number] {
  const mPerDegLat = 111_320;
  const mPerDegLng = mPerDegLat * Math.cos((lat0 * Math.PI) / 180);
  return [(lng - lng0) * mPerDegLng, (lat - lat0) * mPerDegLat];
}

/** 두 좌표 사이 거리(m). 이 범위에서는 평면 근사로 충분하다. */
export function distM([lng1, lat1]: LngLat, [lng2, lat2]: LngLat) {
  const mPerDegLat = 111_320;
  const mPerDegLng = mPerDegLat * Math.cos((lat1 * Math.PI) / 180);
  return Math.hypot((lng2 - lng1) * mPerDegLng, (lat2 - lat1) * mPerDegLat);
}

/** 방위(°). 배가 어느 쪽으로 가야 하는지 화면에 적는다. */
export function bearingTo([lng1, lat1]: LngLat, [lng2, lat2]: LngLat) {
  const mPerDegLat = 111_320;
  const mPerDegLng = mPerDegLat * Math.cos((lat1 * Math.PI) / 180);
  const x = (lng2 - lng1) * mPerDegLng;
  const y = (lat2 - lat1) * mPerDegLat;
  return (((Math.atan2(x, y) * 180) / Math.PI) + 360) % 360;
}

/**
 * 구조정이 지나간 자리를 훑은 것으로 표시한다.
 * 배 위치에서 SWEEP_R 안에 중심이 들어온 칸이 대상이다.
 */
export function sweep(cells: Cell[], boat: LngLat, nowSec: number, searched: Searched): Searched {
  let next: Searched | null = null;
  for (const c of cells) {
    if (distM(boat, c.center) > SWEEP_R) continue;
    // 이미 유효한 기록이 있으면 건드리지 않는다. 다시 지나가면 시각만 새로 찍는다.
    if (c.state === 'done') continue;
    if (!next) next = { ...searched };
    next[c.id] = nowSec;
  }
  return next ?? searched;
}

// 경로는 searchPattern.ts 가 짠다(IAMSAR 기본 패턴). 칸은 "어디를 훑었나"의 기록만 맡는다.

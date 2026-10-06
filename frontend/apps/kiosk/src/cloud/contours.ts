import type { LngLat } from '@floaq/shared';
import type { RomsCell, RomsGrid } from './ocean';
import { rampAt, type ValueRange, type ZoneKey } from './zones';

/**
 * 등치선. marching squares — **육지 마스크를 지킨다.**
 *
 * 바다 격자점 사이를 잇는 것은 ROMS 가 이산화한 연속장을 되살리는 일이라 정당하다.
 * 육지 틈을 가로지르는 것은 다르다 — 없는 물을 만들어 내고, 연안에서 값이 10배 갈리는
 * 자리([[260913_ocean-collector]] §7)를 매끄럽게 뭉갠다.
 *
 * 그래서 **네 꼭짓점이 모두 바다인 칸에서만** 선분을 낸다. 육지에 닿은 칸은 통째로 건너뛰어
 * 등치선이 해안에서 끊긴다 — 끊긴 자리가 "여기는 모른다"는 뜻이다.
 *
 * 격자점이 적으면 선이 각진다. 0.1°(8점)에서 이 기능을 기각했던 이유이고,
 * 0.3°(58점)로 넓히면서 조건이 바뀌었다.
 */

export interface Isoline {
  value: number;
  color: string;
  /** 선분 목록. 잇지 않는다 — 순서를 맞추다 틀리면 없는 연결을 그린다 */
  segments: [LngLat, LngLat][];
}

export interface IsoField {
  levels: Isoline[];
  min: number;
  max: number;
  /** 등치선을 낸 칸 수. 육지에 닿아 건너뛴 칸은 빠진다 */
  cellCount: number;
}

const VALUE: Record<ZoneKey, (c: RomsCell) => number | null> = {
  tide: (c) => c.currentSpeedMs,
  temp: (c) => c.waterTempC,
};

const RAMP: Record<ZoneKey, string[]> = {
  tide: ['#9fd9de', '#5aa9b8', '#2d6b85', '#1b4a63', '#123243'],
  temp: ['#f6c9a4', '#e99a68', '#d1683a', '#b84d26', '#a6401f'],
};

/** 격자 좌표를 정수 인덱스로. 부동소수라 반올림으로 맞춘다 */
const index = (v: number, origin: number, step: number) => Math.round((v - origin) / step);

/** 두 꼭짓점 사이에서 level 이 지나는 지점 */
function lerp(a: LngLat, av: number, b: LngLat, bv: number, level: number): LngLat {
  const t = av === bv ? 0.5 : (level - av) / (bv - av);
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/**
 * @param range 레벨을 놓을 범위. 시간 슬라이더에서 주면 프레임이 바뀌어도 선의 값이 같다 —
 *              프레임마다 min·max 로 놓으면 "25.3℃ 선"이 다음 시각엔 "25.6℃ 선"이 된다
 */
export function buildIsolines(
  grid: RomsGrid | null, key: ZoneKey | null, levelCount = 5, range?: ValueRange | null,
): IsoField | null {
  if (!grid || !key || grid.cells.length < 4) {
    return null;
  }
  const read = VALUE[key];
  const valued = grid.cells
    .map((c) => ({ c, v: read(c) }))
    .filter((x): x is { c: RomsCell; v: number } => x.v != null);
  if (valued.length < 4) {
    return null;
  }

  const latMin = Math.min(...valued.map((x) => x.c.lat));
  const lonMin = Math.min(...valued.map((x) => x.c.lon));
  const at = new Map<string, { lat: number; lon: number; v: number }>();
  for (const { c, v } of valued) {
    at.set(`${index(c.lat, latMin, grid.latStep)},${index(c.lon, lonMin, grid.lonStep)}`,
      { lat: c.lat, lon: c.lon, v });
  }
  const rows = Math.max(...valued.map((x) => index(x.c.lat, latMin, grid.latStep)));
  const cols = Math.max(...valued.map((x) => index(x.c.lon, lonMin, grid.lonStep)));

  const min = Math.min(...valued.map((x) => x.v));
  const max = Math.max(...valued.map((x) => x.v));
  if (max - min < 1e-9) {
    // 값이 모두 같으면 그릴 선이 없다. 억지로 그리면 격자 모양만 나온다
    return { levels: [], min, max, cellCount: 0 };
  }

  const lo = range?.min ?? min;
  const hi = range?.max ?? max;
  const levels: Isoline[] = [];
  let cellCount = 0;
  for (let n = 1; n <= levelCount; n++) {
    const t = n / (levelCount + 1);
    const level = lo + (hi - lo) * t;
    const segments: [LngLat, LngLat][] = [];

    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const sw = at.get(`${i},${j}`);
        const se = at.get(`${i},${j + 1}`);
        const nw = at.get(`${i + 1},${j}`);
        const ne = at.get(`${i + 1},${j + 1}`);
        // 🔴 네 꼭짓점이 다 있어야 한다. 하나라도 육지면 이 칸은 건너뛴다
        if (!sw || !se || !nw || !ne) {
          continue;
        }
        if (n === 1) {
          cellCount++;
        }
        const p = {
          sw: [sw.lon, sw.lat] as LngLat, se: [se.lon, se.lat] as LngLat,
          nw: [nw.lon, nw.lat] as LngLat, ne: [ne.lon, ne.lat] as LngLat,
        };
        // 꼭짓점이 level 위인가. 남서부터 시계방향으로 비트를 쌓는다
        const code = (sw.v > level ? 1 : 0) | (se.v > level ? 2 : 0)
          | (ne.v > level ? 4 : 0) | (nw.v > level ? 8 : 0);
        if (code === 0 || code === 15) {
          continue;
        }
        const bottom = () => lerp(p.sw, sw.v, p.se, se.v, level);
        const right = () => lerp(p.se, se.v, p.ne, ne.v, level);
        const top = () => lerp(p.nw, nw.v, p.ne, ne.v, level);
        const left = () => lerp(p.sw, sw.v, p.nw, nw.v, level);

        switch (code) {
          case 1: case 14: segments.push([left(), bottom()]); break;
          case 2: case 13: segments.push([bottom(), right()]); break;
          case 3: case 12: segments.push([left(), right()]); break;
          case 4: case 11: segments.push([right(), top()]); break;
          case 6: case 9: segments.push([bottom(), top()]); break;
          case 7: case 8: segments.push([left(), top()]); break;
          // 안장점(5·10)은 두 갈래다. 평균으로 가르지 않고 둘 다 그린다 —
          // 한쪽을 고르면 그 선택이 지형처럼 보인다
          case 5: segments.push([left(), bottom()], [right(), top()]); break;
          case 10: segments.push([bottom(), right()], [top(), left()]); break;
          default: break;
        }
      }
    }
    if (segments.length > 0) {
      levels.push({ value: level, color: rampAt(RAMP[key], t), segments });
    }
  }

  return { levels, min, max, cellCount };
}

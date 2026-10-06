import type { ContourBand, LngLat } from '@floaq/shared';
import type { ZoneCell, ZoneGrid } from './ocean';
import { rampAt, type CurrentArrow, type ValueRange, type Zones } from './zones';

/**
 * 기상청 해구별 예측 → 지도 구역. 순수 함수 — `test/chart-check.mjs` 가 검증한다.
 *
 * ROMS 칸(`zones.ts`)과 같은 모양(Zones)으로 내보낸다. 지도·범례 코드가 원자료를 몰라도 되게.
 *
 * 해구는 **보간하지 않는다.** 대해구 한 칸이 약 55km 라 매끈하게 이으면 연안 50km 가 한 값으로 뭉개진다 —
 * 칸을 그대로 칠하는 것이 이 해상도의 정직한 모습이다(ROMS 와 같은 원칙).
 */

/** 해구로 칠할 수 있는 항목. 수온은 소해구에만 있다 */
export type ZoneMetric = 'wave' | 'wind' | 'temp';

const SPEC: Record<ZoneMetric, {
  name: string; unit: string; dec: number; ramp: string[];
  value: (c: ZoneCell) => number | null;
  range: (r: NonNullable<ZoneGrid['range']>) => [number | null, number | null];
}> = {
  // 순차 램프 — 한 색상이 옅은→진한. 해양포털은 무지개 램프지만 색만으로 값 순서를 못 읽어 따르지 않는다
  wave: {
    name: '유의파고', unit: 'm', dec: 1,
    ramp: ['#e7f0fa', '#b8d2ee', '#78a7db', '#3d74b8', '#1b4580'],
    value: (c) => c.waveHeightM, range: (r) => [r.waveMin, r.waveMax],
  },
  wind: {
    name: '풍속', unit: 'm/s', dec: 1,
    ramp: ['#edf5e9', '#c6e2b5', '#8cc378', '#4c9743', '#236428'],
    value: (c) => c.windSpeedMs, range: (r) => [r.windMin, r.windMax],
  },
  temp: {
    name: '표층 수온', unit: '°C', dec: 1,
    ramp: ['#fdeee2', '#f6c9a4', '#e99a68', '#d1683a', '#a6401f'],
    value: (c) => c.waterTempC, range: (r) => [r.tempMin, r.tempMax],
  },
};

/** 칸 한 변(km). 위도 1° = 111km — 경도는 위도에 따라 줄어 위도 쪽으로 말한다 */
const cellKm = (stepDeg: number) => Math.round(stepDeg * 111);

/** 발표본 전 시각 범위. 없거나 평평하면 null — 프레임 범위로 물러선다 */
export function zoneRangeFor(grid: ZoneGrid | null, key: ZoneMetric): ValueRange | null {
  if (!grid?.range) {
    return null;
  }
  const [min, max] = SPEC[key].range(grid.range);
  return min != null && max != null && max > min ? { min, max } : null;
}

export function buildZoneLayer(grid: ZoneGrid | null, key: ZoneMetric, range?: ValueRange | null): Zones | null {
  if (!grid) {
    return null;
  }
  const spec = SPEC[key];
  const valued = grid.cells
    .map((c) => ({ c, v: spec.value(c) }))
    .filter((x): x is { c: ZoneCell; v: number } => x.v != null);
  if (valued.length === 0) {
    return null;
  }
  const min = range ? range.min : Math.min(...valued.map((x) => x.v));
  const max = range ? range.max : Math.max(...valued.map((x) => x.v));
  const span = max - min;

  const bands: ContourBand[] = valued.map(({ c, v }) => {
    const t = span > 0 ? Math.max(0, Math.min(1, (v - min) / span)) : 0.5;
    const fill = rampAt(spec.ramp, t);
    const ring: LngLat[] = [
      [c.lonMin, c.latMin], [c.lonMax, c.latMin], [c.lonMax, c.latMax], [c.lonMin, c.latMax],
    ];
    return { fill, line: fill, op: 0.42, polys: [[ring]] };
  });

  const levelName = grid.level === 'large' ? '대해구' : '소해구';
  return {
    bands,
    legend: {
      name: spec.name, unit: spec.unit, min, max, dec: spec.dec, ramp: spec.ramp,
      predcDt: grid.validAt,
      note: `${levelName} ${bands.length}칸 · 한 칸 약 ${cellKm(grid.stepDeg)}km`,
      source: '기상청 해구별 예측',
    },
  };
}

/**
 * 바람 화살표 — **불어가는 쪽**을 가리킨다.
 *
 * 풍향은 기상 관례상 불어오는 쪽이다(북풍 = 0°). 그대로 그리면 화살표가 바람 반대로 선다 —
 * 180° 돌려 ROMS 유향(흘러가는 쪽)과 같은 읽기로 맞춘다.
 * 파향은 관례가 명세에 없어 화살표를 그리지 않는다.
 *
 * @param around 이 좌표에서 maxDeg 이내 칸만. 전국 1,330칸에 마커를 다 올리면 선내 PC 에서 지도가 끌린다
 */
export function buildWindArrows(grid: ZoneGrid | null, around?: LngLat, maxDeg = 3): CurrentArrow[] {
  if (!grid) {
    return [];
  }
  return grid.cells
    .filter((c) => c.windDirDeg != null && c.windSpeedMs != null)
    .map((c) => ({ c, at: [(c.lonMin + c.lonMax) / 2, (c.latMin + c.latMax) / 2] as LngLat }))
    .filter(({ at }) => !around || (Math.abs(at[0] - around[0]) <= maxDeg && Math.abs(at[1] - around[1]) <= maxDeg))
    .map(({ c, at }) => ({ at, deg: (c.windDirDeg! + 180) % 360, speedMs: c.windSpeedMs! }));
}

/** 발표본 경계 [lng, lat] 네 모서리. 층을 바꿀 때 지도를 여기에 맞춘다 */
export function zoneBounds(grid: ZoneGrid | null): LngLat[] {
  if (!grid || grid.cells.length === 0) {
    return [];
  }
  const latMin = Math.min(...grid.cells.map((c) => c.latMin));
  const latMax = Math.max(...grid.cells.map((c) => c.latMax));
  const lonMin = Math.min(...grid.cells.map((c) => c.lonMin));
  const lonMax = Math.max(...grid.cells.map((c) => c.lonMax));
  return [[lonMin, latMin], [lonMax, latMax]];
}

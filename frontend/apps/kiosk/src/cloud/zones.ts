import type { ContourBand, LngLat } from '@floaq/shared';
import type { RomsCell, RomsGrid } from './ocean';

/**
 * ROMS 격자 → 지도 구역. 순수 함수 — `test/nav-check.mjs` 가 검증한다.
 *
 * 합성 등치선(`mock/metrics.js`)을 대체한다. 그쪽은 고정 중심에서 사인파를 겹쳐 만든 가짜라
 * 배를 옮겨도 안 바뀌었고, 무엇보다 **화면에서 실데이터와 구분되지 않았다**.
 *
 * 매끈한 등치선 대신 칸을 그대로 그린다. 3km 격자라 굵게 보이지만
 * 그게 우리가 가진 해상도의 정직한 모습이다 — 보간하면 연안 경계에서 없는 값을 만든다
 * ([[260913_ocean-collector]] §7).
 */

/** 지도에 그릴 수 있는 항목. 나머지(파고·적조)는 격자 데이터가 없다 */
export type ZoneKey = 'tide' | 'temp';

export interface ZoneLegend {
  name: string;
  unit: string;
  min: number;
  max: number;
  dec: number;
  ramp: string[];
  /** 이 값들이 유효한 예측 시각 */
  predcDt: string;
  /** 칸 설명 ("본선 주변 격자 60칸 · 한 칸 약 3km"). 없으면 화면이 ROMS 문구를 쓴다 */
  note?: string;
  /** 출처 ("KHOA ROMS" · "기상청 해구별 예측") */
  source?: string;
}

export interface Zones {
  bands: ContourBand[];
  legend: ZoneLegend;
}

const SPEC: Record<ZoneKey, {
  name: string; unit: string; dec: number; ramp: string[];
  value: (c: RomsCell) => number | null;
}> = {
  // 순차 램프는 **한 색상이 옅은 쪽에서 진한 쪽으로** 간다.
  // 이전 램프는 파랑→청록→노랑→주황으로 색상이 돌았다(무지개) — 색만 보고 값 순서를 못 읽는다.
  // 방향도 뒤집었다. 밝은 종이 배경에서 진한 쪽이 "많다"로 읽힌다.
  tide: {
    name: '표층 유속', unit: 'm/s', dec: 2,
    ramp: ['#dff3f5', '#9fd9de', '#5aa9b8', '#2d6b85', '#123243'],
    value: (c) => c.currentSpeedMs,
  },
  temp: {
    name: '표층 수온', unit: '°C', dec: 1,
    ramp: ['#fdeee2', '#f6c9a4', '#e99a68', '#d1683a', '#a6401f'],
    value: (c) => c.waterTempC,
  },
};

/** 램프에서 색을 고른다. 구간 경계를 넘지 않게 끝을 물린다 */
export function rampAt(ramp: string[], t: number): string {
  const i = Math.max(0, Math.min(ramp.length - 1, Math.floor(t * ramp.length)));
  return ramp[i]!;
}

/** 칸 하나를 감싸는 사각형 */
function cellRing(cell: RomsCell, latStep: number, lonStep: number): LngLat[] {
  const dLat = latStep / 2;
  const dLon = lonStep / 2;
  return [
    [cell.lon - dLon, cell.lat - dLat],
    [cell.lon + dLon, cell.lat - dLat],
    [cell.lon + dLon, cell.lat + dLat],
    [cell.lon - dLon, cell.lat + dLat],
  ];
}

/** 색 기준 범위 */
export interface ValueRange {
  min: number;
  max: number;
}

/**
 * 지금 이후 전 시각에 걸친 이 항목의 범위. 서버가 `/grid` 응답에 싣는다.
 *
 * 프레임마다 min·max 를 다시 잡으면 시간 슬라이더를 넘길 때 **같은 색이 다른 값**이 된다 —
 * 수온이 1℃ 오른 것이 색으로는 안 보이고, 반대로 0.1℃ 차이가 진한 색 차이로 보인다.
 *
 * @return 범위가 없거나 평평하면 null — 호출부가 프레임 자체 범위로 물러선다
 */
export function rangeFor(grid: RomsGrid | null, key: ZoneKey | null): ValueRange | null {
  const r = grid?.range;
  if (!r || !key) {
    return null;
  }
  const [min, max] = key === 'tide' ? [r.speedMin, r.speedMax] : [r.tempMin, r.tempMax];
  return min != null && max != null && max > min ? { min, max } : null;
}

/** 유향 화살표 하나 */
export interface CurrentArrow {
  at: LngLat;
  /** 유향 deg. 북 0 · 시계방향 */
  deg: number;
  speedMs: number;
}

/**
 * 칸마다 유향 화살표.
 *
 * 방위나 유속이 없는 칸은 뺀다 — 0° 로 두면 '북'으로 읽힌다.
 * ⚠ KHOA 가이드에 crdir 방향 관례(흘러가는 쪽/오는 쪽)가 없다. 해양 관례인 **흘러가는 쪽**으로 읽는다.
 */
export function buildArrows(grid: RomsGrid | null): CurrentArrow[] {
  if (!grid) {
    return [];
  }
  return grid.cells
    .filter((c) => c.currentDirDeg != null && c.currentSpeedMs != null)
    .map((c) => ({ at: [c.lon, c.lat] as LngLat, deg: c.currentDirDeg!, speedMs: c.currentSpeedMs! }));
}

/**
 * @param range 색 기준 범위. 주면 그 범위로 칠하고 범례도 그 범위다(시간 슬라이더용).
 *              없으면 이 프레임의 min·max
 */
export function buildZones(grid: RomsGrid | null, key: ZoneKey | null, range?: ValueRange | null): Zones | null {
  if (!grid || !key) {
    return null;
  }
  const spec = SPEC[key];
  const valued = grid.cells
    .map((c) => ({ cell: c, v: spec.value(c) }))
    .filter((x): x is { cell: RomsCell; v: number } => x.v != null);
  if (valued.length === 0) {
    return null;
  }

  const min = range ? range.min : Math.min(...valued.map((x) => x.v));
  const max = range ? range.max : Math.max(...valued.map((x) => x.v));
  // 칸이 하나거나 값이 모두 같으면 0으로 나눈다. 그때는 램프 가운데로 칠한다
  const span = max - min;

  const bands: ContourBand[] = valued.map(({ cell, v }) => {
    // 고정 범위 밖 값은 끝 색에 물린다. 범위는 전 시각 min·max 라 정상이면 벗어나지 않는다
    const t = span > 0 ? Math.max(0, Math.min(1, (v - min) / span)) : 0.5;
    const fill = rampAt(spec.ramp, t);
    return { fill, line: fill, op: 0.34, polys: [[cellRing(cell, grid.latStep, grid.lonStep)]] };
  });

  return {
    bands,
    legend: {
      name: spec.name, unit: spec.unit, min, max, dec: spec.dec,
      ramp: spec.ramp, predcDt: grid.predcDt,
    },
  };
}

/**
 * 차트 공용 계산. 순수 함수 — `test/chart-check.mjs` 가 검증한다.
 *
 * 라이브러리를 넣지 않은 이유: 그려야 할 것이 라인 하나와 막대 하나다.
 * 선내 PC 사양이 미상이라(계획.md §0) 번들을 키우지 않는 편이 안전하고,
 * 색이 테마 토큰을 그대로 따라간다.
 */

export interface Extent {
  min: number;
  max: number;
}

/**
 * 축 범위. 0 에서 시작하지 않는다 — 수온 25~26℃ 를 0 부터 그리면 변화가 안 보인다.
 *
 * ⚠ 막대에는 쓰지 않는다. 막대는 길이가 곧 값이라 0 에서 시작해야 한다
 * (자르면 2배를 10배로 보이게 만든다).
 */
export function niceExtent(values: number[], padRatio = 0.12): Extent {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length === 0) {
    return { min: 0, max: 1 };
  }
  const lo = Math.min(...clean);
  const hi = Math.max(...clean);
  if (lo === hi) {
    // 값이 하나뿐이거나 모두 같다. 0 폭이면 나눗셈이 무한대가 된다
    const pad = Math.abs(lo) * 0.1 || 1;
    return { min: lo - pad, max: hi + pad };
  }
  const pad = (hi - lo) * padRatio;
  return { min: lo - pad, max: hi + pad };
}

/** 눈금 값. 4~6개면 격자가 배경으로 물러난다 */
export function ticks(extent: Extent, count = 4): number[] {
  const span = extent.max - extent.min;
  if (span <= 0) {
    return [extent.min];
  }
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const first = Math.ceil(extent.min / step) * step;
  const out: number[] = [];
  for (let v = first; v <= extent.max + step * 1e-6; v += step) {
    // 부동소수 잔차가 눈금 라벨에 그대로 찍힌다
    out.push(Math.round(v / step) * step);
  }
  return out;
}

export const scaleX = (i: number, n: number, w: number) => (n <= 1 ? w / 2 : (i / (n - 1)) * w);

export const scaleY = (v: number, e: Extent, h: number) =>
  e.max === e.min ? h / 2 : h - ((v - e.min) / (e.max - e.min)) * h;

/** 값이 빈 구간에서 선을 잇지 않는다. 이으면 없는 값을 있는 것처럼 그린다 */
export function linePath(
  values: (number | null)[], extent: Extent, w: number, h: number,
): string {
  let d = '';
  let pen = false;
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) { pen = false; return; }
    const x = scaleX(i, values.length, w);
    const y = scaleY(v, extent, h);
    d += `${pen ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
    pen = true;
  });
  return d.trim();
}

/** 램프에서 색 하나. 구간 경계를 넘지 않게 끝을 물린다 */
export function rampAt(ramp: string[], t: number): string {
  const i = Math.max(0, Math.min(ramp.length - 1, Math.floor(t * ramp.length)));
  return ramp[i]!;
}

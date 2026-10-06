// charts/scale.ts 검증. 축을 잘못 잡으면 화면이 값의 크기를 왜곡한다.
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const server = await createServer({
  root: here('..'), configFile: here('../vite.config.ts'),
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true, include: [] }, logLevel: 'silent',
});

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name} ${extra}`); }
};

const S = await server.ssrLoadModule('/src/charts/scale.ts');

console.log('\n축 범위');
// 수온 25~26℃ 를 0 부터 그리면 변화가 안 보인다. 라인은 0 에서 시작하지 않는다
const e = S.niceExtent([25.1, 25.9, 25.5]);
ok('데이터 범위에 여유만 붙인다', e.min > 24 && e.min < 25.1 && e.max > 25.9 && e.max < 27, JSON.stringify(e));
ok('0 을 포함하지 않는다', e.min > 0);

const flat = S.niceExtent([25.0, 25.0]);
ok('값이 모두 같아도 폭이 0 이 아니다', flat.max > flat.min, JSON.stringify(flat));
ok('빈 입력도 폭이 있다', S.niceExtent([]).max > S.niceExtent([]).min);
ok('NaN 은 무시', S.niceExtent([1, NaN, 3]).max > 3);

console.log('\n눈금');
const t = S.ticks({ min: 0, max: 1 }, 4);
ok('4개 안팎', t.length >= 3 && t.length <= 7, JSON.stringify(t));
ok('부동소수 잔차가 없다', t.every((v) => Math.abs(v * 1000 - Math.round(v * 1000)) < 1e-6), JSON.stringify(t));
ok('폭이 0 이면 한 개', S.ticks({ min: 5, max: 5 }).length === 1);

console.log('\n좌표');
ok('첫 점은 0', S.scaleX(0, 10, 100) === 0);
ok('끝 점은 폭', S.scaleX(9, 10, 100) === 100);
ok('점이 하나면 가운데', S.scaleX(0, 1, 100) === 50);
// SVG 는 y 가 아래로 자란다. 큰 값이 위로 가야 한다
ok('최대값이 위(y=0)', S.scaleY(10, { min: 0, max: 10 }, 100) === 0);
ok('최소값이 아래(y=h)', S.scaleY(0, { min: 0, max: 10 }, 100) === 100);

console.log('\n선 잇기');
// 값이 빈 구간을 이으면 없는 값을 있는 것처럼 그린다
const gap = S.linePath([1, null, 3], { min: 0, max: 4 }, 100, 100);
ok('결측에서 선을 끊는다', (gap.match(/M/g) || []).length === 2, gap);
ok('연속이면 M 하나', (S.linePath([1, 2, 3], { min: 0, max: 4 }, 100, 100).match(/M/g) || []).length === 1);
ok('전부 결측이면 빈 경로', S.linePath([null, null], { min: 0, max: 1 }, 100, 100) === '');

console.log('\n램프');
const ramp = ['a', 'b', 'c', 'd', 'e'];
ok('0 은 첫 색', S.rampAt(ramp, 0) === 'a');
ok('1 은 마지막 색', S.rampAt(ramp, 1) === 'e');
ok('범위를 벗어나도 끝에 물린다', S.rampAt(ramp, 2) === 'e' && S.rampAt(ramp, -1) === 'a');

console.log('\n지도 램프 — 순차는 한 색상이 옅은→진한');
const Z = await server.ssrLoadModule('/src/cloud/zones.ts');
const grid = {
  predcDt: '2026-09-13T09:00:00Z', latStep: 0.02864, lonStep: 0.03197,
  cells: [
    { lat: 35.0, lon: 129.0, currentDirDeg: 0, currentSpeedMs: 0.03, waterTempC: 24.9 },
    { lat: 35.03, lon: 129.03, currentDirDeg: 0, currentSpeedMs: 0.34, waterTempC: 25.9 },
  ],
};
const tide = Z.buildZones(grid, 'tide');
ok('작은 값이 옅은 색', tide.bands[0].fill === '#dff3f5', tide.bands[0].fill);
ok('큰 값이 진한 색', tide.bands[1].fill === '#123243', tide.bands[1].fill);

console.log('\n등치선 — 육지를 가로지르지 않는다');
const C = await server.ssrLoadModule('/src/cloud/contours.ts');
const STEP = { latStep: 0.02864, lonStep: 0.03197 };
const cell = (i, j, v) => ({
  lat: 35 + i * STEP.latStep, lon: 129 + j * STEP.lonStep,
  currentDirDeg: 0, currentSpeedMs: v, waterTempC: 20 + v,
});
// 2x2 전부 바다. 값이 갈리므로 선이 지나간다
const full = C.buildIsolines({ predcDt: 'x', ...STEP,
  cells: [cell(0, 0, 0.1), cell(0, 1, 0.5), cell(1, 0, 0.2), cell(1, 1, 0.6)] }, 'tide', 3);
ok('바다 칸에서는 선이 나온다', full.levels.length > 0 && full.cellCount === 1,
  `levels=${full.levels.length} cells=${full.cellCount}`);
ok('레벨이 min~max 안', full.levels.every((l) => l.value > full.min && l.value < full.max));
ok('선분은 두 점', full.levels[0].segments.every((s) => s.length === 2));
ok('좌표는 [lng, lat]', full.levels[0].segments[0][0][0] > 100);

// 한 꼭짓점이 육지(빠짐)다. 그 칸은 통째로 건너뛴다 — 없는 물을 만들지 않는다
const holed = C.buildIsolines({ predcDt: 'x', ...STEP,
  cells: [cell(0, 0, 0.1), cell(0, 1, 0.5), cell(1, 0, 0.2)] }, 'tide', 3);
ok('육지에 닿은 칸은 건너뛴다', holed === null || holed.cellCount === 0,
  JSON.stringify(holed && holed.cellCount));

// 값이 모두 같으면 그릴 선이 없다 — 억지로 그리면 격자 모양만 나온다
const flatField = C.buildIsolines({ predcDt: 'x', ...STEP,
  cells: [cell(0, 0, 0.3), cell(0, 1, 0.3), cell(1, 0, 0.3), cell(1, 1, 0.3)] }, 'tide', 3);
ok('평평하면 선이 없다', flatField.levels.length === 0);

ok('점이 모자라면 null', C.buildIsolines({ predcDt: 'x', ...STEP, cells: [cell(0, 0, 0.1)] }, 'tide') === null);
ok('격자 없으면 null', C.buildIsolines(null, 'tide') === null);

// 안장점을 한쪽으로 고르면 그 선택이 지형처럼 보인다. 둘 다 그린다
const saddle = C.buildIsolines({ predcDt: 'x', ...STEP,
  cells: [cell(0, 0, 0.9), cell(0, 1, 0.1), cell(1, 0, 0.1), cell(1, 1, 0.9)] }, 'tide', 1);
ok('안장점은 선분 둘', saddle.levels[0].segments.length === 2,
  String(saddle.levels[0].segments.length));

// 고정 범위를 주면 레벨이 그 범위에 놓인다 — 시간을 넘겨도 "같은 값의 선"이 유지된다
const fixedIso = C.buildIsolines({ predcDt: 'x', ...STEP,
  cells: [cell(0, 0, 0.1), cell(0, 1, 0.5), cell(1, 0, 0.2), cell(1, 1, 0.6)] }, 'tide', 1, { min: 0, max: 0.8 });
ok('고정 범위면 레벨이 범위 가운데', fixedIso.levels.length === 1 && Math.abs(fixedIso.levels[0].value - 0.4) < 1e-9,
  JSON.stringify(fixedIso.levels.map((l) => l.value)));

console.log('\n시간 슬라이더 — 색 기준 고정 · 화살표 · 눈금');
const fixed = Z.buildZones(grid, 'tide', { min: 0, max: 1 });
ok('고정 범위면 범례가 그 범위', fixed.legend.min === 0 && fixed.legend.max === 1);
ok('고정 범위로 칠한다 (0.34 → 두 번째 색)', fixed.bands[1].fill === '#9fd9de', fixed.bands[1].fill);
const clamped = Z.buildZones(grid, 'tide', { min: 0.1, max: 0.2 });
ok('범위 밖 값은 끝 색에 물린다', clamped.bands[0].fill === '#dff3f5' && clamped.bands[1].fill === '#123243',
  `${clamped.bands[0].fill} ${clamped.bands[1].fill}`);
const withRange = { ...grid, range: { speedMin: 0.01, speedMax: 0.9, tempMin: 20, tempMax: 26 } };
ok('rangeFor 는 항목별 범위', JSON.stringify(Z.rangeFor(withRange, 'temp')) === '{"min":20,"max":26}');
ok('범위가 없으면 null (옛 캐시)', Z.rangeFor(grid, 'tide') === null);
ok('평평한 범위는 null', Z.rangeFor({ ...grid, range: { speedMin: 0.3, speedMax: 0.3, tempMin: null, tempMax: null } }, 'tide') === null);

const arrows = Z.buildArrows({ ...grid, cells: [...grid.cells,
  { lat: 35.06, lon: 129.06, currentDirDeg: null, currentSpeedMs: 0.2, waterTempC: 25 }] });
ok('방위 없는 칸은 화살표를 안 그린다 (0° 는 북이다)', arrows.length === 2, String(arrows.length));
ok('화살표 좌표는 [lng, lat]', arrows[0].at[0] === 129.0 && arrows[0].at[1] === 35.0);
ok('격자 없으면 화살표 없음', Z.buildArrows(null).length === 0);

console.log('\n해구 층 — 기상청 해구별 예측');
const ZL = await server.ssrLoadModule('/src/cloud/zoneLayer.ts');
const zcell = (lz, sz, latMin, lonMin, step, v) => ({
  lzone: lz, szone: sz, latMin, latMax: latMin + step, lonMin, lonMax: lonMin + step,
  waveHeightM: v.wh ?? null, wavePeriodMaxS: null, waveDirDeg: null,
  windSpeedMs: v.ws ?? null, windDirDeg: v.wd ?? null,
  visibilityM: null, rainMm: null, waterTempC: v.tw ?? null, swellLevel: null,
});
// 2026-09-14 실응답 — 부산 앞 대해구 92 와 육지 대해구
const zgrid = {
  level: 'large', issuedAt: '2026-09-14T00:00:00Z', validAt: '2026-09-14T12:00:00Z', stepDeg: 0.5,
  times: ['2026-09-14T12:00:00Z'], range: { waveMin: 0, waveMax: 2, windMin: 0, windMax: 12, tempMin: null, tempMax: null },
  cells: [
    zcell(92, 0, 35.0, 129.0, 0.5, { wh: 0.6, ws: 6.6, wd: 39.6 }),
    zcell(93, 0, 35.0, 129.5, 0.5, { wh: 1.8, ws: 10.7, wd: 54.1 }),
    zcell(17, 0, 37.5, 127.0, 0.5, {}),
  ],
};
const zw = ZL.buildZoneLayer(zgrid, 'wave', ZL.zoneRangeFor(zgrid, 'wave'));
ok('결측 칸은 칠하지 않는다 (0m 로 읽힌다)', zw.bands.length === 2, String(zw.bands.length));
ok('칸은 해구 경계 사각형', JSON.stringify(zw.bands[0].polys[0][0]) === JSON.stringify([[129, 35], [129.5, 35], [129.5, 35.5], [129, 35.5]]));
ok('발표본 범위로 범례', zw.legend.min === 0 && zw.legend.max === 2);
ok('범례에 층·칸 크기', zw.legend.note === '대해구 2칸 · 한 칸 약 56km', zw.legend.note);
ok('발효시각을 들고 간다', zw.legend.predcDt === zgrid.validAt);
ok('대해구에 수온이 없으면 null', ZL.buildZoneLayer(zgrid, 'temp') === null);
ok('수온 범위가 없으면 null', ZL.zoneRangeFor(zgrid, 'temp') === null);

const wind = ZL.buildWindArrows(zgrid);
ok('바람 화살표는 불어가는 쪽 (39.6 → 219.6)', wind.length === 2 && Math.abs(wind[0].deg - 219.6) < 1e-9, JSON.stringify(wind[0]));
ok('화살표는 칸 중심', wind[0].at[0] === 129.25 && wind[0].at[1] === 35.25);
ok('주변만 고르면 먼 칸은 뺀다', ZL.buildWindArrows(zgrid, [129.25, 35.25], 0.3).length === 1);
ok('발표본 경계', JSON.stringify(ZL.zoneBounds(zgrid)) === JSON.stringify([[127, 35], [130, 38]]), JSON.stringify(ZL.zoneBounds(zgrid)));

const T = await server.ssrLoadModule('/src/cloud/timeline.ts');
// KST 자정 = 전날 15:00Z
const hours = ['2026-09-14T13:00:00Z', '2026-09-14T14:00:00Z', '2026-09-14T15:00:00Z', '2026-09-14T16:00:00Z'];
const tk = T.dayTicks(hours);
ok('KST 자정에만 날짜 눈금', tk.length === 1 && tk[0].index === 2 && tk[0].label === '09.15', JSON.stringify(tk));
ok('눈금 위치는 슬라이더 인덱스 비율', Math.abs(tk[0].pct - 200 / 3) < 1e-9, String(tk[0].pct));
ok('시각이 하나면 눈금 없음', T.dayTicks([hours[0]]).length === 0);
ok('프레임 라벨은 KST', T.frameLabel('2026-09-14T21:00:00Z') === '9/15(화) 06시', T.frameLabel('2026-09-14T21:00:00Z'));

await server.close();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

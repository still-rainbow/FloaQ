// nav/step.ts 검증. 가상 항해가 실제로 움직이는지, 속력 환산이 맞는지.
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const server = await createServer({
  root: here('..'),
  configFile: here('../vite.config.ts'),
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true, include: [] },
  logLevel: 'silent',
});

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name} ${extra}`); }
};

const S = await server.ssrLoadModule('/src/nav/step.ts');
const AT = [129.05, 35.05];

console.log('\n속력 환산');
// 1kn = 1해리/시 = 위도 1분/시. km 를 거치면 1.852배 빨라진다 — 처음 그렇게 짜서 틀렸다
ok('1kn = 1/(60*3600) deg/s', Math.abs(S.KN_TO_DEG_LAT_PER_SEC - 1 / 216000) < 1e-12, String(S.KN_TO_DEG_LAT_PER_SEC));
ok('끝까지 밀면 8kn (바깥 고리는 배속으로 빨라지지 속력이 커지지 않는다)', S.speedKn(0, -1) === 8, String(S.speedKn(0, -1)));
ok('데드존 안이면 0', S.speedKn(0.1, 0) === 0, String(S.speedKn(0.1, 0)));

console.log('\n한 걸음');
ok('데드존 안이면 안 움직인다', S.step(AT, 0.05, 0, 1) === null);
ok('dt 0 이면 안 움직인다', S.step(AT, 0, -1, 0) === null);

const up = S.step(AT, 0, -1, 1);
ok('화면 위로 밀면 북상 (y 부호 반전)', up[1] > AT[1], JSON.stringify(up));
ok('북상만 하면 경도는 그대로', Math.abs(up[0] - AT[0]) < 1e-12, JSON.stringify(up));

const right = S.step(AT, 1, 0, 1);
ok('오른쪽이면 동진', right[0] > AT[0] && Math.abs(right[1] - AT[1]) < 1e-12, JSON.stringify(right));

console.log('\n두 고리 — 안쪽은 실제 속력, 바깥은 시연 배속');
const INNER = S.INNER_RATIO;
ok('점선 안은 배속 없음', S.timeScale(0, -INNER) === 1);
ok('점선 밖은 배속', S.timeScale(0, -1) === S.FAST_SCALE, String(S.timeScale(0, -1)));
ok('점선 끝에서 8kn', Math.abs(S.speedKn(0, -INNER) - 8) < 1e-9, String(S.speedKn(0, -INNER)));
ok('점선 절반이면 4kn', Math.abs(S.speedKn(0, -INNER / 2) - 4) < 1e-9, String(S.speedKn(0, -INNER / 2)));
ok('바깥에서도 8kn 로 고정', S.speedKn(0, -1) === 8, String(S.speedKn(0, -1)));

// 실제 8kn 은 4.1m/s 다. zoom 13 에서 1픽셀이 약 19m 라 10초에 2픽셀 — 안 움직이는 것처럼 보인다
const slow = S.step(AT, 0, -INNER, 1);
const slowM = (slow[1] - AT[1]) * 111320;
ok('안쪽은 실제 8kn ≈ 4.1m/s', Math.abs(slowM - 4.115) < 0.02, `${slowM.toFixed(2)}m/s`);

const fast = S.step(AT, 0, -1, 1);
const mPerSec = (fast[1] - AT[1]) * 111320;
ok('바깥은 초당 400m 이상', mPerSec > 400, `${mPerSec.toFixed(0)}m/s`);
ok('격자 한 칸(3km)을 10초 안에', 3000 / mPerSec < 10, `${(3000 / mPerSec).toFixed(1)}초`);
ok('둘의 비가 배속과 같다', Math.abs(mPerSec / slowM - S.FAST_SCALE) < 1e-6);

console.log('\n경도 수축 보정');
// 보정 없이 더하면 고위도에서 동서로 빨라진다
const low = S.step([129.05, 5], 1, 0, 1);
const high = S.step([129.05, 60], 1, 0, 1);
ok('고위도에서 경도 변화가 더 크다', (high[0] - 129.05) > (low[0] - 129.05) * 1.9,
  `${(low[0] - 129.05).toExponential(3)} vs ${(high[0] - 129.05).toExponential(3)}`);
// 실제 이동 거리는 같아야 한다
const lowM = (low[0] - 129.05) * 111320 * Math.cos(5 * Math.PI / 180);
const highM = (high[0] - 129.05) * 111320 * Math.cos(60 * Math.PI / 180);
ok('실제 이동 거리는 위도와 무관', Math.abs(lowM - highM) < 1, `${lowM.toFixed(0)}m vs ${highM.toFixed(0)}m`);

console.log('\n누적');
let at = AT;
for (let i = 0; i < 60; i++) at = S.step(at, 0, -1, 1 / 60);
const movedM = (at[1] - AT[1]) * 111320;
ok('1초치를 60프레임으로 나눠도 같은 거리', Math.abs(movedM - mPerSec) < 1, `${movedM.toFixed(0)}m`);

console.log('\n지도 구역 — 실제 격자');
const Z = await server.ssrLoadModule('/src/cloud/zones.ts');
// 2026-09-13 실측: 남쪽 외해 0.28~0.40, 북쪽 내만 0.035 — 10배 갈린다
const GRID = {
  predcDt: '2026-09-13T09:00:00Z', latStep: 0.02864, lonStep: 0.03197,
  cells: [
    { lat: 35.00898, lon: 129.02008, currentDirDeg: 73, currentSpeedMs: 0.34, waterTempC: 25.1 },
    { lat: 35.03764, lon: 129.05204, currentDirDeg: 80, currentSpeedMs: 0.31, waterTempC: 25.9 },
    { lat: 35.06628, lon: 129.05204, currentDirDeg: 0, currentSpeedMs: 0.03, waterTempC: 24.9 },
  ],
};
const z = Z.buildZones(GRID, 'tide');
ok('칸마다 밴드 하나', z.bands.length === 3, String(z.bands.length));
ok('범례 범위가 실제 값', z.legend.min === 0.03 && z.legend.max === 0.34, JSON.stringify([z.legend.min, z.legend.max]));
ok('예측 시각을 들고 간다', z.legend.predcDt === GRID.predcDt);
const ring = z.bands[0].polys[0][0];
ok('칸은 사각형 4점', ring.length === 4, String(ring.length));
ok('칸 크기가 격자 간격', Math.abs((ring[2][1] - ring[0][1]) - GRID.latStep) < 1e-9);
ok('좌표는 [lng, lat]', Math.abs(ring[0][0] - (129.02008 - GRID.lonStep / 2)) < 1e-9);
ok('값 없는 항목은 null', Z.buildZones({ ...GRID, cells: GRID.cells.map((c) => ({ ...c, waterTempC: null })) }, 'temp') === null);
ok('격자 없으면 null', Z.buildZones(null, 'tide') === null);
ok('값이 모두 같으면 램프 가운데', Z.buildZones({ ...GRID, cells: [GRID.cells[0]] }, 'tide').bands.length === 1);

await server.close();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

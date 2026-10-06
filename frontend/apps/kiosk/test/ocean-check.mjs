// cloud/readings.ts 검증. 입력은 2026-09-13·14 EC2 실응답을 그대로 옮긴 것이다.
// vite 모듈 그래프로 실제 소스를 로드한다 — mqtt-check.mjs 와 같은 방식.
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

const R = await server.ssrLoadModule('/src/cloud/readings.ts');

// 기준 시각을 고정한다. formatAge 가 "N분 전"을 계산하는 기준
const NOW = new Date('2026-09-13T09:00:00Z');   // 18:00 KST

const src = (source, kind, observedAt, intervalSec, payload, resultCode = '00') => ({
  source, kind, observedAt, fetchedAt: '2026-09-13T08:59:00Z',
  ageSec: observedAt ? Math.floor((NOW - new Date(observedAt)) / 1000) : null,
  intervalSec, resultCode, resultMsg: null, payload,
});

/** 운항지수 지금 구간. 2026-09-14 대한해협 실응답 값 — 시각만 NOW 에 맞췄다 */
const SHIP_NOW = { at: '2026-09-13T09:00:00Z', slot: '밤', score: '좋음', level: 2,
  currentSpeedMs: 0.31, windSpeedMs: 6.6, waveHeightM: 0.6 };

const REAL = [
  src('roms', 'FORECAST', '2026-09-12T15:00:00Z', 3600, {
    gridCount: 1424, baseAt: '2026-09-12T15:00:00Z', validAt: '2026-09-13T09:00:00Z',
    lat: 35.03764, lon: 129.05204, distanceKm: 1.4, currentDirDeg: 285.73, currentSpeedMs: 0.31, waterTempC: 25.86,
  }),
  src('sea-obs', 'OBSERVATION', '2026-09-13T08:00:00Z', 1800, {
    stationCount: 2, stations: [
      { network: 'C', stn: '22459', name: '오륙도', lat: 35.0945, lon: 129.1283, distanceKm: 8.6,
        waveHeightM: 0.4, windDirDeg: null, windSpeedMs: null, windGustMs: null, waterTempC: 25.4, airTempC: null, pressureHpa: null, humidityPct: null },
      { network: 'L', stn: '984', name: '오륙도', lat: 35.091, lon: 129.127, distanceKm: 8.4,
        waveHeightM: null, windDirDeg: 194, windSpeedMs: 5.3, windGustMs: 6.4, waterTempC: null, airTempC: 26.2, pressureHpa: 1015.9, humidityPct: null },
    ],
  }),
  // 2026-09-14 getPwnCd·getPwnStatus 실응답. 현황 문장은 "없 음" 처럼 공백이 섞여 온다
  src('weather-warning', 'ADVISORY', '2026-09-10T21:00:00Z', 600, {
    activeMarineWarnings: [], activeAreas: [], eventCount: 75,
    status: { announcedAt: '2026-09-10T21:00:00Z', effectiveAt: '2026-09-10T23:00:00Z', current: '없 음', preliminary: '없음', note: '없음' },
    events: [{ announcedAt: '2026-09-10T21:00:00Z', areaName: '제주도남쪽바깥먼바다', name: '풍랑주의보', action: '해제' }],
  }),
  src('fishing-ground', 'OBSERVATION', '2026-09-13T08:30:00Z', 1800, {
    stationCount: 1, stations: [
      { code: 'bgj8a', name: '기장', sea: '남해', lat: 35.2208, lon: 129.2635, distanceKm: 26.1, waterTempC: 25.8, observedAt: '2026-09-13T08:30:00Z' },
    ],
  }),
  src('red-tide', 'ADVISORY', '2026-09-12T15:00:00Z', 3600, {
    codNews: '20260913-001', dayReport: '20260913',
    organisms: [{ name: 'Cochlodinium polykrikoides', area: '전남 여수', maxDensity: 0.1 }],
    breaking: '- 적조 예비특보 확대 발표(2026. 8. 14. 16:00)',
  }),
  src('jellyfish', 'ADVISORY', '2026-09-09T15:00:00Z', 86400, {
    subject: '해파리 모니터링 주간보고 19차 (2026.09.10)', caveat: '설문 응답률…',
  }),
  src('ship-index', 'FORECAST', '2026-09-12T15:00:00Z', 3600, {
    focusCode: 'AA_0004', focusName: '대한해협', validAt: SHIP_NOW.at, current: SHIP_NOW,
    areas: [{ code: 'AA_0004', name: '대한해협', slots: [SHIP_NOW] }],
  }),
  // 2026-09-16 조석예보 실응답 모양. 서버가 조회 좌표로 잘라 가까운 순으로 준다(StationNear).
  // ⚠ REAL 은 인덱스로도 참조된다(REAL[1]·REAL[6]) — 새 소스는 끝에만 붙인다
  src('tide-forecast', 'FORECAST', '2026-09-13T09:00:00Z', 86400, {
    stationCount: 1, requestedStations: 166, failedStations: 0, rowCount: 3984,
    stations: [
      { code: 'DT_0005', name: '부산', lat: 35.09638, lon: 129.03527, distanceKm: 8.2,
        predcDt: '2026-09-13T09:00:00Z', tideLevelM: 1.0547 },
    ],
  }),
];

/** /current 응답. 2026-09-13 실측 */
const CUR = { predcDt: '2026-09-13T09:00:00Z', lat: 35.03764, lon: 129.05204, currentDirDeg: 285.73,
  currentSpeedMs: 0.31, waterTempC: 25.86, distanceKm: 1.4, neighborSpreadMs: 0.34, neighborCount: 7 };

const row = (cat, label) => cat.rows.find((r) => r.label === label);
const withSource = (name, payload) => REAL.map((x) => (x.source === name ? { ...x, payload } : x));

console.log('\nbuildCategories — 실응답');
const cats = R.buildCategories(REAL, NOW);

const warn = row(cats.safe, '해상 특보');
ok('특보 없음 → ok pill', warn.pill === 'ok' && warn.value === '없음', JSON.stringify(warn));
ok('특보 시각은 "발표"', /발표/.test(warn.age) && !/관측/.test(warn.age), warn.age);
ok('발효 없으면 해역 문구 없음', !/본선 구역 미판정/.test(warn.age), warn.age);

const pre = row(cats.safe, '예비특보');
ok('예비특보 "없음" → ok', pre.value === '없음' && pre.pill === 'ok', JSON.stringify(pre));

const wave = row(cats.safe, '유의파고');
ok('파고는 파고부이(C)에서', wave.value === '0.4' && wave.unit === 'm', JSON.stringify(wave));
ok('지점·거리 병기', /오륙도 8\.6km/.test(wave.age), wave.age);
ok('1시간 전 관측', /^1시간 전 관측/.test(wave.age), wave.age);

const wind = row(cats.safe, '풍속 · 풍향');
ok('바람은 등표(L)에서 — 요소별로 지점이 갈린다', wind.value === '5.3' && /984|오륙도 8\.4km/.test(wind.age), JSON.stringify(wind));
ok('풍향 16방위 한글', /남 194°|남남서 194°/.test(wind.age), wind.age);
ok('돌풍은 같은 지점 값으로 붙인다', /돌풍 6\.4m\/s · 오륙도 8\.4km/.test(wind.age), wind.age);
const noGust = R.buildCategories(withSource('sea-obs', { ...REAL[1].payload,
  stations: REAL[1].payload.stations.map((s) => ({ ...s, windGustMs: null })) }), NOW);
ok('돌풍 없으면 문구도 없다', !/돌풍/.test(row(noGust.safe, '풍속 · 풍향').age));

const temp = row(cats.fish, '표층 수온');
ok('수온은 수과원 우선', temp.value === '25.8' && /기장 26\.1km · 수과원/.test(temp.age), JSON.stringify(temp));
ok('30분 전 관측', /^30분 전 관측/.test(temp.age), temp.age);

const cold = row(cats.fish, '저체온 한계');
ok('조업 표에는 저체온 추정을 싣지 않는다', cold === undefined);

const red = row(cats.fish, '적조');
ok('특보 문구 있으면 warn', red.pill === 'warn' && red.value === '특보', JSON.stringify(red));
ok('조사해역 텍스트 병기', /전남 여수/.test(red.age), red.age);

const jelly = row(cats.fish, '해파리');
ok('해파리는 항상 stale + 단서', jelly.stale === true && /판단 근거 아님/.test(jelly.age), JSON.stringify(jelly));

const cur = row(cats.nav, '표층 유속 예측');
ok('유속 m/s 2자리', cur.value === '0.31' && cur.unit === 'm/s', JSON.stringify(cur));
ok('예측값 문구 — "N분 전"이 아니다', /^18시 예측값/.test(cur.age) && !/전 관측/.test(cur.age), cur.age);
ok('kn 병기 · 방위 · 격자 거리', /0\.6kn/.test(cur.age) && /서북서 286°/.test(cur.age) && /격자 1\.4km/.test(cur.age), cur.age);
ok('예보는 stale 아님 (validAt 있음)', cur.stale === false, String(cur.stale));

console.log('\n해상 특보 — 특보구역 이벤트 (2026-09-14 전환)');
const hot = R.buildCategories(withSource('weather-warning', {
  activeMarineWarnings: ['풍랑주의보'],
  activeAreas: [
    { areaCode: 'S1311100', areaName: '부산앞바다', kind: '풍랑', level: '주의보', name: '풍랑주의보', since: '2026-09-08T09:00:00Z' },
    { areaCode: 'S1311400', areaName: '거제시동부앞바다', kind: '풍랑', level: '주의보', name: '풍랑주의보', since: '2026-09-08T09:00:00Z' },
    { areaCode: 'S1312010', areaName: '남해동부안쪽먼바다', kind: '풍랑', level: '경보', name: '풍랑경보', since: '2026-09-09T03:00:00Z' },
  ],
  status: { current: '풍랑주의보 : 부산앞바다, 거제시동부앞바다', preliminary: '(1) 풍랑 예비특보\n09월 14일 새벽 : 남해동부앞바다', note: null },
  eventCount: 3, events: [],
}), NOW);
const hotWarn = row(hot.safe, '해상 특보');
ok('발효 중 → alert', hotWarn.pill === 'alert' && hotWarn.value === '풍랑주의보', JSON.stringify(hotWarn));
ok('해역 2곳 + 외 N곳', /부산앞바다, 거제시동부앞바다 외 1곳/.test(hotWarn.age), hotWarn.age);
ok('본선 구역 미판정을 숨기지 않는다', /본선 구역 미판정/.test(hotWarn.age), hotWarn.age);
const hotPre = row(hot.safe, '예비특보');
ok('예비특보 있음 → warn + 원문 한 줄', hotPre.value === '있음' && hotPre.pill === 'warn' && /남해동부앞바다/.test(hotPre.age) && !/\n/.test(hotPre.age), JSON.stringify(hotPre));

console.log('\n해상 특보 — 조업 해역 판정 (warning-zone 계층)');
const HOT_AREAS = [
  { areaCode: 'S1323200', areaName: '제주도동부앞바다', kind: '풍랑', level: '주의보', name: '풍랑주의보', since: '2026-09-08T09:00:00Z' },
  { areaCode: 'S1310000', areaName: '남해동부전해상', kind: '풍랑', level: '경보', name: '풍랑경보', since: '2026-09-09T03:00:00Z' },
];
const focused = (focus) => R.buildCategories(withSource('weather-warning', {
  activeMarineWarnings: ['풍랑주의보', '풍랑경보'], activeAreas: HOT_AREAS,
  status: { current: '풍랑주의보 : 제주도동부앞바다', preliminary: '없음', note: null }, eventCount: 2, events: [],
  focus: { codes: ['S1311100', 'S1312010'], names: ['부산앞바다', '남해동부안쪽먼바다'], hierarchy: true, relatedCount: 8, ...focus },
}), NOW);
const fHit = row(focused({ activeMarineWarnings: ['풍랑경보'], activeAreas: [HOT_AREAS[1]] }).safe, '해상 특보');
ok('조업 해역 상위 구역 경보 → 조업 해역 값', fHit.value === '풍랑경보' && fHit.pill === 'alert', JSON.stringify(fHit));
ok('조업 해역 이름 + 전국 수', /조업 해역 부산앞바다·남해동부안쪽먼바다/.test(fHit.age) && /전국 2곳 발효/.test(fHit.age), fHit.age);
ok('조업 해역 판정이면 "본선 구역 미판정" 문구 없음', !/본선 구역 미판정/.test(fHit.age), fHit.age);
const fMiss = row(focused({ activeMarineWarnings: [], activeAreas: [] }).safe, '해상 특보');
ok('남의 해역만 발효 → 조업 해역은 없음 + 전국은 문구로', fMiss.value === '없음' && fMiss.pill === 'ok' && /전국 2곳 발효/.test(fMiss.age), JSON.stringify(fMiss));
const fFlat = row(focused({ hierarchy: false, activeMarineWarnings: [], activeAreas: [] }).safe, '해상 특보');
ok('계층 없으면 숨기지 않는다', /상위 구역 미반영/.test(fFlat.age), fFlat.age);
const fLine = R.statusLine(withSource('weather-warning', {
  activeMarineWarnings: ['풍랑주의보'], activeAreas: [HOT_AREAS[0]],
  focus: { codes: ['S1311100'], names: ['부산앞바다'], hierarchy: true, relatedCount: 5, activeMarineWarnings: [], activeAreas: [] },
}));
ok('statusLine 도 조업 해역 기준', /^조업 해역 해상특보 없음/.test(fLine), fLine);

// localStorage 에 옛 모양(notices) 캐시가 남아 있어도 죽지 않는다
const legacy = R.buildCategories(withSource('weather-warning', {
  activeMarineWarnings: [], noticeCount: 28, notices: [{ announcedAt: null, title: '[특보] 제09-77호' }],
}), NOW);
ok('옛 캐시 — 특보 행은 그대로', row(legacy.safe, '해상 특보').value === '없음');
ok('옛 캐시 — 예비특보는 "없음"이 아니라 미수신', row(legacy.safe, '예비특보').value === '값 없음' && /특보현황 미수신/.test(row(legacy.safe, '예비특보').age));

console.log('\n선박운항지수');
const ship = row(cats.nav, '운항지수');
ok('지금 구간 등급 + 알약', ship.value === '좋음' && ship.pill === 'ok', JSON.stringify(ship));
ok('권역·날짜·구간·파고·풍속', /대한해협 13일 밤/.test(ship.age) && /파고 0\.6m/.test(ship.age) && /풍속 6\.6m\/s/.test(ship.age), ship.age);
ok('참고지수임을 밝힌다', /참고지수/.test(ship.age), ship.age);
ok('구간 시작 직후 stale 아님', ship.stale === false);
ok('본선 격자가 있어도 운항지수 행이 있다', !!row(R.buildCategories(REAL, NOW, CUR).nav, '운항지수'));
const bad = R.buildCategories(withSource('ship-index', { ...REAL[6].payload, current: { ...SHIP_NOW, score: '매우나쁨', level: 5 } }), NOW);
ok('매우나쁨 → alert', row(bad.nav, '운항지수').pill === 'alert');
const mid = R.buildCategories(withSource('ship-index', { ...REAL[6].payload, current: { ...SHIP_NOW, score: '보통', level: 3 } }), NOW);
ok('보통 → 알약 없음 (색으로 말할 상태가 아니다)', row(mid.nav, '운항지수').pill === undefined);
ok('13시간 지나면 stale (폴링 멈춤)', row(R.buildCategories(REAL, new Date('2026-09-13T22:00:00Z')).nav, '운항지수').stale === true);
ok('소스 없으면 미수신', row(R.buildCategories(REAL.filter((x) => x.source !== 'ship-index'), NOW).nav, '운항지수').age === '미수신');
const shipWith = (next, current = SHIP_NOW) => R.buildCategories(withSource('ship-index', {
  ...REAL[6].payload, current,
  areas: [{ code: 'AA_0004', name: '대한해협', slots: [current, next] }],
}), NOW);
const SLOT_NEXT = { ...SHIP_NOW, at: '2026-09-13T21:00:00Z', slot: '새벽' };
const worse = row(shipWith({ ...SLOT_NEXT, score: '나쁨', level: 4 }).nav, '운항지수');
ok('다음 구간 악화 문구', /다음 14일 새벽 나쁨\(악화\)/.test(worse.age), worse.age);
ok('다음 구간이 나쁨 이상이면 미리 warn', worse.pill === 'warn' && worse.value === '좋음', JSON.stringify(worse));
const better = row(shipWith({ ...SLOT_NEXT, score: '좋음', level: 2 }, { ...SHIP_NOW, score: '나쁨', level: 4 }).nav, '운항지수');
ok('호전 문구 · 지금 등급 알약 유지', /\(호전\)/.test(better.age) && better.pill === 'warn', JSON.stringify(better));
const same = row(shipWith({ ...SLOT_NEXT, score: '좋음', level: 2 }).nav, '운항지수');
ok('같은 등급이면 악화·호전 없음', /다음 14일 새벽 좋음 ·/.test(same.age) && !/악화|호전/.test(same.age), same.age);
ok('다음 구간 없으면 문구 없음', !/다음/.test(row(cats.nav, '운항지수').age));

console.log('\n조위 (KHOA 조석예보)');
const tide = row(cats.nav, '조위');
ok('조위 m 2자리 — 원본 cm 를 100 으로 나눈 값', tide.value === '1.05' && tide.unit === 'm', JSON.stringify(tide));
ok('지점·거리·기관 병기 — 만마다 만조가 다르다', /부산 8\.2km · KHOA/.test(tide.age), tide.age);
ok('예보 문구 — "N분 전 관측"이 아니다', /^18시 예보/.test(tide.age) && !/관측/.test(tide.age), tide.age);
ok('예보 시각이 아직 안 지났으면 stale 아님', tide.stale === false, String(tide.stale));
ok('본선 격자가 있어도 조위 행이 있다', !!row(R.buildCategories(REAL, NOW, CUR).nav, '조위'));
const tideLate = row(R.buildCategories(REAL, new Date('2026-09-13T10:00:00Z')).nav, '조위');
ok('예보 시각이 지나면 stale (폴링 멈춤)', tideLate.stale === true && tideLate.value === '1.05', JSON.stringify(tideLate));
const noStation = row(R.buildCategories(withSource('tide-forecast', { stationCount: 0, stations: [] }), NOW).nav, '조위');
ok('반경 안에 지점이 없어도 행은 남는다 — 빼면 "원래 없는 항목"으로 읽힌다', noStation.value === '값 없음', JSON.stringify(noStation));
ok('소스가 없으면 미수신', row(R.buildCategories(REAL.filter((x) => x.source !== 'tide-forecast'), NOW).nav, '조위').age === '미수신');
// 조류예보는 행으로 내지 않는다 — 항해 탭 유속은 ROMS 가 답한다 (결정 2026-09-16)
ok('조류예보 행은 만들지 않는다', !row(cats.nav, '조류 예보') && !row(cats.nav, '유속 예보'));

console.log('\n본선 위치 격자 (/current)');
const cCur = R.buildCategories(REAL, NOW, CUR);
const curRow = row(cCur.nav, '표층 유속 예측');
ok('본선 기준 격자가 해역 대표값보다 우선', curRow.value === '0.31' && /본선 기준 격자 1\.4km/.test(curRow.age), curRow.age);
const unc = row(cCur.nav, '유속 불확실성');
ok('불확실성 행 — 30분 표류 반경으로 환산', unc.value === '±0.34' && /이웃 7칸/.test(unc.age) && /±612m/.test(unc.age), JSON.stringify(unc));
ok('예측 시각 이전이면 stale 아님', curRow.stale === false);
const cLate = R.buildCategories(REAL, new Date('2026-09-13T10:00:00Z'), CUR);
ok('예측 시각이 지나면 stale (폴링 멈춤)', row(cLate.nav, '표층 유속 예측').stale === true);
ok('이웃 없으면 불확실성 행 없음', !row(R.buildCategories(REAL, NOW, { ...CUR, neighborSpreadMs: null, neighborCount: 1 }).nav, '유속 불확실성'));
ok('statusLine 도 본선 격자 유속', /유속 0\.31m\/s/.test(R.statusLine(REAL, CUR)));
ok('current 없으면 대표값으로 물러섬', row(R.buildCategories(REAL, NOW, null).nav, '표층 유속 예측').value === '0.31');


console.log('\n수온 — 조업 탭과 익수 경보가 같은 값을 써야 한다');
const byName = (list) => Object.fromEntries(list.map((x) => [x.source, x]));
const w = R.waterTemp(byName(REAL), null);
ok('수과원 관측이 1순위', w.c === 25.8 && /기장 26\.1km · 수과원/.test(w.where), JSON.stringify(w.where));
ok('관측은 forecast 아님', w.forecast === false);

// 수과원이 없으면 기상청 부이
const noFg = REAL.filter((x) => x.source !== 'fishing-ground');
const w2 = R.waterTemp(byName(noFg), null);
ok('수과원 없으면 기상청', w2.c === 25.4 && /기상청/.test(w2.where), JSON.stringify(w2.where));

// 관측이 모두 없으면 예측으로 물러선다
const onlyRoms = REAL.filter((x) => x.source === 'roms');
const w3 = R.waterTemp(byName(onlyRoms), CUR);
ok('관측 없으면 ROMS 예측', w3.c === 25.86 && w3.forecast === true, JSON.stringify(w3));

ok('아무것도 없으면 null', R.waterTemp({}, null) === null);
// 익수 경보에서 지어낸 수온으로 생존 시간을 말하면 안 된다
ok('수온 없는 조업 표에도 저체온 행이 없다', row(R.buildCategories([], NOW).fish, '저체온 한계') === undefined);

console.log('\nstale 판정');
const old = src('sea-obs', 'OBSERVATION', '2026-09-13T06:00:00Z', 1800, REAL[1].payload);   // 3시간 전 = 6주기
const cOld = R.buildCategories([old], NOW);
ok('주기 3배 초과 → stale', row(cOld.safe, '유의파고').stale === true);
const failed = { ...REAL[1], resultCode: '22' };
const cFail = R.buildCategories([failed], NOW);
ok('갱신 실패는 값 유지 + 문구', row(cFail.safe, '유의파고').value === '0.4' && /갱신 실패/.test(row(cFail.safe, '유의파고').age));

console.log('\n빈 입력');
const empty = R.buildCategories([], NOW);
ok('소스 없으면 행은 남고 "값 없음"', row(empty.safe, '유의파고').value === '값 없음' && row(empty.safe, '유의파고').age === '미수신');
ok('빈 응답의 조업 표에도 저체온 행이 없다', row(empty.fish, '저체온 한계') === undefined);
ok('metric 은 유지 — 지도 버튼 자리가 안 사라진다', row(empty.safe, '유의파고').metric === 'wave');
ok('예비특보·운항지수 행도 남는다', row(empty.safe, '예비특보').value === '값 없음' && row(empty.nav, '운항지수').value === '값 없음');
ok('조위 행도 남는다', row(empty.nav, '조위').value === '값 없음' && row(empty.nav, '조위').age === '미수신');

console.log('\nstatusLine');
ok('현황 한 줄', R.statusLine(REAL) === '발효 중 해상특보 없음 · 파고 0.4m · 수온 25.8°C · 유속 0.31m/s', R.statusLine(REAL));
ok('빈 입력 문구', /없습니다/.test(R.statusLine([])));

console.log('\ncompass16');
ok('0 → 북', R.compass16(0) === '북');
ok('285.73 → 서북서', R.compass16(285.73) === '서북서');
ok('360 → 북', R.compass16(360) === '북');
ok('-10 → 북 (350° 는 337.5 보다 360 에 가깝다)', R.compass16(-10) === '북');
ok('340 → 북북서', R.compass16(340) === '북북서');

console.log('\nkiosk 해역 이동 키');
const O = await server.ssrLoadModule('/src/cloud/ocean.ts');
ok('키가 있으면 헤더를 싣는다', O.kioskHeaders('k-1')['X-Floaq-Kiosk-Key'] === 'k-1');
ok('키가 없으면 헤더도 없다 — 빈 헤더로 preflight 만 부르지 않는다', Object.keys(O.kioskHeaders('')).length === 0);
ok('OUTSIDE_AREA 는 이동 중 — 10초 뒤 다시 묻는다', O.outsideKind('OUTSIDE_AREA') === 'moving');
ok('OUTSIDE_AREA_NOT_MOVED 는 옮기지 않음 — 기다려도 안 들어온다', O.outsideKind('OUTSIDE_AREA_NOT_MOVED') === 'notMoved');
ok('정상 응답은 해역 밖이 아니다', O.outsideKind('OK') === null && O.outsideKind(undefined) === null);
ok('옮기지 않음 오류는 타입으로 가른다', new O.AreaNotMovedError() instanceof O.AreaNotMovedError);

await server.close();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

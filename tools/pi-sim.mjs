#!/usr/bin/env node
/**
 * 가짜 Pi — 키오스크·Pi 없이 사고 한 건을 처음부터 끝까지 흘려본다.
 *
 *   node tools/pi-sim.mjs                        인명 추락: 감지 → 30초 대기 → 신고 → 3분 떠다님 → 구조 완료
 *   node tools/pi-sim.mjs --type FIRE            화재 (선원이 직접 신고 — 대기 없이 바로 신고)
 *   node tools/pi-sim.mjs --lost 90              신고 30초 뒤부터 부표가 90초 동안 끊김
 *                                                (관제는 60초 넘게 못 받아야 두절로 본다 — 30초로는 안 뜬다)
 *   node tools/pi-sim.mjs --no-close             끝내지 않는다 — 관제에서 종결을 눌러 본다
 *   node tools/pi-sim.mjs --cancel               대기 중에 선원이 취소 (오탐)
 *   node tools/pi-sim.mjs --ship 동해수산호       다른 배로
 *   node tools/pi-sim.mjs --speed 30             움직임 30배 — 지도에서 눈으로 보려면 (실제 속도는 너무 느리다)
 *   node tools/pi-sim.mjs --help                 전부 보기
 *
 * ── 목데이터가 아니다 ─────────────────────────────────────────────────
 * 진짜 Pi 가 보내는 것과 <b>똑같은 요청</b>을 <b>똑같은 주소</b>(/api/pi/*)로 보낸다. 서버는 받아서
 * DB 에 넣고, 관제 화면은 평소처럼 API 로 읽는다. 화면 코드에는 이 스크립트를 위한 것이 하나도 없다 —
 * 그래서 여기서 되면 진짜 배로도 되고, 여기서 안 되면 진짜로도 안 된다.
 *
 * ── 준비 ──────────────────────────────────────────────────────────────
 * 백엔드를 <b>local 프로필</b>로 켠다. 켤 때 시연 시더(db/demo/refresh_demo.sql)가 시연 배마다
 * 개발용 열쇠를 넣는다 — 열쇠 = 'floaq-dev-' + ship_id. 이 스크립트가 같은 규칙으로 만든다.
 * 운영 서버에는 이 열쇠가 없으니 여기서 floaq.example.com 로 보내도 401 로 막힌다.
 *
 * ── 끝낼 때 ───────────────────────────────────────────────────────────
 * Ctrl+C 를 누르면 <b>사고를 종결하고</b> 나간다. 진행 중인 채로 두면 그 배는 다음 사고를 못 받는다
 * (배 한 척에 진행 중 사고는 하나뿐이다).
 */

import { randomUUID } from 'node:crypto';

// ── 시연 배 (db/demo/refresh_demo.sql 이 까는 것과 같다) ──────────────────
// 성진호·대원호·삼양호·금호호는 시연 사고가 진행 중이라 비어 있지 않다. 기본은 비어 있는 태성호다.
const SHIPS = {
  제7금양호: '00000000-0000-7000-8000-000000000001',
  동해수산호: '00000000-0000-7000-8000-000000000002',
  성진호: '00000000-0000-7000-8000-000000000003',
  대원호: '00000000-0000-7000-8000-000000000004',
  삼양호: '00000000-0000-7000-8000-000000000005',
  금호호: '00000000-0000-7000-8000-000000000006',
  태성호: '00000000-0000-7000-8000-000000000007',
};

// 사고 종류 → 화면 이름 · 조난 코드(DSC nature). 서버·웹과 같은 표다(web lib/api/accidents.ts TYPE_LABEL)
const TYPES = {
  MOB: ['인명 추락', 110],
  FIRE: ['선박 화재', 100],
  FLOODING: ['침수', 101],
  COLLISION: ['충돌', 102],
  GROUNDING: ['좌초', 103],
  ENGINE_FAILURE: ['기관 고장', 106],
  OTHER_DISTRESS: ['기타 조난', null],
  MEDICAL: ['응급 환자', null],
};

// ── 인자 ────────────────────────────────────────────────────────────────
const HELP = `
가짜 Pi — 로컬 백엔드에 사고 한 건을 흘려 보냅니다.

  --type <종류>        MOB(기본) FIRE FLOODING COLLISION GROUNDING ENGINE_FAILURE OTHER_DISTRESS MEDICAL
  --ship <배 이름>     ${Object.keys(SHIPS).join(' · ')}  (기본 태성호)
  --wait <초>          감지 뒤 신고까지 대기 (기본 30, 인명 추락만)
  --close-after <초>   신고 뒤 몇 초 만에 끝낼지 (기본 180)
  --no-close           끝내지 않고 계속 — 관제에서 종결을 눌러 보세요. Ctrl+C 로 나가면 종결됩니다
  --cancel             대기 중에 선원이 취소 (인명 추락만)
  --hold-at <초>       신고 뒤 몇 초에 사람이 부표를 잡는지 (기본 90, 인명 추락만. 0 이면 안 잡음)
  --lost <초>          신고 30초 뒤부터 부표가 이만큼 끊김 (인명 추락만)
                       ⚠ 관제는 60초 넘게 못 받아야 '두절'로 봅니다. 두절·재개를 보려면 --lost 90
  --at <위도,경도>     사고 지점 (기본 35.100,129.130 — 부산 앞바다)
  --url <주소>         백엔드 주소 (기본 http://localhost:8080)
  --every <초>         터미널에 위치를 몇 초마다 찍을지 (기본 5. 보내기는 늘 1초마다)
  --speed <배>         움직임을 몇 배로 (기본 1 = 실제 속도). 실제 속도는 지도에서 거의 안 보입니다 —
                       부표가 초당 0.25m 라 10초에 한 픽셀도 안 움직입니다. 눈으로 볼 땐 --speed 30
`;

const argv = process.argv.slice(2);
const flag = (k) => argv.includes(k);
const opt = (k, d) => {
  const i = argv.indexOf(k);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : d;
};

if (flag('--help') || flag('-h')) {
  console.log(HELP);
  process.exit(0);
}

const TYPE = String(opt('--type', 'MOB')).toUpperCase();
const SHIP_NAME = opt('--ship', '태성호');
const URL_BASE = String(opt('--url', 'http://localhost:8080')).replace(/\/$/, '');
const WAIT = Number(opt('--wait', 30));
const CLOSE_AFTER = Number(opt('--close-after', 180));
const NO_CLOSE = flag('--no-close');
const CANCEL = flag('--cancel');
const HOLD_AT = Number(opt('--hold-at', 90));
const LOST = Number(opt('--lost', 0));
const EVERY = Math.max(1, Number(opt('--every', 5)));
/** 움직임 배율. 시각은 그대로 흐르고 <b>거리만</b> 늘린다 — 신고·종결 시각이 실제와 어긋나면 안 된다 */
const SPEED = Math.max(0.1, Number(opt('--speed', 1)));
const [LAT0, LON0] = String(opt('--at', '35.100,129.130')).split(',').map(Number);

const fail = (msg) => { console.error(`\n✗ ${msg}\n`); process.exit(1); };

if (!TYPES[TYPE]) fail(`모르는 종류입니다: ${TYPE}\n  가능: ${Object.keys(TYPES).join(' ')}`);
if (!SHIPS[SHIP_NAME]) fail(`시연 배가 아닙니다: ${SHIP_NAME}\n  가능: ${Object.keys(SHIPS).join(' · ')}`);
if (![LAT0, LON0].every(Number.isFinite)) fail('--at 은 위도,경도 입니다. 예: --at 35.1,129.13');

const MOB = TYPE === 'MOB';
if (LOST > 0 && LOST <= 60) {
  console.log(`
  ⚠ --lost ${LOST} 는 60초 이하라 관제에 '두절'이 안 뜹니다 (관제는 60초 넘게 못 받아야 두절로 봅니다).`);
  console.log('    두절·재개를 보려면 --lost 90 처럼 60초보다 길게 주세요.');
}
if (CANCEL && !MOB) fail('--cancel 은 인명 추락에만 있습니다. 다른 사고는 선원이 직접 신고해 대기가 없습니다.');

const SHIP = SHIPS[SHIP_NAME];
// 시연 시더가 넣는 개발용 열쇠 (refresh_demo.sql ⑥)
const KEY = `floaq-dev-${SHIP}`;
const ACC = randomUUID();

// ── 보내기 ───────────────────────────────────────────────────────────────
const now = () => Math.floor(Date.now() / 1000);
const clock = (sec = now()) => new Date(sec * 1000).toTimeString().slice(0, 8);
const T0 = now();
const elapsed = () => {
  const s = now() - T0;
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};
const say = (msg) => console.log(`[${elapsed()}] ${msg}`);

/** 진짜 Pi 와 같은 봉투(api.md §4.1). 한 요청에 여러 줄을 담을 수 있지만 여기서는 한 줄씩 보낸다 */
async function send(path, rows) {
  let res;
  try {
    res = await fetch(`${URL_BASE}/api/pi/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Ship-Secret-Key': KEY },
      body: JSON.stringify({ request_id: randomUUID(), v: 1, ts: now(), data: rows }),
    });
  } catch {
    fail(`백엔드에 닿지 않습니다 — ${URL_BASE}\n  백엔드가 켜져 있나요?`);
  }
  if (res.ok) return true;

  const body = await res.json().catch(() => ({}));
  const code = body?.code ?? '';
  if (res.status === 401 || code.startsWith('PI_KEY')) {
    fail(`열쇠가 맞지 않습니다 (${res.status} ${code}).\n`
      + '  백엔드를 local 프로필로 켰나요? 켤 때 시연 시더가 개발용 열쇠를 넣습니다.\n'
      + '  (운영 서버로는 보낼 수 없습니다 — 거기엔 이 열쇠가 없습니다)');
  }
  if (code === 'ACCIDENT_ALREADY_ACTIVE') {
    fail(`${SHIP_NAME}에 이미 진행 중인 사고가 있습니다.\n`
      + `  --ship 으로 다른 배를 고르거나, 관제에서 그 사고를 먼저 종결하세요.`);
  }
  console.error(`  ! ${path} ${res.status} ${code} ${body?.message ?? ''}`);
  return false;
}

/** 사고 행. 서버가 id 로 덮어쓰므로 바뀔 때마다 전부 보낸다 — 진짜 Pi 도 그렇게 한다 */
const accident = (status, extra = {}) => send('accidents', [{
  accident_id: ACC,
  ship_id: SHIP,
  accident_type: TYPE,
  trigger_source: MOB ? 'AI' : 'MANUAL',
  report_type: 'DISTRESS',
  report_dsc: TYPES[TYPE][1],
  status,
  accident_lat: LAT0,
  accident_lon: LON0,
  created_at: T0,
  ...extra,
}]);

const state = (status, prev, reason, at = now()) => send('accident-states', [{
  accident_id: ACC, status, prev_status: prev, reason, caused_by: 'pi-sim', created_at: at,
}]);

// ── 움직임 ───────────────────────────────────────────────────────────────
// 미터 → 도. 위도 1도 ≈ 110,574m, 경도 1도 ≈ 111,320m × cos(위도)
const M_LAT = 1 / 110574;
const M_LON = 1 / (111320 * Math.cos((LAT0 * Math.PI) / 180));

/**
 * 배는 사고 지점 주변을 천천히 돈다 — 사람이 빠진 곳을 떠나지 않는다(시연 시더와 같은 모양).
 * 반경 150m, 한 바퀴 10분. 뱃머리는 도는 방향을 본다.
 */
function shipAt(t0) {
  const t = t0 * SPEED;
  const a = (t / 600) * 2 * Math.PI;
  const r = 150;
  return {
    lat: LAT0 + Math.sin(a) * r * M_LAT,
    lon: LON0 + 0.0015 + Math.cos(a) * r * M_LON,
    heading: ((90 - (a * 180) / Math.PI) % 360 + 360) % 360,
    speed: ((2 * Math.PI * r) / 600 / 0.514444) * SPEED, // m/s → kn
  };
}

/**
 * 부표는 북동쪽으로 초당 0.25m 쯤 떠내려가고, 멀리 갈수록 조금씩 북쪽으로 휜다.
 *
 * <p>⚠ 전에는 좌우로 ±6m 를 sin 으로 흔들었다. 그런데 {@code --speed} 가 흔드는 빠르기까지
 * 곱해져 30배면 3.6초마다 왔다 갔다 했고, 1초마다 찍은 점을 이으니 지도에 <b>톱니 선</b>이
 * 그려졌다(2026-09-21). 진짜 부표는 그렇게 규칙적으로 흔들리지 않는다 — 떠내려가는 길만 흉내 낸다.
 * 실제 GPS 흔들림은 진짜 Pi 데이터로 보면 된다.</p>
 */
function buoyAt(t0) {
  const d = t0 * SPEED * 0.25;     // 떠내려간 거리(m)
  const bend = (d * d) / 20000;    // 1km 가면 50m 쯤 북쪽으로 휜다
  return {
    lat: LAT0 + (d * 0.7071 + bend) * M_LAT,
    lon: LON0 + (d * 0.7071 - bend) * M_LON,
  };
}

// ── 흐름 ─────────────────────────────────────────────────────────────────
let closed = false;
let reportedAt = null;
let seq = 0;

async function close(reason) {
  if (closed) return;
  closed = true;
  const at = now();
  // 구조 완료는 발견과 종결을 한 번에 한다 — 키오스크의 "구조 완료"와 같다(Pi orchestrator)
  const rescued = reason === 'TABLET_RESCUE';
  await accident('CLOSE', { rescued_at: rescued ? at : undefined, closed_at: at });
  await state('CLOSE', 'REPORT', reason, at);
  say(`${rescued ? '구조 완료' : '종료'} — 사고를 끝냈습니다 (${clock(at)})`);
}

async function main() {
  console.log(`\n가짜 Pi → ${URL_BASE}`);
  console.log(`  배 ${SHIP_NAME} · ${TYPES[TYPE][0]} · 사고 ${ACC}`);
  console.log(`  ${NO_CLOSE ? '끝내지 않음 (Ctrl+C 로 종결하고 나감)' : `신고 뒤 ${CLOSE_AFTER}초에 끝냄`}\n`);

  if (MOB) {
    // 카메라가 사람을 잡는다 → 부표 발사 → 30초 동안 선원이 되돌릴 수 있다 → 신고
    await accident('DETECT');
    await state('DETECT', null, 'AI_DETECT', T0);
    say('감지 — 카메라가 사람을 잡았습니다');

    await accident('WAIT', { report_due_at: T0 + WAIT });
    await state('WAIT', 'DETECT', 'COUNTDOWN_START', T0 + 1);
    await send('launches', [{
      accident_id: ACC, result: 'SUCCESS', launch_lat: LAT0, launch_lon: LON0,
      target_lat: LAT0, target_lon: LON0, horizontal_angle: 42, vertical_angle: 18,
      confidence_score: 0.91, created_at: T0 + 2,
    }]);
    say(`부표 발사 · ${WAIT}초 뒤 신고 (해경 화면에는 신고 뒤에 뜹니다)`);
  } else {
    // 화재·충돌 같은 사고는 선원이 버튼으로 직접 신고한다 — 대기 없이 바로 신고
    await accident('REPORT');
    await state('REPORT', null, 'TABLET_MANUAL', T0);
    reportedAt = T0;
    say(`선원 신고 — ${TYPES[TYPE][0]} (바로 신고됩니다)`);
  }

  const tick = setInterval(async () => {
    if (closed) return;
    const t = now() - T0;

    // 대기가 끝나면 신고
    if (MOB && reportedAt === null) {
      if (CANCEL && t >= Math.min(10, WAIT - 1)) {
        closed = true;
        // 취소에는 종료 시각을 싣지 않는다 — 서버가 '종료 시각은 종결일 때만'이라며 통째로 거절한다.
        // 진짜 Pi 도 안 싣는다(orchestrator cancel). 종료 시각은 경위 줄로 서버가 채운다
        await accident('CANCEL');
        await state('CANCEL', 'WAIT', 'TABLET_CANCEL');
        say('선원이 취소했습니다 (오탐) — 해경 화면에는 안 뜹니다');
        clearInterval(tick);
        return;
      }
      if (t >= WAIT) {
        reportedAt = now();
        await accident('REPORT', { report_due_at: T0 + WAIT });
        await state('REPORT', 'WAIT', 'TIMEOUT', reportedAt);
        await send('reports', [{
          accident_id: ACC, channel: 'DSC', trigger_kind: 'AUTO', status: 'SENDING', sent_count: 1,
          report_lat: LAT0, report_lon: LON0, first_sent_at: reportedAt, last_sent_at: reportedAt,
          created_at: reportedAt,
        }]);
        say('신고 발신 — 관제에 경광등이 떠야 합니다');
      }
    }

    // 배 위치 — 늘 보낸다
    const s = shipAt(t);
    await send('ship-positions', [{
      ship_id: SHIP, lat: s.lat, lon: s.lon, speed_kn: Number(s.speed.toFixed(1)),
      heading_deg: Number(s.heading.toFixed(1)), accuracy_m: 4, created_at: now(),
    }]);

    // 부표 — 인명 추락만. 발사 뒤부터, 끊긴 동안은 안 보낸다
    let b = null;
    const since = reportedAt === null ? -1 : now() - reportedAt;
    const lostNow = LOST > 0 && since >= 30 && since < 30 + LOST;
    if (MOB && t >= 3 && !lostNow) {
      b = buoyAt(t);
      const held = HOLD_AT > 0 && since >= HOLD_AT;
      await send('buoys', [{
        accident_id: ACC, seq: ++seq, lat: b.lat, lon: b.lon, is_pressed: held,
        rssi: -70 - (t % 7), created_at: now(), received_at: now(),
      }]);
      if (held && since === HOLD_AT) say('사람이 부표를 잡았습니다');
    }
    if (MOB && LOST > 0 && since === 30) say(`부표 끊김 — ${LOST}초 동안 안 보냅니다`);
    if (MOB && LOST > 0 && since === 30 + LOST) say('부표 다시 잡힘');

    if (t % EVERY === 0) {
      say(`배 ${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}`
        + (b ? ` · 부표 ${b.lat.toFixed(5)}, ${b.lon.toFixed(5)}` : lostNow ? ' · 부표 (끊김)' : ''));
    }

    // 끝낼 때
    if (!NO_CLOSE && reportedAt !== null && now() - reportedAt >= CLOSE_AFTER) {
      clearInterval(tick);
      await close(MOB ? 'TABLET_RESCUE' : 'TABLET_CLOSE');
      console.log('');
      process.exit(0);
    }
  }, 1000);

  // Ctrl+C — 진행 중으로 두면 그 배가 다음 사고를 못 받는다. 끝내고 나간다
  process.on('SIGINT', async () => {
    clearInterval(tick);
    if (!closed && reportedAt !== null) {
      console.log('');
      await close('TABLET_CLOSE');
    } else if (!closed) {
      // 신고 전이면 취소로 끝낸다 — 해경 화면에 뜬 적이 없는 사고다
      closed = true;
      // 취소에는 종료 시각을 싣지 않는다 — 위와 같은 이유다
      await accident('CANCEL');
      await state('CANCEL', MOB ? 'WAIT' : 'DETECT', 'TABLET_CANCEL');
      say('신고 전에 멈췄습니다 — 취소로 끝냈습니다');
    }
    console.log('');
    process.exit(0);
  });
}

main();

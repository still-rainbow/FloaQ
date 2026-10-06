// vite 의 모듈 그래프로 실제 소스를 로드한다.
// node --experimental-strip-types 로는 barrel 의 JSX(MapView.tsx)에 걸린다.
//
// 페이로드 정본: IoT `iot/pi/floaq/contracts/*.py` (2026-09-15 수령) · 웹 안내 `ref/mqtt-연동-웹.md`.
// 두 문서가 다른 곳(accident/state 필드)은 둘 다 받는지 확인한다.
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

// Windows 에서 URL.pathname 은 `/C:/...` 라 앞에 슬래시가 붙는다. fileURLToPath 가 그걸 벗긴다
const here = (p) => fileURLToPath(new URL(p, import.meta.url));

const server = await createServer({
  root: here('..'),
  configFile: here('../vite.config.ts'),
  server: { middlewareMode: true, hmr: false },
  // 의존성 사전 번들 스캐너를 끈다. SSR 로 소스만 불러올 거라 필요 없고,
  // 켜 두면 server.close() 와 경합해 무관한 에러를 뱉는다
  optimizeDeps: { noDiscovery: true, include: [] },
  logLevel: 'silent',
});

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name} ${extra}`); }
};

const env = (data, ts = 1757000000, id = 'req-1') =>
  JSON.stringify({ request_id: id, v: 1, ts, data: [data] });

// ── envelope ────────────────────────────────────────────────
const E = await server.ssrLoadModule('/../../packages/shared/src/mqtt/envelope.ts');

console.log('\nenvelope');
const id = E.newRequestId();
ok('UUID 형식', /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id), id);
const t0 = Date.now();
const ms = parseInt(E.newRequestId().replace(/-/g, '').slice(0, 12), 16);
ok('v7 앞 48비트가 현재 ms', Math.abs(ms - t0) < 5000, `${ms} vs ${t0}`);
ok('두 번 부르면 다르다', E.newRequestId() !== E.newRequestId());

const seen = E.makeDedupe(3);
ok('처음은 통과', seen('a') === true);
ok('두 번째는 막힌다', seen('a') === false);
seen('b'); seen('c'); seen('d');           // a 가 링에서 밀려난다
ok('링 크기를 넘으면 잊는다', seen('a') === true);

ok('깨진 JSON 은 null', E.parseEnvelope('{nope') === null);
ok('data 없으면 null', E.parseEnvelope('{"request_id":"x"}') === null);
ok('정상 파싱', E.parseEnvelope(env({ a: 1 }))?.data[0].a === 1);

// ── topics ──────────────────────────────────────────────────
const TP = await server.ssrLoadModule('/src/pi/topics.ts');
// ship_id 는 런타임 값이다 (2026-09-17) — 등록이 발급한다. 테스트는 고정 값으로 한 벌 만든다
const SHIP = 'ship-test';
const T = TP.topicsFor(SHIP);

console.log('\ntopics');
const willBody = JSON.parse(TP.kioskWillFor(SHIP).payload);
ok('kiosk LWT 는 봉투 없이 {online:false, ts:0}', willBody.online === false && willBody.ts === 0 && !('data' in willBody));
const onBody = JSON.parse(TP.onlinePayload(true, 1789456675));
ok('online 페이로드도 봉투 없음', onBody.online === true && onBody.ts === 1789456675 && !('request_id' in onBody));
ok('GPS 는 Pi 가 발행 — pi/sensor/gps 구독', T.sensorGps.endsWith('/pi/sensor/gps'));
ok('키오스크 GPS 발행 토픽은 없다', !('kioskGps' in T));

// ── decode ──────────────────────────────────────────────────
const D = await server.ssrLoadModule('/src/pi/decode.ts');

console.log('\ndecode — 장비 · 시계');
let r = D.decode(T, T.deviceStatus, env({
  camera_l: 'OK', camera_r: 'OK', camera_dirty: false,
  imu: 'OK', lora: 'OK', ai: 'OK', gps: 'OK', internet: true,
}), false);
ok('device → DEVICE_HEALTH', r.msg?.type === 'DEVICE_HEALTH');
ok('전부 OK', r.msg?.camera === 'OK' && r.msg?.buoy === 'OK');
ok('인터넷 여부를 싣는다', r.msg?.internet === true);
ok('ts 로 시계 오프셋 산출', r.serverTsMs === 1757000000000);

r = D.decode(T, T.deviceStatus, env({
  camera_l: 'OK', camera_r: 'OK', camera_dirty: true,
  imu: 'UNKNOWN', lora: 'ERROR', ai: 'OK',
}), false);
ok('이물질은 WARN (ERROR 아님)', r.msg?.camera === 'WARN', r.msg?.camera);
ok('UNKNOWN 을 OK 로 읽지 않는다', r.msg?.imu === 'WARN', r.msg?.imu);
ok('LoRa ERROR → 부표 LOST', r.msg?.buoy === 'LOST', r.msg?.buoy);

r = D.decode(T, T.deviceStatus, env({ camera_l: 'OK' }, 1757000000), true);
ok('retained 는 시계 보정에 안 쓴다', r.serverTsMs === null);

ok('모르는 v 는 버린다', D.decode(T, T.deviceStatus, JSON.stringify({ request_id: 'x', v: 2, ts: 1, data: [{}] }), false).msg === null);

console.log('\ndecode — */online (봉투 없음)');
r = D.decode(T, T.piOnline, '{"online": true, "ts": 1789456632}', true);
ok('pi/online → PI_ONLINE true', r.msg?.type === 'PI_ONLINE' && r.msg?.online === true);
r = D.decode(T, T.piOnline, '{"online": false, "ts": 0}', true);
ok('LWT(ts 0) → PI_ONLINE false', r.msg?.online === false);
r = D.decode(T, T.piOnline, env({ online: true }), false);
ok('봉투로 온 online 은 모양이 틀려 무시', r.msg === null);
ok('자기 kiosk/online 은 화면에 안 올린다', D.decode(T, T.kioskOnline, '{"online":true,"ts":1}', true).msg === null);

console.log('\ndecode — 사고 상태 (IoT 코드 형식: 좌표·유형 없음)');
D.resetFix();
r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-1', status: 'DETECT', prev_status: null, reason: 'AI_DETECT',
  caused_by: null, report_due_at: null, changed_at: 1757000000,
}), false);
ok('최초 생성 → INCIDENT_DETECTED', r.msg?.type === 'INCIDENT_DETECTED');
ok('AI 감지는 DISTRESS·MOB', r.msg?.incident.urgency === 'DISTRESS' && r.msg?.incident.alertType === 'MOB');
ok('좌표 없으면 0 (⚠ 래치 전)', r.msg?.incident.lat === 0);

D.decode(T, T.jetsonDetection, env({ lat: 35.05, lon: 129.11 }), false);
r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-1', status: 'WAIT', prev_status: 'DETECT', reason: 'COUNTDOWN_START',
  caused_by: null, report_due_at: 1757000030, changed_at: 1757000001,
}), true);
ok('🔴 retained WAIT(prev=DETECT) 도 사고 전체로 — 새로고침 복구', r.msg?.type === 'INCIDENT_DETECTED' && r.msg?.incident.status === 'PENDING');
ok('detection 좌표가 래치된다', r.msg?.incident.lat === 35.05, r.msg?.incident.lat);
ok('report_due_at → deadline', r.msg?.incident.deadline === new Date(1757000030000).toISOString());

r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-1', status: 'REPORT', prev_status: 'WAIT', reason: 'TIMEOUT',
  caused_by: null, report_due_at: null, changed_at: 1757000030,
}), false);
ok('진행 중 전이도 사고 전체', r.msg?.type === 'INCIDENT_DETECTED' && r.msg?.incident.status === 'REPORTED');
ok('WAIT 를 벗어나면 deadline 없음', r.msg?.incident.deadline === undefined);

r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-1', status: 'CLOSE', prev_status: 'REPORT', reason: 'TABLET_CLOSE',
  caused_by: 'x', report_due_at: null, changed_at: 1757000100,
}), true);
ok('끝난 사고는 전이만 — retained CLOSE 로 사고를 새로 세우지 않는다', r.msg?.type === 'INCIDENT_STATE' && r.msg?.status === 'RESOLVED');

console.log('\ndecode — 사고 상태 (웹 안내 문서 형식: 좌표·유형 있음)');
D.resetFix();
r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-2', status: 'REPORT', prev_status: null, reason: 'TABLET_MANUAL',
  accident_type: 'ENGINE_FAILURE', report_type: 'DISTRESS', lat: 35.1, lon: 129.2,
  wait_sec: 30, report_due_at: null, created_at: 1757000500,
}), false);
ok('accident_type → 앱 유형 (ENGINE_FAILURE → DISABLED)', r.msg?.incident.alertType === 'DISABLED', r.msg?.incident.alertType);
ok('페이로드 좌표를 쓴다', r.msg?.incident.lat === 35.1 && r.msg?.incident.lon === 129.2);
ok('created_at → 감지 시각', r.msg?.incident.detectedAt === new Date(1757000500000).toISOString());

D.rememberManual('acc-3', 'MEDICAL', 'URGENCY');
r = D.decode(T, T.accidentState, env({
  accident_id: 'acc-3', status: 'REPORT', prev_status: null, reason: 'TABLET_MANUAL',
  caused_by: 'x', report_due_at: null, changed_at: 1757000600,
}), false);
ok('유형 없는 형식이면 이 단말이 연 수동 신고의 유형을 쓴다', r.msg?.incident.alertType === 'MEDICAL' && r.msg?.incident.urgency === 'URGENCY');

console.log('\ndecode — retained 삭제 (0바이트)');
r = D.decode(T, T.accidentState, '', true);
ok('사고 retained 삭제 → INCIDENT_CLEARED', r.msg?.type === 'INCIDENT_CLEARED');
r = D.decode(T, T.buoyDrift, '', true);
ok('표류 retained 삭제 → BUOY_DRIFT_CLEARED', r.msg?.type === 'BUOY_DRIFT_CLEARED');

console.log('');
console.log('신고 상태 (pi/report/status)');
r = D.decode(T, T.reportStatus, env({
  accident_id: 'acc-1', report_id: 7, channel: 'DSC', status: 'ACKED',
  sent_count: 3, first_sent_at: 1789456600, last_sent_at: 1789456660,
  acked_at: 1789456665, acked_by: '440123456', fail_reason: null,
}), true);
ok('채널·상태를 읽는다', r.msg?.report.channel === 'DSC' && r.msg?.report.status === 'ACKED');
ok('누적 횟수', r.msg?.report.sentCount === 3);
ok('ACK 을 보낸 국의 MMSI', r.msg?.report.ackedBy === '440123456');
ok('보낸 적 없으면 null (0 으로 채우지 않는다)',
  D.decode(T, T.reportStatus, env({ channel: 'AIS_MOB', status: 'SENDING', acked_at: null }), true)
    .msg?.report.ackedAt === null);
// 🔴 인터넷 두절은 반드시 드러나야 한다 — 안 그러면 사용자는 신고가 나간 줄 안다 (mqtt.md §5.11)
r = D.decode(T, T.reportStatus, env({
  channel: 'AIS_SART', status: 'FAILED', fail_reason: 'NO_INTERNET',
}), true);
ok('전송 실패 사유가 그대로 온다', r.msg?.report.failReason === 'NO_INTERNET');

console.log('');
console.log('감지 스틸컷 (jetson/snapshot)');
r = D.decode(T, T.jetsonSnapshot, env({
  accident_id: 'acc-1', format: 'jpeg', width: 1280, height: 720, bytes: 40000,
  data: 'QUJD', captured_at: 1789456590, confidence: 0.87,
  bbox: [100, 200, 60, 120], camera: 'L',
}), true);
ok('스틸컷을 읽는다', r.msg?.type === 'SNAPSHOT' && r.msg?.data === 'QUJD');
ok('bbox 네 값', Array.isArray(r.msg?.bbox) && r.msg.bbox.length === 4);
ok('확신도', r.msg?.confidence === 0.87);
ok('data 없으면 버린다', D.decode(T, T.jetsonSnapshot, env({ accident_id: 'a' }), true).msg === null);
// 🔴 bbox 가 네 숫자가 아니면 그리지 않는다 — 깨진 좌표로 박스를 그리면 엉뚱한 곳을 가리킨다
ok('bbox 가 망가지면 null',
  D.decode(T, T.jetsonSnapshot, env({ data: 'QQ', bbox: [1, 2] }), true).msg?.bbox === null);

console.log('');
console.log('AI 상태 (jetson/status)');
r = D.decode(T, T.jetsonStatus, env({
  model_version: 'yolo11n-0.3', inference_fps: 12.4,
  camera_l: 'OK', camera_r: 'ERROR', camera_dirty: true,
  gps_received: false, uptime_sec: 3600,
}), true);
ok('모델·FPS 를 읽는다', r.msg?.modelVersion === 'yolo11n-0.3' && r.msg?.inferenceFps === 12.4);
ok('카메라 좌우를 따로 본다', r.msg?.cameraL === 'OK' && r.msg?.cameraR === 'ERROR');
ok('이물질 감지', r.msg?.cameraDirty === true);
// 🔴 필드가 없으면 "GPS 안 옴"으로 본다. true 로 두면 좌표가 안 나오는 상태를 조용히 지나친다
ok('gps_received 가 없으면 false',
  D.decode(T, T.jetsonStatus, env({ model_version: 'x' }), true).msg?.gpsReceived === false);
ok('camera_dirty 도 없으면 false',
  D.decode(T, T.jetsonStatus, env({ model_version: 'x' }), true).msg?.cameraDirty === false);
ok('다른 토픽의 삭제는 무시', D.decode(T, T.launchResult, '', true).msg === null);

console.log('\ndecode — 부표 · 표류 · GPS · IMU');
r = D.decode(T, T.buoyPosition, env({
  accident_id: 'acc-1', buoy_log_id: 7, lat: 35.06, lon: 129.12, seq: 3, is_pressed: 0,
  measured_at: 1757000040, received_at: 1757000041, rssi: -80,
}), false);
ok('부표 → BUOY_POS', r.msg?.type === 'BUOY_POS' && r.msg?.buoy.lat === 35.06);
ok('지도에는 측정 시각을 쓴다', r.msg?.buoy.at === new Date(1757000040000).toISOString(), r.msg?.buoy.at);

r = D.decode(T, T.buoyDrift, env({
  accident_id: 'acc-1', estimate_id: 1, base_lat: 35.06, base_lon: 129.12, last_received_at: 1757000040,
  elapsed_sec: 120, center_lat: 35.061, center_lon: 129.123, radius_m: 182.4,
  input_current_speed: null, input_current_dir: null, input_wind_speed: null, input_wind_dir: null,
  input_observed_at: null, estimated_at: 1757000160,
}), true);
ok('표류 → BUOY_LOST (중심에 원)', r.msg?.type === 'BUOY_LOST' && r.msg?.buoy.lat === 35.061 && r.msg?.buoy.lost === true);
ok('반경은 m 반올림', r.msg?.buoy.estimatedRadiusM === 182);
ok('마지막 실제 수신 위치를 들고 간다', r.msg?.buoy.lastFix?.lat === 35.06);
ok('해양 입력 없음은 null — "해양 데이터 없이 추정"', r.msg?.buoy.driftInputAt === null);

r = D.decode(T, T.sensorGps, env({
  ship_id: 'ship-1', lat: 35.2, lon: 129.3, speed_kn: 6.5, heading_deg: 90, accuracy_m: null, measured_at: 1757000200,
}), true);
ok('GPS → VESSEL_FIX', r.msg?.type === 'VESSEL_FIX' && r.msg?.lat === 35.2 && r.msg?.speedKn === 6.5);

r = D.decode(T, T.sensorImu, env({ imu_position: 'HULL', roll: 3.2, pitch: -1.1, yaw: 10, heading_deg: 271, measured_at: 1 }), false);
ok('IMU → TELEMETRY', r.msg?.type === 'TELEMETRY' && r.msg?.rollDeg === 3.2);

// 모르는 토픽이 와도 죽지 않는다. mqtt.md §0.1 "알 수 없는 필드는 무시하고 진행"과 같은 태도다.
// (jetson/status 는 2026-09-17 부터 디코딩한다 — 그 전까지 이 자리가 그 토픽이었다)
r = D.decode(T, `ship/${SHIP}/pi/아직/없는/토픽`, env({ fps: 12 }), false);
ok('모르는 토픽은 msg 없이 통과', r.msg === null && r.requestId === 'req-1');

r = D.decode(T, T.accidentState, '{깨진', false);
ok('깨진 페이로드는 조용히 null', r.msg === null && r.requestId === null);

// ── reducer ─────────────────────────────────────────────────
const R = await server.ssrLoadModule('/src/state/reducer.ts');

console.log('\nreducer');
const msg = (m) => ({ kind: 'MESSAGE', msg: m });
const base = { vesselId: 'ship-1', at: '2026-09-15T00:00:00Z' };
const inc = (over) => ({ incidentId: 'acc-1', status: 'PENDING', lat: 35.05, lon: 129.11,
  detectedAt: '2026-09-15T00:00:00Z', deadline: '2026-09-15T00:00:30Z', urgency: 'DISTRESS', alertType: 'MOB', ...over });
let s = R.reducer(R.initialState, msg({ type: 'INCIDENT_DETECTED', ...base, incident: inc({}) }));
s = R.reducer(s, msg({ type: 'INCIDENT_DETECTED', ...base,
  incident: inc({ status: 'REPORTED', lat: 0, lon: 0, detectedAt: '2026-09-15T00:00:31Z', deadline: undefined }) }));
ok('같은 사고면 감지 시각은 처음 값', s.incident.detectedAt === '2026-09-15T00:00:00Z');
ok('좌표를 모르는 메시지가 알던 좌표를 지우지 않는다', s.incident.lat === 35.05);
ok('상태·deadline 은 새 메시지 기준', s.incident.status === 'REPORTED' && s.incident.deadline === undefined);

// 🔴 retained 는 끝난 사고의 것일 수 있다 (ref/mqtt.md §2.2).
//    안 버리면 **새 사고에 옛 사진이 붙고** 사람이 그걸 보고 취소를 판단한다
const shot = (id) => ({ type: 'SNAPSHOT', ...base, incidentId: id, data: 'QUJD',
  format: 'jpeg', width: 640, height: 480, confidence: 0.9, bbox: null, camera: 'L', capturedAt: null });
s = R.reducer(s, msg(shot('acc-1')));
ok('지금 사고의 스틸컷은 받는다', s.snapshot?.data === 'QUJD');
s = R.reducer(s, msg(shot('acc-OLD')));
ok('다른 사고의 스틸컷은 버린다', s.snapshot?.incidentId === 'acc-1');

// 채널별 신고 상태도 같은 규칙
const rep = (id, ch) => ({ type: 'REPORT_STATUS', ...base, incidentId: id,
  report: { channel: ch, status: 'SENDING', sentCount: 1, firstSentAt: null, lastSentAt: null,
    ackedAt: null, ackedBy: null, failReason: null } });
s = R.reducer(s, msg(rep('acc-1', 'DSC')));
s = R.reducer(s, msg(rep('acc-1', 'AIS_MOB')));
ok('채널마다 한 칸씩 모인다', Object.keys(s.reports).length === 2);
s = R.reducer(s, msg(rep('acc-OLD', 'AIS_SART')));
ok('다른 사고의 신고는 버린다', Object.keys(s.reports).length === 2);

s = R.reducer(s, msg({ type: 'INCIDENT_CLEARED', ...base }));
ok('사고가 끝나면 스틸컷·신고 기록도 걷는다',
  s.snapshot === null && Object.keys(s.reports).length === 0);
// AI 상태는 사고와 무관한 장비 값이다 — 사고가 끝나도 남아야 한다
s = R.reducer(s, msg({ type: 'JETSON_STATUS', ...base, modelVersion: 'v1', inferenceFps: 10,
  cameraL: 'OK', cameraR: 'OK', cameraDirty: false, gpsReceived: true, uptimeSec: 1 }));
ok('AI 상태를 들고 있다', s.jetson?.modelVersion === 'v1' && typeof s.jetsonAt === 'number');
s = R.reducer(s, msg({ type: 'INCIDENT_CLEARED', ...base }));
ok('사고가 끝나도 AI 상태는 남는다', s.jetson?.modelVersion === 'v1');
// 이어지는 검증이 사고를 전제하므로 되돌려 둔다
s = R.reducer(s, msg({ type: 'INCIDENT_DETECTED', ...base, incident: inc({ status: 'REPORTED' }) }));

s = R.reducer(s, msg({ type: 'BUOY_LOST', ...base, incidentId: 'acc-1',
  buoy: { buoyId: 'buoy', lat: 35.061, lon: 129.123, at: base.at, lost: true, estimatedRadiusM: 182, lastFix: { lat: 35.06, lon: 129.12 }, driftInputAt: null } }));
s = R.reducer(s, msg({ type: 'BUOY_DRIFT_CLEARED', ...base }));
ok('표류 삭제 → 원을 걷고 마지막 실제 위치로', s.buoy.lost === false && s.buoy.estimatedRadiusM === undefined && s.buoy.lat === 35.06);

s = R.reducer(s, msg({ type: 'VESSEL_FIX', ...base, lat: 35.2, lon: 129.3, speedKn: 6.5, headingDeg: 90, accuracyM: null, measuredAt: base.at }));
s = R.reducer(s, msg({ type: 'TELEMETRY', ...base, rollDeg: 3 }));
ok('IMU 가 GPS 속력을 지우지 않는다', s.telemetry.speedKn === 6.5 && s.telemetry.rollDeg === 3);
ok('GPS 위치를 기억', s.vesselFix?.lat === 35.2);

s = R.reducer(s, msg({ type: 'PI_ONLINE', ...base, online: false }));
ok('Pi 두절', s.piOnline === false);
s = R.reducer(s, { kind: 'DESYNC' });
ok('브로커가 끊기면 Pi 생존은 모름', s.piOnline === null);

s = R.reducer(s, msg({ type: 'INCIDENT_CLEARED', ...base }));
ok('사고 retained 삭제 → 사고·부표를 걷는다', s.incident === null && s.buoy === null);

// ── commands ────────────────────────────────────────────────
const C = await server.ssrLoadModule('/src/pi/commands.ts');

console.log('\ncommands');
const sent = [];
let connected = true;
// 토픽 한 벌을 게터로 받는다 (2026-09-17) — 등록 전에는 null 이라 발행 자체를 막는다
const bus = C.createCommandBus((topic, payload, o) => {
  if (!connected) return false;
  sent.push({ topic, payload: JSON.parse(payload), o });
  return true;
}, () => T);

const p1 = bus.cancelReport('acc-1');
ok('토픽이 kiosk/command/cancel', sent[0].topic.endsWith('/kiosk/command/cancel'), sent[0].topic);
ok('retain 금지', sent[0].o.retain === false);
ok('QoS 1', sent[0].o.qos === 1);
ok('🔴 data 는 배열', Array.isArray(sent[0].payload.data));
ok('issued_by TABLET', sent[0].payload.data[0].issued_by === 'TABLET');

// 응답은 data 가 단건 객체다 (CommandAck)
bus.handleResponse(JSON.stringify({
  request_id: sent[0].payload.request_id, v: 1, ts: 1, is_success: true, error: null,
  data: { accident_id: 'acc-1', command: 'cancel', status: 'CANCEL' },
}));
const r1 = await p1;
ok('성공 응답이 약속을 푼다', r1.accepted === true);
ok('응답의 현재 상태를 앱 상태로', r1.status === 'CANCELLED', r1.status);

const p2 = bus.reportNow('acc-1');
bus.handleResponse(JSON.stringify({
  request_id: sent[1].payload.request_id, v: 1, ts: 1, is_success: false,
  error: { code: 'INVALID_STATE', message: 'report_now is only valid in WAIT' },
  data: { accident_id: 'acc-1', command: 'report_now', status: 'REPORT' },
}));
const r2 = await p2;
ok('거절 사유가 그대로 온다', r2.accepted === false && r2.reason === 'INVALID_STATE');
ok('거절돼도 현재 상태가 온다', r2.status === 'REPORTED');

// 다른 명령의 응답이 내 약속을 풀면 안 된다
const before = sent.length;
const p3 = bus.resolveIncident('acc-1');
bus.handleResponse(JSON.stringify({ request_id: 'someone-else', v: 1, ts: 1, is_success: true, error: null, data: {} }));
let settled = false; void p3.then(() => { settled = true; });
await new Promise((res) => setTimeout(res, 2200));
ok('남의 request_id 는 무시', settled === false);
ok('close 토픽으로 나간다', sent[before].topic.endsWith('/kiosk/command/close'), sent[before].topic);
ok('🔴 2초 응답 없으면 같은 request_id 로 재발행', sent.length === before + 2
  && sent[before + 1].payload.request_id === sent[before].payload.request_id, String(sent.length - before));
bus.abortAll();
ok('abortAll 이 OFFLINE 으로 깨운다', (await p3).reason === 'OFFLINE');

const pm = bus.manualAlert({ alertType: 'DISABLED', lat: 35.0, lon: 129.0 });
const mp = sent[sent.length - 1].payload.data[0];
ok('report_manual 토픽', sent[sent.length - 1].topic.endsWith('/kiosk/command/report_manual'));
ok('DISABLED → ENGINE_FAILURE', mp.accident_type === 'ENGINE_FAILURE', mp.accident_type);
ok('accident_id 를 키오스크가 만든다', typeof mp.accident_id === 'string' && mp.accident_id.length === 36);
ok('좌표가 실린다', mp.lat === 35.0 && mp.lon === 129.0);
bus.abortAll(); await pm;

// 🔴 유형이 IoT `contracts/enums.py AccidentType` 8종 안에 있어야 한다.
//    밖의 값을 보내면 Pi 가 ValidationError 로 버리고 **응답도 주지 않는다** —
//    화면에는 5초 뒤 타임아웃만 뜬다. HAZARD 로 실제로 겪었다(2026-09-18).
const IOT_ACCIDENT_TYPES = new Set([
  'MOB', 'FIRE', 'FLOODING', 'COLLISION', 'GROUNDING',
  'ENGINE_FAILURE', 'OTHER_DISTRESS', 'MEDICAL',
]);
const APP_ALERT_TYPES = [
  'MOB', 'FIRE', 'FLOODING', 'COLLISION', 'GROUNDING',
  'DISABLED', 'UNDESIGNATED', 'MEDICAL',
];
const strayTypes = [];
for (const t of APP_ALERT_TYPES) {
  const pending = bus.manualAlert({ alertType: t, lat: 35.0, lon: 129.0 });
  const got = sent[sent.length - 1].payload.data[0].accident_type;
  if (!IOT_ACCIDENT_TYPES.has(got)) strayTypes.push(`${t}->${got}`);
  bus.abortAll(); await pending;
}
ok('수동 신고 유형 8종이 전부 IoT AccidentType 안에 있다',
  strayTypes.length === 0, strayTypes.join(' '));

connected = false;
ok('끊긴 상태 publish 는 OFFLINE', (await bus.cancelReport('acc-1')).reason === 'OFFLINE');

// 🔴 등록 전에는 토픽이 없다. 'ship-unset' 으로 쏘면 브로커가 조용히 받아 다른 방에 둔다
//    (ref/kiosk_시연.md §9 "아무것도 안 옴. 에러도 없음")
const beforeUnreg = sent.length;
const unregistered = C.createCommandBus(() => true, () => null);
const r0 = await unregistered.cancelReport('acc-x');
ok('등록 전에는 발행하지 않는다', r0.accepted === false && r0.reason === 'OFFLINE');
ok('등록 전에는 아무것도 안 나간다', sent.length === beforeUnreg);

console.log(`\n${pass} 통과 / ${fail} 실패`);
await server.close();
process.exit(fail ? 1 : 0);

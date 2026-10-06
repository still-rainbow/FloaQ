import type { ServerMessage, Snapshot } from '@floaq/shared';

/**
 * Pi 없이 화면을 검증하기 위한 녹화 시나리오.
 *
 * 목 서버가 아니다 — 서버를 세우지 않고 같은 리듀서에 메시지를 흘려보낸다.
 * 인프라가 0 이고, Pi 가 준비되면 .env 한 줄로 갈아탄다.
 *
 * **IoT 팀에 넘기는 규약 예시가 이 파일이다.** 이 순서대로 보내면 화면이 돈다.
 *
 * ⚠ 검증되는 것은 렌더링과 상태 전이뿐이다. 재연결·하트비트·CORS·시계 오프셋은
 *    실제 Pi 에 붙어야 검증된다 — fixture 가 통과했다고 통신이 된다는 뜻이 아니다.
 */

const VESSEL = 'v-1';
const INCIDENT = 'i-42';

/** 기준 시각을 실행 시점으로 잡는다. 고정 시각이면 "몇 분 전" 표시가 과거로 굳는다 */
const t0 = () => Date.now();
const iso = (offsetMs: number) => new Date(t0() + offsetMs).toISOString();

export const fixtureSnapshot = (): Snapshot => ({
  serverNow: iso(0),
  vesselId: VESSEL,
  vesselName: '제7해성호',
  incident: null,
  buoy: null,
  telemetry: { headingDeg: 214, speedKn: 6.2, rollDeg: 3.2, pitchDeg: 1.1 },
  health: { camera: 'OK', ai: 'OK', imu: 'OK', buoy: 'OK' },
});

export interface FixtureStep {
  /** 시작 후 경과(ms) */
  afterMs: number;
  msg: () => ServerMessage;
}

/**
 * 익수 감지 → 부표 발사 → 유예 → 자동 신고 → 부표 추적 → 두절.
 * 계획.md §9.3 · IoT orchestrator.on_detection 순서 그대로다.
 */
export const fixtureSteps: FixtureStep[] = [
  {
    // DETECT — 부표 조준·발사 중. 경보는 여기서 뜨고 버튼은 아직 잠긴다
    afterMs: 3_000,
    msg: () => ({
      type: 'INCIDENT_DETECTED', vesselId: VESSEL, at: iso(0),
      incident: {
        incidentId: INCIDENT, status: 'DETECTED',
        lat: 35.1712, lon: 129.2043, detectedAt: iso(0),
        urgency: 'DISTRESS', alertType: 'MOB',
      },
    }),
  },
  {
    // WAIT — 발사 끝, 카운트다운. 발사 시간 2초는 시연용 값이다 (실측 아님)
    afterMs: 5_000,
    msg: () => ({
      type: 'INCIDENT_DETECTED', vesselId: VESSEL, at: iso(0),
      incident: {
        incidentId: INCIDENT, status: 'PENDING',
        lat: 35.1712, lon: 129.2043, detectedAt: iso(-2_000),
        // 30초 유예. 절대 시각으로 보낸다 — 남은 초를 보내면 재연결 시 못 세운다
        deadline: iso(30_000),
        urgency: 'DISTRESS', alertType: 'MOB',
      },
    }),
  },
  {
    // 무응답 → 자동 신고. fail-safe 가 실제로 도는지 보는 구간이다
    afterMs: 35_000,
    msg: () => ({
      type: 'INCIDENT_STATE', vesselId: VESSEL, at: iso(0),
      incidentId: INCIDENT, status: 'REPORTED',
    }),
  },
  {
    afterMs: 37_000,
    msg: () => ({
      type: 'BUOY_POS', vesselId: VESSEL, at: iso(0), incidentId: INCIDENT,
      buoy: { buoyId: 'b-1', lat: 35.1714, lon: 129.2048, at: iso(0), lost: false },
    }),
  },
  {
    afterMs: 47_000,
    msg: () => ({
      type: 'BUOY_LOST', vesselId: VESSEL, at: iso(0), incidentId: INCIDENT,
      buoy: {
        buoyId: 'b-1', lat: 35.1714, lon: 129.2048,
        at: iso(-60_000), lost: true,
        // 1σ 타원. 95% 는 여기에 2.36 을 곱한 값이라 장축 180m 다.
        // ⚠ 단축이 장축보다 **길지 않게** 둔다 — 뒤집힌 값은 지도가 90° 돌려 그린다
        estimatedRadiusM: 180,
        driftEllipse: { majorM: 76, minorM: 42, bearingDeg: 38 },
        driftTarget: 'BUOY',
      },
    }),
  },
  {
    afterMs: 52_000,
    msg: () => ({
      type: 'DEVICE_HEALTH', vesselId: VESSEL, at: iso(0),
      camera: 'OK', ai: 'OK', imu: 'OK', buoy: 'LOST',
    }),
  },
];

/** 마지막 스텝 시각. 재생 중 표시를 끄는 기준 — 스텝을 늘리면 따라 늘어난다 */
export const fixtureDurationMs = Math.max(...fixtureSteps.map((s) => s.afterMs));

/** 스텝을 순서대로 발화. 반환값을 부르면 남은 타이머를 전부 걷는다 */
export function playFixture(onMessage: (m: ServerMessage) => void): () => void {
  const timers = fixtureSteps.map((s) => setTimeout(() => onMessage(s.msg()), s.afterMs));
  return () => timers.forEach(clearTimeout);
}

import { authFetch } from '../auth';
import { seaOfSnap } from '../ocean';
import type { Buoy, Incident, IncidentState, Stage, Stages, Urgency } from '../../types';
import type { LngLat } from '@floaq/shared';

/**
 * 서버 사고 API → 화면이 쓰는 {@link Incident}.
 *
 * <p><b>화면 타입을 서버 모양으로 바꾸지 않는다.</b> 목데이터가 화면에 맞춰 만들어져 있어
 * 컴포넌트 전부가 그 모양을 전제하고 있고, 서버 응답은 DB 모양이다. 둘을 억지로 같게 하면
 * 한쪽이 바뀔 때마다 반대쪽이 깨진다 — <b>여기 한 곳에서만 옮긴다</b>(2026-09-18).</p>
 *
 * <p>서버에 없는 값은 <b>비워 둔다.</b> 목데이터의 그럴듯한 값을 남겨 두면 화면이
 * 실데이터처럼 보이면서 실제로는 지어낸 것을 그린다 — 그게 지금까지 문제였다.</p>
 */

/* ── 서버 응답 모양 (backend com.floaq.accident.dto) ─────── */

type AccidentStatus = 'DETECT' | 'WAIT' | 'REPORT' | 'CANCEL' | 'CLOSE';
type AccidentType =
  | 'MOB' | 'FIRE' | 'FLOODING' | 'COLLISION' | 'GROUNDING'
  | 'ENGINE_FAILURE' | 'OTHER_DISTRESS' | 'MEDICAL';

interface ShipBrief {
  shipId: string;
  name: string | null;
  registrationNo?: string | null;
  mmsi?: string | null;
}

interface SummaryView {
  accidentId: string;
  ship: ShipBrief;
  accidentType: AccidentType | null;
  triggerSource: 'AI' | 'MANUAL' | null;
  reportType: 'DISTRESS' | 'URGENCY' | null;
  reportDsc: number | null;
  status: AccidentStatus;
  lat: number | null;
  lon: number | null;
  createdAt: string;
  reportedAt: string | null;
  rescuedAt: string | null;
  closedAt: string | null;
  waterTempC: number | null;
  /** 관제가 이 사고를 접수한 시각. reports[].ackedAt(DSC 무선 ACK)과 다른 값이다 */
  webAckedAt: string | null;
  /** 사고가 나던 때의 바다. 없으면 null — 그때만 화면이 해양 조회로 메운다 */
  ocean: OceanDto | null;
}

interface BuoyStateView {
  lat: number | null;
  lon: number | null;
  isPressed: boolean;
  measuredAt: string | null;
  heldAt: string | null;
}

interface ReportViewDto {
  channel: string;
  status: string;
  sentCount: number | null;
  firstSentAt: string | null;
  lastSentAt: string | null;
  ackedAt: string | null;
}

/** 부표 투하 결과. 사고당 한 행이고 결과가 늦게 붙어 upsert 된다 */
interface LaunchViewDto {
  result: 'SUCCESS' | 'FAILED' | null;
  failReason: 'NOT_LOADED' | 'DEVICE_ERROR' | 'OUT_OF_RANGE' | 'NO_SOLUTION' | null;
  launchLat: number | null;
  launchLon: number | null;
  targetLat: number | null;
  targetLon: number | null;
  horizontalAngle: number | null;
  verticalAngle: number | null;
  confidenceScore: number | null;
  launchedAt: string | null;
}

interface DetailView extends SummaryView {
  buoy: BuoyStateView | null;
  reports: ReportViewDto[];
  launch: LaunchViewDto | null;
}

interface TimelineView {
  at: string;
  kind: 'STATE' | 'COMMAND';
  status: AccidentStatus | null;
  reason: string | null;
  commandType: string | null;
  issuedBy: { name: string | null } | null;
}

interface BuoyPointView {
  lat: number | null;
  lon: number | null;
  /** 그 순간 버튼이 눌려 있었나. 놓은 시점을 여기서 뽑는다 */
  isPressed: boolean;
  measuredAt: string;
}

/** `/api/accidents/{id}/ship-positions` 한 점. 선수각은 없으면 null 이다 — 0 은 "정북"이라 다른 뜻이다 */
interface ShipPointView {
  lat: number | null;
  lon: number | null;
  speedKn: number | null;
  headingDeg: number | null;
  measuredAt: string;
}

/** 사고 행에 박혀 있는 그때의 바다. 목록·상세 둘 다 싣는다 */
interface OceanDto {
  currentSpeedMs: number | null;
  currentDirDeg: number | null;
  windSpeedMs: number | null;
  windDirDeg: number | null;
  spreadMs: number | null;
  observedAt: string;
}

/** `/api/accidents/{id}/photos` — 감지 순간 · 가장 최근 프레임 */
interface PhotosDto {
  detect: PhotoDto | null;
  latest: PhotoDto | null;
}
interface PhotoDto {
  url: string;
  expiresAt: string;
  capturedAt: string | null;
  camera: 'L' | 'R' | null;
  seq: number | null;
}

const photoOf = (p: PhotoDto | null | undefined): Incident['photos']['detect'] =>
  p ? { url: p.url, capturedAt: p.capturedAt, camera: p.camera } : null;

interface Page<T> {
  content: T[];
  page: number;
  size: number;
  totalElements: number;
  hasNext: boolean;
}

/* ── 값 옮기기 ───────────────────────────────────────────── */

/** DSC nature of distress — 우리가 만든 분류가 아니다(§9.21) */
const TYPE_LABEL: Record<AccidentType, [string, string]> = {
  MOB: ['인명 추락', '110'],
  FIRE: ['선박 화재', '100'],
  FLOODING: ['침수 · 전복 위험 · 표류', '101'],
  COLLISION: ['충돌', '102'],
  GROUNDING: ['좌초', '103'],
  ENGINE_FAILURE: ['기관 고장 · 조종 불능 · 표류 중', '106'],
  OTHER_DISTRESS: ['기타 조난', ''],
  MEDICAL: ['응급 환자 · 부상', ''],
};

/** 진행 중은 셋이다 — 감지 · 신고 대기 · 신고 발신. 화면은 그 셋을 갈라 보지 않는다 */
const LIVE: AccidentStatus[] = ['DETECT', 'WAIT', 'REPORT'];

const STATUS_TEXT: Record<AccidentStatus, string> = {
  DETECT: '감지', WAIT: '신고 대기', REPORT: '신고 발신', CANCEL: '취소', CLOSE: '종결',
};

const REASON_TEXT: Record<string, string> = {
  AI_DETECT: 'AI 가 익수를 감지했습니다',
  COUNTDOWN_START: '신고 대기 시작',
  TIMEOUT: '응답이 없어 자동 신고',
  TABLET_CANCEL: '선내에서 취소',
  TABLET_REPORT_NOW: '선내에서 즉시 신고',
  TABLET_MANUAL: '선내에서 수동 신고',
  TABLET_RESCUE: '선내에서 구조 확정',
  TABLET_CLOSE: '선내에서 종결',
};

const stateOf = (s: AccidentStatus): IncidentState =>
  (LIVE.includes(s) ? 'live' : s === 'CANCEL' ? 'cancel' : 'closed');

const pad = (n: number) => String(n).padStart(2, '0');

/** ISO → 'HH:MM:SS'. 화면은 하루 안의 시각만 쓴다 */
function hms(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** ISO → 'YYYY-MM-DD' */
function day(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const stageAt = (iso: string | null | undefined, note?: string): Stage =>
  (iso ? { at: hms(iso), note } : { at: null });

const secSince = (iso: string | null | undefined): number =>
  (iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000)) : 0);

/**
 * 부표 위치를 지금도 받고 있나.
 *
 * <p>서버는 실측/추정을 갈라 주지 않는다 — 마지막 수신 시각만 준다. LoRa 가 1Hz 라
 * 이만큼 끊기면 두절로 본다. 판정 주체가 정해지면(api.md §9 4) 이 값을 서버에서 받는다.</p>
 */
const LOST_SEC = 60;

const FAIL_TEXT: Record<string, string> = {
  NOT_LOADED: '부표가 장전되지 않음',
  DEVICE_ERROR: '장치 오류',
  OUT_OF_RANGE: '사거리 밖',
  NO_SOLUTION: '조준 해 없음',
};

/**
 * 발사 기록 → 화면의 `facts`(값 + 단위)와 `params`(막대 + 값).
 *
 * <p>구조에 쓰이는 값이 아니다 — <b>장치가 제대로 작동했나</b>를 말한다. 그래서 진행 중
 * 사고 화면에서는 숨기고(lib/facts.ts LAUNCH_FACTS) 종료 리포트와 상세에만 싣는다.</p>
 *
 * <p>⚠ `감지에서 발사까지` 는 서버가 주는 값이 아니라 <b>여기서 뺀다</b> —
 * 투하 시각과 감지 시각의 차이다. 두 값이 다 있을 때만 적는다.</p>
 */
function launchFacts(l: LaunchViewDto | null, detectedAt: string):
  { facts: Incident['facts']; params: Incident['params'] } {
  if (!l) return { facts: [], params: [] };

  const facts: Incident['facts'] = [];
  if (l.result === 'FAILED') {
    facts.push(['발사', '실패', '']);
    if (l.failReason) facts.push(['실패 사유', FAIL_TEXT[l.failReason] ?? l.failReason, '']);
  }
  if (l.launchedAt) {
    const gap = (new Date(l.launchedAt).getTime() - new Date(detectedAt).getTime()) / 1000;
    if (gap >= 0 && gap < 600) facts.push(['감지에서 발사까지', gap.toFixed(1), '초']);
  }
  // 착수 지점 오차 — 겨눈 곳과 실제로 떨어진 곳의 거리. 조준이 맞았나를 한 숫자로 말한다
  if (l.launchLat != null && l.launchLon != null && l.targetLat != null && l.targetLon != null) {
    const dy = (l.targetLat - l.launchLat) * 110574;
    const dx = (l.targetLon - l.launchLon) * 111320 * Math.cos(l.launchLat * Math.PI / 180);
    facts.push(['발사 오차', Math.hypot(dx, dy).toFixed(1), 'm']);
  }

  /* 막대는 0~100 이다. 각도는 그대로, 신뢰도는 백분율로 옮긴다 */
  const params: Incident['params'] = [];
  if (l.horizontalAngle != null) params.push(['사각', Math.round(l.horizontalAngle), `${l.horizontalAngle.toFixed(1)} °`]);
  if (l.verticalAngle != null) params.push(['상하각', Math.round(l.verticalAngle), `${l.verticalAngle.toFixed(1)} °`]);
  if (l.confidenceScore != null) params.push(['탐지 신뢰도', Math.round(l.confidenceScore * 100), `${Math.round(l.confidenceScore * 100)} %`]);
  return { facts, params };
}

/**
 * 🔴 <b>부표를 놓은 순간</b>을 궤적에서 뽑는다.
 *
 * <p>눌려 있다가 풀린 지점이다 — <b>신호가 오는 중에만 관측된다.</b> 통신이 끊겨 눌림이
 * 안 오는 것은 놓은 것이 아니라 <b>모르는 것</b>이고, 그건 따로 다룬다(types.ts heldAtLastFix).</p>
 *
 * <p>이 값이 중요한 이유: 잡고 있던 구간은 사람이 부표와 <b>함께</b> 흘렀다. 그 구간을 사람
 * 계수(1%)로 세면 부표 계수(3%)와 <b>3배</b> 틀린다. 놓은 자리에서 다시 시작해야 맞다(lib/view.ts).</p>
 *
 * @returns 놓은 시각과 그때 부표가 있던 자리. 놓은 적이 없으면 둘 다 null
 */
function releaseOf(pts: BuoyPointView[]): { at: string | null; from: LngLat | null } {
  let lastHeld = -1;
  for (let i = 0; i < pts.length; i += 1) if (pts[i]!.isPressed) lastHeld = i;
  if (lastHeld < 0) return { at: null, from: null };

  // 마지막으로 눌려 있던 다음에 <b>안 눌린 채로 받은</b> 점이 있어야 놓은 것이다
  const after = pts[lastHeld + 1];
  if (!after) return { at: null, from: null };

  const held = pts[lastHeld]!;
  return {
    at: after.measuredAt,
    // 놓은 자리는 마지막으로 잡고 있던 자리로 본다. 그 사이 어딘가지만 알 방법이 없고,
    // 앞쪽으로 잡는 편이 사람 추정을 조금 더 넓게 만든다 — 좁히는 실수보다 낫다
    from: held.lat != null && held.lon != null ? [held.lon, held.lat] : null,
  };
}

function buoyOf(b: BuoyStateView | null, track: LngLat[], pts: BuoyPointView[] = []): Buoy | null {
  if (!b || b.lat == null || b.lon == null) return null;
  const now: LngLat = [b.lon, b.lat];
  const ageSec = secSince(b.measuredAt);
  const rel = releaseOf(pts);
  return {
    at: now,
    fix: ageSec > LOST_SEC ? 'estimated' : 'measured',
    ageSec,
    // 실측 궤적의 마지막 점이 곧 마지막으로 받은 자리다. 궤적이 없으면 현재 값을 그대로 쓴다
    lastFixAt: track.length ? track[track.length - 1]! : now,
    heldAt: b.heldAt ? hms(b.heldAt) : null,
    // 🔴 서버의 isPressed 는 <b>마지막으로 받은 패킷의 눌림 상태</b>다 — 우리가 필요했던 값 그대로다
    heldAtLastFix: b.isPressed,
    // 궤적의 눌림 변화에서 뽑는다 — 서버에 컬럼이 따로 없어도 이미 오는 값으로 알 수 있다
    releasedAt: rel.at ? hms(rel.at) : null,
    releasedFrom: rel.from,
  };
}

function stagesOf(v: SummaryView, reports: ReportViewDto[]): Stages {
  /*
   * ③ 단계는 <b>관제가 받았나</b>다(`webAckedAt`). DSC 무선 ACK(`reports[].ackedAt`)은
   * 해안국이 응답했다는 다른 사실이라, 없으면 그때만 대신 쓴다 — 둘 다 "누가 받았다"이긴 하다.
   */
  const radio = reports.map((r) => r.ackedAt).filter((x): x is string => !!x).sort();
  return {
    detect: { at: hms(v.createdAt) },
    report: stageAt(v.reportedAt, '신고 발신'),
    ack: stageAt(v.webAckedAt ?? radio[0], v.webAckedAt ? '관제 접수' : '해경 무선 응답'),
    found: stageAt(v.rescuedAt, '구조 확정'),
    close: stageAt(v.closedAt, '종결'),
  };
}

/**
 * 배를 어디에 어느 쪽으로 그릴지, 마지막 소식이 언제였는지.
 *
 * <p>사고 행의 위도·경도는 <b>감지된 순간</b>의 자리다. 그 뒤 배가 움직였으면 그 자리는 틀린다 —
 * 항적의 마지막 점이 있으면 그쪽이 지금 자리다.</p>
 *
 * <p><b>항적이 없을 때 경과를 감지 시각부터 센다.</b> 0 으로 두면 "방금 받았다"가 되는데 사실이 아니고,
 * 그렇다고 모른다고 비우면 익수 아닌 사고의 색이 정해지지 않는다. 사고 신고 자체가 그 배에서 온
 * 마지막 소식이므로, 감지 이후 경과가 곧 "소식이 끊긴 지"의 답이다.</p>
 */
function shipOf(pts: ShipPointView[], atDetect: LngLat, detectedAt: string):
  { ship: LngLat; hdg: number; shipAgeSec: number; shipFix: boolean } {
  const fixed = pts.filter((p): p is ShipPointView & { lat: number; lon: number } =>
    p.lat != null && p.lon != null);
  const last = fixed[fixed.length - 1];
  return {
    ship: last ? [last.lon, last.lat] : atDetect,
    // 선수각이 없으면 0 — 지도가 북쪽을 보는 배를 그린다. 값이 없다는 뜻으로 읽히진 않지만
    // 돌릴 근거가 없을 때 어느 쪽이든 찍는 것보다는 낫다
    hdg: last?.headingDeg ?? 0,
    shipAgeSec: secSince(last ? last.measuredAt : detectedAt),
    shipFix: last != null,
  };
}

/** 화면이 쓰는 한 건. 상세를 안 받았어도 목록 값만으로 그려진다 */
function toIncident(
  v: SummaryView | DetailView,
  extra: {
    buoy?: BuoyStateView | null;
    reports?: ReportViewDto[];
    track?: LngLat[];
    /** 궤적 원본. 놓은 시점을 뽑는 데 쓴다 — 좌표만으로는 눌림 변화를 알 수 없다 */
    points?: BuoyPointView[];
    /** 사고 선박 항적. 마지막 점이 지금 배 자리이자 마지막 소식 시각이다 */
    shipPts?: ShipPointView[];
    /** 사진 두 장. 없으면 화면이 "아직 받지 못했습니다"를 그린다 */
    photos?: PhotosDto | null;
    timeline?: TimelineView[];
    launch?: LaunchViewDto | null;
  } = {},
): Incident {
  const reports = extra.reports ?? [];
  const track = extra.track ?? [];
  const live = LIVE.includes(v.status);
  const type = v.accidentType ? TYPE_LABEL[v.accidentType] : ['조난', ''];
  const atDetect: LngLat = [v.lon ?? 0, v.lat ?? 0];
  // 익수 지점은 감지된 자리에 그대로 둔다 — 배가 그 뒤로 움직여도 사람이 빠진 곳은 변하지 않는다
  const mob = v.accidentType === 'MOB' && v.lat != null && v.lon != null ? atDetect : null;
  const nav = shipOf(extra.shipPts ?? [], atDetect, v.createdAt);
  const buoy = buoyOf(extra.buoy ?? null, track, extra.points ?? []);
  const elapsedSec = secSince(v.createdAt);

  return {
    id: v.accidentId,
    ship: v.ship.shipId,
    day: day(v.createdAt),
    state: stateOf(v.status),
    badge: live
      ? ['진행 중', 'warn']
      : v.status === 'CANCEL' ? ['취소', 'cancel'] : ['완료', 'resolved'],
    head: `${hms(v.createdAt)} · ${STATUS_TEXT[v.status]}`,
    map: {
      ship: nav.ship,
      hdg: nav.hdg,
      shipAgeSec: nav.shipAgeSec,
      shipFix: nav.shipFix,
      mob,
      mobText: mob ? hms(v.createdAt) : undefined,
      buoy,
      // 부표를 잡고 있으면 부표 = 사람이라 마커를 따로 세우지 않는다
      person: mob && (!buoy || !buoy.heldAtLastFix)
        ? { reason: buoy ? '부표 버튼 안 눌림' : '부표 없음' }
        : null,
      track: track.length ? { measured: track } : null,
    },
    ...launchFacts(extra.launch ?? null, v.createdAt),
    // 사고 설명 문단은 서버에 그런 칸이 없다. 목데이터 때는 손으로 쓴 문장이었다
    result: '',
    timeline: (extra.timeline ?? []).map((t) => ([
      t.kind === 'COMMAND' ? 'command' : 'state',
      hms(t.at),
      t.status ? STATUS_TEXT[t.status] : (t.commandType ?? '명령'),
      t.reason ? (REASON_TEXT[t.reason] ?? t.reason) : (t.issuedBy?.name ?? ''),
    ] as [string, string, string, string])),
    // 영상(mp4)은 받지 않는다 — 배가 만들지 않는다(2026-09-21). 칸은 '영상 그만 받기' 표시에만 남는다
    clip: { src: '', startSec: 0, dur: 0, fps: 5, trigger: 0, got: 0 },
    photos: { detect: photoOf(extra.photos?.detect), latest: photoOf(extra.photos?.latest) },
    type: {
      urg: (v.reportType === 'URGENCY' ? 'urgency' : 'distress') as Urgency,
      label: type[0]!,
      dsc: v.reportDsc != null ? String(v.reportDsc) : type[1]!,
    },
    detectedAt: v.createdAt,
    oceanSnap: seaOfSnap(v.ocean),
    stages: stagesOf(v, reports),
    // 수온이 없으면 생존 시계를 못 돌린다. 임의 값 대신 NaN 을 줘서 화면이 '—' 를 그리게 한다
    waterTemp: v.waterTempC ?? Number.NaN,
    elapsedSec,
    send: live && reports.some((r) => r.status === 'SENDING')
      ? { sent: reports.reduce((n, r) => n + (r.sentCount ?? 0), 0), total: 8 }
      : null,
  };
}

/* ── 부르기 ──────────────────────────────────────────────── */

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await authFetch(path);
    if (!res.ok) return null;
    const body = await res.json() as { success?: boolean; data?: T | null };
    return body && body.success ? (body.data ?? null) : null;
  } catch {
    // 서버가 안 떠 있거나 끊겼다. 화면은 빈 목록을 그리고 다음 폴링에서 다시 본다
    return null;
  }
}

export interface Fleet {
  id: string;
  name: string;
  reg: string;
}

export interface IncidentFeed {
  incidents: Incident[];
  /** 사고에 딸려 온 배들. 선박 목록 API 를 따로 안 불러도 이름이 채워진다 */
  vessels: Fleet[];
}

/** 목록 한 페이지. 화면은 진행 중과 기록을 한 배열로 쓴다 */
export async function fetchIncidents(size = 100): Promise<IncidentFeed | null> {
  const page = await get<Page<SummaryView>>(`/api/accidents?size=${size}`);
  if (!page) return null;

  const vessels = new Map<string, Fleet>();
  for (const v of page.content) {
    if (!vessels.has(v.ship.shipId)) {
      vessels.set(v.ship.shipId, {
        id: v.ship.shipId,
        name: v.ship.name ?? '이름 없음',
        reg: v.ship.registrationNo ?? '',
      });
    }
  }

  return { incidents: page.content.map((v) => toIncident(v)), vessels: [...vessels.values()] };
}

/**
 * 한 건의 상세 — 부표 · 배 · 신고 · 궤적 · 경위 · 사진까지. 목록 값만으로는 지도에 부표를 못 그린다.
 * 여섯 요청을 한꺼번에 보내고, 하나가 실패해도 나머지로 그린다.
 */
export async function fetchIncidentDetail(id: string): Promise<Incident | null> {
  const [detail, timeline, points, reports, shipPts, photos] = await Promise.all([
    get<DetailView>(`/api/accidents/${id}`),
    get<TimelineView[]>(`/api/accidents/${id}/timeline`),
    get<BuoyPointView[]>(`/api/accidents/${id}/buoy-positions`),
    get<ReportViewDto[]>(`/api/accidents/${id}/reports`),
    get<ShipPointView[]>(`/api/accidents/${id}/ship-positions`),
    get<PhotosDto>(`/api/accidents/${id}/photos`),
  ]);
  if (!detail) return null;

  const kept = (points ?? []).filter(
    (p): p is BuoyPointView & { lat: number; lon: number } => p.lat != null && p.lon != null);
  const track: LngLat[] = kept.map((p) => [p.lon, p.lat] as LngLat);

  return toIncident(detail, {
    launch: detail.launch,
    points: kept,
    shipPts: shipPts ?? [],
    photos,
    buoy: detail.buoy,
    reports: reports ?? detail.reports ?? [],
    track,
    timeline: timeline ?? [],
  });
}

/**
 * 🔴 <b>목록이 상세를 덮지 않게</b> 겹친다.
 *
 * <p>목록(`GET /api/accidents`)과 상세(`GET /api/accidents/{id}` 외 3개)가 같은 주기로 도는데,
 * 목록에는 <b>부표 · 궤적 · 경위 · 해경 접수가 없다</b>. 나중에 도착한 목록이 상세를 통째로
 * 갈아 끼우면 그 값들이 사라졌다가 다음 상세에서 되살아난다 — 화면에서는 단계 바가
 * `구조대 대응` ↔ `탐지 · 부표 발사` 로 깜빡이고 부표 마커가 5초마다 나타났다 사라진다(2026-09-18).</p>
 *
 * <p>그래서 <b>목록이 아는 것만</b> 새로 쓴다. 상태 · 시각 · 좌표는 목록이 정본이고,
 * 상세로만 오는 값은 갖고 있던 것을 남긴다. 상세를 한 번도 안 받은 사고는 그냥 목록 값이다.</p>
 */
export function keepDetail(prev: Incident | undefined, next: Incident): Incident {
  if (!prev) return next;
  /*
   * ⚠ "상세를 받았나"를 부표·경위가 있는지로 짐작하면 안 된다. 부표를 못 쏜 사고, 상태 전이가
   *   한 번뿐인 사고는 상세를 받아도 둘 다 비어 있어서 <b>매번 목록이 이겼다</b> —
   *   접수 시각이 5초마다 사라졌다 나타나고 단계 바가 깜빡였다(2026-09-18).
   *
   * 그래서 출처를 따지지 않고 <b>값이 있는 쪽</b>을 남긴다. 목록 매핑은 이 값들을 절대 못 만들므로
   * (상세 인자를 안 받는다) 목록이 덮어쓸 일이 애초에 없다.
   */
  return {
    ...next,
    map: {
      ...next.map,
      /*
       * 배 자리는 목록도 늘 채워 보낸다 — 항적이 없으면 감지된 자리로. 그래서 "값이 있나"로는
       * 가를 수 없고, 실제 수신에서 나왔는지(shipFix)로 가른다. 안 그러면 5초마다 배가
       * 지금 자리와 감지 자리를 오간다(부표·단계 바와 같은 함정).
       */
      ...(next.map.shipFix || !prev.map.shipFix ? {} : {
        ship: prev.map.ship, hdg: prev.map.hdg, shipAgeSec: prev.map.shipAgeSec, shipFix: true,
      }),
      // 부표 · 사람 · 궤적은 상세(또는 부표 요청)에서만 온다
      buoy: next.map.buoy ?? prev.map.buoy,
      person: next.map.buoy ? next.map.person : prev.map.person,
      track: next.map.track ?? prev.map.track,
    },
    timeline: next.timeline.length ? next.timeline : prev.timeline,
    // 발사 기록도 상세에서만 온다. 목록 값으로 덮으면 5초마다 사라졌다 나타난다
    facts: next.facts.length ? next.facts : prev.facts,
    params: next.params.length ? next.params : prev.params,
    stages: {
      ...next.stages,
      // 접수는 /reports 에서만 온다. 목록의 빈 값으로 덮으면 단계가 뒤로 물러난다
      ack: next.stages.ack.at ? next.stages.ack : prev.stages.ack,
    },
    // '영상 그만 받기'를 누른 기록(stoppedAt)은 화면에만 있다. 목록의 빈 값으로 덮으면 5초 뒤 지워진다
    clip: prev.clip,
    // 사진도 상세에서만 온다. 목록 폴링의 빈 값으로 덮으면 5초마다 사진이 깜빡 사라진다
    photos: {
      detect: next.photos.detect ?? prev.photos.detect,
      latest: next.photos.latest ?? prev.photos.latest,
    },
    send: next.send ?? prev.send,
  };
}

/** {@link fetchIncidentBuoy} 가 돌려주는 것 — 지도에 부표를 그리는 데 필요한 최소 */
export interface BuoyPatch {
  buoy: Buoy | null;
  track: LngLat[];
  /** 배 자리·뱃머리·마지막 소식. 부표와 같은 주기로 갱신해야 둘이 어긋나지 않는다 */
  nav: { ship: LngLat; hdg: number; shipAgeSec: number; shipFix: boolean };
}

/**
 * 지도에 <b>함께 올린</b> 사고의 부표와 배를 받는다 — 요청 셋이다.
 *
 * <p>목록에는 부표가 없어서, 보고 있는 사고 하나만 부표가 그려지고 나머지는 배 마커만 떴다.
 * 그렇다고 {@link fetchIncidentDetail}(요청 5개)를 사고마다 돌릴 이유는 없다 —
 * 경위와 신고 기록은 <b>오른쪽 패널에만</b> 쓰이고, 그건 보고 있는 한 건뿐이다(2026-09-18).</p>
 *
 * <p>배 위치를 여기에 함께 넣은 이유는 <b>지도에 올린 사고마다 배가 그려지기</b> 때문이다.
 * 부표만 갱신하면 부표는 흘러가는데 배는 감지된 자리에 붙박여 둘이 어긋나 보인다(2026-09-20).</p>
 *
 * <p>⚠ 서버 목록 응답에 부표가 들어오면(api.md 제안) 이 함수는 사라진다. 그때 프런트는
 * 이 호출만 걷어내면 되고 화면이 보는 모양은 그대로다.</p>
 */
export async function fetchIncidentBuoy(id: string): Promise<BuoyPatch | null> {
  const [detail, points, shipPts] = await Promise.all([
    get<DetailView>(`/api/accidents/${id}`),
    get<BuoyPointView[]>(`/api/accidents/${id}/buoy-positions`),
    get<ShipPointView[]>(`/api/accidents/${id}/ship-positions`),
    get<PhotosDto>(`/api/accidents/${id}/photos`),
  ]);
  if (!detail) return null;

  const track: LngLat[] = (points ?? [])
    .filter((p): p is BuoyPointView & { lat: number; lon: number } => p.lat != null && p.lon != null)
    .map((p) => [p.lon, p.lat] as LngLat);

  const atDetect: LngLat = [detail.lon ?? 0, detail.lat ?? 0];
  return { buoy: buoyOf(detail.buoy, track), track, nav: shipOf(shipPts ?? [], atDetect, detail.createdAt) };
}

/**
 * 받은 부표를 사고에 얹는다. <b>사람 마커도 여기서 다시 정한다</b> —
 * 잡고 있으면 부표가 곧 사람이라 따로 세우지 않는다(목록 매핑과 같은 규칙).
 */
export function withBuoy(x: Incident, p: BuoyPatch): Incident {
  const mob = x.map.mob;
  return {
    ...x,
    map: {
      ...x.map,
      ...p.nav,
      buoy: p.buoy,
      person: mob && (!p.buoy || !p.buoy.heldAtLastFix)
        ? { reason: p.buoy ? '부표 버튼 안 눌림' : '부표 없음' }
        : null,
      track: p.track.length ? { measured: p.track } : null,
    },
  };
}

/**
 * 사고 접수를 <b>서버에 남긴다</b>. 멱등이라 폴링마다 불러도 최초 시각이 유지된다.
 *
 * <p>전에는 이 시각이 브라우저 안에만 있었다 — 새로고침하면 사라지고 다른 관제사 화면에는
 * 보이지 않았다(2026-09-18).</p>
 *
 * @return 이번이 처음 접수였나. 못 보냈으면 null — 화면은 다음 폴링에서 다시 시도한다
 */
export async function ackIncident(id: string): Promise<boolean | null> {
  try {
    const res = await authFetch(`/api/accidents/${id}/ack`, { method: 'POST' });
    if (!res.ok) return null;
    const body = await res.json() as { success?: boolean; data?: { created?: boolean } };
    return body?.success ? !!body.data?.created : null;
  } catch {
    return null;
  }
}

/**
 * 관제가 사고에 <b>쓰는</b> 나머지 둘. 접수와 같은 모양이다 —
 * 보내지 못하면 null 이고, 화면은 이미 바뀌어 있으므로 다음에 다시 보낸다.
 */
async function post(path: string): Promise<boolean | null> {
  try {
    const res = await authFetch(path, { method: 'POST' });
    if (!res.ok) return null;
    const body = await res.json() as { success?: boolean; data?: { created?: boolean } };
    return body?.success ? !!body.data?.created : null;
  } catch {
    return null;
  }
}

/**
 * 사고자 발견(단계 ④)을 <b>서버에 남긴다</b>. 멱등이라 두 번 불러도 최초 시각이 유지된다.
 *
 * <p>전에는 브라우저 안에만 있었다 — 새로고침하면 사라지고 다른 관제사에게는 보이지 않았다(2026-09-21).</p>
 */
export const rescueIncident = (id: string) => post(`/api/accidents/${id}/rescue`);

/**
 * 사고 종결(단계 ⑤)을 <b>서버에 남긴다</b>. 되돌릴 수 없다.
 *
 * <p>전에는 화면만 '완료'로 바뀌고 새로고침하면 사고가 되살아났다(2026-09-21).</p>
 */
export const closeIncident = (id: string) => post(`/api/accidents/${id}/close`);

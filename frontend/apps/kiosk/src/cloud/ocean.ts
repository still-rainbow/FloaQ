// 배럴은 leaflet 을 끌어와 node 검증에서 죽는다 — 서브패스로 받는다
import { cloudUrl, piUrl } from '@floaq/shared/origins';

/**
 * EC2 `/api/ocean/sources` 응답. 백엔드 `OceanSourceView` 와 1:1 이다.
 *
 * 이 파일이 프론트와 백엔드의 계약이다 — payload 키를 바꾸면 여기와 backend 양쪽을 같이 고친다.
 * (backend: com.floaq.ocean.dto.OceanSourceView, 각 *Collector 의 payload())
 *
 * ⚠ localStorage 캐시에 옛 모양 payload 가 남아 있을 수 있다. 새로 붙인 키는 optional 로 읽는다.
 */

/** 화면이 시각을 뭐라고 부를지가 여기서 갈린다 — 관측 / 예측값 / 발표 */
export type SourceKind = 'OBSERVATION' | 'FORECAST' | 'ADVISORY';

export interface OceanSource<P = unknown> {
  source: string;
  kind: SourceKind | null;
  /** 관측 시각 / 모델 기준 시각 / 발표 시각. 예보에서 이 값의 경과는 신선도가 아니다 */
  observedAt: string | null;
  fetchedAt: string;
  ageSec: number | null;
  intervalSec: number;
  /** '00' 이 아니면 마지막 시도가 실패했다. payload 는 마지막 성공값이 남아 있다 */
  resultCode: string;
  resultMsg: string | null;
  payload: P | null;
}

export interface RomsPayload {
  gridCount: number;
  baseAt: string | null;
  /** 대표값이 유효한 예측 시각. 화면의 "17시 예측값" */
  validAt: string | null;
  lat?: number;
  lon?: number;
  distanceKm?: number;
  currentDirDeg?: number | null;
  currentSpeedMs?: number | null;
  waterTempC?: number | null;
}

export interface SeaObsStation {
  network: string;
  stn: string;
  name: string;
  lat: number;
  lon: number;
  distanceKm: number;
  waveHeightM: number | null;
  windDirDeg: number | null;
  windSpeedMs: number | null;
  windGustMs: number | null;
  waterTempC: number | null;
  airTempC: number | null;
  pressureHpa: number | null;
  humidityPct: number | null;
}

export interface SeaObsPayload {
  stationCount: number;
  stations: SeaObsStation[];
}

/** 발효 중인 특보구역 하나. 전국 목록이다 — 본선 구역인지는 판정하지 않는다 */
export interface WarningArea {
  areaCode: string;
  areaName: string;
  kind: string;
  level: string;
  /** 풍랑주의보 */
  name: string;
  since: string | null;
}

export interface WarningEvent {
  announcedAt: string | null;
  areaName: string;
  name: string;
  /** 발표 · 해제 · 연장 · 정정 · 변경발표 · 변경해제 */
  action: string;
}

/** 기상청 특보현황 문장. "없 음" 처럼 공백이 섞여 온다 */
export interface WarningStatus {
  announcedAt: string | null;
  effectiveAt: string | null;
  current: string | null;
  preliminary: string | null;
  note: string | null;
}

/**
 * 조업 해역 판정. 설정한 특보구역 코드 + 상위·하위 구역 기준이다.
 * 본선 좌표 판정이 아니다 — 기상청이 특보구역 경계를 제공하지 않는다(2026-09-14 회신).
 */
export interface WarningFocus {
  codes: string[];
  names: string[];
  /** false 면 특보구역 계층을 못 받아 설정 코드만 봤다 — 상위 구역 특보가 빠질 수 있다 */
  hierarchy: boolean;
  relatedCount: number;
  activeMarineWarnings: string[];
  activeAreas: WarningArea[];
}

export interface WarningPayload {
  /** 전국 기준. 비어 있으면 발효 중인 해상 특보가 없다 */
  activeMarineWarnings: string[];
  /** 조업 해역 미설정이거나 옛 캐시면 없다 */
  focus?: WarningFocus | null;
  activeAreas?: WarningArea[];
  /** 특보현황 호출이 실패하면 null */
  status?: WarningStatus | null;
  eventCount?: number;
  events?: WarningEvent[];
}

export interface FishingGroundPayload {
  stationCount: number;
  stations: {
    code: string; name: string; sea: string;
    lat: number; lon: number; distanceKm: number;
    waterTempC: number | null; observedAt: string | null;
  }[];
}

export interface RedTidePayload {
  codNews: string;
  dayReport: string;
  organisms: { name: string | null; area: string | null; maxDensity: number | null }[];
  /** 특보 문구. 상세 호출이 실패하면 없다 */
  breaking?: string | null;
  progress?: string | null;
  /** 금후 전망 */
  afterview?: string | null;
  /** 양식장 당부 사항 */
  request?: string | null;
}

export interface JellyfishPayload {
  subject: string | null;
  /** 제공기관 원문 단서. 화면에 반드시 함께 띄운다 */
  caveat: string;
  text?: string | null;
  /** 첨부 원문(PDF) 주소. 백엔드가 https 만 통과시킨다 */
  files?: string[];
}

/** 선박운항지수 한 구간. 등급 1 매우좋음 ~ 5 매우나쁨, 모르는 문구면 null */
export interface ShipIndexSlot {
  at: string;
  /** 새벽 · 오전 · 오후 · 밤 */
  slot: string | null;
  score: string | null;
  level: number | null;
  currentSpeedMs: number | null;
  windSpeedMs: number | null;
  waveHeightM: number | null;
}

export interface ShipIndexPayload {
  /** 설정된 조업 권역. 권역 좌표가 없어 본선 위치로 고르지 못한다 */
  focusCode: string | null;
  focusName: string | null;
  validAt: string | null;
  current: ShipIndexSlot | null;
  areas: { code: string | null; name: string; slots: ShipIndexSlot[] }[];
}

/** `/api/ocean/current` — 좌표 최근접 ROMS 격자 + 이웃 산포. 백엔드 RomsPointView 와 1:1 */
export interface RomsPoint {
  /** 예측 시각. 지금 이후 가장 이른 것 — 항상 미래 */
  predcDt: string;
  lat: number;
  lon: number;
  currentDirDeg: number | null;
  currentSpeedMs: number | null;
  waterTempC: number | null;
  /** 요청 좌표 → 격자. 한 칸(약 3km)을 넘으면 육지를 건너뛴 것 */
  distanceKm: number;
  /** 한 칸 이내 이웃과의 유속 최대 차이. 경계에 걸리면 커진다. 이웃 없으면 null */
  neighborSpreadMs: number | null;
  neighborCount: number;
}

/** `/api/ocean/grid` — 본선 칸 + 이웃 한 겹. 지도 구역 표시용 */
export interface RomsCell {
  lat: number;
  lon: number;
  currentDirDeg: number | null;
  currentSpeedMs: number | null;
  waterTempC: number | null;
}

export interface RomsGrid {
  predcDt: string;
  /** 칸 크기. 화면이 사각형을 그릴 때 쓴다 */
  latStep: number;
  lonStep: number;
  /** 육지 칸은 빠져 있어 9개가 안 될 수 있다 */
  cells: RomsCell[];
  /** 받을 수 있는 예측 시각 전체 (지금 이후, 오름차순). 시간 슬라이더 눈금. 옛 캐시에는 없다 */
  times?: string[];
  /** 지금 이후 전 시각에 걸친 값 범위. 슬라이더를 넘겨도 색 기준이 안 바뀐다 */
  range?: RomsRange | null;
}

/** 본선 주변 칸의 지금 이후 전 시각 min·max. 값이 하나도 없으면 해당 항목이 null */
export interface RomsRange {
  speedMin: number | null;
  speedMax: number | null;
  tempMin: number | null;
  tempMax: number | null;
}

/** 해구 층. large 전국 대해구(0.5°) · small 본선 주변 소해구(1/6°) */
export type ZoneLevel = 'large' | 'small';

/** 해구 한 칸. 값이 null 이면 결측(육지 칸 등). 대해구는 시정·강수·수온·너울이 항상 null */
export interface ZoneCell {
  lzone: number;
  szone: number;
  latMin: number;
  latMax: number;
  lonMin: number;
  lonMax: number;
  waveHeightM: number | null;
  wavePeriodMaxS: number | null;
  /** ⚠ 오는 쪽/가는 쪽 관례가 명세에 없다 */
  waveDirDeg: number | null;
  windSpeedMs: number | null;
  /** 기상 관례 — 불어오는 쪽 */
  windDirDeg: number | null;
  visibilityM: number | null;
  rainMm: number | null;
  waterTempC: number | null;
  /** 너울 위험 1 관심 · 2 주의 · 3 경계 · 4 위험 */
  swellLevel: number | null;
}

/** 발표본 전 발효시각 min·max. 값이 없는 항목은 null */
export interface ZoneRange {
  waveMin: number | null;
  waveMax: number | null;
  windMin: number | null;
  windMax: number | null;
  tempMin: number | null;
  tempMax: number | null;
}

/** `/api/ocean/zones` — 기상청 해구별 예측 한 프레임. 백엔드 ZoneGridView 와 1:1 */
export interface ZoneGrid {
  level: ZoneLevel;
  issuedAt: string | null;
  /** 이 칸들의 발효시각. 3시간 구간의 시작 */
  validAt: string;
  stepDeg: number;
  cells: ZoneCell[];
  times: string[];
  range: ZoneRange | null;
}

/**
 * @param at 발효시각(ISO). 없으면 지금을 덮는 구간
 * @return 발표본이 없으면 503 으로 던진다
 */
export async function fetchOceanZones(level: ZoneLevel, at?: string | null, signal?: AbortSignal): Promise<ZoneGrid | null> {
  return getJson<ZoneGrid>(`/api/ocean/zones?level=${level}${at ? `&at=${encodeURIComponent(at)}` : ''}`, signal);
}

/**
 * 조류·조석예보 지점 한 줄 (`current-forecast` · `tide-forecast`, 2026-09-16).
 *
 * 값이 **예보**라 predcDt 는 지금 이후다 — "N분 전 관측"으로 읽으면 안 된다.
 * 소스마다 오는 값이 다르다: 조류는 유향·유속, 조석은 조위. 없는 항목은 아예 키가 없다
 */
export interface ForecastStation {
  code: string;
  name: string;
  lat: number;
  lon: number;
  distanceKm: number;
  /** 지금 이후 가장 이른 예보 시각 */
  predcDt: string;
  /** 조류예보 — 원본 16방위 한글을 deg 로 바꾼 값. 못 읽었으면 없다 */
  currentDirDeg?: number | null;
  currentSpeedMs?: number | null;
  /** 조석예보 */
  tideLevelM?: number | null;
}

export interface ForecastPayload {
  stationCount: number;
  /** 전국 지점 수. stationCount 는 반경으로 자른 뒤라 이것보다 작다 */
  requestedStations?: number;
  failedStations?: number;
  rowCount?: number;
  stations: ForecastStation[];
}

/** 만조(HIGH) · 간조(LOW). 1시간 간격 예보라 시각이 최대 ±30분 어긋난다 */
export interface TideExtreme {
  at: string;
  levelM: number;
  kind: 'HIGH' | 'LOW';
}

/** `/api/ocean/tide` — 가장 가까운 조석예보 지점의 조위 곡선. 백엔드 TideSeriesView 와 1:1 */
export interface TideSeries {
  stn: string;
  name: string;
  lat: number;
  lon: number;
  distanceKm: number;
  points: { at: string; tideLevelM: number | null }[];
  extremes: TideExtreme[];
}

/** `/api/ocean/series` — 본선 격자의 시각별 예측. 조석 반일주기가 보인다 */
export interface RomsSeries {
  lat: number;
  lon: number;
  distanceKm: number;
  points: { at: string; currentDirDeg: number | null; currentSpeedMs: number | null; waterTempC: number | null }[];
}

/** `/api/ocean/summary` — 사전 생성된 상황 요약. mock 이면 LLM 이 꺼져 있거나 실패한 것 */
export interface OceanSummary {
  headline: string;
  body: string;
  /** 요약이 근거로 삼은 값. 문장만 두면 "그 숫자 어디서 나왔냐"에 답할 수 없다 */
  facts: string[];
  generatedAt: string;
  model: string;
  mock: boolean;
  /** 이 문장이 선 기준 좌표 (2026-09-18). 옛 캐시에는 없다 */
  lat?: number | null;
  lon?: number | null;
  /**
   * 본선 좌표 기준인가. `false` 면 서버 기본 위치 기준이라
   * <b>문장 속 지점·거리가 이 배와 무관하다</b> — 화면이 밝혀야 한다
   */
  shipBased?: boolean;
}

interface ApiResponse<T> {
  success: boolean;
  message: string;
  data: T | null;
  /**
   * Pi 중계가 붙이는 값 (`ref/kiosk_시연.md` §6). EC2 직접 응답에는 없다.
   *
   * `fresh: false` 면 <b>인터넷이 끊겨 Pi 가 옛 값을 준 것</b>이다.
   * 🔴 화면에 반드시 드러내야 한다 — <b>3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은
   * 화면에서 똑같이 생겼다.</b>
   */
  fresh?: boolean;
  /** 이 값을 받은 시각(Unix 초) */
  cached_at?: number;
}

/* ── Pi 중계 신선도 ─────────────────────────────────────────
 *
 * 경로마다 따로 기록하고 <b>가장 비관적인 값</b>으로 합친다.
 *
 * "마지막 응답이 이긴다"로 두면 — 조류는 캐시인데 파고가 방금 들어온 순간 화면이
 * "실시간"이라고 말한다. 하나라도 옛 값이면 옛 값이라고 해야 한다(계획.md §9.10).
 *
 * ⚠ 필드가 없으면 기록하지 않는다. EC2 직접 호출·시연판이 그렇고, 그때는 `null`(모름)이다 —
 * `true`(실시간)로 단정하면 중계가 빠진 것을 아무도 모른다.
 */
interface Freshness { fresh: boolean | null; cachedAt: number | null }

/** 이보다 오래된 기록은 합산에서 뺀다. 폴링 60초의 두 배 — 한 주기를 건너뛰어도 남는다 */
const FRESH_WINDOW_MS = 120_000;

const freshSeen = new Map<string, { fresh: boolean; cachedAt: number | null; at: number }>();

function noteFreshness(path: string, body: ApiResponse<unknown>): void {
  if (typeof body.fresh !== 'boolean') return;   // 중계가 아닌 응답
  freshSeen.set(path, {
    fresh: body.fresh,
    cachedAt: typeof body.cached_at === 'number' ? body.cached_at : null,
    at: Date.now(),
  });
}

/** @return `fresh: null` 이면 중계 응답을 하나도 못 봤다 — 모른다는 뜻이지 실시간이 아니다 */
export function relayFreshness(now = Date.now()): Freshness {
  let fresh: boolean | null = null;
  let cachedAt: number | null = null;
  for (const [path, v] of freshSeen) {
    if (now - v.at > FRESH_WINDOW_MS) { freshSeen.delete(path); continue; }
    fresh = fresh === null ? v.fresh : fresh && v.fresh;          // 하나라도 false 면 false
    if (v.cachedAt != null) cachedAt = cachedAt == null ? v.cachedAt : Math.min(cachedAt, v.cachedAt);
  }
  return { fresh, cachedAt };
}

/**
 * 본선이 수집 해역 밖이라는 표식. **오류가 아니다** —
 * 서버가 해역 이동을 예약했고 다음 수집에 들어온다.
 *
 * 이걸 503 으로 받으면 배가 움직일 때마다 콘솔이 빨개지고,
 * 화면이 "장애"와 "이동 중"을 구분하지 못한다.
 */
const OUTSIDE_AREA = 'OUTSIDE_AREA';

/** 해역 밖인데 서버가 옮기지 않았다 — kiosk 키가 없거나 틀렸다. 기다려도 안 들어온다 */
const OUTSIDE_AREA_NOT_MOVED = 'OUTSIDE_AREA_NOT_MOVED';

/**
 * 해역 밖 표식 판독.
 *
 * @return moving 이동 예약됨(곧 들어온다) · notMoved 옮기지 않음(설정 문제) · null 해역 밖 아님
 */
export function outsideKind(message: string | undefined): 'moving' | 'notMoved' | null {
  if (message === OUTSIDE_AREA) return 'moving';
  if (message === OUTSIDE_AREA_NOT_MOVED) return 'notMoved';
  return null;
}

/** 해역 밖인데 옮겨지지 않았다. "해역 이동 중"으로 기다리지 않고 설정 문제로 드러낸다 */
export class AreaNotMovedError extends Error {
  constructor() {
    super('해역 이동 권한 없음 — VITE_KIOSK_KEY 확인');
    this.name = 'AreaNotMovedError';
  }
}

const env = import.meta.env as Record<string, string | undefined>;

/**
 * 수집 해역 이동 키 헤더 (api.md §1.1). 서버는 이 키가 맞을 때만 해역을 옮긴다.
 *
 * 이동이 걸린 조회(current · grid · series)에만 싣는다 — 커스텀 헤더는 CORS preflight 를 부르므로
 * 나머지(sources · summary · zones)는 단순 GET 으로 둔다.
 * 비밀이 아니라 선내 한정: 이 번들은 선내 PC localhost 에서만 서빙된다.
 *
 * @param key 기본은 VITE_KIOSK_KEY(.env.local). 비면 헤더를 싣지 않는다 — 빈 헤더로 preflight 만 부르지 않게
 */
/**
 * ~~해양 조회에는 더 쓰지 않는다~~(2026-09-17) — <b>가상 모드에서 다시 쓴다</b>(2026-09-18).
 * 실제 모드는 그대로 Pi 가 키를 낸다(키가 브라우저 번들에 들어가지 않는다, `ref/kiosk_시연.md` §0).
 * 가상은 Pi 가 없어 대신 낼 곳이 없으므로 이 헤더가 유일한 길이다 — `areaHeaders()` 가 가른다.
 * 비밀이 아니라 선내 한정이라는 전제는 바뀌지 않았다.
 */
export function kioskHeaders(key: string | undefined = env.VITE_KIOSK_KEY): Record<string, string> {
  return key ? { 'X-Floaq-Kiosk-Key': key } : {};
}

/**
 * 해양 조회를 **어디로 보낼 것인가** — 런타임 스위치 (2026-09-18).
 *
 * <p>실제 모드: `piUrl` → Pi 의 `OceanProxy`. 60초 캐시와 `fresh`·`cached_at` 을 얹어 주고
 * <b>kiosk 키도 Pi 가 낸다</b>(키가 브라우저 번들에 들어가지 않는다, `ref/kiosk_시연.md` §0).</p>
 *
 * <p>가상 모드: `cloudUrl` → EC2 직접. <b>가상은 정의상 Pi 가 없는 모드다</b> —
 * 그런데 해양 조회만 `piUrl` 을 타고 있어서, 선내망 밖에서는 수온·파고가 전부 "값 없음"이 됐다.
 * `vite.config.ts` 가 `mode === 'fixture'` 일 때만 `/pi/api/ocean` 을 EC2 로 우회시켰는데,
 * <b>가상/실제는 빌드 모드가 아니라 상단 칩으로 바꾸는 런타임 값</b>이라 `pnpm dev` 에서는 안 걸렸다.</p>
 *
 * <p>🔴 직접 부를 때는 <b>kiosk 키를 우리가 실어야 한다.</b> Pi 가 없으니 대신 낼 곳이 없다 —
 * 안 실으면 해역 밖 좌표에서 서버가 `OUTSIDE_AREA_NOT_MOVED` 를 주고 화면이
 * "이동 권한 없음 (kiosk 키 확인)" 으로 멈춘다. 실측(2026-09-18): 같은 좌표에
 * 키를 실으면 `OUTSIDE_AREA`(이동 시작)로 바뀐다.</p>
 *
 * <p>⚠ 한계: 이 경로에는 Pi 중계가 붙이는 `fresh`·`cached_at` 이 없다 —
 * `relayFresh` 가 `null`(모름)로 남아 "캐시 · 인터넷 끊김" 알약이 안 뜬다. 가상 모드에서는 맞는 동작이다.</p>
 */
let directToCloud = false;

export function setOceanDirect(on: boolean): void { directToCloud = on; }

/** 이번 조회의 주소. 가상이면 EC2, 실제면 Pi 중계 */
const oceanUrl = (path: string): string => (directToCloud ? cloudUrl(path) : piUrl(path));

/**
 * 수집 해역 이동이 걸린 조회(current · grid · series)에 실을 헤더.
 * <b>직접 부를 때만</b> 싣는다 — Pi 중계에는 Pi 가 자기 키를 넣고,
 * 여기서 또 실으면 커스텀 헤더 때문에 CORS preflight 만 늘어난다.
 */
const areaHeaders = (): Record<string, string> | undefined =>
  (directToCloud ? kioskHeaders() : undefined);

/** 공공데이터 조회 API 라 빨라야 정상이다. 늦으면 이번 폴링을 포기하고 다음 주기를 기다린다 */
const TIMEOUT_MS = 10_000;

/**
 * 좌표를 0.01° 격자에 물린다. **Pi 중계 캐시를 맞히려고 그런다** (2026-09-18).
 *
 * Pi 의 `OceanProxy` 는 쿼리스트링을 그대로 캐시 키로 쓴다(IoT `web/ocean.py _key`).
 * 본선 GPS 가 1Hz 로 흘러서 원시 float 를 보내면 키가 매번 달라지고,
 * **60초 캐시(`FRESH_SEC`)가 한 번도 안 맞아** 모든 조회가 EC2 왕복이 된다.
 * 2026-09-17 시험에서 해양 탭이 느렸던 원인이다.
 *
 * 0.01° 근거: ROMS 격자가 약 1/30°(0.033°)라 한 칸보다 촘촘하다 —
 * 반올림으로 다른 칸에 떨어지지 않는다. 위도 1.1km · 경도 0.9km(35°N) 오차이므로
 * 지점 소스의 `distanceKm` 이 그만큼 흔들리는데, 관측소 간격(수십 km)에 비하면 무시된다.
 */
const cell = (v: number): string => v.toFixed(2);

/**
 * @param at 본선 좌표. 주면 지점 소스(sea-obs · fishing-ground)를 그 좌표 반경으로 잘라 거리까지 재 준다 —
 *           서버는 전국 지점을 들고 있다(선박 여러 척). 없으면 서버 기본 위치 기준이라 거리가 이 배와 무관하다
 */
export async function fetchOceanSources(
  signal?: AbortSignal, at?: { lat: number; lon: number },
): Promise<OceanSource[]> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    // 커스텀 헤더를 싣지 않는다 — 단순 GET 이라 CORS preflight 가 없다
    const q = at ? `?lat=${cell(at.lat)}&lon=${cell(at.lon)}` : '';
    const res = await fetch(oceanUrl(`/api/ocean/sources${q}`), { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as ApiResponse<OceanSource[]>;
    noteFreshness('sources', body);
    if (!body.success || !Array.isArray(body.data)) throw new Error('응답 형식 오류');
    return body.data;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * @return 해역 밖이면 null. 수집 자체가 안 돌면 503 으로 던진다
 * @throws AreaNotMovedError 해역 밖인데 키가 없어 옮기지 않았을 때 — 본선 점 조회만 이걸 가른다(화면 문구의 근거)
 */
export async function fetchOceanCurrent(lat: number, lon: number, signal?: AbortSignal): Promise<RomsPoint | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    const q = `?lat=${cell(lat)}&lon=${cell(lon)}`;
    const res = await fetch(oceanUrl(`/api/ocean/current${q}`), { signal: ctrl.signal, headers: areaHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as ApiResponse<RomsPoint>;
    noteFreshness('current', body);
    const outside = outsideKind(body.message);
    if (outside === 'notMoved') throw new AreaNotMovedError();
    if (outside === 'moving') return null;
    if (!body.success || !body.data) throw new Error('응답 형식 오류');
    return body.data;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * @param at 예측 시각(ISO). 없으면 지금 이후 가장 이른 예측. 과거·범위 밖은 서버가 끝에 물린다
 * @return 해역 밖이면 null (옮기지 않은 경우 포함 — 이유는 current 가 가른다). 수집 자체가 안 돌면 503 으로 던진다
 */
export async function fetchOceanGrid(
  lat: number, lon: number, signal?: AbortSignal, rings = 1, at?: string,
): Promise<RomsGrid | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    const q = `?lat=${cell(lat)}&lon=${cell(lon)}&rings=${rings}`
      + (at ? `&at=${encodeURIComponent(at)}` : '');
    const res = await fetch(oceanUrl(`/api/ocean/grid${q}`), { signal: ctrl.signal, headers: areaHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as ApiResponse<RomsGrid>;
    noteFreshness('grid', body);
    if (outsideKind(body.message)) return null;
    if (!body.success || !body.data) throw new Error('응답 형식 오류');
    return body.data;
  } finally {
    clearTimeout(timer);
  }
}

/** @return 해역 밖이면 null */
export async function fetchOceanSeries(
  lat: number, lon: number, hours = 48, signal?: AbortSignal,
): Promise<RomsSeries | null> {
  const q = `?lat=${cell(lat)}&lon=${cell(lon)}&hours=${hours}`;
  return getJson<RomsSeries>(`/api/ocean/series${q}`, signal, areaHeaders());
}

/**
 * 사전 생성된 요약. **조회가 LLM 을 부르지 않는다** — 서버가 30분에 1회만 만든다.
 * 그래서 폴링 주기(60초)마다 불러도 크레딧이 나가지 않는다.
 *
 * @param at 본선 좌표. 주면 그 자리 기준 문장을 받고, 서버의 다음 생성 기준도 그 자리가 된다.
 *           없으면 서버 기본 위치 기준이라 문장 속 거리가 이 배와 무관하다
 */
export async function fetchOceanSummary(
  signal?: AbortSignal, at?: { lat: number; lon: number },
): Promise<OceanSummary | null> {
  // 0.1°(약 11km) 로 뭉갠다. 원시 GPS 를 그대로 실으면 1Hz 로 흔들려 Pi 중계 캐시 키가
  // 매번 달라지고(쿼리스트링이 키다) 60초 캐시가 한 번도 안 맞는다.
  // 요약은 어차피 15km 안이면 같은 문장이라(서버 SAME_SEA_KM) 이 정도로 뭉개도 내용이 안 바뀐다 —
  // 지점 거리를 재는 /sources 와 달리 여기서는 정밀도가 필요 없다
  const q = at ? `?lat=${at.lat.toFixed(1)}&lon=${at.lon.toFixed(1)}` : '';
  return getJson<OceanSummary>(`/api/ocean/summary${q}`, signal);
}

/**
 * 이 번들이 kiosk 키를 들고 있나 — <b>즉시 재생성 버튼을 띄울지</b>가 이 값으로 갈린다.
 *
 * 없으면 서버가 `NO_KEY` 로 거절한다. 눌러도 안 되는 버튼을 띄우지 않는다.
 * 공개 시연판(`VITE_DEMO=1`)은 키를 안 싣는 것이 규칙이라(vite.config) 저절로 숨는다.
 */
export const hasKioskKey = (): boolean => !!env.VITE_KIOSK_KEY;

/**
 * 재생성 버튼을 띄울 수 있나 — <b>키뿐 아니라 경로가 있어야 한다</b> (2026-09-20).
 *
 * <p>🔴 <b>Pi 중계에는 이 경로가 없다.</b> Pi 는 `GET /api/ocean/{path}` 하나뿐이고
 * `{path}` 가 <b>한 세그먼트</b>다(IoT `web/ocean.py` ALLOWED 8종). `summary/refresh` 는
 * 두 세그먼트에 POST 라, 실제 모드에서 누르면 405 도 아닌 <b>404</b> 였다 —
 * 가상 모드에서만 동작해 온 버튼이다.</p>
 *
 * <p>EC2 로 우회할 수도 없다: 선내판은 Pi 가 내려주므로 EC2 직결이 교차 오리진이고,
 * nginx 의 `$cors_origin` 허용 목록이 <b>`localhost:5174` 둘뿐</b>이다
 * (`infra/nginx/nginx.conf`). 배마다 IP 가 다른 Pi 오리진을 그 목록에 넣을 수도 없다.</p>
 *
 * <p>그래서 <b>가상 모드에서만 띄운다.</b> 이 파일이 이미 세워 둔 규칙 그대로다 —
 * <i>눌러도 안 되는 버튼을 띄우지 않는다</i>. 실제 모드에서도 쓰려면 Pi 중계에
 * POST 경로가 필요하다 — `미정`⚠️ TODO(IoT).</p>
 */
export const canRefreshSummary = (): boolean => hasKioskKey() && directToCloud;

export interface SummaryRefresh {
  summary: OceanSummary;
  /** null 이면 진짜 LLM 응답. 아니면 목으로 물러선 이유 (`NO_KEY` 포함) */
  note: string | null;
}

/**
 * 요약을 **지금** 다시 만든다 (2026-09-18 요청).
 *
 * <p>평소 경로는 조회가 LLM 을 부르지 않는다 — 실제 호출은 서버의 10분 틱이고 그 위에
 * 30분 상한이 있다. 그래서 키를 새로 넣어도 최대 30분을 기다려야 확인이 됐다.</p>
 *
 * <p>🔴 <b>누를 때마다 크레딧이 나간다.</b> 폴링에 절대 붙이지 않는다 — 사람이 누르는 버튼만 부른다.</p>
 *
 * <p>좌표는 `GET /summary` 와 <b>같은 자리수(0.1°)로 보낸다.</b> 다르게 보내면 서버가 쓴 캐시를
 * 그다음 폴링이 못 맞혀서, 버튼은 성공했는데 화면은 다시 목으로 돌아간다.</p>
 */
export async function refreshOceanSummary(
  at: { lat: number; lon: number }, signal?: AbortSignal,
): Promise<SummaryRefresh> {
  const ctrl = new AbortController();
  // LLM 왕복이라 조회보다 길게 잡는다. 실측 1.7초(2026-09-18)지만 게이트웨이가 밀릴 때가 있다
  const timer = setTimeout(() => ctrl.abort(), 25_000);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    const q = `?lat=${at.lat.toFixed(1)}&lon=${at.lon.toFixed(1)}`;
    // 🔴 `oceanUrl` 이 아니라 **`cloudUrl` 로 못 박는다.** 이 경로는 EC2 에만 있다 —
    //    Pi 중계로 보내면 404 다(`canRefreshSummary` 주석). 목적지를 모드에 맡기면
    //    "왜 가상에서만 되지"를 다시 추적하게 된다
    const res = await fetch(cloudUrl(`/api/ocean/summary/refresh${q}`), {
      method: 'POST', signal: ctrl.signal, headers: kioskHeaders(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as ApiResponse<OceanSummary>;
    if (!body.success || !body.data) throw new Error('응답 형식 오류');
    return { summary: body.data, note: body.message === 'OK' ? null : body.message };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 가장 가까운 조석예보 지점의 조위 곡선.
 *
 * 수집을 부르지 않는다 — 조석예보는 전국을 하루 한 번 받아 둔다(ROMS 타일과 다르다).
 * 그래서 kiosk 키도 싣지 않는다.
 *
 * @return 반경(기본 60km) 안에 지점이 없으면 null
 */
export async function fetchOceanTide(
  lat: number, lon: number, hours = 48, signal?: AbortSignal,
): Promise<TideSeries | null> {
  const q = `?lat=${cell(lat)}&lon=${cell(lon)}&hours=${hours}`;
  return getJson<TideSeries>(`/api/ocean/tide${q}`, signal);
}

/** 반경 안에 조석예보 지점이 없다. 오류가 아니라 "없음" — 먼바다에서는 늘 그렇다 */
const NO_STATION = 'NO_STATION';

/** 공통 GET. "값 없음" 표식(해역 밖 · 근처 지점 없음)은 오류가 아니라 null 이다 */
async function getJson<T>(path: string, signal?: AbortSignal, headers?: Record<string, string>): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    const res = await fetch(oceanUrl(path), { signal: ctrl.signal, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as ApiResponse<T>;
    noteFreshness(path.split('?')[0] ?? path, body);
    if (outsideKind(body.message) || body.message === NO_STATION) return null;
    if (!body.success || !body.data) throw new Error('응답 형식 오류');
    return body.data;
  } finally {
    clearTimeout(timer);
  }
}

export const bySource = (list: OceanSource[]) =>
  Object.fromEntries(list.map((s) => [s.source, s])) as Record<string, OceanSource | undefined>;

/** 특보현황 문장이 "없음"인가. 실응답은 "없 음" 처럼 글자 사이 공백이 온다 */
export const isNoneText = (text: string | null | undefined) =>
  !text || text.replace(/\s/g, '') === '없음';

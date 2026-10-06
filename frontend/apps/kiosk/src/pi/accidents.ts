/**
 * 지난 사고 조회. **Pi 의 FastAPI(8000)** 에서 받는다.
 *
 * 🔴 **cloud 가 아니다.** 배에 인터넷이 없어도 지난 사고는 봐야 하고, 사진은
 *    Pi 에만 있다 — EC2 는 R2 오브젝트 키만 알고 키오스크는 R2 에 직접 못 붙는다.
 *    `pi/files.ts` 가 사진에 대해 내린 것과 같은 판단이다.
 *
 * ⚠ **`pi/files.ts` 와 역할이 다르다.** 저쪽은 사고 **하나의 사진 목록**이고
 *   여기는 **사고 목록과 그 요약**이다. 사진을 여러 장 그릴 일이 생기면 저쪽을 쓴다.
 *
 * ⚠ **봉투가 없다.** cloud 는 `{success, message, data}` 로 싸지만 Pi 는 평문
 *   JSON 을 그대로 준다. `cloud/ocean.ts` 의 `getJson` 을 그대로 가져다 쓰면
 *   `body.data` 가 undefined 라 전부 "응답 형식 오류" 가 된다.
 *
 * ⚠ **wire 는 snake_case, 앱은 camelCase.** MQTT 와 같은 규칙이라 변환을 이
 *   파일 한 곳에 둔다 (`pi/decode.ts` 와 같은 판단).
 */

import { piUrl } from '@floaq/shared/origins';

/** 조회가 이보다 오래 걸리면 화면이 멈춘 것처럼 보인다. 선내 무선이 느릴 수 있어 넉넉히. */
const TIMEOUT_MS = 8_000;

/** 목록 한 쪽. Pi 가 100 에서 자른다. */
export const PAGE_SIZE = 20;

export type AccidentStatus =
  | 'DETECT' | 'WAIT' | 'REPORT' | 'CANCEL' | 'CLOSE' | 'RESCUE';

/** 목록 한 줄. 상세와 공유하는 본문이다. */
export interface AccidentRow {
  accidentId: string;
  status: AccidentStatus;
  accidentType: string;
  triggerSource: string;
  reportType: string;
  reportDsc: number | null;
  lat: number | null;
  lon: number | null;
  /** Unix 초. **문자열이 아니다** — 화면이 자기 시계로 경과를 센다 */
  createdAt: number;
  rescuedAt: number | null;
  closedAt: number | null;
}

export interface AccidentPage {
  total: number;
  limit: number;
  offset: number;
  rows: AccidentRow[];
}

export interface LaunchInfo {
  result: string;
  failReason: string | null;
  targetLat: number | null;
  targetLon: number | null;
  horizontalAngle: number | null;
  verticalAngle: number | null;
  confidenceScore: number | null;
  createdAt: number;
}

export interface ReportInfo {
  channel: string;
  status: string;
  triggerKind: string;
  sentCount: number;
  firstSentAt: number | null;
  lastSentAt: number | null;
  ackedAt: number | null;
  ackedBy: string | null;
  failReason: string | null;
}

export interface CommLoss {
  detectedAt: number;
  recoveredAt: number | null;
  lastLat: number;
  lastLon: number;
  thresholdSec: number;
}

export interface AccidentDetail extends AccidentRow {
  launch: LaunchInfo | null;
  reports: ReportInfo[];
  commLosses: CommLoss[];
  fileCount: number;
  /** Pi 의 상대 경로. `piUrl()` 로 감싸야 실제 주소가 된다 */
  snapshotPath: string | null;
}

export interface TimelineEntry {
  status: AccidentStatus;
  prevStatus: AccidentStatus | null;
  reason: string;
  causedBy: string | null;
  createdAt: number;
}

export interface BuoyPoint {
  seq: number;
  lat: number;
  lon: number;
  isPressed: boolean;
  rssi: number | null;
  measuredAt: number;
}

/**
 * Pi 에서 JSON 하나. 실패하면 던진다 — 호출하는 훅이 잡아서 화면 문구로 바꾼다.
 *
 * ⚠ `AbortController` 를 두 겹으로 쓴다. 바깥 signal 은 화면이 사라질 때,
 *   안쪽 타이머는 Pi 가 답이 없을 때다. 하나만 두면 다른 쪽에서 영원히 기다린다.
 */
async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  try {
    const res = await fetch(piUrl(path), { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/* ── wire → 앱 ────────────────────────────────────────────────────── */

type Wire = Record<string, unknown>;

const row = (d: Wire): AccidentRow => ({
  accidentId: String(d.accident_id),
  status: d.status as AccidentStatus,
  accidentType: String(d.accident_type),
  triggerSource: String(d.trigger_source),
  reportType: String(d.report_type),
  reportDsc: (d.report_dsc as number | null) ?? null,
  lat: (d.lat as number | null) ?? null,
  lon: (d.lon as number | null) ?? null,
  createdAt: Number(d.created_at),
  rescuedAt: (d.rescued_at as number | null) ?? null,
  closedAt: (d.closed_at as number | null) ?? null,
});

export async function fetchAccidents(
  { limit = PAGE_SIZE, offset = 0, status }: {
    limit?: number; offset?: number; status?: AccidentStatus | null;
  } = {},
  signal?: AbortSignal,
): Promise<AccidentPage> {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) q.set('status', status);
  const d = await get<Wire>(`/api/accidents?${q}`, signal);
  return {
    total: Number(d.total ?? 0),
    limit: Number(d.limit ?? limit),
    offset: Number(d.offset ?? offset),
    rows: ((d.accidents as Wire[]) ?? []).map(row),
  };
}

export async function fetchAccident(
  id: string, signal?: AbortSignal,
): Promise<AccidentDetail> {
  const d = await get<Wire>(`/api/accidents/${encodeURIComponent(id)}`, signal);
  const l = d.launch as Wire | null;
  return {
    ...row(d),
    launch: !l ? null : {
      result: String(l.result),
      failReason: (l.fail_reason as string | null) ?? null,
      targetLat: (l.target_lat as number | null) ?? null,
      targetLon: (l.target_lon as number | null) ?? null,
      horizontalAngle: (l.horizontal_angle as number | null) ?? null,
      verticalAngle: (l.vertical_angle as number | null) ?? null,
      confidenceScore: (l.confidence_score as number | null) ?? null,
      createdAt: Number(l.created_at),
    },
    reports: ((d.reports as Wire[]) ?? []).map((r) => ({
      channel: String(r.channel),
      status: String(r.status),
      triggerKind: String(r.trigger_kind),
      sentCount: Number(r.sent_count ?? 0),
      firstSentAt: (r.first_sent_at as number | null) ?? null,
      lastSentAt: (r.last_sent_at as number | null) ?? null,
      ackedAt: (r.acked_at as number | null) ?? null,
      ackedBy: (r.acked_by as string | null) ?? null,
      failReason: (r.fail_reason as string | null) ?? null,
    })),
    commLosses: ((d.comm_losses as Wire[]) ?? []).map((c) => ({
      detectedAt: Number(c.detected_at),
      recoveredAt: (c.recovered_at as number | null) ?? null,
      lastLat: Number(c.last_lat),
      lastLon: Number(c.last_lon),
      thresholdSec: Number(c.threshold_sec),
    })),
    fileCount: Number(d.file_count ?? 0),
    snapshotPath: (d.snapshot_url as string | null) ?? null,
  };
}

export async function fetchTimeline(
  id: string, signal?: AbortSignal,
): Promise<TimelineEntry[]> {
  const d = await get<Wire>(
    `/api/accidents/${encodeURIComponent(id)}/timeline`, signal);
  return ((d.entries as Wire[]) ?? []).map((e) => ({
    status: e.status as AccidentStatus,
    prevStatus: (e.prev_status as AccidentStatus | null) ?? null,
    reason: String(e.reason),
    causedBy: (e.caused_by as string | null) ?? null,
    createdAt: Number(e.created_at),
  }));
}

/**
 * 부표 궤적.
 *
 * ⚠ 1Hz 라 10분이면 600점이다. `every` 로 솎아 받는다 — 지도에 600점을 다 찍을
 *   이유가 없고, 좁은 선내 무선에서 그만큼 늦게 뜬다. Pi 가 솎아도 **처음과 끝은
 *   남긴다** (투하 지점과 마지막 수신 위치는 수색에 직접 쓰는 값이다).
 */
export async function fetchBuoyTrack(
  id: string, every = 5, signal?: AbortSignal,
): Promise<BuoyPoint[]> {
  const d = await get<Wire>(
    `/api/accidents/${encodeURIComponent(id)}/buoy-positions?every=${every}`, signal);
  return ((d.positions as Wire[]) ?? []).map((p) => ({
    seq: Number(p.seq),
    lat: Number(p.lat),
    lon: Number(p.lon),
    isPressed: Boolean(p.is_pressed),
    rssi: (p.rssi as number | null) ?? null,
    measuredAt: Number(p.measured_at),
  }));
}

/**
 * 대표 사진 주소.
 *
 * ⚠ 파일 **목록**이 필요하면 `pi/files.ts` 의 `listAccidentFiles` 를 쓴다.
 *   여기 있는 것은 상세가 대표 한 장만 그릴 때 쓰는 지름길이고, 경로는 Pi 가
 *   준 값을 그대로 쓴다 — 순번 자릿수(PUT 은 4자리, 타르볼은 5자리)가 경로마다
 *   달라서 이름을 직접 만들면 틀린다.
 */
export const snapshotSrc = (path: string): string => piUrl(path);

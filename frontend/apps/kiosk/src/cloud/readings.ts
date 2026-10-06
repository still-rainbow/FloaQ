// 배럴(@floaq/shared)은 MapView→leaflet 을 끌어와 node 검증(ocean-check.mjs)에서 window 로 죽는다
import { formatAge } from '@floaq/shared/staleness';
import type { Category, Reading } from '../types';
import {
  bySource, isNoneText,
  type FishingGroundPayload, type ForecastPayload, type JellyfishPayload, type OceanSource,
  type RedTidePayload, type RomsPayload, type RomsPoint, type SeaObsPayload, type SeaObsStation,
  type ShipIndexPayload, type ShipIndexSlot, type WarningPayload,
} from './ocean';

/**
 * 수집 결과 → 화면 행. 순수 함수 — `test/ocean-check.mjs` 가 이 파일만 검증한다.
 *
 * 카테고리는 데이터 출처가 아니라 어민이 내리는 판단으로 나눈다 (§9.18).
 * 값이 없는 행은 "값 없음"으로 그린다. 행을 빼면 사용자가 "원래 없는 항목"으로 읽는다.
 */

export type CloudCatKey = 'safe' | 'fish' | 'nav';

/**
 * stale 기준 = 수집 주기의 3배. 연속 2회를 놓친 것이다.
 * 1배면 정상 지연에도 흐려지고, 임계를 서버가 정하면 근거 없는 숫자가 된다 — 화면 판단이다.
 */
const STALE_FACTOR = 3;

const KNOTS_PER_MS = 1.943844;

const KST = 'Asia/Seoul';

/** 운항지수 구간 최대 길이. 06·12시 두 구간만 있는 날은 12시간 — 넘으면 폴링이 멈춘 것 */
const SHIP_SLOT_MAX_MS = 12 * 3600_000;

/** 특보 해역 나열 상한. 전국 발효 시 수십 곳이라 행이 넘친다 */
const MAX_AREAS = 2;

/* ── 시각 문구 ─────────────────────────────────────────── */

const hourKst = (iso: string) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', hour12: false, timeZone: KST });

const dayKst = (iso: string) =>
  new Date(iso).toLocaleDateString('ko-KR', { day: 'numeric', timeZone: KST });

const dayHourKst = (iso: string) => `${dayKst(iso)} ${hourKst(iso)}`;

/** kind 별로 시각을 다르게 부른다. 예보에 "N분 전"을 붙이면 방금 받은 값이 낡아 보인다 */
function ageText(src: OceanSource, now: Date, suffix = ''): string {
  const failed = src.resultCode !== '00' ? ' · 갱신 실패' : '';
  const tail = suffix ? ` · ${suffix}` : '';
  if (!src.observedAt) return `값 없음${failed}`;
  switch (src.kind) {
    case 'FORECAST': {
      const validAt = (src.payload as RomsPayload | null)?.validAt;
      const base = `기준 ${dayHourKst(src.observedAt)}`;
      return validAt ? `${hourKst(validAt)} 예측값 · ${base}${tail}${failed}` : `예측 없음 · ${base}${failed}`;
    }
    case 'ADVISORY':
      return `${formatAge(src.observedAt, now)} 발표${tail}${failed}`;
    default:
      return `${formatAge(src.observedAt, now)} 관측${tail}${failed}`;
  }
}

function isStale(src: OceanSource): boolean {
  if (src.kind === 'FORECAST') return !(src.payload as RomsPayload | null)?.validAt;
  if (src.ageSec == null) return true;
  return src.ageSec > src.intervalSec * STALE_FACTOR;
}

/* ── 값 포맷 ───────────────────────────────────────────── */

const fmt = (v: number | null | undefined, dec = 1) =>
  v == null || Number.isNaN(v) ? null : v.toFixed(dec);

const COMPASS_16 = ['북', '북북동', '북동', '동북동', '동', '동남동', '남동', '남남동',
  '남', '남남서', '남서', '서남서', '서', '서북서', '북서', '북북서'];

/** deg → 16방위 한글. 조류예보 API 가 이 문자열로 오므로 표기도 맞춘다 */
export const compass16 = (deg: number) => COMPASS_16[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];

const none = (label: string, age: string, metric?: Reading['metric']): Reading =>
  ({ label, value: '값 없음', age, stale: true, ...(metric ? { metric } : {}) });

/** 요소별로 값이 나오는 지점이 다르다(§6). 필요한 요소가 있는 지점 중 가장 가까운 곳 */
const nearestWith = (stations: SeaObsStation[], has: (s: SeaObsStation) => boolean) =>
  stations.filter(has).sort((a, b) => a.distanceKm - b.distanceKm)[0] ?? null;

/** 여러 줄 원문을 행 한 줄로 */
const oneLine = (text: string, max: number) => {
  const line = text.replace(/\s+/g, ' ').trim();
  return line.length > max ? `${line.slice(0, max)}…` : line;
};

/** "부산앞바다, 거제시동부앞바다 외 3곳" */
const areaList = (names: string[]) => {
  const unique = [...new Set(names)];
  const shown = unique.slice(0, MAX_AREAS).join(', ');
  return unique.length > MAX_AREAS ? `${shown} 외 ${unique.length - MAX_AREAS}곳` : shown;
};

/** 운항지수 등급 → 알약. 보통(3)은 알약 없이 문구만 — 색으로 말할 상태가 아니다 */
const SHIP_PILL: Record<number, Reading['pill']> = { 1: 'ok', 2: 'ok', 4: 'warn', 5: 'alert' };

/* ── 카테고리 ──────────────────────────────────────────── */

function safe(all: Record<string, OceanSource | undefined>, now: Date): Category {
  const warn = all['weather-warning'] as OceanSource<WarningPayload> | undefined;
  const obs = all['sea-obs'] as OceanSource<SeaObsPayload> | undefined;
  const rows: Reading[] = [];

  if (warn?.payload) {
    const active = warn.payload.activeMarineWarnings ?? [];
    const areas = (warn.payload.activeAreas ?? []).map((a) => a.areaName);
    const focus = warn.payload.focus;
    if (focus) {
      // 조업 해역(설정 특보구역 + 상위 구역) 기준. 본선 좌표 판정이 아니다 — 경계 데이터가 없다
      const hits = focus.activeMarineWarnings ?? [];
      const national = new Set(areas).size;
      const tail = [
        `기상청 · 조업 해역 ${(focus.names ?? []).join('·')}`,
        focus.hierarchy ? null : '상위 구역 미반영',
        national ? `전국 ${national}곳 발효` : null,
      ].filter(Boolean).join(' · ');
      rows.push({
        label: '해상 특보',
        value: hits.length ? hits.join(' · ') : '없음',
        pill: hits.length ? 'alert' : 'ok',
        age: ageText(warn, now, tail),
        stale: isStale(warn),
      });
    } else {
      rows.push({
        label: '해상 특보',
        value: active.length ? active.join(' · ') : '없음',
        pill: active.length ? 'alert' : 'ok',
        // 해역은 전국 목록이다. 조업 해역 설정이 없으면 판정하지 않는다 — 숨기지 않는다
        age: ageText(warn, now, areas.length ? `기상청 · ${areaList(areas)} · 본선 구역 미판정` : '기상청'),
        stale: isStale(warn),
      });
    }

    const status = warn.payload.status;
    const pre = status?.preliminary;
    rows.push(status
      ? { label: '예비특보', value: isNoneText(pre) ? '없음' : '있음', pill: isNoneText(pre) ? 'ok' : 'warn',
          age: isNoneText(pre) ? ageText(warn, now, '기상청 특보현황') : oneLine(pre!, 60), stale: isStale(warn) }
      // 옛 캐시이거나 현황 호출이 실패했다. "없음"으로 그리면 거짓이 된다
      : none('예비특보', ageText(warn, now, '특보현황 미수신')));
  } else {
    rows.push(none('해상 특보', warn ? ageText(warn, now) : '미수신'));
    rows.push(none('예비특보', warn ? ageText(warn, now) : '미수신'));
  }

  const stations = obs?.payload?.stations ?? [];
  const wave = nearestWith(stations, (s) => s.waveHeightM != null);
  rows.push(wave && obs
    ? { label: '유의파고', value: fmt(wave.waveHeightM)!, unit: 'm', metric: 'wave',
        age: ageText(obs, now, `${wave.name} ${wave.distanceKm}km`), stale: isStale(obs) }
    : none('유의파고', obs ? ageText(obs, now) : '미수신', 'wave'));

  const wind = nearestWith(stations, (s) => s.windSpeedMs != null);
  rows.push(wind && obs
    ? { label: '풍속 · 풍향', value: fmt(wind.windSpeedMs)!, unit: 'm/s', metric: 'wind',
        // 돌풍은 평균 풍속보다 소형선 전복에 직결된다. 같은 지점 값만 붙인다 — 다른 지점 돌풍을 섞으면 출처가 흐려진다
        age: ageText(obs, now, [
          wind.windDirDeg != null ? `${compass16(wind.windDirDeg)} ${Math.round(wind.windDirDeg)}°` : null,
          wind.windGustMs != null ? `돌풍 ${fmt(wind.windGustMs)}m/s` : null,
          `${wind.name} ${wind.distanceKm}km`,
        ].filter(Boolean).join(' · ')),
        stale: isStale(obs) }
    : none('풍속 · 풍향', obs ? ageText(obs, now) : '미수신', 'wind'));

  return { title: '안전 — 나가도 되나?', src: '기상청', rows };
}

function fish(all: Record<string, OceanSource | undefined>, now: Date): Category {
  const fg = all['fishing-ground'] as OceanSource<FishingGroundPayload> | undefined;
  const red = all['red-tide'] as OceanSource<RedTidePayload> | undefined;
  const jelly = all['jellyfish'] as OceanSource<JellyfishPayload> | undefined;
  const rows: Reading[] = [];

  const water = waterTemp(all, undefined);
  if (water) {
    rows.push({ label: '표층 수온', value: fmt(water.c)!, unit: '°C', metric: 'temp',
      age: ageText(water.src, now, water.where), stale: isStale(water.src) });
  } else rows.push(none('표층 수온', fg ? ageText(fg, now) : '미수신', 'temp'));

  // '저체온 한계' 를 조업 표에서 뺐다 (2026-09-18 요청). 조업 판단에 쓰는 값이 아니다 —
  // 익수 경보(AlertLayer)와 해양 종합 화면에는 그대로 남는다. 필요한 자리는 그쪽이다.

  if (red?.payload) {
    const p = red.payload;
    const breaking = p.breaking?.trim();
    const seen = p.organisms.some((o) => (o.maxDensity ?? 0) > 0);
    const areas = [...new Set(p.organisms.map((o) => o.area).filter(Boolean))].join(', ');
    rows.push({
      label: '적조',
      value: breaking ? '특보' : seen ? '출현' : '없음',
      pill: breaking ? 'warn' : seen ? 'warn' : 'ok',
      // 조사해역이 텍스트라 지도에 못 그린다. 문구로만 보여준다
      // 지도 지표가 아니다 — 누르는 줄이 아니라 읽는 줄이다 (2026-09-18)
      age: ageText(red, now, areas || '수과원'), stale: isStale(red),
    });
  } else rows.push(none('적조', red ? ageText(red, now) : '미수신'));

  rows.push(jelly?.payload
    // 설문 응답률이라 판단 근거가 아니다. 제공기관 문구를 그대로 붙인다
    ? { label: '해파리', value: '주간보고', age: ageText(jelly, now, '설문 응답률 · 판단 근거 아님'), stale: true }
    : none('해파리', jelly ? ageText(jelly, now) : '미수신'));

  return { title: '조업 — 어디로 갈까?', src: '수과원 · 기상청', rows };
}

/** 30분 뒤 표류 반경으로 환산해 보여준다. m/s 산포는 어민에게 감이 없다 */
const DRIFT_HORIZON_SEC = 1800;

/** 조업 권역에서 지금 구간 바로 뒤 구간. 권역 코드가 안 맞으면 추정하지 않는다 */
function nextShipSlot(p: ShipIndexPayload, c: ShipIndexSlot): ShipIndexSlot | null {
  const area = p.areas?.find((a) => a.code != null && a.code === p.focusCode);
  const at = new Date(c.at).getTime();
  return area?.slots
    .filter((s) => new Date(s.at).getTime() > at)
    .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())[0] ?? null;
}

/** 등급 숫자가 클수록 나쁘다(1 매우좋음 ~ 5 매우나쁨). 모르면 말하지 않는다 */
const trendWord = (c: ShipIndexSlot, n: ShipIndexSlot) =>
  c.level == null || n.level == null || c.level === n.level ? '' : n.level > c.level ? '(악화)' : '(호전)';

/**
 * 상단바가 쓰는 운항지수 한 덩어리 (2026-09-18).
 *
 * <p>`shipRow` 와 같은 값을 보지만 모양이 다르다 — 표의 한 줄이 아니라
 * <b>멀리서 색으로 읽는 한 단어</b>다. 둘이 다른 값을 말하면 안 되므로 출처를 같은 곳으로 묶는다.</p>
 *
 * <p>등급은 **KHOA 것을 그대로 쓴다**(1 매우좋음 ~ 5 매우나쁨). 우리가 임계를 만들지 않는다 —
 * 만들면 "왜 이 값이 노랑인가"에 근거가 없다.</p>
 */
export interface VoyageNow {
  /** KHOA 문구 그대로 — 매우좋음 · 좋음 · 보통 · 나쁨 · 매우나쁨 */
  score: string;
  /** 1~5. 클수록 나쁘다. 없으면 색을 칠하지 않는다 */
  level: number | null;
  /** 어느 권역 값인가. 본선 좌표 판정이 아니라 설정한 조업 권역이다 */
  areaName: string | null;
  /** 새벽·오전·오후·밤 */
  slot: string | null;
}

export function shipIndexNow(all: Record<string, OceanSource | undefined>): VoyageNow | null {
  const ship = all['ship-index'] as OceanSource<ShipIndexPayload> | undefined;
  const c = ship?.payload?.current;
  if (!c?.score) return null;
  return {
    score: c.score,
    level: c.level ?? null,
    areaName: ship?.payload?.focusName ?? null,
    slot: c.slot ?? null,
  };
}

/**
 * KHOA 선박운항지수 — 설정된 조업 권역의 지금 구간.
 * 권역 평균 참고 지수라 출항 판정 근거가 아니다. 문구에 남긴다.
 */
function shipRow(all: Record<string, OceanSource | undefined>, now: Date): Reading {
  const ship = all['ship-index'] as OceanSource<ShipIndexPayload> | undefined;
  const p = ship?.payload;
  const c = p?.current;
  if (!ship || !p || !c) return none('운항지수', ship ? ageText(ship, now) : '미수신');

  const failed = ship.resultCode !== '00' ? ' · 갱신 실패' : '';
  const detail = [
    c.waveHeightM != null ? `파고 ${fmt(c.waveHeightM)}m` : null,
    c.windSpeedMs != null ? `풍속 ${fmt(c.windSpeedMs)}m/s` : null,
  ].filter(Boolean).join(' · ');
  const next = nextShipSlot(p, c);
  const trend = next ? ` · 다음 ${dayKst(next.at)} ${next.slot ?? ''} ${next.score ?? '값 없음'}${trendWord(c, next)}` : '';
  // 지금은 괜찮아도 다음 구간이 나쁨 이상이면 미리 노랑. 등급은 KHOA 것 — 우리가 임계를 만들지 않는다
  const worsening = next?.level != null && next.level >= 4 && (c.level ?? 0) < 4;
  const pill = worsening ? 'warn' : c.level != null ? SHIP_PILL[c.level] : undefined;
  return {
    label: '운항지수',
    value: c.score ?? '값 없음',
    ...(pill ? { pill } : {}),
    age: `${p.focusName ?? '권역'} ${dayKst(c.at)} ${c.slot ?? ''}${detail ? ` · ${detail}` : ''}${trend} · KHOA 참고지수${failed}`,
    stale: now.getTime() - new Date(c.at).getTime() > SHIP_SLOT_MAX_MS,
  };
}

/**
 * KHOA 조석예보 — 가장 가까운 지점의 지금 조위 (2026-09-16).
 *
 * 지점이 전국 166곳(연안)뿐이라 먼바다에서는 반경 안에 없다. 그때도 행은 남긴다 —
 * 빼면 "원래 없는 항목"으로 읽힌다.
 *
 * 조류예보(current-forecast)는 행으로 내지 않는다. 항해 탭 유속은 ROMS 격자가 답하고 있고,
 * 두 유속을 나란히 두면 "어느 쪽이 맞냐"가 화면의 질문이 된다 (결정 2026-09-16).
 */
function tideRow(all: Record<string, OceanSource | undefined>, now: Date): Reading {
  const tide = all['tide-forecast'] as OceanSource<ForecastPayload> | undefined;
  // payload.stations 는 서버가 조회 좌표로 잘라 가까운 순으로 준다(StationNear)
  const near = tide?.payload?.stations?.find((s) => s.tideLevelM != null);
  if (!tide || !near?.tideLevelM) return none('조위', tide ? ageText(tide, now) : '미수신');

  const failed = tide.resultCode !== '00' ? ' · 갱신 실패' : '';
  return {
    label: '조위',
    value: fmt(near.tideLevelM, 2)!,
    unit: 'm',
    // 만(灣)마다 만조 시각이 다르다. 어느 지점 값인지 숨기지 않는다
    age: `${hourKst(near.predcDt)} 예보 · ${near.name} ${near.distanceKm}km · KHOA${failed}`,
    // 예보 시각이 지났으면 폴링이 멈춘 것이다(오프라인). 값은 남기고 흐리게
    stale: new Date(near.predcDt).getTime() < now.getTime(),
  };
}

function nav(all: Record<string, OceanSource | undefined>, now: Date, current: RomsPoint | null | undefined): Category {
  const roms = all['roms'] as OceanSource<RomsPayload> | undefined;
  const rows: Reading[] = [];
  const p = roms?.payload;

  // 본선 위치 기준 격자가 있으면 그것이 우선이다. 해역 대표값(bbox 중심)은 물러선다
  if (current && current.currentSpeedMs != null) {
    const kn = (current.currentSpeedMs * KNOTS_PER_MS).toFixed(1);
    const dir = current.currentDirDeg != null
      ? `${compass16(current.currentDirDeg)} ${Math.round(current.currentDirDeg)}°` : '방위 없음';
    // 예측 시각이 지났으면 폴링이 멈춘 것이다(오프라인). 값은 남기고 흐리게
    const stale = new Date(current.predcDt).getTime() < now.getTime();
    rows.push({ label: '표층 유속 예측', value: fmt(current.currentSpeedMs, 2)!, unit: 'm/s', metric: 'tide',
      age: `${hourKst(current.predcDt)} 예측값 · ${kn}kn · ${dir} · 본선 기준 격자 ${current.distanceKm}km`, stale });
    if (current.neighborSpreadMs != null) {
      // 격자 3km 옆이 얼마나 다른가. 연안 경계에서 10배 갈린다(2026-09-13 실측) — 점이 아니라 반경으로 읽어야 한다
      const driftM = Math.round(current.neighborSpreadMs * DRIFT_HORIZON_SEC);
      rows.push({ label: '유속 불확실성', value: `±${fmt(current.neighborSpreadMs, 2)}`, unit: 'm/s',
        age: `이웃 ${current.neighborCount}칸 최대 차이 · 30분 표류 ±${driftM}m`, stale });
    }
    rows.push(current.waterTempC != null
      ? { label: '표층 수온 예측', value: fmt(current.waterTempC)!, unit: '°C',
          age: `${hourKst(current.predcDt)} 예측값 · ROMS`, stale }
      : none('표층 수온 예측', '값 없음'));
    rows.push(tideRow(all, now));
    rows.push(shipRow(all, now));
    return { title: '항해 — 언제 갈까?', src: 'KHOA ROMS · 본선 위치', rows };
  }

  if (roms && p && p.currentSpeedMs != null) {
    const kn = (p.currentSpeedMs * KNOTS_PER_MS).toFixed(1);
    const dir = p.currentDirDeg != null ? `${compass16(p.currentDirDeg)} ${Math.round(p.currentDirDeg)}°` : '방위 없음';
    rows.push({ label: '표층 유속 예측', value: fmt(p.currentSpeedMs, 2)!, unit: 'm/s', metric: 'tide',
      age: ageText(roms, now, `${kn}kn · ${dir} · 격자 ${p.distanceKm ?? '?'}km`), stale: isStale(roms) });
    rows.push(p.waterTempC != null
      ? { label: '표층 수온 예측', value: fmt(p.waterTempC)!, unit: '°C', age: ageText(roms, now, 'ROMS'), stale: isStale(roms) }
      : none('표층 수온 예측', ageText(roms, now)));
  } else {
    rows.push(none('표층 유속 예측', roms ? ageText(roms, now) : '미수신', 'tide'));
  }

  rows.push(tideRow(all, now));
  rows.push(shipRow(all, now));
  return { title: '항해 — 언제 갈까?', src: 'KHOA ROMS', rows };
}

/**
 * 지금 수온과 그 출처. 조업 탭과 익수 경보(저체온 추정)가 같은 값을 써야 한다.
 *
 * 우선순위는 **관측 → 예보**다. 수과원 실시간어장이 30분 주기에 관측소 좌표를 갖고 있어 1순위,
 * 없으면 기상청 부이, 그것도 없으면 본선 격자의 ROMS 예측으로 물러선다.
 *
 * 없으면 null 이다 — 익수 경보에서 지어낸 수온으로 생존 시간을 말하면 안 된다.
 */
export interface WaterTemp {
  c: number;
  /** 시각 문구를 만들 소스 */
  src: OceanSource;
  /** 지점·거리·기관 */
  where: string;
  /** 관측이 아니라 예측값인가 */
  forecast: boolean;
}

export function waterTemp(
  all: Record<string, OceanSource | undefined>, current: RomsPoint | null | undefined,
): WaterTemp | null {
  const fg = all['fishing-ground'] as OceanSource<FishingGroundPayload> | undefined;
  const near = fg?.payload?.stations
    ?.filter((s) => s.waterTempC != null).sort((a, b) => a.distanceKm - b.distanceKm)[0];
  if (fg && near?.waterTempC != null) {
    return { c: near.waterTempC, src: fg, where: `${near.name} ${near.distanceKm}km · 수과원`, forecast: false };
  }

  const obs = all['sea-obs'] as OceanSource<SeaObsPayload> | undefined;
  const station = nearestWith(obs?.payload?.stations ?? [], (s) => s.waterTempC != null);
  if (obs && station?.waterTempC != null) {
    return { c: station.waterTempC, src: obs, where: `${station.name} ${station.distanceKm}km · 기상청`, forecast: false };
  }

  // 관측이 없으면 예측으로 물러선다. 화면이 예측임을 밝힌다
  const roms = all['roms'] as OceanSource<RomsPayload> | undefined;
  const c = current?.waterTempC ?? roms?.payload?.waterTempC;
  if (roms && c != null) {
    return { c, src: roms, where: 'ROMS 예측', forecast: true };
  }
  return null;
}

/**
 * @param current 본선 위치 최근접 격자(`/current`). 있으면 항해 탭이 이것을 쓴다.
 *                없으면 해역 대표값(bbox 중심)으로 물러선다
 */
export function buildCategories(
  sources: OceanSource[], now: Date = new Date(), current?: RomsPoint | null,
): Record<CloudCatKey, Category> {
  const all = bySource(sources);
  return { safe: safe(all, now), fish: fish(all, now), nav: nav(all, now, current) };
}

/**
 * "오늘의 바다" 한 줄. LLM 요약이 아니라 수집값을 그대로 이은 것이다.
 * LLM 은 아직 안 붙었고, 붙어도 판단은 하지 않는다 — 특보 기준이 정한다 (§9.18).
 */
export function statusLine(sources: OceanSource[], current?: RomsPoint | null): string {
  const all = bySource(sources);
  const parts: string[] = [];
  const warn = (all['weather-warning'] as OceanSource<WarningPayload> | undefined)?.payload;
  if (warn?.focus) {
    const hits = warn.focus.activeMarineWarnings ?? [];
    parts.push(hits.length ? `조업 해역 해상특보 ${hits.join('·')} 발효 중` : '조업 해역 해상특보 없음');
  } else if (warn) {
    const active = warn.activeMarineWarnings ?? [];
    parts.push(active.length ? `해상특보 ${active.join('·')} 발효 중` : '발효 중 해상특보 없음');
  }
  const wave = nearestWith((all['sea-obs'] as OceanSource<SeaObsPayload> | undefined)?.payload?.stations ?? [], (s) => s.waveHeightM != null);
  if (wave) parts.push(`파고 ${fmt(wave.waveHeightM)}m`);
  const water = waterTemp(all, current);
  if (water) parts.push(`수온 ${fmt(water.c)}°C${water.forecast ? '(예측)' : ''}`);
  const speed = current?.currentSpeedMs
    ?? (all['roms'] as OceanSource<RomsPayload> | undefined)?.payload?.currentSpeedMs;
  if (speed != null) parts.push(`유속 ${fmt(speed, 2)}m/s`);
  return parts.length ? parts.join(' · ') : '수신된 해양 데이터가 없습니다';
}

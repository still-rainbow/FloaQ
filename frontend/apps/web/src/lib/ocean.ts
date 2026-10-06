import type { Sea } from './drift';

/**
 * 표류 추정에 넣을 **실제 바다 값**을 서버에서 받는다 (WEB-10 · APP-24).
 *
 * 지금까지는 `mock/data.ts` 의 `SEA` 상수 하나로 전국 모든 사고를 계산했다 —
 * 부산 사고와 목포 사고가 같은 조류를 쓰는 셈이었다. 여기가 그것을 사고 지점 값으로 바꾼다.
 *
 * 값은 두 곳에서 온다. **한 번에 오지 않는다.**
 *   유속·유향  `/api/ocean/current`       ROMS 격자. 약 3km 간격
 *   풍속·풍향  `/api/ocean/observations`  기상청 관측 지점. 사고 지점 반경에서 가장 가까운 곳
 *
 * 🔴 **있는 값으로 추정하되 무엇으로 계산했는지 같이 준다**({@link SeaReading.basis}).
 *    조류가 없다고 사고자가 제자리에 있는 것은 아니다 — 바람·파랑·해류·조석이 같이 민다.
 *    일부가 없다고 추정을 통째로 지우면 수색에 쓸 정보까지 버린다.
 *
 *    대신 **없는 값을 임의의 숫자로 메우지 않는다.** 0 은 "흐르지 않는다"로 읽히고,
 *    상수는 "정밀한 값"처럼 보인다. 빠진 항은 빠진 채로 두고 화면이 그 사실을 적는다.
 *
 *    조석예보(current-forecast)를 조류 자리에 넣지 않는다 — 조석에 의한 흐름만이라
 *    해류·취송류가 빠진다(CurrentForecastCollector 주석 · 2026-09-14). 선박운항지수는 유향이 없다.
 */

/** `/api/ocean/current` 응답 (백엔드 RomsPointView). 격자가 없으면 data 가 null 이다 */
interface CurrentPoint {
  predcDt: string;
  currentDirDeg: number | null;
  currentSpeedMs: number | null;
  distanceKm: number;
  /** 한 칸 이내 이웃 격자와의 유속 최대 차이. 연안 경계에서 커진다 */
  neighborSpreadMs: number | null;
}

/** `/api/ocean/observations` 응답 한 지점 (백엔드 StationObsView) */
interface StationObs {
  stn: string;
  name: string;
  distanceKm: number;
  observedAt: string;
  windDirDeg: number | null;
  windSpeedMs: number | null;
}

/** 값이 어디서 왔는지. 화면이 "언제 어디 값인지"를 같이 적어야 한다(§9.18) */
export interface SeaSource {
  /** 사고 지점에서 이 값까지의 거리(km) */
  distanceKm: number;
  /** 관측·예측 시각 */
  at: string;
  /** 관측 지점 이름. 격자는 이름이 없어 null */
  name: string | null;
}

/**
 * 무엇으로 계산했는지. <b>화면이 이 값을 그대로 적는다</b> — 같은 원이라도
 * "조류·바람 기반"과 "바람만 기반"은 믿을 만한 정도가 다르다.
 */
export type SeaBasis = 'current-wind' | 'current' | 'wind';

export const BASIS_TEXT: Record<SeaBasis, string> = {
  'current-wind': '조류·바람 기반 추정',
  current: '조류 기반 추정 · 바람 정보 없음',
  wind: '바람 기반 추정 · 조류 정보 없음',
};

export interface SeaReading {
  sea: Sea;
  basis: SeaBasis;
  current: SeaSource | null;
  wind: SeaSource | null;
  /**
   * 유속의 불확실성(m/s). 이웃 격자와 10배까지 갈리는 연안에서 커진다 —
   * 추정 범위를 넓히는 근거다. 격자가 없거나 이웃이 없으면 null.
   */
  spreadMs: number | null;
  /**
   * 사고 행에 <b>박아 둔 값</b>인가. 조회로 방금 받은 값과 읽는 법이 다르다 —
   * 박힌 값은 "몇 시간 전 관측"이 아니라 <b>그날 몇 시 값인지</b>로 읽어야 한다.
   * 5일 전 사고에 "117시간 전 관측"이라고 적으면 맞는 말이지만 쓸모가 없다.
   */
  stored?: boolean;
}

/** 사고 행에 박혀 있는 그때의 바다 (서버 OceanSnapView). 없으면 사고가 그 칸을 안 들고 있다 */
export interface OceanSnapDto {
  currentSpeedMs: number | null;
  currentDirDeg: number | null;
  windSpeedMs: number | null;
  windDirDeg: number | null;
  spreadMs: number | null;
  observedAt: string;
}

/**
 * 사고에 박혀 있는 값 → 화면이 쓰는 {@link SeaReading}.
 *
 * <p><b>조회로 받은 것과 같은 모양</b>으로 돌려준다 — 표도 지도도 출처를 가리지 않고 그린다.
 * 다른 점은 이 값이 <b>사고와 함께 영원히 남는다</b>는 것뿐이다(V20260921_1210).</p>
 *
 * <p>풍향은 서버가 <b>불어오는 쪽</b>으로 준다(기상 관례). 표류 계산은 흘러가는 쪽을 쓰므로
 * 여기서 180° 를 돌린다 — 조회 경로와 같은 자리에서 같은 변환을 한다.</p>
 */
export function seaOfSnap(snap: OceanSnapDto | null | undefined): SeaReading | null {
  if (!snap) return null;
  const hasCurrent = snap.currentSpeedMs !== null && snap.currentDirDeg !== null;
  const hasWind = snap.windSpeedMs !== null && snap.windDirDeg !== null;
  if (!hasCurrent && !hasWind) return null;

  return {
    sea: {
      currentSpeed: hasCurrent ? snap.currentSpeedMs! : 0,
      currentDir: hasCurrent ? snap.currentDirDeg! : 0,
      windSpeed: hasWind ? snap.windSpeedMs! : 0,
      windDir: hasWind ? blownToward(snap.windDirDeg!) : 0,
      currentSpreadMs: snap.spreadMs ?? 0,
    },
    basis: hasCurrent && hasWind ? 'current-wind' : hasCurrent ? 'current' : 'wind',
    // 거리는 안 남긴다 — 받아 둔 값이라 "몇 km 떨어진 격자였나"를 이제 와서 알 수 없다
    current: hasCurrent ? { distanceKm: 0, at: snap.observedAt, name: null } : null,
    wind: hasWind ? { distanceKm: 0, at: snap.observedAt, name: null } : null,
    spreadMs: snap.spreadMs,
    stored: true,
  };
}

/** 관측 지점을 몇 km 까지 뒤질지. 넓히면 먼 지점의 바람을 이 자리 값처럼 쓰게 된다 */
const WIND_RADIUS_KM = 50;

const ok = <T,>(body: { success?: boolean; data?: T | null } | null): T | null =>
  body && body.success ? (body.data ?? null) : null;

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    const res = await fetch(path, { signal });
    if (!res.ok) return null;
    return ok<T>(await res.json());
  } catch {
    // 끊겼거나 중단됐다. 바다 값이 없다고 사고 화면 전체를 실패시키지 않는다
    return null;
  }
}

/**
 * 기상 관례의 풍향은 **불어오는 쪽**이다. 표류 계산은 **흘러가는 쪽**을 쓴다.
 *
 * 🔴 이 변환을 빠뜨리면 추정이 정확히 반대로 흐른다. 남서풍(210°)이면 바람은 030° 로 민다.
 */
const blownToward = (fromDeg: number) => (fromDeg + 180) % 360;

/** 바람 값이 실제로 있는 지점 중 가장 가까운 곳. 지점은 있는데 풍속이 비어 있는 경우가 흔하다 */
function nearestWind(stations: StationObs[]): StationObs | null {
  return stations
    .filter((s) => s.windSpeedMs !== null && s.windDirDeg !== null)
    .reduce<StationObs | null>((best, s) => (best === null || s.distanceKm < best.distanceKm ? s : best), null);
}

/**
 * 사고 지점·시각의 바다 값.
 *
 * @param at 사고 시각(ISO). 지난 사고를 다시 열 때 **그 시각 값**으로 계산한다.
 *           생략하면 지금. ⚠ 보관이 24시간이라 그보다 오래된 사고는 값이 없다
 */
export async function seaAt(
  lat: number, lon: number, at?: string, signal?: AbortSignal,
): Promise<SeaReading | null> {
  const when = at ? `&at=${encodeURIComponent(at)}` : '';
  // 둘은 서로를 기다릴 이유가 없다. 하나가 비어도 다른 하나로 절반은 센다
  const [point, stations] = await Promise.all([
    getJson<CurrentPoint>(`/api/ocean/current?lat=${lat}&lon=${lon}${when}`, signal),
    getJson<StationObs[]>(
      `/api/ocean/observations?lat=${lat}&lon=${lon}&radiusKm=${WIND_RADIUS_KM}${when}`, signal),
  ]);

  const hasCurrent = point !== null && point.currentSpeedMs !== null && point.currentDirDeg !== null;
  const wind = nearestWind(stations ?? []);

  // 둘 다 없으면 그릴 근거가 하나도 없다. 마지막 실측 위치만 남긴다
  if (!hasCurrent && wind === null) {
    return null;
  }

  return {
    sea: {
      // 빠진 항은 0 이다 — 값을 지어내지 않는다. basis 가 무엇이 빠졌는지 말해 준다
      currentSpeed: hasCurrent ? point.currentSpeedMs! : 0,
      currentDir: hasCurrent ? point.currentDirDeg! : 0,
      windSpeed: wind ? wind.windSpeedMs! : 0,
      windDir: wind ? blownToward(wind.windDirDeg!) : 0,
      // 이 자리 유속을 얼마나 모르는가. 추정 범위를 넓히는 근거다
      currentSpreadMs: point?.neighborSpreadMs ?? 0,
    },
    basis: hasCurrent && wind ? 'current-wind' : hasCurrent ? 'current' : 'wind',
    current: hasCurrent ? { distanceKm: point.distanceKm, at: point.predcDt, name: null } : null,
    wind: wind ? { distanceKm: wind.distanceKm, at: wind.observedAt, name: wind.name } : null,
    spreadMs: point?.neighborSpreadMs ?? null,
  };
}

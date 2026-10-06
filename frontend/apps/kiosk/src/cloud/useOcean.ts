import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { LngLat } from '@floaq/shared';
import { useMode } from '../state/store';
import {
  AreaNotMovedError,
  fetchOceanCurrent, fetchOceanGrid, fetchOceanSeries, fetchOceanSources, fetchOceanSummary,
  canRefreshSummary,
  fetchOceanTide, refreshOceanSummary, relayFreshness, setOceanDirect,
  type OceanSource, type OceanSummary, type RomsGrid, type RomsPoint, type RomsSeries,
  type TideSeries,
} from './ocean';

/**
 * EC2 해양 데이터 폴링 + PC 로컬 캐시 (§9.10).
 *
 * 60초 — 가장 짧은 수집 주기가 10분(기상특보)이라 그 이하로 물어도 같은 값이다.
 * 3초로 돌리면 하루 28,800 요청을 같은 값 받는 데 쓴다.
 *
 * 마지막 성공값을 localStorage 에 둔다. 인터넷이 끊겨도 빈 화면 대신 마지막 값 + 경과 시간을 보여준다 —
 * "빈 화면보다 오래된 값이 낫고, 오래된 것을 모르는 것보다 아는 것이 낫다".
 *
 * `/current` 는 본선 위치 기준 최근접 격자다. 위치가 바뀌면 바로 다시 묻는다.
 * 캐시하지 않는다 — 위치마다 다른 값이라 캐시 키가 좌표가 되고, 그러면 오프라인에 옛 위치 값을 보여준다.
 *
 * ⚠ 이 훅은 `/cloud` 만 만진다. 사고 경로(`pi/`·`state/`)는 이 파일을 import 하지 않는다.
 */

const POLL_MS = 60_000;
const CACHE_KEY = 'floaq.kiosk.ocean.v1';

/**
 * 좌표가 멈춘 뒤 이만큼 기다렸다 묻는다.
 *
 * 조이스틱은 프레임마다 위치를 바꾼다 — 그대로 두면 초당 60회 요청이고,
 * 서버 쪽에서는 그 좌표 하나하나가 수집 해역 재중심화 후보가 된다.
 */
const SETTLE_MS = 600;

/**
 * 본선이 해역 밖(OUTSIDE_AREA)이면 이만큼 뒤에 다시 묻는다. 60초 폴링을 기다리지 않는다.
 *
 * 10초 근거: 서버가 해역을 옮기는 즉시 ROMS 를 받기 시작하고, 0.3° 수집이 35페이지 × 0.22초 ≈ 8초다
 * (2026-09-14 실측). 그 뒤에 한 번 물으면 대개 들어와 있다. 더 짧게 잡으면 받는 중에 헛물음만 는다.
 */
const RETRY_MS = 10_000;

interface Cached {
  fetchedAt: string;
  sources: OceanSource[];
}

export interface OceanState {
  sources: OceanSource[];
  /** 마지막으로 EC2 에서 받은 시각. null 이면 캐시도 없다 */
  cloudAt: string | null;
  /** 마지막 시도가 실패했나. 캐시가 있으면 sources 는 그대로 남는다 */
  error: string | null;
  /** 본선 위치 최근접 격자. 못 받았으면 null — 화면이 해역 대표값으로 물러선다 */
  current: RomsPoint | null;
  /** 본선 칸 + 이웃. 지도 구역. 못 받았으면 null — 구역을 그리지 않는다 */
  grid: RomsGrid | null;
  /** 본선 격자의 48시간 예측 시계열. 대시보드 차트용 */
  series: RomsSeries | null;
  /**
   * 가장 가까운 조석예보 지점의 조위 곡선. 반경 안에 지점이 없으면 null —
   * 오류가 아니다. 지점이 전국 166곳(연안)뿐이라 먼바다에서는 늘 그렇다
   */
  tide: TideSeries | null;
  /** 사전 생성된 상황 요약 */
  summary: OceanSummary | null;
  /**
   * 본선이 수집 해역 밖이라 서버가 옮겨 받는 중인가.
   * true 면 "값 없음"이 아니라 "받는 중"이다 — 화면이 두 경우를 다른 문구로 보여야 기다릴 줄 안다
   */
  areaPending: boolean;
  /**
   * 해역 밖인데 서버가 옮기지 않았다 — kiosk 키(VITE_KIOSK_KEY)가 없거나 서버 키와 다르다.
   * 기다려도 안 들어오므로 재조회하지 않고 화면에 설정 문제로 드러낸다
   */
  areaBlocked: boolean;
  /**
   * Pi 중계가 준 값이 실시간인가. `null` 이면 중계 응답을 못 봤다(EC2 직접·시연판) — <b>모른다</b>.
   *
   * 🔴 `false` 를 화면에 반드시 드러낸다. 인터넷이 끊겨 Pi 가 옛 값을 준 것인데,
   * <b>3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 화면에서 똑같이 생겼다</b>
   * (`ref/kiosk_시연.md` §6).
   */
  relayFresh: boolean | null;
  /** 그 옛 값을 Pi 가 받은 시각(Unix 초). 여럿이면 가장 오래된 것 */
  relayCachedAt: number | null;
}

export interface OceanApi extends OceanState {
  /**
   * 요약을 지금 다시 만든다. <b>사람이 누를 때만</b> — 누를 때마다 크레딧이 나간다.
   * 부르는 좌표는 폴링과 같은 자리(본선)다.
   */
  refreshSummary: () => void;
  /** 재생성 왕복 중인가. 버튼을 잠그는 데 쓴다 */
  refreshing: boolean;
  /**
   * 재생성 버튼을 띄울 수 있나. <b>키만으로 갈리지 않는다</b> —
   * 실제 모드에는 이 경로 자체가 없다(`ocean.ts` `canRefreshSummary`).
   */
  canRefresh: boolean;
  /**
   * 마지막 재생성 결과 문구. null 이면 아직 안 눌렀거나 진짜 LLM 응답을 받았다.
   * 실패 이유를 화면에 그대로 보여준다 — 삼키면 "버튼이 안 먹는다"가 된다
   */
  refreshNote: string | null;
}

function readCache(): Cached | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as Cached) : null;
  } catch {
    return null;
  }
}

function writeCache(c: Cached) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(c));
  } catch {
    // 저장 실패는 화면에 영향 없다. 다음 폴링이 다시 채운다
  }
}

/**
 * @param enabled  false 면 폴링을 멈춘다. TopBar 의 오프라인 토글이 이걸 내린다 —
 *                 시연에서 "인터넷 끊김"을 재현하는 스위치다
 * @param vesselAt 본선 위치 [lng, lat]. `/current` 의 입력
 */
/**
 * @param rings 격자를 몇 겹까지 받나. 본 화면은 1(3x3)이면 되고,
 *              상황판은 등치선을 그려야 해 넓게 받는다 — 점이 적으면 선이 각진다
 */
export function useOcean(enabled: boolean, vesselAt: LngLat, rings = 1): OceanApi {
  /**
   * 🔴 <b>가상이면 EC2 로 직접 간다</b> (2026-09-18 요청). 가상은 정의상 Pi 가 없는 모드인데
   * 해양 조회만 Pi 중계를 타고 있었다 — 선내망 밖에서는 수온·파고가 전부 "값 없음"이 됐다.
   *
   * <p>렌더 중에 세운다. 아래 폴링 effect 보다 먼저 정해져 있어야 첫 조회가 맞는 주소로 나간다 —
   * effect 로 미루면 첫 한 바퀴가 옛 주소로 나가고, 그 응답이 화면에 한 번 찍힌다.
   * 같은 값을 다시 넣는 것이라 StrictMode 이중 렌더에도 결과가 같다.</p>
   */
  const { virtual } = useMode();
  setOceanDirect(virtual);

  const [state, setState] = useState<OceanState>(() => {
    const c = readCache();
    return {
      sources: c?.sources ?? [], cloudAt: c?.fetchedAt ?? null, error: null,
      current: null, grid: null, series: null, tide: null, summary: null,
      areaPending: false, areaBlocked: false,
      relayFresh: null, relayCachedAt: null,
    };
  });
  const inflight = useRef<AbortController | null>(null);
  const inflightCur = useRef<AbortController | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  // 좌표를 격자보다 촘촘하게 쪼개지 않는다. ROMS 격자가 약 3km 라 소수 4자리(11m)면 충분하고,
  // 그 아래로는 같은 격자를 다시 묻는 요청이 된다
  const lon = Number(vesselAt[0].toFixed(4));
  const lat = Number(vesselAt[1].toFixed(4));

  useEffect(() => {
    if (!enabled) return;
    let alive = true;

    const poll = async () => {
      inflight.current?.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      try {
        const [sources, summary] = await Promise.all([
          // 지점(파고·풍속·수온) 거리가 본선 좌표 기준이다 — 서버는 전국 지점을 들고 조회 좌표로 자른다
          fetchOceanSources(ctrl.signal, { lat, lon }),
          // 요약도 본선 좌표 기준이다 (2026-09-18). 사전 생성된 것을 받아 오기만 하므로
          // 폴링해도 LLM 을 부르지 않는다. 실패해도 수치는 살린다
          fetchOceanSummary(ctrl.signal, { lat, lon }).catch(() => null),
        ]);
        if (!alive) return;
        const fetchedAt = new Date().toISOString();
        writeCache({ fetchedAt, sources });
        const relay = relayFreshness();
        setState((s) => ({ ...s, sources, summary: summary ?? s.summary, cloudAt: fetchedAt, error: null,
          relayFresh: relay.fresh, relayCachedAt: relay.cachedAt }));
      } catch (e) {
        if (!alive || ctrl.signal.aborted) return;
        // 실패해도 sources 는 건드리지 않는다. 마지막 값을 지우면 화면이 빈다
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
      }
    };

    // 좌표가 멈춘 뒤 묻는다 — 옮기면 지점 거리가 달라 다시 받는다. 조이스틱이 프레임마다 좌표를 바꾼다
    // ⚠ localStorage 캐시는 받은 때 좌표 기준 거리다. 오프라인에 배를 옮기면 옛 거리가 남는다
    const settle = setTimeout(() => void poll(), SETTLE_MS);
    const id = setInterval(() => void poll(), POLL_MS);
    return () => {
      alive = false;
      clearTimeout(settle);
      clearInterval(id);
      inflight.current?.abort();
    };
    // virtual: 주소가 Pi↔EC2 로 바뀐다. 안 넣으면 칩을 눌러도 다음 60초까지 옛 주소 값이 남는다
  }, [enabled, lat, lon, virtual]);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      clearTimeout(retry);
      inflightCur.current?.abort();
      const ctrl = new AbortController();
      inflightCur.current = ctrl;
      try {
        // 같은 좌표를 두 번 묻지만 용도가 다르다 — 점(표류 입력)과 구역(화면).
        // 둘 다 실패해도 서로를 막지 않게 따로 잡는다.
        // current 는 "해역 밖(null)" · "옮기지 않음" · "실패"를 갈라 받는다 — 첫 번째만 짧게 다시 묻는다
        const [cur, grid, series, tide] = await Promise.all([
          fetchOceanCurrent(lat, lon, ctrl.signal).then(
            (v) => ({ v, failed: false, blocked: false }),
            (e: unknown) => ({ v: null, failed: true, blocked: e instanceof AreaNotMovedError })),
          fetchOceanGrid(lat, lon, ctrl.signal, rings).catch(() => null),
          fetchOceanSeries(lat, lon, 48, ctrl.signal).catch(() => null),
          // 조석은 ROMS 타일과 무관하다 — 해역 밖이어도 지점만 가까우면 값이 있다
          fetchOceanTide(lat, lon, 48, ctrl.signal).catch(() => null),
        ]);
        if (!alive) return;
        const pending = !cur.failed && cur.v === null;
        const relay = relayFreshness();
        setState((s) => ({ ...s, current: cur.v, grid, series, tide, areaPending: pending, areaBlocked: cur.blocked,
          relayFresh: relay.fresh, relayCachedAt: relay.cachedAt }));
        if (pending) retry = setTimeout(() => void poll(), RETRY_MS);
      } catch {
        // 503(예측 없음)·타임아웃. 옛 위치 값을 남기면 다른 격자 값이 이 위치 것처럼 보인다 — 비운다
        if (alive && !ctrl.signal.aborted) {
          setState((s) => ({
            ...s, current: null, grid: null, series: null, tide: null,
            areaPending: false, areaBlocked: false,
          }));
        }
      }
    };

    // 좌표가 멈춘 뒤에만 묻는다. 움직이는 동안은 마지막 값이 화면에 남는다
    const settle = setTimeout(() => void poll(), SETTLE_MS);
    const id = setInterval(() => void poll(), POLL_MS);
    return () => {
      alive = false;
      clearTimeout(settle);
      clearTimeout(retry);
      clearInterval(id);
      inflightCur.current?.abort();
    };
  }, [enabled, lat, lon, rings, virtual]);

  /**
   * 🔴 폴링이 아니라 **사람이 누를 때만** 부른다. 서버가 30분 상한을 건너뛰고 LLM 을 부르므로
   * 누를 때마다 크레딧이 나간다. 결과는 바로 화면에 넣는다 — 다음 폴링을 기다리게 하면
   * "눌렀는데 안 바뀐다"가 된다(서버 캐시에는 이미 들어가 있어 다음 폴링도 같은 값을 준다).
   */
  const refreshSummary = useCallback(() => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshNote(null);
    void refreshOceanSummary({ lat, lon })
      .then((r) => {
        setState((s) => ({ ...s, summary: r.summary }));
        setRefreshNote(r.note);
      })
      .catch((e: unknown) => setRefreshNote(e instanceof Error ? e.message : String(e)))
      .finally(() => setRefreshing(false));
  }, [lat, lon, refreshing]);

  // `setOceanDirect(virtual)` 가 렌더 중에 이미 돌았으므로 여기서 읽으면 이번 모드가 맞다.
  // `virtual` 을 의존성에 넣어 모드를 바꾼 렌더에서 다시 계산되게 한다
  const canRefresh = canRefreshSummary();

  return useMemo(
    () => ({ ...state, refreshSummary, refreshing, refreshNote, canRefresh }),
    [state, refreshSummary, refreshing, refreshNote, canRefresh]);
}

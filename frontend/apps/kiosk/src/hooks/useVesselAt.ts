import { useCallback, useMemo, useState } from 'react';
import type { LngLat } from '@floaq/shared';
import { useKiosk, useMode } from '../state/store';

/**
 * 본선 위치.
 *
 * **Pi GPS(`pi/sensor/gps`)가 들어오면 그 값이 이긴다.** 수동 신고의 조난 좌표가 이 값이라
 * 0,0 이 아니라 "화면이 아는 값"을 싣는다.
 *
 * <b>수동 위치는 가상 모드에서만 쓴다</b>(2026-09-17). 실제 운항에서 사람이 지도를 눌러 배를 옮기면
 * **그 좌표가 조난 신고에 그대로 실린다** — 구조대가 그리로 간다. 위치는 GPS 가 정할 일이다.
 *
 * ⚠ 버튼만 숨기지 않고 **저장값도 읽지 않는다.** 가상으로 시험하며 찍어 둔 좌표가 localStorage 에
 * 남아 있는데 실제 모드에서 그걸 쓰면, 화면은 `수동 위치` 라고만 적혀 있어
 * **누가 일부러 고른 값처럼 보인다.** 시험 잔재인지 알 방법이 없다.
 */
const KEY = 'floaq.kiosk.vesselAt';

/** 기본값 — 오륙도 앞. 임시 해역 bbox(계획.md §10)와 같은 곳 */
export const DEFAULT_VESSEL_AT: LngLat = [129.1185, 35.0550];

/**
 * 해양 조회용 좌표를 묶는 단위(도). GPS 는 1Hz 로 바뀌어 그대로 넘기면 조회가 초마다 나간다.
 * 0.01°(약 1.1km) 근거: ROMS 격자가 약 3km 라 이 안의 이동으로 최근접 격자가 거의 바뀌지 않는다
 */
const QUERY_STEP_DEG = 0.01;
const snap = (v: number) => Math.round(v / QUERY_STEP_DEG) * QUERY_STEP_DEG;

const isLngLat = (v: unknown): v is LngLat =>
  Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === 'number' && Number.isFinite(n));

export function useVesselAt() {
  const { vesselFix } = useKiosk();
  const { virtual } = useMode();
  const [stored, setState] = useState<LngLat>(() => {
    try {
      const raw = localStorage.getItem(KEY);
      const v: unknown = raw ? JSON.parse(raw) : null;
      return isLngLat(v) ? v : DEFAULT_VESSEL_AT;
    } catch { return DEFAULT_VESSEL_AT; }
  });
  const [manual, setManual] = useState<boolean>(() => {
    try { return localStorage.getItem(KEY) != null; } catch { return false; }
  });

  const set = useCallback((at: LngLat) => {
    // 실제 모드에서는 어떤 경로로 와도 무시한다. 버튼을 숨기는 것만으로는 부족하다 —
    // 가상에서 `위치 지정` 을 켜 둔 채 실제로 바꾸면 picking 이 남아 지도 클릭이 그대로 먹는다
    if (!virtual) return;
    try { localStorage.setItem(KEY, JSON.stringify(at)); } catch { /* 이번 세션은 돈다 */ }
    setState(at);
    setManual(true);
  }, [virtual]);

  const reset = useCallback(() => {
    try { localStorage.removeItem(KEY); } catch { /* noop */ }
    setState(DEFAULT_VESSEL_AT);
    setManual(false);
  }, []);

  const gps = vesselFix ? ([vesselFix.lon, vesselFix.lat] as LngLat) : null;
  // 실제 모드는 저장된 수동 좌표를 쓰지 않는다. GPS 가 없으면 기본값이고, 화면이 `기본 위치` 라고 적는다
  const fallback = virtual ? stored : DEFAULT_VESSEL_AT;
  const vesselAt = gps ?? fallback;
  // GPS 일 때만 묶는다. 수동 위치는 사람이 고른 값이라 그대로 — 원래도 옮길 때만 바뀐다
  const qLon = gps ? snap(gps[0]) : fallback[0];
  const qLat = gps ? snap(gps[1]) : fallback[1];
  const queryAt = useMemo<LngLat>(() => [qLon, qLat], [qLon, qLat]);

  return {
    /** 지도·신고에 쓰는 위치 */
    vesselAt,
    /** 해양 조회에 쓰는 위치 — GPS 면 0.01° 로 묶임 */
    queryAt,
    /** GPS 가 이기는 동안 수동 위치는 쓰이지 않는다. 실제 모드에서는 아예 `manual` 이 될 수 없다 */
    source: (gps ? 'gps' : virtual && manual ? 'manual' : 'default') as 'gps' | 'manual' | 'default',
    manual: !gps && virtual && manual,
    set,
    reset,
  };
}

import { useEffect, useRef, useState } from 'react';
import { fetchOceanZones, type ZoneGrid, type ZoneLevel } from './ocean';

/**
 * 기상청 해구별 예측 한 프레임.
 *
 * 10분 폴링 — 발표가 하루 2회이고 수집기가 매시 확인하므로, 새 발표본이 화면에 오르는 지연은
 * 최대 1시간 10분이다. 더 자주 물어도 그 1시간은 줄지 않는다.
 *
 * 받은 프레임은 (층, 발효시각) 로 기억한다 — 슬라이더를 앞뒤로 끌 때 대해구 214KB 를 다시 받지 않게.
 * 새 발표본이 오면(issuedAt 이 바뀌면) 비운다 — 옛 발표본 프레임을 새 것처럼 그리지 않는다.
 *
 * 받는 동안·실패해도 직전 프레임을 남긴다(비우면 슬라이더를 끌 때마다 깜빡인다).
 * 층이 바뀌면 비운다 — 대해구 칸을 소해구 범례로 읽지 않게.
 */
const POLL_MS = 10 * 60_000;
/** 손잡이가 멈춘 뒤 묻는다. useGridFrame 과 같은 근거 */
const SETTLE_MS = 200;

export function useZones(enabled: boolean, level: ZoneLevel, at: string | null) {
  const [grid, setGrid] = useState<ZoneGrid | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const cache = useRef<{ level: ZoneLevel; issuedAt: string | null; frames: Map<string, ZoneGrid> }>(
    { level, issuedAt: null, frames: new Map() });

  useEffect(() => {
    if (cache.current.level !== level) {
      cache.current = { level, issuedAt: null, frames: new Map() };
      setGrid(null);
    }
    if (!enabled) return;

    const key = at ?? 'now';
    const hit = cache.current.frames.get(key);
    if (hit) setGrid(hit);

    const ctrl = new AbortController();
    const load = () => {
      setLoading(true);
      fetchOceanZones(level, at, ctrl.signal)
        .then((g) => {
          if (!g || g.level !== level) return;
          if (g.issuedAt !== cache.current.issuedAt) {
            cache.current = { level, issuedAt: g.issuedAt, frames: new Map() };
          }
          cache.current.frames.set(key, g);
          setGrid(g);
          setError(false);
        })
        // 503(발표본 없음)·타임아웃. 직전 프레임은 남기고 화면이 "받지 못함"을 적게 한다
        .catch(() => { if (!ctrl.signal.aborted) setError(true); })
        .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    };

    // 기억에 있으면 바로 그리고 묻지 않는다. 폴링만 새 발표본을 확인한다
    const settle = hit ? undefined : setTimeout(load, SETTLE_MS);
    const id = setInterval(load, POLL_MS);
    return () => {
      clearTimeout(settle);
      clearInterval(id);
      ctrl.abort();
    };
  }, [enabled, level, at]);

  return { grid: enabled ? grid : null, loading, error };
}

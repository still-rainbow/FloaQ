import { useEffect, useRef, useState } from 'react';
import type { LngLat } from '@floaq/shared';
import { fetchOceanGrid, type RomsGrid } from './ocean';

/**
 * 시간 슬라이더가 고른 예측 시각의 격자.
 *
 * "지금" 프레임은 `useOcean` 이 이미 60초마다 받는다 — `at` 이 null 이면 아무것도 하지 않는다.
 *
 * 받은 프레임은 (좌표, 겹 수, 시각) 로 기억한다. 슬라이더를 앞뒤로 끌 때 같은 시각을 다시 묻지 않게.
 * 좌표가 바뀌면 통째로 비운다 — 옛 위치 격자를 새 위치 것처럼 그리지 않는다.
 * 기억 상한을 두지 않는다: 8일 × 1시간 = 178프레임 × 약 60칸이라 수백 KB 다.
 *
 * 받는 동안에는 직전 프레임을 돌려준다. 비우면 슬라이더를 끌 때마다 지도가 깜빡인다.
 */

/**
 * 손잡이가 멈춘 뒤 이만큼 기다렸다 묻는다. 끄는 동안 지나가는 눈금마다 요청하지 않게.
 * 200ms 근거: `/grid` 응답이 로컬 20ms(2026-09-14 실측)라 멈춘 뒤 체감 지연이 이 값으로 정해진다 —
 * 사람이 "멈췄다"고 느끼는 0.1~0.3초 구간의 가운데.
 */
const SETTLE_MS = 200;

export function useGridFrame(vesselAt: LngLat, at: string | null, rings: number) {
  const lon = Number(vesselAt[0].toFixed(4));
  const lat = Number(vesselAt[1].toFixed(4));
  const place = `${lat},${lon},${rings}`;

  const cache = useRef<{ place: string; frames: Map<string, RomsGrid> }>({ place, frames: new Map() });
  const [grid, setGrid] = useState<RomsGrid | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (cache.current.place !== place) {
      cache.current = { place, frames: new Map() };
      setGrid(null);
    }
    if (!at) {
      setLoading(false);
      return;
    }
    const hit = cache.current.frames.get(at);
    if (hit) {
      setGrid(hit);
      setLoading(false);
      return;
    }

    const ctrl = new AbortController();
    setLoading(true);
    const id = setTimeout(() => {
      fetchOceanGrid(lat, lon, ctrl.signal, rings, at)
        .then((g) => {
          // 해역 밖(null)이면 직전 그림을 남긴다. 해역 이동 중이라 곧 "지금" 프레임이 다시 채운다
          if (g && cache.current.place === place) {
            cache.current.frames.set(at, g);
            setGrid(g);
          }
        })
        .catch(() => { /* 이 프레임만 실패. 다음에 같은 시각으로 오면 다시 묻는다 */ })
        .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    }, SETTLE_MS);

    return () => {
      clearTimeout(id);
      ctrl.abort();
    };
  }, [at, lat, lon, rings, place]);

  return { grid: at ? grid : null, loading };
}

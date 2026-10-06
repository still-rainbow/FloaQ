import { useCallback, useState } from 'react';
import type { Vessel } from '../types';

/**
 * 단말에 등록된 선박. 단말 하나에 선박 하나다.
 *
 * ⚠ 시연 범위의 저장 위치다. 실제로는 EC2 에 등록하고 단말은 조회만 하는 편이 맞다 —
 *   지금은 웹 등록 화면이 없어 단말이 진실을 들고 있다.
 */
const KEY = 'floaq.vessel';

export function useVessel() {
  const [vessel, setState] = useState<Vessel | null>(() => {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as Vessel) : null;
    } catch { return null; }
  });

  const save = useCallback((v: Vessel) => {
    try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* 저장 못 해도 이번 세션은 돈다 */ }
    setState(v);
  }, []);

  const wipe = useCallback(() => {
    try { localStorage.removeItem(KEY); } catch { /* noop */ }
    setState(null);
  }, []);

  return { vessel, save, wipe };
}

import { useEffect, useState } from 'react';
import type { MapTheme } from '@floaq/shared';

/**
 * 지도 테마. 선택은 이 단말에 저장된다.
 *
 * ⚠ 밝기(주간·야간)는 없앴다 (2026-09-16). 단말기형 재설계 때 `terminal.css` 에 `data-ui` 규칙이
 * 딸려오지 않아 **버튼만 있고 아무것도 바뀌지 않았다** — 옛 `kiosk.css`·`web-look.css` 에만 규칙이 남아 있다.
 * 야간 모드가 필요해지면 CSS 부터 만들고 이 훅에 되돌린다.
 *
 * localStorage 접근을 try/catch 로 감싼다: 사생활 보호 모드나 저장소 차단 설정에서
 * 접근 자체가 예외를 던지는데, 그 때문에 인명 안전 단말이 흰 화면이 되면 안 된다.
 */
const read = (k: string, fallback: string): string => {
  try { return localStorage.getItem(k) ?? fallback; } catch { return fallback; }
};
const write = (k: string, v: string): void => {
  try { localStorage.setItem(k, v); } catch { /* 저장 실패는 무시한다 — 화면은 계속 돈다 */ }
};

export function useLook() {
  const [theme, setTheme] = useState<MapTheme>(() => read('floaq.theme', 'chart') as MapTheme);

  useEffect(() => { write('floaq.theme', theme); }, [theme]);

  return { theme, setTheme };
}

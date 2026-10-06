import { useEffect, useState } from 'react';
import type { MapTheme } from '@floaq/shared';

// 화면 밝기와 지도 테마. 한 번 정하면 잘 바꾸지 않으므로 지도 위가 아니라 설정에 둔다.
// 저장 실패(사생활 보호 모드)는 무시한다 — 저장만 안 되고 화면은 그대로 동작한다.

const LS = 'floaq.web.look';

export type Ui = 'light' | 'dark';
/**
 * 글자 크기. 화면을 통째로 확대하는 것이 아니라 <b>글자 단계 넷을 함께 올린다</b>(web.css --t-*).
 * 관제실은 화면에서 떨어져 보는 자리가 있어 사람마다 필요한 크기가 다르다.
 */
export type TextSize = 'normal' | 'big';
export interface Look { ui: Ui; theme: MapTheme; text: TextSize }

function read(): Look {
  try {
    const o = JSON.parse(localStorage.getItem(LS) || '{}');
    // 지도 테마 기본은 백야(day). 이미 고른 사람은 저장된 선택을 따른다.
    return { ui: o.ui === 'dark' ? 'dark' : 'light', theme: (o.theme as MapTheme) || 'day',
             text: o.text === 'big' ? 'big' : 'normal' };
  } catch {
    return { ui: 'light', theme: 'day', text: 'normal' };
  }
}

export function useLook() {
  const [look, setLook] = useState<Look>(read);

  useEffect(() => {
    const root = document.documentElement;
    if (look.ui === 'dark') root.dataset.ui = 'dark';
    else delete root.dataset.ui;
    if (look.text === 'big') root.dataset.text = 'big';
    else delete root.dataset.text;
    try { localStorage.setItem(LS, JSON.stringify(look)); } catch { /* 저장만 실패한다 */ }
  }, [look]);

  return {
    look,
    setUi: (ui: Ui) => setLook((p) => ({ ...p, ui })),
    setTheme: (theme: MapTheme) => setLook((p) => ({ ...p, theme })),
    setText: (text: TextSize) => setLook((p) => ({ ...p, text })),
  };
}

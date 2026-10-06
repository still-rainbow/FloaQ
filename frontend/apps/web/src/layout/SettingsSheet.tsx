import { useEffect } from 'react';
import type { MapTheme } from '@floaq/shared';
import type { TextSize, Ui } from '../hooks/useLook';

/**
 * 지도 테마. <b>기본값(백야)이 맨 앞</b>이다 — 목록의 첫 칸을 기본으로 읽는 사람이 많아,
 * 순서와 기본값이 어긋나면 "왜 고른 적 없는 게 켜져 있지"가 된다(useLook.ts).
 */
const THEMES: [MapTheme, string, string][] = [
  ['day', '백야', '#93cbde'],
  ['chart', '해도', '#f7f1e6'],
  ['abyss', '심해', '#0d3348'],
  ['dawn', '여명', '#4a3352'],
];

interface Props {
  open: boolean;
  ui: Ui;
  theme: MapTheme;
  text: TextSize;
  onUi: (v: Ui) => void;
  onTheme: (v: MapTheme) => void;
  onText: (v: TextSize) => void;
  onClose: () => void;
}

export function SettingsSheet({ open, ui, theme, text, onUi, onTheme, onText, onClose }: Props) {
  // Esc 로 닫는다. 모달이 열려 있으면 그쪽이 먼저 먹으므로 여기는 설정 전용이다.
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="setTitle"
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sheet-card">
        <div className="sheet-top">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3.1" />
            <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1" />
          </svg>
          <h3 id="setTitle">설정</h3>
          <button className="icon-btn" aria-label="닫기" onClick={onClose}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="m5 5 14 14M19 5 5 19" />
            </svg>
          </button>
        </div>

        <div className="sheet-body">
          <section className="set-sec">
            <h4>화면</h4>
            <div className="set-row">
              <span className="set-label">밝기</span>
              <div className="pick" role="group" aria-label="화면 밝기">
                <button className="pick-btn" aria-pressed={ui === 'light'} onClick={() => onUi('light')}>주간</button>
                <button className="pick-btn" aria-pressed={ui === 'dark'} onClick={() => onUi('dark')}>야간</button>
              </div>
            </div>
            {/*
              화면 배율을 통째로 키우지 않는다 — 그러면 줄 수가 늘어 스크롤이 생기고,
              한 번에 안 보이는 글자까지 더해진다. 글자 단계 넷을 같이 올려 비율을 지킨다.
            */}
            <div className="set-row">
              <span className="set-label">글자 크기</span>
              <div className="pick" role="group" aria-label="글자 크기">
                <button className="pick-btn" aria-pressed={text === 'normal'} onClick={() => onText('normal')}>보통</button>
                <button className="pick-btn" aria-pressed={text === 'big'} onClick={() => onText('big')}>크게</button>
              </div>
            </div>
            <div className="set-row">
              <span className="set-label">지도 테마</span>
              <div className="pick" role="group" aria-label="지도 테마">
                {THEMES.map(([key, name, swatch]) => (
                  <button key={key} className="pick-btn" aria-pressed={theme === key} onClick={() => onTheme(key)}>
                    <i style={{ background: swatch }} />{name}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

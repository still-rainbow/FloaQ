import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';

/**
 * 정렬 메뉴. 브라우저 기본 select 는 OS 마다 모양이 달라 화면과 따로 논다 — 직접 그린다.
 * 버튼은 글자처럼 가볍게 두고, 펼친 목록에서는 지금 고른 것에 체크를 붙인다.
 * 바깥을 누르거나 Esc 면 닫힌다. 화살표·Enter 로도 고를 수 있다.
 *
 * 목록은 body 에 띄운다. 패널 안에 두면 좁은 화면에서 패널 높이에 잘려
 * 아래 항목이 안 보이고 패널에 스크롤이 생긴다. 대신 스크롤·창 크기 변경 때는 닫는다 —
 * 버튼이 움직이는데 목록만 제자리에 남으면 엉뚱한 곳을 가리킨다.
 */
export function SortMenu<T extends string>({ value, options, onChange, label, title }: {
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
  /** 스크린리더용 이름 */
  label: string;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  /** 키보드로 옮겨 다니는 중인 항목 */
  const [hi, setHi] = useState(0);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const current = options.find(([v]) => v === value)?.[1] ?? '';

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!root.current?.contains(t) && !menu.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const close = (e: Event) => {
      // 목록 자체를 스크롤하는 것은 닫지 않는다
      if (e.type === 'scroll' && menu.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  function toggle() {
    if (!open) {
      const r = btn.current?.getBoundingClientRect();
      if (r) setPos({ top: r.bottom + 5, left: Math.max(8, r.left - 6) });
      setHi(Math.max(0, options.findIndex(([v]) => v === value)));
    }
    setOpen((o) => !o);
  }

  function pick(v: T) {
    onChange(v);
    setOpen(false);
  }

  function onKeyDown(e: ReactKeyboardEvent) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); toggle(); }
      return;
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => (h + 1) % options.length); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => (h - 1 + options.length) % options.length); }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const o = options[hi];
      if (o) pick(o[0]);
    }
  }

  return (
    <div className="fsort" ref={root} title={title}>
      <button type="button" className="sort-btn" ref={btn}
              aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}: ${current}`}
              onClick={toggle} onKeyDown={onKeyDown}>
        <span className="sort-ico" aria-hidden="true">⇅</span>
        {current}
        <i className="sort-caret" aria-hidden="true" />
      </button>
      {open && pos ? createPortal(
        <ul className="sort-menu" role="listbox" aria-label={label} ref={menu}
            style={{ top: pos.top, left: pos.left }}>
          {options.map(([v, t], i) => (
            <li key={v} role="option" aria-selected={v === value}
                className={i === hi ? 'is-hi' : undefined}
                onMouseEnter={() => setHi(i)}
                // 버튼에서 포커스가 빠지지 않게 한다
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(v)}>
              <span>{t}</span>
              {v === value ? <b aria-hidden="true">✓</b> : null}
            </li>
          ))}
        </ul>,
        document.body,
      ) : null}
    </div>
  );
}

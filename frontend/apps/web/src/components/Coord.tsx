import { useState } from 'react';
import type { LngLat } from '@floaq/shared';
import { copyText, ddm } from '../lib/ddm';

/**
 * 좌표 표기(신규 2). 무전으로 읽어 주는 상황을 고려해 도분(DDM)으로 보여 주고,
 * 복사도 DDM 문자열로 나간다. 십진도는 기록·API 의 정본이지만 관제 화면에서는 읽지 않아 뺐다.
 */
export function Coord({ at, label, primary }: { at: LngLat; label: string; primary?: boolean }) {
  const [copied, setCopied] = useState(false);
  const text = ddm(at);

  async function onCopy() {
    const ok = await copyText(text);
    setCopied(ok);
    // 실패해도 좌표는 화면에 이미 보인다. 조용히 넘어가고 성공만 알린다.
    if (ok) window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className={`coord${primary ? ' is-primary' : ''}`}>
      <span className="coord-label">{label}</span>
      <span className="coord-val mono">{text}</span>
      {/*
        상자 없는 글자 하나다. 테두리를 두르면 좌표 줄에서 버튼이 좌표만큼 무게가 있어
        숫자보다 먼저 눈에 들어오게 된다 — 읽어야 하는 것은 좌표다.
        눈만 있을 때는 무슨 버튼인지도 안 읽혔다 — 글자가 제 이름을 적는 것보다 짧지 않다(2026-09-18).
      */}
      <button className={`coord-copy${copied ? ' is-copied' : ''}`} onClick={onCopy}
              aria-label={`${label} 좌표 복사`}>
        {copied ? '복사됨' : '복사'}
      </button>
    </div>
  );
}

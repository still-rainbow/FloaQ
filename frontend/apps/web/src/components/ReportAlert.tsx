import { useEffect } from 'react';
import { byVessel } from '../lib/fleet';
import { shortLeft, survival } from '../lib/survival';
import type { Incident } from '../types';

/**
 * **새 신고가 들어왔다.** 사고 한 건이 방금 접수된 순간에 한 번 뜬다.
 *
 * <p>목록에 카드를 한 장 더하는 것만으로는 부족하다 — 다른 사고를 보고 있으면 눈이 그쪽에 있고,
 * "급한 순"에서 방금 빠진 사람은 남은 시간이 제일 길어 <b>목록 맨 아래</b>로 간다.
 * 들어온 사실 자체를 화면 가운데서 한 번 말해야 놓치지 않는다.</p>
 *
 * <p>배경이 빨갛게 점멸한다. 관제실의 경광등과 같은 역할이라 <b>일부러 과하게</b> 뒀다 —
 * 다만 움직임을 줄이도록 설정한 사용자에게는 깜빡이지 않는다(web.css `prefers-reduced-motion`).</p>
 *
 * ⚠ 지금은 신고 시뮬레이션 버튼이 띄운다. WebSocket `ACCIDENT_REPORTED`(api.md §6)가 붙으면
 *   그 이벤트가 이 자리를 가져간다.
 */
export function ReportAlert({ x, onClose }: { x: Incident | null; onClose: () => void }) {
  // 급한 화면이라 Esc 하나로 닫힌다. 확인 버튼을 못 찾아 헤매면 그 시간이 그대로 손해다
  useEffect(() => {
    if (!x) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [x, onClose]);

  if (!x) return null;

  const v = byVessel[x.ship];
  const s = survival(x.waterTemp, x.elapsedSec);
  const detect = x.stages.detect.at ?? '—';
  const report = x.stages.report.at ?? '—';
  const at = x.map.mob ?? x.map.ship;

  return (
    <div className="alert-veil" role="presentation" onClick={onClose}>
      <div className="alert-card" role="alertdialog" aria-modal="true"
           aria-labelledby="alert-title" onClick={(e) => e.stopPropagation()}>
        <div className="alert-head">
          <span className="alert-siren" aria-hidden="true" />
          <b id="alert-title">새 신고 접수</b>
          <span className="alert-urg">조난 · DSC {x.type.dsc}</span>
        </div>

        <h2 className="alert-ship">{v?.name ?? x.ship}</h2>
        <p className="alert-reg mono">{v?.reg ?? ''}</p>

        <dl className="alert-rows">
          <div><dt>사고</dt><dd>{x.type.label}</dd></div>
          <div><dt>감지</dt><dd className="mono">{detect}</dd></div>
          <div><dt>신고 발신</dt><dd className="mono">{report}</dd></div>
          <div>
            <dt>위치</dt>
            <dd className="mono">{at[1].toFixed(4)}, {at[0].toFixed(4)}</dd>
          </div>
          <div>
            <dt>부표</dt>
            {/* 구조 쪽이 가장 먼저 묻는 것 — 바다에 찾을 주황색이 있는가 */}
            <dd>{x.map.buoy ? '발사됨 · 위치 들어오는 중' : '없음'}</dd>
          </div>
          {/* 목록 카드·상세와 같은 말을 쓴다 — 화면마다 다르면 같은 숫자를 다른 것으로 읽게 된다 */}
          <div><dt>의식 유지</dt><dd>예상 {shortLeft(s).replace('약 ', '')}</dd></div>
        </dl>

        <button className="alert-go" onClick={onClose}>사고 화면으로</button>
      </div>
    </div>
  );
}

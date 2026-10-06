import { useCallback, useState } from 'react';
import type { ReportChannelState } from '@floaq/shared';
import { useCommands, useKiosk } from '../state/store';
import { rejectText } from '../pi/reject';
import { IcoCheck, IcoWarn } from '../layout/Icons';

/**
 * 신고 중 표시 (`REPORT`) — `ref/kiosk_시연.md` §A 화면 넷 중 하나.
 *
 * <p>🔴 <b>전체 화면에서 상단 바로 내렸다</b> (2026-09-18 요청). 전체 화면은 <b>지도를 덮었고,
 * 그래서 부표가 어디 있는지 볼 수 없었다</b> — 신고가 나간 뒤 선원이 실제로 하는 일이 그것이다.</p>
 *
 * <p>다만 전체 화면으로 뒀던 이유는 그대로 살린다: 신고 뒤 알아야 할 것이 <b>채널별로 다르고</b>,
 * 실패한 채널을 못 보면 "신고했다"고 믿는다. 그래서 <b>지도 위에 떠 있는 작은 칩이 아니라
 * 폭 전체를 쓰는 바</b>다 — 실패 채널은 맨 앞에 크게 두고, 지도는 그 아래로 온전히 남는다.</p>
 *
 * <p>🔴 <b>`NO_INTERNET` 은 반드시 띄운다</b> — 안 그러면 사용자는 신고가 나간 줄 안다
 * (`ref/mqtt.md` §5.11).</p>
 *
 * <p>⚠ 채널 셋의 ACK 동작이 다르다. `DSC` 만 수신처가 ACK 을 보내고 그것이 <b>종료 신호</b>다 —
 * 받는 즉시 재송이 멈춘다. AIS 둘은 ACK 이 없어서 "확인됨"을 기대하면 안 된다.</p>
 */

const CH_NAME: Record<string, string> = {
  DSC: 'DSC 조난경보', AIS_MOB: 'AIS MOB', AIS_SART: 'AIS SART',
};

/** 채널 순서를 고정한다 — 들어온 순서대로 그리면 볼 때마다 자리가 바뀐다 */
const CH_ORDER = ['DSC', 'AIS_MOB', 'AIS_SART'] as const;

const FAIL_TEXT: Record<string, string> = {
  NO_INTERNET: '인터넷 두절 — 나가지 못했습니다',
  NO_RECEIVER: '수신처 없음',
  TIMEOUT: '응답 시간 초과',
};

const hm = (iso: string | null) =>
  (iso ? new Date(iso).toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');

function ChannelRow({ r }: { r: ReportChannelState }) {
  const tone = r.status === 'FAILED' ? 'alert'
    : r.status === 'ACKED' ? 'ok'
      : r.status === 'STOPPED' ? 'dim' : 'warn';
  const text = r.status === 'ACKED' ? '수신 확인'
    : r.status === 'FAILED' ? (FAIL_TEXT[r.failReason ?? ''] ?? '전송 실패')
      : r.status === 'STOPPED' ? '중지됨' : '전송 중';

  return (
    <li className={`rep-chip is-${tone}`}>
      <b className="rep-ch">{CH_NAME[r.channel] ?? r.channel}</b>
      <span className="rep-state">{text}</span>
      <span className="rep-meta mono">
        {r.sentCount > 0 && `${r.sentCount}회`}
        {r.lastSentAt && ` · ${hm(r.lastSentAt)}`}
        {/* ACK 을 보낸 국의 MMSI. 누가 받았는지가 구조 조율의 첫 정보다 */}
        {r.ackedBy && ` · ${r.ackedBy}`}
      </span>
    </li>
  );
}

export function ReportingLayer({ onAccepted }: { onAccepted?: (label: string) => void }) {
  const s = useKiosk();
  const { rescue, resolveIncident } = useCommands();
  const [busy, setBusy] = useState<string | null>(null);
  const inc = s.incident;

  const run = useCallback(async (label: string, fn: () => Promise<{ accepted: boolean; reason?: string }>) => {
    setBusy(`${label} 요청 중…`);
    try {
      const r = await fn();
      if (r.accepted) { setBusy(null); onAccepted?.(label); }
      else setBusy(`${label} 거절 — ${rejectText(r.reason as never)}`);
    } catch {
      setBusy(`${label} 실패 — Pi 응답 없음. 다시 누르세요`);
    }
  }, [onAccepted]);

  if (!inc || inc.status !== 'REPORTED') return null;

  const rows = CH_ORDER.map((c) => s.reports[c]).filter((r): r is ReportChannelState => !!r);
  const failed = rows.filter((r) => r.status === 'FAILED');

  return (
    <div className="rep-bar" role="alert">
      <span className="rep-bar-head">
        <IcoCheck size={26} />
        <b>신고 발신됨</b>
      </span>

      {/* 실패를 맨 앞에. 뒤에 두면 성공한 줄만 보고 지나간다 */}
      {failed.length > 0 && (
        <span className="rep-alarm">
          <IcoWarn size={22} />
          {failed.map((r) => CH_NAME[r.channel] ?? r.channel).join(' · ')} 실패 —
          {' '}{FAIL_TEXT[failed[0]?.failReason ?? ''] ?? '전송 불가'}
        </span>
      )}

      {rows.length > 0
        ? <ul className="rep-chips">{rows.map((r) => <ChannelRow key={r.channel} r={r} />)}</ul>
        : <span className="rep-empty">채널 상태를 기다리는 중입니다…</span>}

      {/* 부표 좌표는 지도에도 있다. 여기 숫자는 지도를 못 읽는 상황(확대·표류 원)에서의 백업이다 */}
      {s.buoy && (
        <span className="rep-buoy mono">
          부표 {s.buoy.lat.toFixed(4)}, {s.buoy.lon.toFixed(4)}
          {s.buoy.lost && ' · 두절 · 표류 추정'}
        </span>
      )}

      <span className="rep-spacer" />

      <span className="rep-actions">
        <button className="btn-rescue" disabled={!!busy}
          onClick={() => void run('구조 완료', () => rescue(inc.incidentId))}>
          {busy ? '보내는 중…' : '구조 완료'}
        </button>
        {/* ⚠ 종료가 오른쪽이고 색이 약하다. 되돌릴 수 없는 쪽이라 손이 먼저 가는 자리에 두지 않는다 */}
        <button className="btn-close-acc" disabled={!!busy}
          onClick={() => void run('사고 종료', () => resolveIncident(inc.incidentId))}>
          사고 종료<small>구조 못 함</small>
        </button>
      </span>

      {busy && <span className="rep-busy">{busy}</span>}
    </div>
  );
}

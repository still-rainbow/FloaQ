import { ROLE_LABEL } from '../lib/auth';
import type { Session } from '../lib/auth';

// 인터넷 연결 표시는 두지 않는다 — 관제는 인터넷이 끊길 일이 없다(2026-09-15). 선내 kiosk 에만 있다.

/**
 * 화면은 세 갈래다. 전에는 상단바에 `관제 | 계정 관리`, 왼쪽 목록 위에 `사고 | 등록 선박`,
 * 그 안에 또 `전체 | 진행 중 | 종결` 이 있어 <b>카드 한 장을 보기까지 선택지를 세 번</b> 지나야 했다.
 * 셋을 한 줄로 합쳤다(2026-09-17).
 */
export type View = 'live' | 'log' | 'accounts';


interface Props {
  session: Session;
  view: View;
  /** 상단 탭. 관리자(SA)에게만 `계정 관리` 가 붙는다 — 해경은 관제만 본다(WEB-01) */
  onView: (v: View) => void;
  canAccounts: boolean;
  /** 사고 탭 옆 숫자. 진행 중인 건수다 — 0 이면 붙이지 않는다 */
  liveCount: number;
  /**
   * 계정 관리 탭 옆 숫자. 승인을 기다리는 신청 수(해경 가입 + 선박 등록)다.
   * 해경 계정에는 그 탭 자체가 없어 늘 0 으로 온다.
   */
  pendingCount: number;
  /**
   * ⚠ 데모용. Pi 가 아직 없어 "새 신고가 들어오는 순간"을 볼 방법이 없다.
   * WebSocket 수신(api.md §6)이 붙으면 이 버튼은 사라진다.
   */
  onLogout: () => void;
  onSettings: () => void;
}

export function TopBar({ session, view, onView, canAccounts, liveCount, pendingCount, onLogout, onSettings }: Props) {
  return (
    <header className="topbar">
      {/* 로고는 <b>홈으로 가는 버튼</b>이다. 어느 화면에 있든 "지금 무슨 일이 벌어지나"로
          한 번에 돌아올 수 있어야 한다 — 웹에서 로고를 누르면 처음으로 가는 것은 몸에 밴 동작이다 */}
      <button className="brand" onClick={() => onView('live')} aria-label="사고 화면으로">
        <svg className="mascot bobbing" viewBox="0 0 32 32" aria-hidden="true">
          <circle cx="16" cy="16" r="11" fill="#e2643a" />
          <path d="M5 16a11 11 0 0 1 22 0Z" fill="#ffb185" />
          <circle cx="16" cy="16" r="5.1" fill="#0c2a3d" />
          <circle cx="13.9" cy="14.9" r="1.75" fill="#eafcff" />
          <circle cx="18.1" cy="14.9" r="1.75" fill="#eafcff" />
          <circle cx="14.25" cy="15.2" r=".85" fill="#06131f" />
          <circle cx="18.45" cy="15.2" r=".85" fill="#06131f" />
          <path d="M14.5 18.7q1.5 1.15 3 0" stroke="#eafcff" strokeWidth="1.05" fill="none" strokeLinecap="round" />
        </svg>
        <div className="brand-name">Floa<em>Q</em></div>
      </button>

      {/* 최상위 탭. 사고 → 기록 → (관리자만) 계정 관리 */}
      <nav className="view-tabs" role="tablist" aria-label="화면 전환">
        {(['live', 'log', ...(canAccounts ? ['accounts' as const] : [])] as View[]).map((k) => (
          <button key={k} className="view-tab" role="tab" aria-selected={view === k}
                  onClick={() => onView(k)}>
            {{ live: '사고', log: '기록', accounts: '계정 관리' }[k]}
            {/* 숫자는 <b>손댈 것이 있는 탭</b>에만. 0 이면 붙이지 않는다 — "0"을 보여 줄 이유가 없다.
                사고는 진행 중 건수, 계정 관리는 승인 대기 신청 수. 기록은 셀 것이 없다 */}
            {k === 'live' && liveCount ? <em className="view-tab-n mono">{liveCount}</em> : null}
            {k === 'accounts' && pendingCount
              ? <em className="view-tab-n mono">{pendingCount}</em> : null}
          </button>
        ))}

        {/* ⚠ 데모 버튼. 탭과 같은 줄에 두되 모양을 달리해 화면 전환과 섮이지 않게 한다 */}
      </nav>

      <div className="topbar-right">

        <button className="icon-btn" title="설정" aria-label="설정" onClick={onSettings}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3.1" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.7 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.1 4.7a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v.09a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1.03Z" />
          </svg>
        </button>

        {/* 로그인한 사람과 역할. 계정에 소속·계급을 두지 않는다 — 해경 쪽에서 알 수 없는 정보다 */}
        <div className="user" title={`${session.email} · ${ROLE_LABEL[session.role]}`}>
          <span className="avatar">{session.name.slice(0, 1)}</span>
          <span className="user-name">{session.name}</span>
          <em className="user-role">{ROLE_LABEL[session.role]}</em>
        </div>
        <button className="btn logout-btn" onClick={onLogout}>로그아웃</button>
      </div>
    </header>
  );
}

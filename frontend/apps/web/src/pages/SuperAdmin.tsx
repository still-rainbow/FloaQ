import { useCallback, useEffect, useState } from 'react';
import { SearchBox, matches } from '../components/SearchBox';
import type { ReactNode } from 'react';
import { applications, deactivate, decide } from '../lib/auth';
import type { Account, AdminError } from '../lib/auth';
import { decideShip, removeShip, shipRequests } from '../lib/shipRequests';
import { ADMIN_TAB_KEY, useSticky } from '../lib/sticky';
import type { ShipRequest } from '../lib/shipRequests';

// 슈퍼 관리자는 관제 화면을 쓰지 않는다. 계정 승인(W-04) · 선박 등록 승인(W-05) 둘만 본다.
// 통계(W-06)는 뺐다(2026-09-17). 남아 있던 화면·계산 코드도 지웠다(2026-09-20) —
// 옛 목데이터의 경위 문구로 판정하던 코드라 지금 데이터로는 틀린 값이 나왔다.
// 기관 계정을 셀프 가입으로 열 수 없다는 것이 승인 화면의 존재 이유다(계획.md §9.13).

const ADMIN_MESSAGE: Record<AdminError, string> = {
  expired: '로그인이 만료되었습니다. 다시 로그인해 주세요.',
  forbidden: '계정 관리 권한이 없습니다.',
  conflict: '이미 처리되었거나 없는 신청입니다. 목록을 다시 불러왔습니다.',
  server: '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  // 삭제를 막은 이유를 그대로 적는다 — "실패했습니다"만 뜨면 다시 누를 수밖에 없다
  'in-use': '진행 중인 사고가 있는 선박입니다. 사고가 종결된 뒤에 지울 수 있습니다.',
};

const SHIELD_ICON = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3 4.5 6v6c0 4.6 3.1 7.9 7.5 9 4.4-1.1 7.5-4.4 7.5-9V6Z" />
  </svg>
);

const SHIP_ICON = (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 17h16l-2 4H6Z" /><path d="M6 17V9l6-3 6 3v8" /><path d="M12 6V3" />
  </svg>
);

type Section = 'accounts' | 'ships';

/** 승인 목록 한 줄 — 해경 계정 신청과 선박 등록 요청이 같은 모양이다 */
interface ApprovalRow {
  id: string;
  title: string;
  meta: ReactNode;
  status: 'wait' | 'ok' | 'no';
  /**
   * 검색이 훑을 글자. {@link meta} 는 ReactNode 라 못 읽으므로 원본 값에서 따로 모은다 —
   * 화면에 보이는 것(이메일 · 등록번호)으로 찾을 수 있어야 검색이 쓸모가 있다.
   */
  search: string;
}

/**
 * 삭제 확인. 되돌릴 수 없는 동작이라 한 번 묻는다 — 목록은 줄이 븽븽해
 * 옆줄을 누르기 쉽고, 지우면 무엇이 어떻게 되는지를 버튼 이름만으로는 못 말한다.
 */
interface AskDelete { id: string; title: string }

/** 받침으로 갈리는 조사. 만들어 쓰는 문장이라 '을(를)' 같은 괄호를 적을 이유가 없다 */
const eulReul = (w: string) => {
  const code = w.charCodeAt(w.length - 1) - 0xac00;
  return code >= 0 && code <= 11171 && code % 28 ? '을' : '를';
};

const waitingOf = (rows: ApprovalRow[] | null) => rows?.filter((r) => r.status === 'wait').length ?? 0;

export function SuperAdmin() {
  /**
   * 한 페이지에 계정 신청 · 선박 요청을 다 쌓으니 처리한 신청까지 좌라락 늘어졌다(2026-09-15).
   * 위 탭으로 나누고, 할 일이 있는 해경 계정부터 연다.
   */
  /* 새로고침해도 보던 쪽에 남는다 — 선박 등록을 보다 F5 하면 해경 계정으로 튕겼다(lib/sticky.ts) */
  const [section, setSection] = useSticky<Section>(ADMIN_TAB_KEY, ['accounts', 'ships'], 'accounts');
  /** 응답을 기다리는 동안 버튼을 잠근다 — 두 번 누르면 두 번째가 409 로 떨어져 오류처럼 보인다 */
  const [busy, setBusy] = useState(false);

  /** 해경 계정 신청(WEB-07). null = 불러오는 중 */
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);

  const reloadAccounts = useCallback(async () => {
    const r = await applications();
    if (r.ok) setAccounts(r.list);
    else {
      setAccountError(ADMIN_MESSAGE[r.error]);
      setAccounts((prev) => prev ?? []);
    }
  }, []);
  useEffect(() => { void reloadAccounts(); }, [reloadAccounts]);

  /** 선박 등록 요청(WEB-08). ⚠ 신청 경로가 아직 없어 목록은 비어 있는 것이 정상이다 — lib/shipRequests.ts */
  const [ships, setShips] = useState<ShipRequest[] | null>(null);
  const [shipError, setShipError] = useState<string | null>(null);

  const reloadShips = useCallback(async () => {
    const r = await shipRequests();
    if (r.ok) setShips(r.list);
    else {
      setShipError(ADMIN_MESSAGE[r.error]);
      setShips((prev) => prev ?? []);
    }
  }, []);
  useEffect(() => { void reloadShips(); }, [reloadShips]);

  async function decideAccount(id: string, approve: boolean) {
    setBusy(true);
    setAccountError(null);
    const r = await decide(id, approve);
    if (!r.ok) setAccountError(ADMIN_MESSAGE[r.error]);
    // 성공이든 실패든 서버 상태로 다시 그린다 — 다른 관리자가 먼저 처리했을 수 있다
    await reloadAccounts();
    setBusy(false);
  }

  /** 해경 계정 삭제. 행은 남고 상태만 DELETED 로 바뀜다(lib/auth.ts deactivate) */
  async function removeAccount(id: string) {
    setBusy(true);
    setAccountError(null);
    const r = await deactivate(id);
    if (!r.ok) setAccountError(ADMIN_MESSAGE[r.error]);
    await reloadAccounts();
    setBusy(false);
  }

  /** 선박 삭제. 진행 중인 사고가 있으면 서버가 막는다 — 그 이유가 그대로 뜨다 */
  async function removeShipRow(id: string) {
    setBusy(true);
    setShipError(null);
    const r = await removeShip(id);
    if (!r.ok) setShipError(ADMIN_MESSAGE[r.error]);
    await reloadShips();
    setBusy(false);
  }

  async function decideShipRequest(id: string, approve: boolean) {
    setBusy(true);
    setShipError(null);
    const r = await decideShip(id, approve);
    if (!r.ok) setShipError(ADMIN_MESSAGE[r.error]);
    // 계정과 같다 — 성공이든 실패든 서버 상태로 다시 그린다. 다른 관리자가 먼저 처리했을 수 있다
    await reloadShips();
    setBusy(false);
  }

  const accountRows: ApprovalRow[] | null = accounts?.map((a) => ({
    id: a.id,
    title: a.name,
    meta: <><span className="mono">{a.email}</span> · 신청 {a.appliedAt}</>,
    status: a.status === 'wait' ? 'wait' : a.status === 'active' ? 'ok' : 'no',
    search: `${a.name} ${a.email}`,
  })) ?? null;

  const shipRows: ApprovalRow[] | null = ships?.map((s) => ({
    id: s.id,
    title: s.name,
    meta: <><span className="mono">{s.regNo}</span> · 승선 {s.crew}명 · 요청 {s.requestedAt}</>,
    status: s.status === 'wait' ? 'wait' : s.status === 'approved' ? 'ok' : 'no',
    search: `${s.name} ${s.regNo}`,
  })) ?? null;

  const tabs: [Section, string, number][] = [
    ['accounts', '해경', waitingOf(accountRows)],
    ['ships', '선박', waitingOf(shipRows)],
  ];

  return (
    <div className="admin-view">
      <div className="admin-wrap">
        <div className="dtabs admin-tabs" role="tablist" aria-label="계정 관리 전환">
          {tabs.map(([k, label, waiting]) => (
            <button key={k} role="tab" aria-selected={section === k} onClick={() => setSection(k)}
                    // title 로 건수를 달면 탭 이름("해경")이 가려져 읽힌다 — 이름과 건수를 함께 읽게 한다
                    aria-label={waiting ? `${label}, 승인 대기 ${waiting}건` : label}>
              {label}
              {/* 건수는 승인 대기다 — 할 일이 남았는지가 탭에서 보여야 한다 */}
              {waiting ? <span className="dtab-count mono">{waiting}</span> : null}
            </button>
          ))}
        </div>

        {section === 'accounts' ? (
          <Approvals
            title="해경 계정 가입 승인"
            lede="승인하면 신청한 기관 이메일로 로그인할 수 있습니다."
            icon={SHIELD_ICON}
            rows={accountRows}
            error={accountError}
            busy={busy}
            emptyWaiting="새 가입 신청이 들어오면 여기에 나옵니다."
            onDecide={decideAccount}
            onRemove={removeAccount}
            removeWhat="해경 계정"
            removeNote="이 계정은 다시 로그인할 수 없게 됩니다. 그동안 처리한 사고 기록은 그대로 남습니다."
          />
        ) : null}

        {section === 'ships' ? (
          <Approvals
            title="선박 등록 승인"
            lede="선내 단말에서 선박을 처음 등록하면 여기에 요청이 들어옵니다."
            icon={SHIP_ICON}
            rows={shipRows}
            error={shipError}
            busy={busy}
            emptyWaiting="새 선박 등록 요청이 들어오면 여기에 나옵니다."
            onDecide={decideShipRequest}
            onRemove={removeShipRow}
            removeWhat="등록 선박"
            removeNote="이 선박은 등록 목록에서 빠집니다. 지난 사고 기록은 그대로 남습니다."
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * 승인 목록. 처음엔 승인 대기만 보인다 — 처리한 신청은 "처리됨" 탭으로 옮겨 목록이 늘어지지 않게 한다.
 * 탭은 왼쪽 사고 목록의 상태 탭(전체 · 진행 중 · 종결)과 같은 모양이다.
 */
/** 한 쪽에 보이는 신청 수. 스크롤 대신 쪽으로 나눈다 — 페이지도 목록 칸도 늘어지지 않게 */
const PAGE_SIZE = 5;

function Approvals({ title, lede, icon, rows, error, busy, emptyWaiting, onDecide,
                    onRemove, removeWhat, removeNote }: {
  title: string;
  lede: string;
  icon: ReactNode;
  /** null = 불러오는 중 */
  rows: ApprovalRow[] | null;
  error: string | null;
  busy: boolean;
  emptyWaiting: string;
  onDecide: (id: string, approve: boolean) => Promise<void>;
  /** 승인된 줄을 지운다 */
  onRemove: (id: string) => Promise<void>;
  /** 묻는 문장에 들어갈 말 — '해경 계정' · '등록 선박' */
  removeWhat: string;
  /** 지우면 무엇이 어떻게 되는지 */
  removeNote: string;
}) {
  const [tab, setTab] = useState<'wait' | 'done'>('wait');
  const [page, setPage] = useState(0);
  const [ask, setAsk] = useState<AskDelete | null>(null);
  /** 승인 대기와 처리됨이 <b>같은 검색어</b>를 쓴다 — 찾는 사람은 어느 쪽에 있는지 모른다 */
  const [q, setQ] = useState('');
  const found = rows?.filter((r) => matches(q, r.title, r.search)) ?? null;
  const waiting = found?.filter((r) => r.status === 'wait') ?? [];
  const done = found?.filter((r) => r.status !== 'wait') ?? [];
  const list = tab === 'wait' ? waiting : done;
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  // 마지막 쪽의 신청을 승인·반려하면 그 쪽이 빈다 — 남아 있는 마지막 쪽으로 당긴다
  const cur = Math.min(page, pages - 1);
  const shown = list.slice(cur * PAGE_SIZE, (cur + 1) * PAGE_SIZE);

  return (
    <>
      <h2>{title}</h2>
      <p>{lede}</p>

      <div className="ftabs admin-ftabs" role="group" aria-label="처리 상태">
        {([['wait', '승인 대기', waiting.length], ['done', '처리됨', done.length]] as const).map(([k, label, n]) => (
          <button key={k} className="ftab" aria-pressed={tab === k} onClick={() => { setTab(k); setPage(0); }}>
            {label} <span className="ftab-count mono">{n}</span>
          </button>
        ))}
      </div>

      {/* 탭 밑에 둔다 — 어느 탭을 보고 있든 같은 검색어가 걸려 옮겨 다닐 필요가 없다 */}
      <div className="admin-search">
        <SearchBox value={q} onChange={(v) => { setQ(v); setPage(0); }}
                   hits={(waiting.length + done.length)}
                   placeholder={removeWhat === '해경 계정' ? '이름 · 이메일로 찾기' : '배 이름 · 등록번호로 찾기'} />
      </div>

      {error ? <p className="auth-error" role="alert">{error}</p> : null}
      {rows === null ? <div className="empty">불러오는 중…</div> : null}
      {/* 불러오기에 실패해 비어 있는 것을 "대기 없음"으로 보여 주면 신청을 놓친다 */}
      {rows && !list.length && !error ? (
        <div className="empty req-empty">
          <b>{tab === 'wait' ? '승인 대기 없음' : '처리한 신청 없음'}</b>
          {tab === 'wait' ? emptyWaiting : '승인하거나 반려한 신청이 여기에 모입니다.'}
        </div>
      ) : null}

      {shown.map((r) => (
        <div className="req" key={r.id}>
          <span className="vessel-avatar">{icon}</span>
          <span>
            <h3>{r.title}</h3>
            <p>{r.meta}</p>
          </span>
          {/* 칸을 늘리지 않고 자리를 바꾼다 — 3열 그리드가 무너지면 줄이 어긋난다 */}
          {r.status === 'wait' ? (
            <span className="req-act">
              <button className="btn primary" disabled={busy} onClick={() => { void onDecide(r.id, true); }}>승인</button>
              <button className="btn" disabled={busy} onClick={() => { void onDecide(r.id, false); }}>반려</button>
            </span>
          ) : (
            <span className="req-act">
              <span className={`req-done ${r.status === 'ok' ? 'yes' : 'no'}`}>{r.status === 'ok' ? '승인됨' : '반려됨'}</span>
              {/* 반려된 줄도 지운다(2026-09-20) — 반려는 "못 쓴다"까지만 정할 뿐 목록에서 치우지
                  않아서, 안 받기로 한 신청이 승인 화면에 계속 쌓였다. 대기 중인 줄에는 이 자리에
                  승인·반려가 있으니, 지울 수 있는 것은 이미 판정이 끝난 줄뿐이다 */}
              <button className="req-del" disabled={busy}
                      onClick={() => setAsk({ id: r.id, title: r.title })}>삭제</button>
            </span>
          )}
        </div>
      ))}

      {/*
        삭제 확인. 두 번 누르게 하는 방식은 첫 번째 누름이 무슨 뜻인지를 못 말해 준다 —
        무엇을 지우는지, 지우면 어떻게 되는지를 문장으로 묻는다(사고 종결 확인과 같은 모양).
      */}
      {ask ? (
        <div className="ask-veil" role="presentation" onClick={() => setAsk(null)}>
          <div className="ask-card" role="alertdialog" aria-modal="true" aria-labelledby="askDel"
               onClick={(e) => e.stopPropagation()}>
            <h2 id="askDel"><b>{ask.title}</b> {removeWhat}{eulReul(removeWhat)}<br />삭제하시겠습니까?</h2>
            <p>{removeNote}</p>
            <div className="ask-btns">
              <button className="ask-no" onClick={() => setAsk(null)}>취소</button>
              <button className="ask-yes" disabled={busy}
                      onClick={() => { const id = ask.id; setAsk(null); void onRemove(id); }}>
                삭제
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {pages > 1 ? (
        <nav className="pager" aria-label="목록 쪽 이동">
          <span className="pager-range">
            {cur * PAGE_SIZE + 1}–{Math.min(list.length, (cur + 1) * PAGE_SIZE)} / {list.length}건
          </span>
          <button className="btn" disabled={cur === 0} onClick={() => setPage(cur - 1)}>이전</button>
          {Array.from({ length: pages }, (_, i) => (
            <button key={i} className="btn pager-no" aria-current={i === cur ? 'page' : undefined}
                    aria-label={`${i + 1}쪽`} onClick={() => setPage(i)}>
              {i + 1}
            </button>
          ))}
          <button className="btn" disabled={cur === pages - 1} onClick={() => setPage(cur + 1)}>다음</button>
        </nav>
      ) : null}
    </>
  );
}

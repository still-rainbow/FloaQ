import { useEffect, useMemo, useRef, useState } from 'react';
import { FLEET, byVessel } from '../lib/fleet';
import { ButtonBadge, LoraBadge, URG } from '../components/Badges';
import { buoyState } from '../lib/buoyState';
import { currentLabel } from '../lib/stages';
import { isAdrift, isMob, silentPct, urgencyOf } from '../lib/kind';
import { noOf } from '../lib/mapNo';
import { LOG_TAB_KEY, useSticky } from '../lib/sticky';
import { ago, elapsed } from '../lib/time';
import { hhmm, leftPct, survival } from '../lib/survival';
import { byRecent, byUrgent, incidentsOf, isFresh } from '../lib/history';
import { SortMenu } from '../components/SortMenu';
import { SearchBox, matches } from '../components/SearchBox';
import { MapEye } from '../components/MapEye';
import type { Incident } from '../types';

const SHIP_SVG = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 17h16l-2 4H6Z" /><path d="M6 17V9l6-3 6 3v8" /><path d="M12 6V3" />
  </svg>
);

/** W-02 — 진행 중 사고는 상단에 고정한다. 종결 건을 스크롤로 찾게 만들면 안 된다. */
type StateFilter = 'all' | 'live' | 'done';
type Sort = 'urgent' | 'recent' | 'oldest';
type VesselSort = 'reg' | 'count' | 'recent' | 'name';

/** 가장 최근 사고. 사고가 없으면 undefined */
const lastOf = (hist: Incident[]) =>
  hist.reduce<Incident | undefined>((m, x) => (!m || byRecent(x, m) < 0 ? x : m), undefined);

interface Props {
  /**
   * 상단 탭이 정한다 — `live` 는 진행 중 사고만, `log` 는 종결된 사고와 등록 선박이다.
   * 전에는 이 패널이 자기 탭(사고/등록 선박)과 필터(전체/진행 중/종결)를 따로 들고 있어
   * 상단바까지 세 겹이었다. 상단 한 줄로 합쳤다(2026-09-17).
   */
  view: 'live' | 'log';
  /** App 이 들고 있는 사고 배열. 접수 확인이 목록에도 즉시 보여야 한다. */
  incidents: Incident[];
  selVessel: string | null;
  /** 상세를 보고 있는 사고 하나 */
  selIncident: string | null;
  /** 지도에 함께 띄운 사고들. 포커스와 별개다 — 여러 건을 나란히 보기 위한 것이다. */
  picked: string[];
  onSelect: (vesselId: string, wantTab?: 'incident') => void;
  /** 카드 클릭 — 지도를 그 사고로 옮기고 상세를 연다 */
  onFocusIncident: (x: Incident) => void;
  /** 토글 — 지도에 함께 띄울지 */
  onTogglePick: (x: Incident) => void;
  /** 선박 카드의 지도 스위치 — 한 건이면 그것, 여러 건이면 가장 최근 것을 켠다. 켜져 있으면 그 배의 사고를 전부 내린다 */
  onToggleVessel: (vesselId: string) => void;
  onClearPicks: () => void;
}

export function VesselListPane({
  view, incidents, selVessel, selIncident, picked, onSelect, onFocusIncident, onTogglePick, onToggleVessel, onClearPicks,
}: Props) {
  const listRef = useRef<HTMLElement>(null);

  // 지도에서 마커를 누르면 목록 밖에 있는 카드가 포커스될 수 있다. 보이지 않으면 고른 티가 안 난다.
  // block:'nearest' 라서 이미 보이는 카드는 화면을 흔들지 않는다.
  useEffect(() => {
    listRef.current?.querySelector('[aria-current="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  }, [selIncident]);
  /** 기록 탭 안에서만 갈라진다 — 종결된 사고인가, 등록 선박인가 */
  /* 새로고침해도 보던 쪽에 남는다 — 등록 선박을 훑다 F5 하면 종결된 사고로 튕겼다(lib/sticky.ts) */
  const [logTab, setLogTab] = useSticky(LOG_TAB_KEY, ['done', 'vessels'] as const, 'done');
  // 상단 탭이 곴 목록의 범위다. 사고 탭은 진행 중만, 기록 탭은 종결된 것만 보여 준다
  const state: StateFilter = view === 'live' ? 'live' : 'done';
  /*
   * 정렬은 <b>탭마다 따로</b> 기억한다. 하나로 두면 기록에서 최신 순을 고른 것이
   * 사고 탭까지 따라와, 다시 들어와도 급한 순으로 돌아오지 않았다(2026-09-17).
   * 고를 수 있는 값이 탭마다 다르기도 하다.
   */
  const [liveSort, setLiveSort] = useState<Sort>('urgent');
  const [logSort, setLogSort] = useState<Sort>('recent');
  const sort = view === 'live' ? liveSort : logSort;
  const setSort = view === 'live' ? setLiveSort : setLogSort;
  const [vSort, setVSort] = useState<VesselSort>('reg');
  /**
   * 검색어. <b>목록마다 따로 기억한다</b> — 사고에서 친 배 이름이 기록으로 따라오면
   * 거기 목록이 통째로 비어 "기록이 없다"로 읽힌다(2026-09-19).
   */
  const [qLive, setQLive] = useState('');
  const [qLog, setQLog] = useState('');
  const [qVessel, setQVessel] = useState('');
  const q = view === 'live' ? qLive : qLog;
  const setQ = view === 'live' ? setQLive : setQLog;

  const rows = useMemo(() => {
    const pass = (x: Incident) => {
      if (state === 'live' && x.state !== 'live') return false;
      if (state === 'done' && x.state === 'live') return false;
      return true;
    };

    /* 배 이름·등록번호로 거른다. 사고 자체에는 검색할 글자가 없어 배를 따라간다 */
    const list = incidents.filter(pass).filter((x) => {
      const v = byVessel[x.ship];
      return matches(q, v?.name, v?.reg, x.type.label);
    });

    // 진행 중이 항상 위. 그 안에서만 정렬 기준을 적용한다.
    // 급한 순의 기준은 lib/history.ts 에 둔다 — 화면을 열 때 그 첫 건을
    // 자동으로 여는데(App.tsx), 여기서 따로 정렬하면 둘이 어긋난다.
    return list.sort((a, b) => {
      if (sort === 'urgent') return byUrgent(a, b);
      const recent = Number(b.state === 'live') - Number(a.state === 'live') || byRecent(a, b);
      return sort === 'oldest' ? -recent : recent;
    });
  }, [incidents, state, sort, q]);

  const liveCount = incidents.filter((x) => x.state === 'live').length;

  // 상태 필터 버튼 옆 건수 — 눌렀을 때 뜨는 카드 수와 같아야 한다.
  const stateCount = { all: incidents.length, live: liveCount, done: incidents.length - liveCount };

  // 등록 선박 정렬. 한 배의 사고는 0건일 수도 여러 건일 수도 있어 이력을 한 번만 모아 둔다.
  const vessels = useMemo(() => {
    const rows = FLEET.filter((v) => matches(qVessel, v.name, v.reg)).map((v) => {
      const hist = incidentsOf(incidents, v.id);
      return { v, hist, live: hist.some((x) => x.state === 'live'), last: lastOf(hist) };
    });
    if (vSort === 'reg') return rows;
    type Row = (typeof rows)[number];
    // 사고가 없는 배는 최근 사고 비교에서 항상 뒤로 간다
    const byLast = (a: Row, b: Row) =>
      a.last && b.last ? byRecent(a.last, b.last) : Number(!a.last) - Number(!b.last);
    return [...rows].sort((a, b) => {
      if (vSort === 'count') return b.hist.length - a.hist.length || Number(b.live) - Number(a.live) || byLast(a, b);
      if (vSort === 'recent') return byLast(a, b);
      return a.v.name.localeCompare(b.v.name, 'ko');
    });
  }, [incidents, vSort, qVessel]);

  return (
    <section className="pane pane-pad list-pane" ref={listRef}>
      {/* 기록 탭 안에서만 갈라진다. 사고 탭은 볼 것이 한 종류라 줄이 필요 없다 */}
      {view === 'log' ? (
        <div className="seg" role="group" aria-label="기록 전환">
          <button aria-pressed={logTab === 'done'} onClick={() => setLogTab('done')}>
            종결된 사고 <span className="mono">{stateCount.done}</span>
          </button>
          <button aria-pressed={logTab === 'vessels'} onClick={() => setLogTab('vessels')}>
            등록 선박 <span className="mono">{FLEET.length}</span>
          </button>
        </div>
      ) : null}

      {/*
        지도에 뭐가 올라가 있는지는 <b>어느 목록을 보고 있든</b> 같은 사실이다 —
        사고 목록 안에 두었더니 등록 선박 탭에서는 사라져, 지도에 떠 있는 것을 내릴 길이 없었다(2026-09-18).
        목록 밖으로 내서 세 목록(사고·종결·등록 선박)이 한 줄을 같이 쓴다.
      */}
      {picked.length ? (
        <div className="pick-summary">
          지도에 <b>{picked.length}건</b> 함께 표시 중
          <button className="chip-toggle" onClick={onClearPicks}>전부 해제</button>
        </div>
      ) : null}

      {/* ── W-02 사고 목록 ── */}
      <div hidden={view === 'log' && logTab === 'vessels'}>
        <div className="fbar">
          <SearchBox value={q} onChange={setQ} hits={rows.length}
                     placeholder="배 이름 · 등록번호로 찾기" />
          <SortMenu value={sort} onChange={setSort} label="정렬"
                    title={sort === 'urgent' ? '저체온증 기준 잔여시간이 짧은 순' : undefined}
                    options={view === 'live'
                      ? ([['urgent', '급한 순'], ['recent', '최신 순']] as const)
                      : ([['recent', '최신 순'], ['oldest', '오래된 순']] as const)} />
        </div>

        <div className="list inc-list">
          {rows.map((x) => {
            const v = byVessel[x.ship]!;
            const live = x.state === 'live';
            const s = survival(x.waterTemp, x.elapsedSec);
            /*
             * 카드 색은 긴급도가 아니라 **지금 얼마나 급한가**를 따른다.
             * 관제에 오는 사고는 대부분 조난이라 긴급도로 칠하면 전부 같은 빨강이 된다 —
             * 색이 아무것도 구분해 주지 못했다(2026-09-17).
             *
             * 재는 값은 유형에 따라 다르지만 묻는 것은 하나다 — 이 숫자가 0이 되면 늦는다.
             *   MOB   → 의식 유지 예상 시간(저체온증)
             *   그 외 → 마지막 소식 이후 경과 · DSC 위험도 중 급한 쪽(lib/kind.ts)
             */
            const lv = urgencyOf(x);
            const silentSec = x.map.shipAgeSec ?? 0;
            /*
             * 카드는 <b>항상 통째로</b> 보여 준다. 한니 보고 있는 카드만 펼치게 해 봤는데,
             * 그러면 지도에 안 올린 사고의 <b>부표 연결과 사람이 잡았는지를 못 보게 된다</b> —
             * 그걸 보고 어느 사고를 먼저 여는지 정하는 것이다. 줄이 늘어난다면 그것보다 낫다(2026-09-18).
             */
            const bs = live && isMob(x) ? buoyState(x) : null;
            return (
              <div key={x.id}
                   className={`inc-card lv-${lv}${live ? ' is-live' : ''}`
                     + (picked.includes(x.id) ? ' is-picked' : '')}
                   aria-current={x.id === selIncident ? 'true' : undefined}>
                <button className="inc-card-body"
                        title="지도를 이 사고로 옮기고 상세를 봅니다"
                        onClick={() => onFocusIncident(x)}>
                  {/*
                    보는 중 배지는 <b>글 흐름 밖</b>에 둔다. 줄 안에 끼우면 붙는 순간 줄이 꺾여
                    카드가 20px 커지거나(목록이 움직인다) 시각이 … 로 잘렸다(2026-09-17).
                    이름 줄은 오른쪽을 늘 비워 두므로 배지가 있든 없든 크기가 같다.
                  */}
                  {/*
                    ⚠ 새 신고는 급한 순을 무시하고 맨 위에 선다(lib/history.ts `isFresh`).
                    줄을 서지 않은 카드는 <b>왜 거기 있는지 말해야 한다</b> — 아무 표시가 없으면
                    정렬이 고장 난 것으로 보인다(2026-09-17).
                    자리는 하나뿐이라 새 신고가 이긴다. 보는 중은 테두리가 이미 말하고 있다.
                  */}
                  {isFresh(x)
                    ? <b className="inc-now-tag is-new">새 신고</b>
                    : x.id === selIncident ? <b className="inc-now-tag">보는 중</b> : null}

                  {/* 배 이름과 유형은 한 덩어리다 — "보성호 인명 추락"이 한 번에 읽힌다 */}
                  <div className="inc-card-top">
                    {noOf(picked, x.id) > 0
                      ? <i className="inc-no" title="지도에 표시된 번호">{noOf(picked, x.id)}</i>
                      : null}
                    <h3>
                      {v.name}
                      <b title={x.type.dsc ? `DSC ${x.type.dsc}` : undefined}>
                        {x.type.label}{isAdrift(x) ? ' · 표류 중' : ''}
                      </b>
                    </h3>
                  </div>

                  {/*
                    배지는 이름 줄이 아니라 아랫줄에 둔다. 이름·유형·보는 중·완료를 한 줄에 쌓으면
                    좁은 카드에서 <b>배 이름이 두 줄로 꺾인다</b>("해동 / 호") — 제일 먼저 읽혀야 할 것이
                    제일 먼저 깨졌다(2026-09-17).
                  */}
                  <p className="inc-card-when">
                    {/* 경과가 제일 큼 — 새 신고는 이 숫자가 작아서 튀어나온다. 시각은 근거라 작게 */}
                    {/* 배지가 붙어도 줄이 늘지 않게 한 칸에 가둔다 — 자리가 모자라면
                        카드가 세로로 커지는 대신 이쪽이 … 로 줄어든다(2026-09-17) */}
                    <span className="when-main">
                      {live
                        ? <><b className="inc-elapsed">{elapsed(x.elapsedSec)}</b> 경과
                            {/* 초는 뗀다 — 정확한 시각은 경과 카운터와 오른쪽 경위가 답한다.
                                 초까지 두면 단계가 들어갈 자리가 없어 경과가 잘렸다 */}
                            <span className="inc-clock mono">{x.head.split(' · ')[0]!.slice(0, 5)}</span></>
                        : (() => {
                            /*
                             * 끝난 사고는 <b>어떻게 끝났는지</b>를 적는다. 목 데이터의 head 를 그대로 쓰니
                             * 익수는 '6분 31초 만에 구조'(주로 걸린 시간), 그 외는 '예인 완료'(주로 결과)로
                             * 한 목록 안에서 두 가지 말을 하고 있었다 — 걸린 시간은 여기서 물어볼 것이 아니다.
                             * 종결 사유(stages.close.note)에서 바로 짓어 목록 전제를 맞춘다(2026-09-18).
                             */
                            const at = (x.stages.detect.at ?? x.head.split(' · ')[0] ?? '').slice(0, 5);
                            const done = x.stages.close.note
                              ?? (x.state === 'cancel' ? '취소' : '종결');
                            return <>{x.day} <span className="mono">{at}</span> · {done}</>;
                          })()}
                    </span>
                    {/* 단계는 시각 줄 오른쪽 끝에. 부표 문장 옆에 두면 좁은 카드에서
                        둘 다 두 줄로 꺾였다("사람은 / 따로", "구조대 대응 단 / 계") */}
                    {live ? <span className="when-stage">{currentLabel(x)} 단계</span> : null}
                    <span className="inc-tags">
                      {/* 진행 중은 카드 전체가 이미 말한다. 종결 쪽(완료·취소)만 배지로 찍는다 */}
                      {!live && x.badge[0] !== '진행 중'
                        ? <span className={`badge ${x.badge[1]}`}>{x.badge[0]}</span>
                        : null}
                    </span>
                  </p>

                  {/*
                    부표 줄은 <b>한 문장</b>이다. 전에는 `신호 ○ · 사람 ✕` 처럼 축을 따로 찍었는데
                    처음 보는 사람에게 다 막혔다 — 특히 `사람 ✕` 가 "사람이 없다"로 읽혔다.
                    진짜 정보는 두 축의 <b>조합</b>에 있어서 조합의 이름을 쓴다(lib/buoyState.ts).
                    색은 <b>신호 한 축만</b> 맡는다(들어오는 중 초록 · 끊김 빨강). 색을 조합으로 정하니
                    "2초 전 신호"가 노랗게 나와 색과 글자가 다른 말을 했다. 사람이 안 잡은 것은 ⚠ 로 찍는다.
                  */}
                  {bs ? (() => {
                    return (
                      <p className="buoy-line">
                        <span className={`bl-state tone-${bs.tone}`} title={bs.why}>
                          <i className="bl-dot" aria-hidden="true" />
                          {bs.text}
                          {/* 색은 신호가 쓰므로, 사람이 안 잡은 것은 ⚠ 로 표시한다 */}
                          {bs.tail
                            ? (
                              <em className={`bl-tail${bs.notHeld ? ' is-notheld' : ''}`}>
                                {' · '}{bs.notHeld ? '⚠ ' : ''}{bs.tail}
                              </em>
                            )
                            : null}
                        </span>
                      </p>
                    );
                  })() : null}

                  {/*
                    남은 시간을 <b>막대로</b> 보인다. 숫자는 읽어야 알지만 길이는 읽기 전에 보인다 —
                    카드가 여러 장일 때 "누가 제일 급한가"를 훑는 데 이게 제일 빠르다.
                  */}
                  {live && isMob(x) ? (
                    <div className="inc-left"
                         title="저체온증 생존곱선표 기준 · 의식을 유지할 가능성이 높은 시간입니다. 의료적 확정치가 아닙니다">
                      <span className="il-bar"><i style={{ width: `${leftPct(s)}%` }} /></span>
                      {/*
                        숫자만 두면 위에 있는 '50분 55초 경과' 와 구분이 안 돼 어느 쪽이
                        남은 시간인지 헷갈렸다. 두 줄이 같은 모양으로 끝나게 한다 —
                        윗줄은 …경과, 아랫줄은 …남음(2026-09-18).
                      */}
                      {/*
                        🔴 장기 미종결은 <b>남은 시간을 말하지 않는다.</b> `상한 초과` 는 여전히
                        생존 시계의 언어인데, 이틀 지난 사고에 그 말을 붙이면 아직 재고 있는 것처럼
                        읽힌다. 그때 필요한 정보는 <b>얼마나 안 닫혔나</b>다(2026-09-19).
                      */}
                      <span className="il-txt">
                        {lv === 'stale' ? <>{elapsed(x.elapsedSec).split(' ')[0]}<em>째 미종결</em></>
                          : Number.isFinite(s.consciousLeftMin)
                            ? (s.past ? '상한 초과' : <>{hhmm(s.consciousLeftMin)}<em>남음</em></>)
                            : '—'}
                      </span>
                    </div>
                  ) : null}

                  {/*
                    MOB 의 남은 시간 막대와 <b>같은 자리·같은 모양</b>이다. 재는 값만 다르다 —
                    여기서 0 이 된다는 것은 배에서 아무것도 못 보내고 있다는 뜻이다.
                  */}
                  {live && !isMob(x) ? (
                    <div className="inc-left"
                         title="배에서 마지막으로 위치가 올라온 뒤 지난 시간입니다. 길이가 줄어들수록 지금 상황을 모르는 것입니다">
                      <span className="il-bar"><i style={{ width: `${silentPct(silentSec)}%` }} /></span>
                      <span className="il-txt">
                        {silentSec > 0 ? <>{ago(silentSec)}<em>전 수신</em></> : '수신 중'}
                      </span>
                    </div>
                  ) : null}
                </button>

                {/* 지도에 올릴지 내릴지 — 켜고 끄는 것이므로 스위치가 맞다. */}
                <button className="inc-pick" role="switch"
                        aria-checked={picked.includes(x.id)}
                        title={picked.includes(x.id) ? '지도에서 내리기' : '지도에 함께 표시'}
                        onClick={() => onTogglePick(x)}>
                  <MapEye on={picked.includes(x.id)} />
                  <em>지도에 표시</em>
                </button>
              </div>
            );
          })}
          {/*
            빈 목록이 <b>사실을 그대로</b> 말해야 한다. `해당 사고 없음 · 필터를 바꿔 보세요` 는
            거를 필터가 화면에 없는데도 사용자에게 할 일을 떠넘겼다 — 진행 중인 사고가 없는 것은
            정상이고 좋은 상태다(2026-09-19).
          */}
          {!rows.length ? (
            <div className="empty">
              {view === 'live'
                ? <><b>진행 중인 사고가 없습니다</b>새 신고가 들어오면 여기에 뜹니다.</>
                : <><b>종결된 사고가 없습니다</b>사고가 끝나면 여기에 쌓입니다.</>}
            </div>
          ) : null}
        </div>
      </div>

      {/* ── 등록 선박 ── */}
      <div hidden={!(view === 'log' && logTab === 'vessels')}>
        {/* 선박에는 거를 상태가 없다. 사고 탭의 보조 줄과 같은 모양으로 검색·정렬만 둔다 */}
        <div className="fbar">
          <SearchBox value={qVessel} onChange={setQVessel} hits={vessels.length}
                     placeholder="배 이름 · 등록번호로 찾기" />
          <SortMenu value={vSort} onChange={setVSort} label="선박 정렬"
                    options={[['reg', '등록 순'], ['count', '사고 많은 순'], ['recent', '최근 사고 순'], ['name', '이름 순']] as const} />
        </div>
        {/* 좁은 화면에서는 이름과 사고 여부 점만 남긴 가로 칩이 된다(web.css .vessel-list) */}
        <div className="list vessel-list">
          {vessels.map(({ v, hist }) => {
            // 이력은 진행 중이 맨 앞에 온다(incidentsOf).
            const live = hist[0]?.state === 'live' ? hist[0] : undefined;
            // 건수가 먼저다 — 지난 사고가 있는 배인지가 이 목록을 여는 이유다. 진행 중이면 뒤에 붙인다
            const line = `사고 ${hist.length}건${live ? ' · 진행 중' : ''}`;
            // 그 배의 사고가 하나라도 지도에 올라가 있으면 켜짐
            const on = hist.some((h) => picked.includes(h.id));
            return (
              // 진행 중이면 사고 카드와 같은 긴급도 색(조난 빨강 · 긴급 노랑 · 안전 초록)을 입힌다
              <div key={v.id} className={`vessel-card${live ? ` is-live ${URG[live.type.urg][1]}` : ''}${on ? ' is-picked' : ''}`}
                   aria-current={v.id === selVessel ? 'true' : undefined}>
                <button className="vessel-card-body" onClick={() => onSelect(v.id)}>
                  <span className="vessel-avatar">{SHIP_SVG}</span>
                  <span className="vessel-card-text"><h3>{v.name}</h3><p>{line}</p></span>
                </button>
                {/* 사고 카드와 같은 지도 스위치. 진행 중 사고가 없으면 회색 칸이다 —
                    점 대신 이 스위치가 "지금 사고 중인가"를 말한다. 사고가 한 건도 없는 배만 잠근다. */}
                <button className="inc-pick vessel-pick" role="switch"
                        aria-checked={on}
                        disabled={!hist.length}
                        title={!hist.length ? '사고 기록 없음'
                          : on ? '지도에서 내리기'
                            : hist.length > 1 ? '가장 최근 사고를 지도에 표시' : '사고를 지도에 표시'}
                        onClick={() => onToggleVessel(v.id)}>
                  <MapEye on={on} />
                  <em>지도에 표시</em>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

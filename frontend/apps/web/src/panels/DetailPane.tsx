import { useEffect, useState } from 'react';
import { oceanRows } from '../lib/oceanRows';
import { Readings } from './Readings';
import { URG } from '../components/Badges';
import { buoyState } from '../lib/buoyState';
import { SurvivalMeter } from '../components/SurvivalMeter';
import { Coord } from '../components/Coord';
import { incidentView } from '../lib/view';
import { useSea } from '../lib/useSea';
import { BASIS_TEXT } from '../lib/ocean';
import type { SeaReading } from '../lib/ocean';
import { isAdrift, isMob } from '../lib/kind';
import { OUTCOME_FACTS, secOfClock } from '../lib/facts';
import { STEPS } from '../lib/drift';
import { currentLabel, stagesOf } from '../lib/stages';
import { noOf } from '../lib/mapNo';
import { elapsed } from '../lib/time';
import { MapEye } from '../components/MapEye';
import type { DetailTab, Incident, Reading, Vessel } from '../types';

/** 지금으로부터 얼마 전. `2분 05초 전` · `8초 전` · `방금` */
const agoText = (sec: number) => {
  const s = Math.round(sec);
  if (s < 1) return '방금';
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}분 ${String(s % 60).padStart(2, '0')}초 전` : `${s}초 전`;
};

const pad = (n: number, w: number) => String(n).padStart(w, '0');

export function clock(sec: number) {
  const w = Math.floor(sec);
  const d = Math.floor((sec - w) * 10);
  return `${pad(Math.floor(w / 3600) % 24, 2)}:${pad(Math.floor(w / 60) % 60, 2)}:${pad(w % 60, 2)}.${d}`;
}

interface Props {
  vessel: Vessel | null;
  incident: Incident | null;
  /** 고른 선박의 사고 이력. 0건일 수도 여러 건일 수도 있다 — 진행 중이 위, 나머지는 최신 순 */
  history: Incident[];
  /** 이력 한 줄을 누르면 지도와 상세를 그 사고로 옮긴다 */
  onPickIncident: (x: Incident) => void;
  /** 지도에 함께 띄운 사고들 — 카드의 지도 스위치와 번호가 여기서 나온다 */
  picked: string[];
  /** 카드의 지도 스위치. 켜면 카드를 누른 것과 같다(지도에 올리고 그 사고로 포커스) */
  onTogglePick: (x: Incident) => void;
  /** 여러 건 중 하나를 보다가 카드 목록으로 돌아간다 */
  tab: DetailTab;
  onTab: (t: DetailTab) => void;
  resolvedBy: Record<string, string>;
  onResolve: (x: Incident) => void;
  /**
   * 🔴 관리자다 — <b>보되 손대지 않는다</b>(App.tsx isAdmin). 종결·영상 중단 같은 대응 동작을 숨긴다.
   * `live` 를 끄지 않는 이유는, 그러면 진행 중 사고가 <b>종결된 것처럼</b> 그려지기 때문이다.
   */
  readOnly?: boolean;
  /** 해경 접수 확인(신규 3) — W-03 진입이 트리거다 */
  onAck: (x: Incident) => void;
  /** 영상 그만 받기 — 사고 후 구간을 종결 전에 끝낸다 */
  onStopVideo: (x: Incident) => void;
  /** 종료 리포트 열기. 종결된 사고에서만 부른다 */
  onReport: (x: Incident) => void;
  /** 표류 슬라이더의 Δt. 지도와 같은 값을 봐야 좌표가 어긋나지 않는다. */
  dt: number;
}

export function DetailPane({
  vessel, incident, history, onPickIncident, picked, onTogglePick, tab, onTab, resolvedBy, onResolve, onAck, onStopVideo, onReport, readOnly, dt,
}: Props) {
  const x = incident;
  const sea = useSea(incident);
  /** 해양 정보 표 — 하드코딩이 아니라 서버에서 받은 값으로 만든다(lib/oceanRows.ts) */
  const cats = oceanRows(sea, incident?.waterTemp);
  const live = x?.state === 'live' && !resolvedBy[x.id];
  const shipCoord = x?.map.ship;
  /** 해양 정보는 평소 접어 둔다. 사고를 바꿔 봐도 열어 둔 상태는 유지한다. */
  const [oceanOpen, setOceanOpen] = useState(false);

  /*
   * 해경 접수는 여기서 찍지 않는다(2026-09-17). 사고가 관제 목록에 오르는 순간이 곴 접수라
   * App 이 진행 중인 사고 전부에 한 번씩 찍는다 — 여는 사람을 기다리면 열지 않은 사고가
   * ② 구조 요청 에 멈춰 "신고가 안 닿았다"로 보인다.
   */

  // 사고 중이 아니면 그 배가 어디 있는지 알 수 없다 — 위치는 사고 중에만 받는다.
  // 모르는 것을 아는 체하지 않고 관할 해역을 기준으로 둠다.
  const base = live && shipCoord
    ? `기준 지점: 사고 위치 ${shipCoord[1].toFixed(3)}, ${shipCoord[0].toFixed(3)}`
    : '기준 지점: 관할 해역';

  return (
    <section className="pane pane-pad">
      <div className="detail-head">
        <div>
          <h2>{vessel ? vessel.name : '선박 미선택'}</h2>
          <p>{vessel ? vessel.reg : '왼쪽 목록에서 선박을 고르세요'}</p>
        </div>
        {/*
          진행 중에는 배지를 달지 않는다 — 사고 탭에 있는 것은 전부 진행 중이라
          '진행 중' 이 아무것도 구분해 주지 않는다(2026-09-18).
          끝난 사고만 어떻게 끝났는지를 배지로 찍는다 — 완료 · 취소.
        */}
        {x && x.state !== 'live'
          ? <span className={`badge ${x.state === 'cancel' ? 'cancel' : 'resolved'}`}>
              {x.state === 'cancel' ? '취소' : '완료'}
            </span>
          : null}
      </div>

      <div className="dtabs" role="tablist" aria-label="상세 전환">
        {(['ship', 'incident'] as DetailTab[]).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k}
                  // 선박을 골랐으면 0건이어도 연다. 막아 두면 흐려져서 "0"이 안 읽힌다.
                  disabled={k === 'incident' && !x && !vessel}
                  onClick={() => onTab(k)}>
            {{ ship: '선박', incident: '사고' }[k]}
            {k === 'incident' && vessel ? <span className="dtab-count mono">{history.length}</span> : null}
          </button>
        ))}
      </div>

      {/* 선박 — 좌표 대신 등록 정보와 센서 상태를 본다 */}
      <div hidden={tab !== 'ship'}>
        {!vessel ? (
          <div className="empty">
            <b>선박 미선택</b>
            {/* 한 줄로 흘리면 "고르면"과 "제원과 상태가" 사이에서 아무 데나 접힌다.
                조건과 결과 사이에서 끊어 읽히게 줄을 나눈다 */}
            왼쪽 목록에서 선박을 고르면<br />제원과 상태가 여기 나옵니다.
          </div>
        ) : (
          <>
            {/*
              센서·영상 상태(`vessel.dev`)는 뺐다(2026-09-17). 선내 장비 상태라 해경이 보고 할 일이 없고,
              그 안에서 관제에 쓸모 있는 "부표 두절"은 사고 카드 배지·지도 마커·부표 상세에 이미 나온다.
            */}
            <Readings rows={[
              ['선박번호', `<span class="mono" style="font-size:calc(13px * var(--t-k))">${vessel.reg}</span>`, '', 0],
              // 위치는 사고 중일 때만 받는다. 받지 않는 값을 '수신 안 함'으로 적어 둘 이유가 없다.
              ...(live && shipCoord
                ? [['위치',
                    `<span class="mono" style="font-size:calc(13px * var(--t-k))">${shipCoord[1].toFixed(4)}, ${shipCoord[0].toFixed(4)}</span>`,
                    '', 0] as Reading]
                : []),
            ]} />
            {/*
              이 문구가 답하는 질문은 "왜 위치 칸이 없지?" 다. 그러니 <b>위치 칸이 없을 때만</b> 띄운다 —
              항상 띄우면 좌표가 멀쩡히 보이는 화면 밑에 "받지 않습니다"가 붙어 앞뒤가 안 맞는다.
            */}
            {live && shipCoord ? null : (
              <p className="src-note">
                평시에는 선박 위치를 받지 않습니다. 사고가 나면 그때부터 실시간으로 받습니다.
              </p>
            )}

            {/* 한 배에 사고가 여러 건일 수 있다. 사고 탭은 한 건만 보여 주므로 나머지로 가는 길이 여기 있어야 한다. */}
            <section className="hist">
              <div className="section-label">
                <h3>사고 이력</h3><span className="eyebrow mono">{history.length}건</span>
              </div>
              {history.length ? (
                <ol className="hist-list">
                  {history.map((h) => {
                    const on = picked.includes(h.id);
                    const no = noOf(picked, h.id);
                    return (
                      // 이력 한 줄에도 사고 카드와 같은 지도 스위치를 단다. 켜면 그 사고로 포커스가 간다
                      <li key={h.id} data-urg={h.type.urg}
                          className={`hist-item${on ? ' is-picked' : ''}${h.id === x?.id ? ' is-current' : ''}`}>
                        <button className="hist-row"
                                aria-current={h.id === x?.id ? 'true' : undefined}
                                onClick={() => onPickIncident(h)}>
                          {no > 0 ? <i className="inc-no" title="지도에 표시된 번호">{no}</i> : null}
                          {/*
                            유형·시각·배지를 한 줄에 세우면 좁은 패널에서 유형이 "기관 ···" 으로 잘린다.
                            무슨 사고였는지가 이 줄의 요점이라 그것부터 온전히 보이게 두 줄로 나눈다.
                          */}
                          <span className="hist-main">
                            <b title={h.type.dsc ? `DSC ${h.type.dsc}` : undefined}>{h.type.label}</b>
                            <span className="mono hist-when">
                              {h.day} {(h.head.split(' · ')[0] ?? '').slice(0, 5)}
                            </span>
                          </span>
                          {/*
                            이력 줄의 배지는 <b>끝났는지 아닌지</b>만 말한다. 사고의 badge 는 진행 중일 때
                            부표 상태를 다시 적는다('부표 신호 끊김') — 그런다니 이력 목록에서 어느 것이
                            진행 중인지가 한니도 안 읽혔다. 부표 상태는 그 사고를 여면 상세가 말해 준다(2026-09-18).
                          */}
                          {h.state === 'live'
                            ? <span className="badge warn">진행 중</span>
                            : h.state === 'cancel'
                              ? <span className="badge cancel">취소</span>
                              : <span className="badge resolved">완료</span>}
                        </button>
                        {/* 목록 카드와 같은 눈이다. 같은 일을 하는 자리가 화면마다 다르게 생기면 안 된다 */}
                        <button className="hist-pick" role="switch" aria-checked={on}
                                title={on ? '지도에서 내리기' : '지도에 함께 표시'}
                                aria-label={on ? '지도에서 내리기' : '지도에 함께 표시'}
                                onClick={() => onTogglePick(h)}>
                          <MapEye on={on} />
                        </button>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <div className="empty"><b>사고 기록 없음</b>{vessel.name} 에 접수된 사고가 없습니다.</div>
              )}
            </section>
          </>
        )}

      </div>

      {/* 사고 = W-03 */}
      <div hidden={tab !== 'incident'}>
        {x ? (
          <>
            {/*
              그 배의 다른 사고로 가는 길은 <b>선박 탭의 사고 이력</b> 하나다(2026-09-18).
              여기에도 카드 목록을 여는 버튼을 두었는데, 그 목록이 선박 탭 이력과 같은 것을
              모양만 달리 그리고 있었다. 사고 탭은 <b>한 건의 상세</b>만 맡는다.
            */}
            <IncidentTab x={x} live={!!live} resolvedBy={resolvedBy} dt={dt} onReport={onReport}
                         onResolve={onResolve}
                         onStopVideo={onStopVideo} readOnly={!!readOnly} />

            {/*
              해양 정보. 패널 맨 아래 — 상황을 읽고 난 뒤에 "근거가 뭐지"를 묻는 자리다.

              🔴 <b>사고마다 그때의 바다를 보여 준다</b>(types.ts OceanSnap). 종결된 사고에
              '지금 바다'를 띄우면 9월 7일 사고를 여는 사람이 <b>오늘 바람을 그런 바람으로</b>
              읽게 된다. 진행 중일 때만 '지금'이 곶 그때라 받는 값을 그대로 쓴다(2026-09-18).
            */}
            <div className={`ocean${oceanOpen ? ' is-open' : ''}`}>
              <button className="ocean-toggle" aria-expanded={oceanOpen}
                      onClick={() => setOceanOpen((o) => !o)}>
                <span className="ocean-i" aria-hidden="true">i</span>
                <b>해양 정보</b>
                {/* ⚠ 여기에 관측 시각을 적지 않는다. `사고 당시 · 11:00` 은 <b>사고가 11시에 났다</b>로
                    읽힌다 — 10:38 사고인데 그렇게 보였다(2026-09-21). 관측 시각은 표 안의 줄이
                    "9월 21일 11:00 값"으로 적고, 여기서는 어느 때 값인지만 말한다 */}
                <span className="ocean-sub">{live ? '지금 받는 값' : '사고 당시'}</span>
                <span className="ocean-caret" aria-hidden="true">▾</span>
              </button>
              {oceanOpen ? (
                <div className="ocean-body">
                  {(['safe', 'nav'] as const).map((k) => (
                    <div key={k}>
                      <div className="section-label">
                        <h3>{cats[k].title}</h3>
                        <span className="eyebrow">{cats[k].src}</span>
                      </div>
                      {/* 받는 값만 적는다 — 빈 표는 '값이 없다'를 그대로 말한다(lib/oceanRows.ts) */}
                      {cats[k].rows.length
                        ? <Readings rows={cats[k].rows} />
                        : (
                          /* 칸마다 긴 문장을 두 번 적지 않는다. 까닭은 아래 한 줄이 맡는다 */
                          <p className="src-note">{live ? '받고 있는 값이 없습니다.' : '기록이 없습니다.'}</p>
                        )}
                    </div>
                  ))}
                  {/* 표 밑 한 줄 — 이 숫자들이 <b>언제·어디</b> 것인지. 값이 없을 때는 왜 없는지 */}
                  <p className="src-note">
                    {live
                      ? base
                      : sea
                        /* 조류 예보는 정시 단위라 사고 시각과 최대 30분 벌어진다.
                           그 차이를 감추면 표의 시각이 왜 사고 시각과 다른지 알 수 없다 */
                        ? `사고 시각(${x.stages.detect.at ?? '—'})에 가장 가까운 관측·예보 값입니다 — 지금 바다와 다릅니다.`
                        /* 해양 관측은 24시간만 보관한다(OceanRetention.WINDOW). "못 받았다"가 아니라
                           "이제 없다"가 맞는 말이다 — 고장으로 읽히면 안 된다 */
                        : '해양 관측값은 24시간만 보관합니다 — 이 사고는 그보다 오래됐습니다.'}
                  </p>
                </div>
              ) : null}
            </div>
          </>
        ) : vessel && history.length ? (
          /*
           * 여기에 그 배의 사고 카드 목록을 다시 그렸는데, 선박 탭의 사고 이력과
           * 같은 것을 모양만 달리 보여 준 셈이었다 — 길은 한 군데로 모았다(2026-09-18).
           */
          <div className="empty">
            <b>볼 사고를 고릅니다</b>
            {vessel.name} 사고 {history.length}건은 <b style={{ display: 'inline', fontSize: 'inherit', margin: 0 }}>선박 탭 · 사고 이력</b> 에 있습니다.
          </div>
        ) : (
          <div className="empty">
            <b>사고 기록 없음</b>{vessel ? `${vessel.name} 에 접수된 사고가 없습니다.` : '선박을 먼저 고르세요.'}
          </div>
        )}
      </div>
    </section>
  );
}


/**
 * 종결된 사고의 맨 윗줄 — <b>얼마 만에, 어떻게 끝났나</b>.
 *
 * <p>진행 중 화면의 "위치"가 앉아 있던 자리다. 끝난 사고에서 좌표는 아무도 쓰지 않는다.
 * 대신 다시 열어 보는 이유가 되는 값을 그 자리에 크게 둔다.</p>
 *
 * <p>걸린 시간은 감지와 종료 시각에서 <b>계산한다</b> — `facts` 에 따로 적어 두면
 * 시각과 어긋날 수 있고, 비-MOB 사고에는 아예 그 항목이 없는 경우가 있다.</p>
 */
function Outcome({ x, onReport }: { x: Incident; onReport: (x: Incident) => void }) {
  const from = secOfClock(x.stages.detect.at);
  const to = secOfClock(x.stages.close.at);
  const took = from !== null && to !== null && to >= from ? to - from : null;
  const what = x.stages.close.note ?? (x.state === 'cancel' ? '취소' : '종결');
  // 표류 거리처럼 끌어올리기로 한 값은 여기서 받는다
  const promoted = x.facts.filter(([k, v]) => OUTCOME_FACTS.has(k) && v !== '');

  return (
    <section className="inc-sec inc-outcome">
      <div className="section-label"><h3>결과</h3></div>
      <p className="oc-line">
        {took !== null ? <b>{elapsed(took)}</b> : null}
        <span>{took !== null ? ' 만에 ' : ''}{what}</span>
      </p>
      {/*
       * 날짜를 같이 적는다. 시간만 적혀 있으면 기록을 다시 여는 사람은
       * <b>오늘 일로 읽는다</b> — 종결된 사고를 보는 것이 기록 탭의 전부인데도 그러다(2026-09-18).
       * 단계 줄마다 날짜를 반복하진 않는다 — 하루 안에 닫힌 사고라 이 줄이 한 번 말하면 된다.
       */}
      <p className="oc-when mono">
        {x.day} {x.stages.detect.at ?? '—'} → {x.stages.close.at ?? '—'}
      </p>
      {/*
       * 다섯 단계가 몇 시 몇 분이었나. 진행 중에는 화면 위 단계 바가 이 일을 하는데,
       * 종결되면 그 바가 답을 다 채운 채로 지나가 버려 다시 볼 자리가 없었다(2026-09-17).
       * 총 시간(위 큰 숫자)만으로는 <b>어느 구간이 오래 걸렸는지</b>를 못 짚는다.
       */}
      <ol className="oc-stages">
        {stagesOf(x).map(([k, label, st]) => (
          <li key={k} className={st.at ? 'is-done' : ''}>
            <span>{label}</span>
            <b className="mono">{st.at ?? '—'}</b>
          </li>
        ))}
      </ol>

      {promoted.length ? (
        <dl className="facts oc-facts">
          {promoted.map(([k, v, unit], i) => (
            <div className="fact" key={i}>
              <dt>{k}</dt>
              <dd>{v}{unit ? <small>{unit}</small> : null}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {/* 리포트는 종결 직후 한 번 떴다 사라졌다. 다시 여는 길이 없어 여기 둔다 */}
      <button className="btn oc-report" onClick={() => onReport(x)}>종료 리포트 보기</button>
    </section>
  );
}

function IncidentTab({ x, live, resolvedBy, onResolve, onStopVideo, onReport, readOnly, dt }: {
  x: Incident; live: boolean; dt: number; onReport: (x: Incident) => void;
  resolvedBy: Record<string, string>;
  onResolve: (x: Incident) => void;
  readOnly: boolean;
  onStopVideo: (x: Incident) => void;
}) {
  const sea = useSea(x);
  const cats = oceanRows(sea, x.waterTemp);
  const c = x.clip;
  /** 사진 두 장(감지 순간 · 현재). 진행 중에는 이것이 전부다 — 영상은 끝난 뒤에 온다 */
  const ph = x.photos;
  /**
   * 그릴 것이 있나. 진행 중이든 끝났든 <b>사진</b>이다.
   *
   * <p>⚠ 끝난 사고는 전에 mp4 영상을 봤다. 그런데 <b>배가 mp4 를 만들지 않는다</b> — Pi·Jetson
   * 어디에도 인코딩하는 코드가 없고, 키오스크의 "사고 전후"도 사진을 넘겨 보여 주는 것이다.
   * 받을 것이 없는 자리를 기다리게 해 두지 않고 뺐다(2026-09-21).</p>
   *
   * <p>없으면 아래 자리를 아예 그리지 않는다(빈 자리를 칠해 두면 받은 것처럼 보인다).</p>
   */
  const hasMedia = Boolean(ph.detect || ph.latest);
  /** 사진이 찍힌 뒤 몇 초 지났나. 늦게 들어오고 있는지가 한눈에 보여야 한다 */
  const shotAgo = (iso: string | null) =>
    iso ? agoText(Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))) : null;
  /** 영상 그만 받기를 눌렀는가. 누른 뒤에는 최신 프레임이 더 오지 않는다. */
  const stopped = !!c.stoppedAt;
  const u = URG[x.type.urg];
  const b = x.map.buoy;
  // MOB 이 아니면 조난 대상이 배다. 화면의 절반이 갈린다.
  const mob = isMob(x);
  // 조종 불능이거나 위치를 못 받고 있으면 배도 흘러간다
  const adrift = isAdrift(x);
  // 지도와 같은 계산. 슬라이더를 끌면 여기 좌표도 같이 움직인다.
  // 바다 값은 사고 지점 기준이다. 없으면 추정을 그리지 않는다
  const view = incidentView(x, dt, sea?.sea ?? null);
  const dtLabel = STEPS.find(([s]) => s === dt)?.[1] ?? '';
  // 카드와 같은 문장을 쓴다 — 만드는 곳이 한 군데여야 둘이 어긋나지 않는다
  const bs = mob ? buoyState(x) : null;

  return (
    <>
      {/* §9.21 유형 · §9.20 종결. 종결은 kiosk·웹 양쪽에서 할 수 있고 먼저 누른 쪽이 성립한다. */}
      <div className="inc-head">
        <div className="inc-type">
          <span className={`urg-tag ${u[1]}`}>{u[0]}</span>
          <b title={x.type.dsc ? `DSC ${x.type.dsc}` : undefined}>{x.type.label}</b>
          {x.type.dsc ? <span className="mono inc-dsc">DSC {x.type.dsc}</span> : null}
        </div>
        {live && readOnly
          // 관리자는 진행 중이라는 사실만 본다. 종결은 해경이 하는 일이다
          ? <span className="inc-closed">진행 중</span>
          : live
          // 상태가 아니라 동작이다. "사고 종결"이라고만 쓰면 상태 배지로 읽혀 "왜 진행 중인데 종결이냐"가 된다.
          ? <button className="btn-resolve" onClick={() => onResolve(x)}>종결 처리</button>
          : <span className="inc-closed">종결됨 · {resolvedBy[x.id] || (x.state === 'cancel' ? '오탐 취소' : '선내 단말')}</span>}
      </div>

      {/* 정보 종류마다 inc-sec 로 묶는다. 섹션 사이에 선이 들어간다(web.css). */}

      {/*
       * ── 결과. 종결된 사고를 다시 여는 이유가 이것이다 ──
       * 몇 분 만에 끝났나, 그동안 얼마나 흘렀나. 선령·풍속과 같은 줄에 두면
       * 셋 다 똑같이 작은 글자가 되어 제일 중요한 것이 묻힌다(2026-09-17).
       */}
      {!live ? <Outcome x={x} onReport={onReport} /> : null}

      {/*
       * ── 남은 시간. <b>패널의 첫 칸</b> ──
       * 물에 빠진 사람에게만 해당한다. 배 위에 있으면 저체온증 시계가 돌지 않는다.
       *
       * <p>위치보다 앞에 둔다. 좌표는 "어디로 가나"에 답하고 이 시계는 "얼마나 급한가"에
       * 답하는데, 대응 속도를 정하는 것이 뒤에 있으면 이미 다 읽고 난 뒤에 보게 된다(2026-09-18).</p>
       *
       * <p>끝난 사고에서는 시계가 멈춰 있다 — 남은 시간을 적어 두면 아직 물에 있는 것처럼 읽힌다.</p>
       */}
      {mob && live ? (
        <section className="inc-sec">
          <SurvivalMeter tempC={x.waterTemp} elapsedSec={x.elapsedSec} />
        </section>
      ) : null}

      {/*
       * ── 위치. MOB 은 사람과 부표를, 나머지는 배를 본다 ──
       * <b>진행 중에만 둔다.</b> 끝난 사고에서 "지금 어디 있나"는 답할 질문이 아니다 —
       * 사람은 이미 배 위에 있고, 좌표는 아무도 쓰지 않는다. 마지막 자리는 경위와 리포트에 남는다.
       */}
      {live ? (
      <section className="inc-sec">
      {/*
       * 배지는 제목 <b>오른쪽</b>에 앝힌다. 제목 밑에 한 줄을 더 쓰면 정작 읽으려는 좌표가
       * 그만큼 아래로 밀린다. 배지가 답하는 것은 "이 좌표를 얼마나 믿을 수 있나"라,
       * 제목과 한 줄에 있어야 바로 아래 좌표를 읽는 눈에 같이 들어온다(2026-09-18).
       */}
      <div className="section-label">
        <h3>위치</h3>
        {/* 사람 위치를 아는지는 아래 좌표(주역 표시)와 설명 문단이 이미 말한다.
            배지로 한 번 더 적으면 같은 말이 세 번 나온다. */}
        {/*
         * 부표 상태는 <b>왼쪽 목록 카드와 같은 줄</b>을 쓴다(lib/buoyState.ts).
         * 같은 사실을 두 곳에서 다른 말·다른 모양으로 적고 있었다 —
         * 카드는 "51분 전 신호 끊김 · 사람이 잡고 있었음", 여기는 "부표 (추정) · 마지막으로
         * 받은 것이 51분 전". 두 번 배우게 할 이유가 없다(2026-09-18).
         *
         * <p>표류 슬라이더를 끌었을 때의 '10분 뒤'는 아래 좌표 이름이 이미 말한다 —
         * 사람 (추정 · 10분 뒤). 배지에 한 번 더 적지 않는다.</p>
         */}
        {bs ? (
          <p className="buoy-line bl-inline">
            <span className={`bl-state tone-${bs.tone}`} title={bs.why}>
              <i className="bl-dot" aria-hidden="true" />
              {bs.text}
              {bs.tail ? (
                <em className={`bl-tail${bs.notHeld ? ' is-notheld' : ''}`}>
                  {' · '}{bs.notHeld ? '⚠ ' : ''}{bs.tail}
                </em>
              ) : null}
            </span>
          </p>
        ) : (
          /* 배가 조난 대상이다. 부표를 쏘지 않았으므로 실측/추정 배지가 없다 —
             대신 배가 흘러가는지 아닌지가 그 자리를 대신한다. */
          <div className="state-badges">
            {adrift
              ? <span className="hold-badge is-unknown">⚠ 조종 불능 · 표류 중</span>
              : <span className="hold-badge is-held">✓ 위치 유지 중</span>}
          </div>
        )}
      </div>

      {/*
       * 🔴 <b>너무 오래 끊겨 추정을 포기했다</b>(lib/drift.ts MAX_DRIFT_SEC).
       *
       * <p>마커는 마지막으로 받은 자리에 그대로 있고 범위는 없다. 그 상태를 말하지 않으면
       * 보는 사람은 "왜 범위가 없지"가 아니라 <b>"여기 있구나"</b>로 읽는다 — 그게 제일 위험하다.</p>
       */}
      {(view.person?.beyond || view.buoy?.beyond) ? (
        <p className="beyond-note">
          <b>마지막 수신 {agoText(mob && b ? b.ageSec : x.map.shipAgeSec ?? 0)} · 추정 범위를 그리지 않습니다</b>
          조류가 여러 번 바뀌어 계산이 의미를 잃습니다. 표시된 자리는 마지막으로 받은 위치입니다.
        </p>
      ) : null}

      {mob ? (
        <>
          {view.person
            ? <Coord at={view.person.at} label={`사람 (추정${dt ? ' · ' + dtLabel : ''})`} primary />
            : null}
          {b && view.buoy
            ? <Coord at={view.buoy.at}
                     label={b.fix === 'measured' && !dt ? '부표 (실측)' : `부표 (추정${dt ? ' · ' + dtLabel : ''})`}
                     primary={!view.person} />
            : null}
          {x.map.mob ? <Coord at={x.map.mob} label="감지 지점" /> : null}
          {/* 추정 근거 문구(조류·바람 기반 추정 · 조류 1.1km · 바람 울산 9.1km)는 지웠다(2026-09-18) */}
        </>
      ) : (
        <>
          {/* 배가 어디로 흘러갈지는 그리지 않는다(lib/kind.ts) — 마지막으로 받은 자리만 적는다 */}
          {view.ship ? <Coord at={view.ship.at} label="선박 위치" primary /> : null}
        </>
      )}

      {/*
       * 좌표 밑에 <b>이 좌표가 어디서 나왔는지</b>를 붙인다. 위의 배지가 "실측이냐 추정이냐"를
       * 말하고 이 줄이 "얼마나 오래됐느냐"를 말한다 — 둘은 같은 질문의 앞뒤라 한 자리에 모인다.
       *
       * <p>🔴 <b>부표가 없으면 받는 위치 자체가 없다.</b> 전에는 그때 선박 GPS 의 수신 시각을
       * 대신 적었는데, 이 칸에는 선박 좌표가 나오지도 않는다 — "부표 없음 · 발사 실패"
       * 바로 밑에 "마지막 수신 방금"이 붙어 <b>없는 수신을 있다고 말했다</b>(2026-09-18).
       * 받는 것이 없을 때는 그 사실과, 대신 무엇으로 계산했는지를 적는다.</p>
       *
       * <p>익수가 아니면 선박 좌표가 바로 위에 있으므로 선박 수신 시각이 맞는 답이다.
       * 경과 시간을 적어 두는 데도 여기뿐이라 같이 적는다.</p>
       */}
      <p className="sec-meta">
        {!mob ? (
          <>경과 {elapsed(x.elapsedSec)}{' · '}마지막 수신 (선박) {agoText(x.map.shipAgeSec ?? 0)}</>
        ) : b ? (
          /* 위의 부표 줄이 이미 "51분 전 신호 끊김"으로 같은 시간을 말한다 */
          null
        ) : (
          <>받는 위치 없음 · 감지 지점에서 {elapsed(x.elapsedSec)} 표류한 계산값</>
        )}
      </p>
      </section>
      ) : null}

      {/*
       * 이미 받고 있는 해황이다. MOB 의 생존 잔여시간 자리에 들어간다 —
       * 화재는 바람이, 침수·전복은 파고가 급함을 말한다.
       *
       * ⚠ <b>진행 중에만 둔다.</b> 여기 오는 값은 공공데이터의 <b>지금</b> 바다다(40분 전 관측).
       *   9월 7일에 끝난 사고를 열었는데 오늘 바람이 뜨면 그때 해황으로 읽힌다 — 거짓말이다.
       *   사고 당시 해황을 보여주려면 그 시각의 값을 따로 저장해 두어야 한다(2026-09-17).
       */}
      {!mob && live ? (
        <section className="inc-sec">
          <div className="section-label">
            <h3>현장 해황</h3><span className="eyebrow">공공데이터</span>
          </div>
          <Readings rows={cats.safe.rows.filter(([label]) => label !== '수온')} />
        </section>
      ) : null}

      {/*
        신고 블록(발송 시각 · 발신 상태 · 해경 접수 시각)은 지웠다 — 위 단계 띠의
        ② 구조 요청 · ③ 구조대 대응 이 같은 두 시각을 이미 보여 준다(2026-09-18).
      */}

      {/*
       * 진행 중에만 두는 줄. 종결 화면에는 선령·환자 수·최근접 세력 같은 값이 남아 있었는데,
       * 받는 데이터도 아니고 지난 사고를 다시 열어 보는 이유도 아니다 — 통째로 뺐다(2026-09-17).
       * 발사 품질(감지→발사 시간, 발사 오차)은 종료 리포트에 싣는다.
       */}
      {/*
        경과·마지막 수신을 따로 두던 두 칸짜리 상자는 없앤다(2026-09-18).
        경과는 이미 의식 유지 예상 밑에, 마지막 수신은 위치 밑에 있어 같은 값이 두 번씩 나왔고,
        그 상자 하나만 테두리를 두르고 있어 패널이 듭쿨날쿨해 보였다.
      */}

      {/*
       * ⚠ 한때 여기에 <b>발사 기록</b>(감지→발사 시간 · 오차 · 사각 · 신뢰도)을 관리자에게만 띄웠다.
       *   빼기로 했다(2026-09-19) — 구조에도 안 쓰이고, 그 숫자로 무엇을 판단할지(장치 분석)는
       *   지금 할 일이 아니다. 값은 여전히 `x.facts`·`x.params` 에 들어 있고
       *   <b>종료 리포트</b>가 그것을 싣는다(components/CloseReport.tsx).
       */}

      <section className="inc-sec">
      <div className="section-label">
        <h3>{live ? '선내 카메라' : '사고 사진'}</h3>
        <span className="eyebrow mono">
          {!hasMedia
            ? '없음'
            : live
              ? (stopped ? `수신 중단 · ${c.stoppedAt}` : '몇 초마다 새로 받음')
              : '감지 순간 · 마지막 사진'}
        </span>
      </div>

      {/*
       * 🔴 <b>받은 것이 없으면 자리도 그리지 않는다</b>(2026-09-21).
       *
       * <p>전에는 빈 값(`src: ''`, 길이 0)으로도 아래 그림을 그렸다. 사진 자리는 바다색으로
       * 칠해져 <b>사진처럼 보였고</b>, 그 위에서 빨간 점이 깜빡였고, 종결 사고에는 빈 칸 20개가
       * 필름처럼 깔렸다. 한 장도 받은 적 없는 사고인데 화면은 "받고 있다"고 말하고 있었다.</p>
       *
       * <p>사진은 Pi 가 사고 묶음으로 서버에 올린다(`/api/pi/archives` → R2 + accident_file).
       * 관제는 그중 두 장을 `/photos` 로 받는다.</p>
       */}
      {!hasMedia ? (
        <p className="src-note">
          {live
            ? '감지 순간 사진과 현재 사진을 아직 받지 못했습니다.'
            : '이 사고의 사진을 받지 못했습니다.'}
        </p>
      ) : (
        /*
         * 사진 두 장. 앞은 "무엇을 보고 사고로 판단했나", 뒤는 "지금 배 위가 어떤가".
         * 끝난 사고는 뒤 칸이 '현재'가 아니라 <b>마지막 사진</b>이다 — 더 들어오지 않는다.
         *
         * <p>🔴 <b>진짜 사진이다</b>(2026-09-21). 전에는 여기에 바다색으로 칠한 상자를 두고 그 위에서
         * 빨간 점을 깜빡였다 — 받은 적 없는 사진이 들어오고 있는 것처럼 보였다.
         * 지금은 Pi 가 R2 에 올린 사진의 서명 주소를 받아 그대로 띄운다.</p>
         *
         * <p>"현재"는 <b>실시간 동영상이 아니라 가장 최근 사진</b>이다. 동영상(Jetson 스트림)은 배 안
         * 랜에서만 보여 인터넷의 관제 웹은 닿을 수 없다. 대신 상세를 5초마다 다시 받으므로
         * 새 사진이 올라오면 곧 바뀐다.</p>
         *
         * <p>누르면 원본을 새 탭에 연다 — 작은 칸으로는 무엇을 보고 사고로 판단했는지 확인이 안 된다.</p>
         */
        <div className="shots">
          {([
            [ph.detect, mob ? '감지 순간' : '신고 순간', mob ? '익수 확정' : '수동 신고'],
            [ph.latest, live ? '현재' : '마지막 사진', live ? '가장 최근' : '사고 뒤 마지막'],
          ] as const).map(([p, name, sub]) => (
            <figure className="shot" key={name}>
              {p ? (
                <a className="shot-img" href={p.url} target="_blank" rel="noreferrer" title="원본 크게 보기">
                  <img src={p.url} alt={`${name} 사진`} loading="lazy" />
                </a>
              ) : (
                <div className="shot-img is-wait"><span>아직 안 옴</span></div>
              )}
              <figcaption>
                <b>{name}</b>
                <span className="mono">
                  {p?.capturedAt
                    ? `${sub} · ${shotAgo(p.capturedAt)} 촬영${p.camera ? ` · 카메라 ${p.camera}` : ''}`
                    : sub}
                </span>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      {/* 사고 후 구간은 종결하거나 1시간이 지나야 끝난다. 그 전에 끊고 싶을 때 쓴다.
          ⚠ API 미정 — 지금은 화면 상태만 바뀐다(App.stopVideo). */}
      {hasMedia && live && !readOnly ? (
        stopped
          ? <p className="video-stopped">영상 수신을 멈췄습니다 · <span className="mono">{c.stoppedAt}</span></p>
          : <button className="btn-stop-video" onClick={() => onStopVideo(x)}>영상 그만 받기</button>
      ) : null}

      </section>
    </>
  );
}

import { useEffect, useState } from 'react';
import { currentStage, doneCount, stagesOf } from '../lib/stages';
import { byVessel } from '../lib/fleet';
import type { Incident } from '../types';

/**
 * 대응 단계 상황판(신규 10).
 *
 * 화면 **최상단에 전체 폭으로** 깐다. 오른쪽 상세 패널 안에 있으면 지도를 보는 동안
 * 진행 상황이 시야에서 사라지는데, 이건 사고를 보는 내내 붙어 있어야 하는 정보다.
 *
 * **진행 바가 아니라 체크리스트다.** ③ 해경 접수와 ④ 사고자 발견은 순서가 뒤바뀐다 —
 * 부표 버튼은 발사 몇 초 뒤에 눌릴 수 있고 해경 접수는 1분 뒤일 수 있다.
 * 그래서 칸을 나란히 두고 달성 여부와 시각만 적는다. 화살표로 잇지 않는다.
 *
 * <p>칸에는 <b>이름과 시각만</b> 둔다. 전에는 밑에 회색 설명("신고 발신 중" · "관제 웹 열람")이
 * 붙어 있었는데, 다섯 칸에 다 깔리니 시각이 묻혔다 — 자세한 경위는 상세 패널의 경위 표가 갖는다(2026-09-17).</p>
 */
const HINT = '단계는 순서대로 진행되지 않습니다. 해경 접수와 사고자 발견은 앞뒤가 바뀔 수 있어 '
  + '진행 바가 아니라 체크리스트로 그립니다. 강조된 칸은 가장 최근에 달성된 단계입니다.';

/**
 * 손으로 달성하는 단계. 앞의 셋은 Pi 가 보내는 사실이라 관제가 누를 것이 없다 —
 * 감지·발사도, 신고 발신도, 해경 접수도 화면을 열면 자동으로 찍힌다. 뒤의 둘만이 사람의 판단이다.
 */
interface Props {
  x: Incident;
  /** ④ 사고자 발견 */
  onFound: (x: Incident) => void;
  /** ⑤ 종결. 되돌릴 수 없어 확인 창을 한 번 거친다 */
  onResolve: (x: Incident) => void;
  /**
   * 이 사고를 <b>어느 쪽으로 그릴까</b>. 칸 색과 맥박, 버튼 유무가 여기서 갈린다 —
   * {@code 'live'} 는 지금 칸이 빨강이고 흰 점이 뛴다, {@code 'log'} 는 마지막 칸이 남색이고 멎어 있다.
   *
   * <p>전에는 {@code live: boolean} 이었다. 참이면 무엇이 되는지가 이름에 없어
   * {@code live={!isAdmin && ...}} 처럼 <b>상관없는 값</b>이 흘러들었고, 관리자가 보면
   * 진행 중 사고가 종결된 색으로 떴다(2026-09-19). 이름을 탭 쪽 말로 바꾸면 그런 값은
   * 애초에 넣을 수가 없다 — {@code kind={!isAdmin}} 은 타입이 거부한다(2026-09-20).</p>
   *
   * <p>⚠ <b>탭 이름을 그대로 넘기면 안 된다.</b> 사고 탭에서 방금 종결한 사고는 목록이
   * 갱신되기 전까지 몇 초간 사고 탭에 남는데, 그동안 빨간 칸이 뛰면 아직 진행 중으로 읽힌다.
   * 넘기는 쪽이 <b>사고의 상태</b>로 정한다(App.tsx).</p>
   */
  kind: 'live' | 'log';
  /**
   * 🔴 관리자다 — 보되 손대지 않는다(App.tsx isAdmin). <b>버튼만</b> 숨긴다.
   *
   * <p>전에는 이걸 `live=false` 로 넘겨서 껐는데, 같은 값이 색까지 바꾸는 바람에
   * <b>진행 중 사고가 종결된 것처럼 남색</b>으로 떴다. 색과 권한은 다른 축이다(2026-09-19).</p>
   */
  readOnly?: boolean;
}

export function StageBoard({ x, onFound, onResolve, kind, readOnly }: Props) {
  const live = kind === 'live';
  const rows = stagesOf(x);
  const now = currentStage(x);
  /** 지금 칸이 몇 번째인가. 이 앞은 지나간 칸, 뒤는 앞으로 할 칸이다 */
  const nowIdx = rows.findIndex(([k]) => k === now);
  const done = doneCount(x);
  /** 종결 확인 창. 항상 떠 있는 줄이라 지나가다 실수로 누를 수 있다 */
  const [asking, setAsking] = useState(false);
  // 사고를 바꾸면 물음을 거둔다 — 앞 사고에서 물은 것이 다음 사고의 종결로 이어지면 안 된다
  useEffect(() => { setAsking(false); }, [x.id]);

  const ship = byVessel[x.ship]?.name ?? x.ship;

  /** 누를 수 있는 칸인가 — 진행 중이고, 아직 안 된 ④·⑤ 만 */
  const actOf = (key: string, at: string | null) => {
    if (!live || readOnly || at) return null;
    if (key === 'found') return { label: '발견 처리', run: () => onFound(x) };
    if (key === 'close') return { label: '종결 처리', run: () => setAsking(true) };
    return null;
  };
  /**
   * 지금 눌러야 할 것 하나만 채운 버튼으로 둔다. 둘 다 진하면 어느 쪽이 먼저인지 안 읽힌다 —
   * 발견이 아직이면 종결은 한 걸음 물러난다.
   */
  const nextAct = !x.stages.found.at ? 'found' : 'close';

  return (
    <>
      {/* 기록으로 넘어간 사고는 마지막 칸의 색을 달리 쓴다 — web.css .stage-bar.is-log */}
      <section className={`stage-bar is-${kind}`}
               aria-label={`대응 단계 ${done}/${rows.length} 달성`} title={HINT}>
        {/* 여러 사고가 지도에 함께 떠 있을 수 있다. 이 단계가 누구 것인지 먼저 밝힌다. */}
        <div className="stage-who">
          <b>{ship}</b>
          <span className="mono">{done}/{rows.length} <em>단계 완료</em></span>
        </div>
        <ol>
          {/*
           * 🔴 색은 <b>달성 여부가 아니라 위치</b>로 정한다.
           *
           * <p>전에는 시각이 있으면 회색, 없으면 흰색이었다. 그러면 종결된 사고에서
           * 접수가 안 찍힌 ③ 칸이 <b>지나간 자리인데 흰색</b>(앞으로 할 것)으로 보인다 —
           * 다섯 칸이 시간순으로 놓여 있는데 색만 순서를 안 따르는 셈이다(2026-09-19).</p>
           *
           * <p>지난 칸은 달성했든 못 했든 회색, 지금 칸만 색, 뒤는 흰색.
           * 달성 여부는 <b>시각이 적혔나 `—` 인가</b>로 이미 말하고 있다.</p>
           */}
          {rows.map(([key, name, st], i) => {
            const isNow = key === now;
            const act = actOf(key, st.at);
            return (
              <li
                key={key}
                className={`stage-cell${st.at ? ' is-done' : ''}`
                  + (nowIdx >= 0 && i < nowIdx ? ' is-past' : '')
                  + (isNow ? ' is-now' : '')
                  + (act && key !== nextAct ? ' is-later' : '')}
                aria-current={isNow ? 'step' : undefined}
              >
                {/* 번호는 단계 순서다. 끝난 칸과 앞으로 할 칸은 칸 밝기로 갈린다(web.css) */}
                <span className="stage-no mono" aria-hidden="true">{i + 1}</span>
                <span className="stage-name">
                  {name}
                  {/*
                   * 지금 이 단계에 머물러 있다는 신호. <b>진행 중일 때만</b> 뛴다 —
                   * 종결된 사고의 마지막 칸(남색)에 있으면 아직 진행 중으로 읽힌다.
                   *
                   * 전에 카드 경과 시간 옆에 같은 점을 뒀다가 뺐다(2026-09-19). 흰 바탕 위
                   * 빨간 점이라 빨간 글자에 묻혔고, 무엇을 뜻하는지도 자리로는 말하지 못했다.
                   * 여기는 채운 빨간 칸 위의 흰 점이라 대비가 최대고, <b>그 칸 하나가
                   * "지금 여기"</b>라 자리만으로 뜻이 정해진다.
                   */}
                  {isNow && live ? <i className="now-beat" aria-hidden="true" /> : null}
                </span>
                {/* 버튼은 시각이 들어갈 자리에 둔다 — 누르면 그 자리가 바로 그 시각이 된다 */}
                {act
                  ? <button className="stage-do" onClick={act.run}>{act.label}</button>
                  : <span className="stage-at mono">{st.at ?? '—'}</span>}
              </li>
            );
          })}
        </ol>
      </section>

      {/*
        종결 확인. 두 번 누르게 하는 방식은 첫 번째 누름이 무슨 뜻인지 알려 주지 못한다 —
        무엇을 종결하는지 문장으로 묻는다.
      */}
      {asking ? (
        <div className="ask-veil" role="presentation" onClick={() => setAsking(false)}>
          <div className="ask-card" role="alertdialog" aria-modal="true"
               aria-labelledby="ask-title" onClick={(e) => e.stopPropagation()}>
            <h2 id="ask-title">
              <b>{ship}</b>의 <b>{x.type.label}</b> 사고를<br />종결 처리하시겠습니까?
            </h2>
            <p>종결하면 되돌릴 수 없습니다.</p>
            <div className="ask-btns">
              <button className="ask-no" onClick={() => setAsking(false)}>취소</button>
              <button className="ask-yes" onClick={() => { setAsking(false); onResolve(x); }}>
                종결 처리
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

import { useEffect, useState } from 'react';
import { MapView } from '@floaq/shared';
import type { FloaqMapApi, LngLat, MarkerSpec } from '@floaq/shared';
import { ddm } from '../lib/ddm';
import { LAUNCH_FACTS, REPORT_HIDE, secOfClock } from '../lib/facts';
import { isMob } from '../lib/kind';
import { labelFor, orderOf } from '../lib/stages';
import type { StageKey } from '../lib/stages';
import { distM } from '../lib/searchGrid';
import { elapsed } from '../lib/time';
import { byVessel } from '../lib/fleet';
import type { Incident } from '../types';

/**
 * 사고 종료 요약 리포트(신규 5). 종료 처리 시점의 **스냅샷**이다.
 *
 * <p>전에는 dl·ul 이 여섯 덩이 이어지고 글자가 전부 같은 크기라, 펼쳐 놓아도
 * <b>무엇을 말하는 문서인지</b>가 안 읽혔다. 읽는 사람이 제일 먼저 묻는 것은
 * "얼마나 걸렸나"와 "어디서 늦었나" 둘이다. 그 둘을 맨 위에 크게 두고
 * 나머지는 근거로 아래에 깐다(2026-09-17).</p>
 *
 * ⚠ 양식 미정 — 결정 필요 6. 확정되면 이 컴포넌트만 갈아끼운다.
 *
 * PDF 는 별도 라이브러리를 넣지 않고 브라우저 인쇄로 낸다. 의존성 하나를 아끼려는 것도 있지만,
 * 해경 쪽 PC 에서 무엇이 깔려 있을지 모르는 상태에서 인쇄가 가장 확실한 출력 경로다.
 */
/**
 * 리포트 맨 위의 <b>개요 한 문단</b>. 표와 지도를 보기 전에 이 문단만 읽어도
 * 사고가 어떤 일이었는지 끝까지 알 수 있어야 한다.
 *
 * <p>숫자를 나열하지 않고 <b>문장으로</b> 쓴다 — 리포트를 받아 보는 사람은
 * 이 화면을 쓰던 사람이 아니다. 칸 이름과 시각만 있으면 무슨 일이 있었는지를
 * 읽는 사람이 직접 조립해야 한다.</p>
 *
 * <p>모두 사고에 적혀 있는 값에서만 만든다. 없는 것은 문장을 빼고 지나간다 —
 * 빈칸을 그럴듯한 말로 메우면 그것만으로 있지도 않았던 일이 기록에 남는다.</p>
 */
/** 받침으로 갈리는 조사. 만들어 쓰는 문장이라 '이(가)' 같은 괄호를 적을 이유가 없다 */
const jong = (word: string): number => {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code < 0 || code > 11171 ? 0 : code % 28;
};
const iGa = (w: string) => (jong(w) ? '이' : '가');
const euRo = (w: string) => { const j = jong(w); return j === 0 || j === 8 ? '로' : '으로'; };

function briefOf(x: Incident, shipName: string, reg: string, took: number | null): string[] {
  const m = x.map;
  const b = m.buoy;
  const mob = isMob(x);
  const at = (k: keyof Incident['stages']) => x.stages[k].at;
  const launchAt = x.timeline.find(([k]) => k === 'launch')?.[1] ?? null;
  const gap = (a: string | null, c: string | null) => {
    const s0 = secOfClock(a); const s1 = secOfClock(c);
    return s0 !== null && s1 !== null && s1 >= s0 ? s1 - s0 : null;
  };
  const km = (a: LngLat, c: LngLat) => {
    const d = Math.round(distM(a, c));
    return d >= 1000 ? `${(d / 1000).toFixed(1)}km` : `${d}m`;
  };

  const out: string[] = [];

  /* 1. 언제 · 어느 배 · 무슨 사고. 카메라가 잡은 것과 사람이 누른 것은 다른 일이다 */
  const how = mob ? '감지됐습니다' : '신고되었습니다';
  out.push(`${x.day} ${at('detect') ?? '—'}, ${shipName}(${reg})에서 ${x.type.label}${iGa(x.type.label)} ${how}.`);

  /* 2. 부표. 쌀는지 못 쌀는지가 이후 모든 것을 가른다 */
  if (mob) {
    if (b && launchAt) {
      const g = gap(at('detect'), launchAt);
      out.push(`${g !== null ? `${g}초 뒤인 ${launchAt}` : launchAt}에 구명 부표가 발사됐습니다.`);
    } else if (!b) {
      out.push('부표는 발사되지 않았습니다 — 바다에 잡을 것이 없는 상태였습니다.');
    }
  }

  /* 3. 신고와 접수 */
  if (at('report') && at('ack')) {
    out.push(`${at('report')}에 신고가 나갔고, 해경이 ${at('ack')}에 접수했습니다.`);
  } else if (at('report')) {
    out.push(`${at('report')}에 신고가 나갔으나 접수 확인은 기록되지 않았습니다.`);
  }

  /* 4. 사고자를 어떻게 찾았나. 거리를 적는 것은 다음 사고에 쓸모가 있어서다 */
  if (at('found')) {
    const why = x.stages.found.note === '부표 잡음'
      ? '부표 버튼이 눌려 사고자가 부표를 잡은 것이 확인됐습니다'
      : '사고자가 발견됐습니다';
    const far = m.foundAt && m.mob ? ` 발견 지점은 감지 지점에서 약 ${km(m.mob, m.foundAt)} 떨어진 곳입니다.` : '';
    out.push(`${at('found')}에 ${why}.${far}`);
  }

  /* 5. 어떻게 끝났나 */
  const done = x.stages.close.note ?? (x.state === 'cancel' ? '취소' : '종결');
  out.push(took !== null
    ? `${mob ? '감지' : '신고'}에서 ${elapsed(took)} 만에 ${done}${euRo(done)} 마무리됐습니다.`
    : `${done}${euRo(done)} 마무리됐습니다.`);

  /* 6. 물에 빠진 사고에서만. 수온은 그때 얼마나 급했는지를 말해 준다 */
  if (mob) out.push(`당시 수온은 ${x.waterTemp.toFixed(1)}℃였습니다.`);

  return out;
}

/**
 * 리포트용 지도의 마커. 관제 지도와 <b>같은 모양</b>을 쓴다 — 리포트에서만
 * 다른 기호를 쓰면 화면을 보며 상황을 꺼 본 사람이 다시 배워야 한다.
 * 누를 일은 없어 click 은 달지 않는다.
 */
const RP_AT: LngLat = [129.1195, 35.0918];
const RP_MARKERS: MarkerSpec[] = [
  { id: 'rpShip', at: RP_AT, cls: 'mk-vessel', hidden: true,
    html: '<svg width="26" height="26" viewBox="0 0 26 26">'
        + '<circle cx="13" cy="13" r="12" style="fill:rgba(var(--mk-rgb),.18)"/>'
        + '<path d="M13 5 21.4 18.4H4.6Z" style="fill:var(--mk-c)" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/>'
        + '</svg><div class="mk-label" id="rpShipLabel"></div>' },
  { id: 'rpMob', at: RP_AT, cls: 'mk-flag', hidden: true,
    html: '<svg width="26" height="26" viewBox="0 0 26 26">'
        + '<circle cx="13" cy="13" r="12" fill="rgba(217,64,64,.16)"/>'
        + '<path d="M13 6.5 19 18H7Z" fill="none" stroke="#d94040" stroke-width="2.2" stroke-linejoin="round"/>'
        + '</svg><div class="mk-label" id="rpMobLabel"></div>' },
  { id: 'rpBuoy', at: RP_AT, cls: 'mk-buoy', hidden: true,
    html: '<b></b><i></i><div class="mk-label" id="rpBuoyLabel"></div>' },
  /* 사고자를 찾은 자리. 리포트에서 제일 중요한 점 하나라 넣은 원으로 놓는다 */
  { id: 'rpFound', at: RP_AT, cls: 'mk-found', hidden: true,
    html: '<svg width="26" height="26" viewBox="0 0 26 26">'
        + '<circle cx="13" cy="13" r="11" fill="rgba(47,143,109,.18)" stroke="#2f8f6d" stroke-width="2.2"/>'
        + '<path d="M8.4 13.2 11.6 16.4 17.6 10" fill="none" stroke="#2f8f6d" stroke-width="2.4"'
        + ' stroke-linecap="round" stroke-linejoin="round"/>'
        + '</svg><div class="mk-label" id="rpFoundLabel"></div>' },
];

function rpLabel(id: string, head: string, sub: string) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `${head}<span>${sub}</span>`;
}

/**
 * 사고가 <b>어디서 어느 쪽으로</b> 진행했는지. 시각만 적힌 표는 몇 분 걸렸는지는 말해도
 * 배와 부표가 얼마나 떨어졌는지는 못 말한다 — 나중에 리포트를 다시 꾸는 이유의 절반이 그것이다.
 *
 * <p>실선은 부표에게서 <b>실제로 받은</b> 경로, 점선은 통신이 끊긴 뒤 조류·바람으로 계산한 구간이다.
 * 둘을 한 색으로 그리면 받은 것과 계산한 것이 같은 말로 읽힌다(2026-09-18).</p>
 */
function ReportMap({ x }: { x: Incident }) {
  const [api, setApi] = useState<FloaqMapApi | null>(null);
  const v = byVessel[x.ship]!;

  useEffect(() => {
    if (!api) return;
    const m = x.map;
    const b = m.buoy;
    /* 바다를 누른다 — 종이에 눈으로 출력되어도 경로가 타일에 묻히지 않게 */
    api.setDim(true);

    api.setMarker('rpShip', m.ship, true);
    const shipEl = api.markers.rpShip?.getElement();
    if (shipEl) shipEl.dataset.urg = x.type.urg;
    rpLabel('rpShipLabel', v.name, '선박');

    api.setMarker('rpMob', m.mob, !!m.mob);
    if (m.mob) rpLabel('rpMobLabel', '감지 지점', x.stages.detect.at ?? '');

    api.setMarker('rpBuoy', b ? b.at : null, !!b);
    if (b) rpLabel('rpBuoyLabel', '부표 최종', b.fix === 'measured' ? '실측' : '추정');

    api.setMarker('rpFound', m.foundAt ?? null, !!m.foundAt);
    if (m.foundAt) rpLabel('rpFoundLabel', '사고자 발견', x.stages.found.at ?? '');

    /* 실선 = 받은 경로, 점선 = 두절 구간의 계산 경로(web.css LINE_STYLE) */
    const measured = m.track?.measured ?? [];
    api.setLine('btrack', measured.length > 1 ? measured : []);
    api.setLine('etrack', b && b.fix === 'estimated' ? [b.lastFixAt, b.at] : []);

    const pts: LngLat[] = [m.ship, ...(m.mob ? [m.mob] : []), ...measured,
                           ...(m.foundAt ? [m.foundAt] : []),
                           ...(b ? [b.lastFixAt, b.at] : [])];
    /*
     * 크기를 다시 재고 나서 맞춘다. 리포트는 모달이라 지도가 만들어질 때 칸이 아직
     * 제 크기가 아니다 — 그 상태에서 맞춰 두면 점들이 화면 밖으로 나가 <b>빈 바다만</b> 보인다.
     * 모달이 자리를 잡은 뒤 한 번 더 맞춰 그 경우까지 덮는다(2026-09-18).
     */
    const fit = () => { api.invalidate(); api.fitPoints(pts); };
    fit();
    const t = window.setTimeout(fit, 260);
    return () => window.clearTimeout(t);
  }, [api, x, v]);

  return (
    /* 관제 지도와 같은 마커 모양을 쓰려면 같은 겹(.map-wrap.is-incident) 안에 있어야 한다 */
    <div className="map-wrap is-incident rp-map" data-theme="day">
      {/*
        눈금은 안 그린다(기본값 auto). 리포트 지도는 점 서너간에 꽉 맞춰 잡아 아주 깊게 들어가는데,
        그러면 경위도 글자가 좁은 칸에서 겹쳐 읽힐 수도 없으면서 경로만 가린다.
        정확한 좌표는 아래 '기록'의 감지 지점·부표 최종이 적어 준다(2026-09-18).
      */}
      <MapView className="rp-map-canvas" center={RP_AT} zoom={13}
               theme="day" markers={RP_MARKERS} onReady={setApi} />
    </div>
  );
}

export function CloseReport({ x, closedBy, onClose }: {
  x: Incident | null;
  closedBy: string;
  onClose: () => void;
}) {
  if (!x) return null;
  const v = byVessel[x.ship]!;
  const b = x.map.buoy;
  // 발사 품질 수치 중 해경이 쓸 것만 남긴다(lib/facts.ts REPORT_HIDE)
  const launch = x.facts.filter(([k]) => LAUNCH_FACTS.has(k) && !REPORT_HIDE.has(k));
  const params = x.params.filter(([k]) => !REPORT_HIDE.has(k));

  const from = secOfClock(x.stages.detect.at);
  const to = secOfClock(x.stages.close.at);
  const took = from !== null && to !== null && to >= from ? to - from : null;

  /**
   * 단계마다 <b>앞 단계에서 몇 초 걸렸나</b>. 총 시간만으로는 어디서 늦었는지 못 짚는다 —
   * 리포트를 나중에 다시 꺼내 보는 이유가 대개 이것이다.
   */
  let prev = from;
  const rows = orderOf(x).map((k: StageKey) => {
    const at = secOfClock(x.stages[k].at);
    const gap = at !== null && prev !== null && at >= prev ? at - prev : null;
    if (at !== null) prev = at;
    return { k, label: labelFor(x, k), at: x.stages[k].at, sec: at, gap };
  });

  /*
   * 경위를 <b>단계 안으로 집어넣는다.</b> 전에는 밑에 따로 있었는데, 거기 적힌 시각이
   * 위 표의 시각과 거의 같아 같은 문서를 두 번 읽는 꼴이 됐다(2026-09-18).
   * 표는 "언제 닿았나"를, 그 안의 줄들은 "그때 무슨 일이 있었나"를 말한다.
   *
   * <p>줄은 시각으로 나눈다 — 단계는 순서대로 닿지 않을 수 있어, 목록 순서로 자르면
   * 엉땡한 단계에 붙는다. 닿은 단계를 시각순으로 세우고, 각 줄을 그 시각을 넘지 않는
   * 마지막 단계에 달아 준다.</p>
   */
  const stamped = rows.filter((r) => r.sec !== null).sort((a2, b2) => a2.sec! - b2.sec!);
  const logsOf = (k: StageKey) => x.timeline.filter(([, at]) => {
    const t = secOfClock(at);
    if (t === null) return false;
    let owner: StageKey | null = null;
    for (const r of stamped) if (r.sec! <= t) owner = r.k;
    return (owner ?? stamped[0]?.k ?? null) === k;
  });

  return (
    <div className="modal" role="presentation" onClick={onClose}>
      <div className="report-modal" role="dialog" aria-modal="true" aria-label="사고 종료 리포트"
           onClick={(e) => e.stopPropagation()}>
        <div className="report-head no-print">
          <h2>사고 종료 리포트</h2>
          <div className="report-actions">
            <button className="btn" onClick={() => window.print()}>인쇄 · PDF 저장</button>
            <button className="btn" onClick={onClose}>닫기</button>
          </div>
        </div>

        <div className="report-sheet" id="report-sheet">
          {/* ── 한 문단으로 읽히는 머리. 배 · 사고 · 걸린 시간이 여기서 다 끝난다 ── */}
          <header className="rp-hero">
            <p className="rp-eyebrow">FloaQ 사고 종료 리포트 · {x.day}</p>
            <h1 className="rp-ship">
              {v.name}<em>{v.reg}</em>
            </h1>
            <p className="rp-kind">
              {x.type.label}{x.type.dsc ? <span className="mono"> DSC {x.type.dsc}</span> : null}
            </p>
            <p className="rp-took">
              {took !== null ? <b>{elapsed(took)}</b> : <b>—</b>}
              <span>만에 {x.stages.close.note ?? '종결'}</span>
            </p>
            <p className="rp-span mono">
              {x.day} {x.stages.detect.at ?? '—'} → {x.stages.close.at ?? '—'}
            </p>
          </header>

          {/*
            ── 그때 상황이 어떠는지 한 문단 ──
            시각과 좌표는 무슨 일이 언제 있었는지는 말해도 <b>그게 무슨 뜻이었는지</b>는 안 말해 준다.
            사고를 가지고 있는 판단 문장이 있는데 지금까지 어느 화면에도 안 나오고 있었다(2026-09-18).
          */}
          <section className="rp-sec rp-brief">
            <h3>개요</h3>
            <p>{briefOf(x, v.name, v.reg, took).join(' ')}</p>
          </section>

          {/* ── 어디서 늦었나. 총 시간 다음으로 먼저 보는 것이다 ── */}
          <section className="rp-sec">
            <h3>대응 단계</h3>
            <ol className="rp-steps">
              {rows.map((r, i) => {
                const logs = r.at ? logsOf(r.k) : [];
                return (
                  <li key={r.k} className={r.at ? 'is-done' : 'is-miss'}>
                    <i className="rp-no">{i + 1}</i>
                    <b className="rp-step-name">{r.label}</b>
                    <span className="rp-step-at mono">{r.at ?? '미달성'}</span>
                    <span className="rp-step-gap mono">
                      {r.gap !== null && i > 0 ? `+${elapsed(r.gap)}` : ''}
                    </span>
                    {/* 그 단계 안에서 실제로 있었던 일. 없으면 줄을 만들지 않는다 */}
                    {logs.length ? (
                      <ul className="rp-step-log">
                        {logs.map(([, at, head, note], n) => (
                          <li key={n}>
                            <b className="mono">{at}</b>
                            <span>{head}</span>
                            {note ? <em>{note}</em> : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </section>

          {/* ── 어디서 어느 쪽으로. 표가 못 말하는 것을 지도가 말한다 ── */}
          <section className="rp-sec rp-course">
            <h3>현장 경로</h3>
            <ReportMap x={x} />
            <ul className="rp-legend">
              <li className="lg-ship">선박</li>
              {x.map.mob ? <li className="lg-mob">감지 지점</li> : null}
              {x.map.foundAt ? <li className="lg-found">사고자 발견</li> : null}
              {b ? <li className="lg-buoy">부표 최종</li> : null}
              {(x.map.track?.measured?.length ?? 0) > 1 ? <li className="lg-btrack">부표가 보낸 경로</li> : null}
              {b && b.fix === 'estimated' ? <li className="lg-etrack">통신 두절 구간(계산)</li> : null}
            </ul>
          </section>

          {/* ── 사실관계. 여기부터는 근거라 작게 ── */}
          <section className="rp-sec">
            <h3>기록</h3>
            <dl className="rp-rows">
              <div><dt>종결 주체</dt><dd>{closedBy}</dd></div>
              <div><dt>수온</dt><dd>{x.waterTemp.toFixed(1)}℃</dd></div>
              <div><dt>감지 지점</dt><dd className="mono">{x.map.mob ? ddm(x.map.mob) : '—'}</dd></div>
              <div>
                <dt>부표 최종</dt>
                <dd className="mono">
                  {b ? `${ddm(b.at)} (${b.fix === 'measured' ? '실측' : '추정'})` : '발사 없음'}
                </dd>
              </div>
              <div><dt>부표 잡음</dt><dd>{b?.heldAt ? `확인 ${b.heldAt}` : '미확인'}</dd></div>
              {launch.map(([name, val, unit]) => (
                <div key={name}><dt>{name}</dt><dd className="mono">{val}{unit ?? ''}</dd></div>
              ))}
              {params.map(([name, , val]) => (
                <div key={name}><dt>{name}</dt><dd className="mono">{val}</dd></div>
              ))}
            </dl>
            {!params.length && !launch.length ? (
              <p className="rp-none">발사 없음 — 취소된 감지입니다.</p>
            ) : null}
          </section>

        </div>
      </div>
    </div>
  );
}

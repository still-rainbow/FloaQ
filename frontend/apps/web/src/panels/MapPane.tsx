import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FloaqMap, MapView } from '@floaq/shared';
import type { FloaqMapApi, LngLat, MapTheme, MarkerSpec } from '@floaq/shared';
import { MapEye } from '../components/MapEye';
import { byVessel } from '../lib/fleet';
import { incidentView } from '../lib/view';
import { useSeaOf } from '../lib/useSea';
import type { IncidentView } from '../lib/view';
import { DriftSlider } from '../components/DriftSlider';
import { ago } from '../lib/time';
import { BAND_RAMP, STEPS } from '../lib/drift';
import { isAdrift, isMob } from '../lib/kind';
import { noOf } from '../lib/mapNo';
import { ddm } from '../lib/ddm';
import type { Incident, Urgency } from '../types';

/** 잇달아 같은 좌표가 들어오면 걷어낸다. 궤적 끝과 다음 조각의 시작이 같은 점일 때가 있다 */
const noRepeat = (pts: LngLat[]): LngLat[] =>
  pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1]![0] || p[1] !== pts[i - 1]![1]);

const URG_CLASS: Record<Urgency, string> = { distress: 'urg-d', urgency: 'urg-u' };

/** 사고마다 지도에 부표·사람 표시를 켜고 끈다 */
interface Layers { buoy: boolean; person: boolean }

/**
 * 사람 마커. 버튼이 안 눌렸으면 받은 사람 추정 위치,
 * 눌렸으면 버튼이 잘못 눌렸을 경우를 대비해 부표와 따로 계산한 추정 위치(lib/view.ts personAlt)다.
 * 부표 위치에 세우면 확인하는 의미가 없다.
 */
const personOf = (x: Incident, v: IncidentView) => (isMob(x) ? v.person ?? v.personAlt : null);

/**
 * 0장 — 이 지도의 핵심은 **부표 마커가 사라지지 않는 것**이다.
 * 통신이 끊겨도 마커는 남고, 실측이면 채워진 원, 추정이면 점선 원으로 형태만 바뀐다.
 * 부표 버튼이 눌리지 않았으면 사람 마커가 따로 하나 더 선다(0.2).
 *
 * 사고는 여러 건을 함께 띄울 수 있다. 슬롯 0 이 지금 보고 있는(포커스) 사고이고
 * 나머지 슬롯은 함께 띄운 사고다. **모두 같은 것을 그린다** — 선박·익수 지점·부표·사람·
 * 궤적·추정 범위까지. 함께 보는 이유가 위치 하나 찍어 보려는 게 아니기 때문이다.
 * 포커스만 조금 더 진하게 두어 어느 쪽을 보고 있는지 알 수 있게 한다.
 */
const SLOTS = 8;

const shipSvg = (i: number) =>
  '<svg width="26" height="26" viewBox="0 0 26 26">'
  // 색은 긴급도를 따른다(web.css .mk-vessel[data-urg]). 조난 빨강 · 긴급 노랑 · 안전 초록
  + '<circle cx="13" cy="13" r="12" style="fill:rgba(var(--mk-rgb),.18)"/>'
  + `<g id="mkShipRot${i}" transform="translate(13 13)">`
  + '<path d="M0-8 5.4 5.4-5.4 5.4Z" style="fill:var(--mk-c)" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/>'
  + '</g></svg>';

/**
 * 마커 클릭을 지금 화면의 슬롯으로 되돌려 주는 통로.
 * 마커는 지도가 만들어질 때 한 번만 생성되므로 핸들러를 나중에 갈아끼울 수 없다.
 * 그래서 고정된 핸들러가 이 상자를 거쳐 그때그때의 함수를 부른다.
 */
const slotClick: { fn: ((slot: number) => void) | null } =
  // 개발 중 이 파일이 다시 불리면(HMR) 상자가 새로 생기는데, 이미 만든 마커는 옛 상자를 부른다.
  // 그러면 옛 상자의 fn 이 비어 마커를 눌러도 아무 일이 없다. 한 상자를 전역에 두어 늘 같은 것을 보게 한다.
  ((globalThis as { __floaqSlotClick?: { fn: ((slot: number) => void) | null } }).__floaqSlotClick ??= { fn: null });

/** 받침이 있으면 '으로', 없거나 ㄹ 받침이면 '로' — `금호호로 이동` · `영진으로 이동` */
const ro = (word: string) => {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  if (code < 0 || code > 11171) return '로';
  const jong = code % 28;
  return jong === 0 || jong === 8 ? '로' : '으로';
};

const MARKERS: MarkerSpec[] = [];
for (let i = 0; i < SLOTS; i += 1) {
  MARKERS.push(
    { id: `ship${i}`, at: [129.1195, 35.0918], cls: 'mk-vessel', hidden: true,
      click: () => slotClick.fn?.(i),
      html: `${shipSvg(i)}<div class="mk-label" id="mkShipLabel${i}"></div>` },
    { id: `mob${i}`, at: [129.1195, 35.0918], cls: 'mk-flag', hidden: true,
      click: () => slotClick.fn?.(i),
      html: '<svg width="26" height="26" viewBox="0 0 26 26">'
          + '<circle cx="13" cy="13" r="12" fill="rgba(217,64,64,.16)"/>'
          + '<path d="M13 6.5 19 18H7Z" fill="none" stroke="#d94040" stroke-width="2.2" stroke-linejoin="round"/>'
          + `</svg><div class="mk-label" id="mkMobLabel${i}"></div>` },
    { id: `buoy${i}`, at: [129.1195, 35.0918], cls: 'mk-buoy', hidden: true,
      click: () => slotClick.fn?.(i),
      html: `<b></b><i></i><div class="mk-label" id="mkBuoyLabel${i}"></div>` },
    { id: `person${i}`, at: [129.1195, 35.0918], cls: 'mk-person', hidden: true,
      click: () => slotClick.fn?.(i),
      html: `<b></b><i></i><div class="mk-label" id="mkPersonLabel${i}"></div>` },
  );
}

function label(id: string, head: string, sub: string) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `${head}<span>${sub}</span>`;
}

interface Props {
  incident: Incident | null;
  /** 함께 띄운 사고들(포커스 제외). 슬롯 1 부터 들어간다. */
  others: Incident[];
  theme: MapTheme;
  onApi: (api: FloaqMapApi) => void;
  /** 표류 슬라이더의 Δt(초). App 이 들고 있다 — 지도와 좌표 표시가 같은 값을 봐야 한다. */
  dt: number;
  onDt: (sec: number) => void;
  /** 카드를 누를 때마다 오르는 값. 같은 사고를 다시 눌러도 화면을 그 위치로 되돌린다. */
  focusTick: number;
  /** 지도에 올린 순서. 마커·범례 번호가 여기서 나온다. */
  picked: string[];
  /** 지도에서 마커를 누르면 그 사고로 포커스가 옮겨 간다. */
  onFocusIncident: (x: Incident) => void;
  // 내리기(×)·전부 해제는 왼쪽 목록이 전담한다. 범례 패널과 함께 지웠다(2026-09-17)
  /**
   * 지금 어느 지도인가. 진행 중(live)과 기록(log) 는 <b>한니도 다를 것처럼 부여진다</b> —
   * 지나가는 알림 한 줄로 알리는 대신 지도 자신이 어느 쪽인지 계속 말하게 한다(2026-09-18).
   */
  mode: 'live' | 'log';
  /** 수색 모드로 전환 — 출동한 구조정이 보는 화면 */
  onOpenSearch: () => void;
  /**
   * 관리자다 — 보되 손대지 않는다(App.tsx isAdmin). 수색 모드는 <b>출동한 배</b>가 쓰는 화면이고
   * 안에 사고자 발견 처리가 있다. 출동하지 않는 사람에게 열어 둘 이유가 없다.
   */
  readOnly?: boolean;
  /**
   * 기록 탭에서 고른 배가 <b>지금 사고 중</b>이면 그 사고(App.tsx liveHere).
   * 지도가 비었으면 가운데 안내 자리에, 지난 사고가 떠 있으면 왼쪽 위에 사고 탭으로 가는 길을 띄운다
   */
  liveHere?: Incident | null;
}

export function MapPane({
  incident, others, theme, onApi, dt, onDt, focusTick, picked, mode,
  onFocusIncident, onOpenSearch, readOnly, liveHere,
}: Props) {
  const apiRef = useRef<FloaqMapApi | null>(null);
  const [ready, setReady] = useState(false);
  /** 지도에 뜬 사고들의 바다 값. 함께 띄운 사고도 추정을 그려야 하므로 전부 받는다 */
  const seaOf = useSeaOf(incident ? [incident, ...others] : others);
  /**
   * 부표·사람을 지도에서 내린다. <b>띄운 사고 전부에 한꺼번에</b> 적용된다.
   *
   * <p>전에는 사고마다 스위치가 달린 범례 패널이 지도 오른쪽 위를 덮고 있었다. 그 패널이 하던 일
   * 여섯 중 다섯(건수·번호·부표 상태·포커스 이동·전부 해제)이 왼쪽 목록과 겹쳤고,
   * 사고가 늘수록 패널이 커져 마커를 가렸다 — 통째로 걷어냈다(2026-09-17).</p>
   *
   * <p>남은 것은 이 두 줄이다. 그리고 이 두 줄은 <b>스위치이면서 범례다</b> —
   * 지도의 주황 점이 부표고 빨간 점선 원이 사람이라는 것을 여기 말고 적어 둔 데가 없었다.
   * 모양을 그려 두면 "이게 왜 있나"가 자리를 더 쓰지 않고 풀린다.</p>
   */
  const [hide, setHide] = useState({ buoy: false, person: false });
  const layersOf = useCallback(
    (): Layers => ({ buoy: !hide.buoy, person: !hide.person }),
    [hide],
  );

  /** 마지막으로 그린 점들. '전체 보기'가 이걸로 화면을 맞춘다. */
  const allPts = useRef<LngLat[]>([]);
  /** 포커스한 사고의 점들. 카드를 다시 눌렀을 때 여기로 돌아온다. */
  const focusPts = useRef<LngLat[]>([]);

  /**
   * 지도에 그릴 사고들. 포커스한 것이 앞에 오지만, **포커스가 없어도 그린다** —
   * 토글만 켜고 카드를 누르지 않은 경우가 그렇다. 예전에는 여기서 빈 배열이 나와
   * 토글을 켜도 지도에 아무것도 안 떴다.
   */
  const shown = useMemo(() => {
    const list = incident ? [incident, ...others] : others;
    return list.slice(0, SLOTS).map((x) => ({
      x,
      v: incidentView(x, dt, seaOf[x.id]?.sea ?? null),
      focus: !!incident && x.id === incident.id,
    }));
  }, [incident, others, dt, seaOf]);

  const view = shown.find((s) => s.focus)?.v ?? incidentView(null, dt, null);


  // 마커·궤적은 선택한 사고에 맞춰 여기서만 그린다.
  // onReady 안에서 그리면 뒤늦게 실행돼 선택 상태를 덮어쓴다.
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;

    const pts: LngLat[] = [];
    const mineOfFocus: LngLat[] = [];

    for (let i = 0; i < SLOTS; i += 1) {
      const slot = shown[i];

      if (!slot) {
        (['ship', 'mob', 'buoy', 'person'] as const)
          .forEach((k) => api.setMarker(`${k}${i}`, null, false));
        api.setLine(`btrack${i}`, []);
        api.setLine(`etrack${i}`, []);
        api.setLine(`pheld${i}`, []);
        api.setLine(`ptrack${i}`, []);
        api.setBand(`buoy${i}`, null);
        api.setBand(`person${i}`, null);
        continue;
      }

      const { x, v, focus } = slot;
      const m = x.map;
      const ves = byVessel[x.ship]!;
      // 포커스가 아닌 사고는 한 단계 옅게. 다 진하면 어느 것을 보고 있는지 알 수 없다.
      const back = !focus;
      // 범례의 부표·사람 스위치. 끄면 마커와 함께 추정 범위·궤적도 내린다.
      const L = layersOf();
      const showBuoy = !!v.buoy && L.buoy;
      const person = personOf(x, v);
      const showPerson = !!person && L.person;
      // 사람 마커가 따로 서면 부표는 대리 지표로 물러난다(0.2)
      const apart = showPerson;

      api.setMarker(`ship${i}`, v.ship?.at ?? m.ship, true);
      api.setMarker(`mob${i}`, m.mob, !!m.mob);
      api.setMarker(`buoy${i}`, v.buoy?.at ?? null, showBuoy);
      api.setMarker(`person${i}`, person?.at ?? null, showPerson);

      // 실측 구간은 실선, 추정 구간은 점선. 한 선으로 이으면 어디까지가 실제 값인지 사라진다.
      api.setLine(`btrack${i}`, showBuoy ? m.track?.measured ?? [] : []);
      /**
       * 부표 추정 구간 — **마지막으로 받은 자리에서 지금 추정 위치까지** 점선으로 잇는다.
       * 전에는 목업에 적어 둔 궤적을 그렸는데, 그것과 계산된 추정 위치가 따로 놀아
       * 추정 마커가 실측 궤적과 끊긴 채 떠 있었다. 이제 둘이 반드시 이어진다.
       */
      const bEst = showBuoy && m.buoy?.fix === 'estimated' && v.buoy ? [m.buoy.lastFixAt, v.buoy.at] : [];
      api.setLine(`etrack${i}`, bEst);

      /**
       * 사람 경로는 두 토막이다.
       *   잡고 있던 구간  부표가 실제로 보낸 위치를 따라간 길 → **실선**(아는 값)
       *   놓은 뒤 구간    혼자 흘러간 길 → 점선(추정)
       * 잡은 적이 없으면 익수 지점에서 통째로 점선이다.
       */
      /*
       * 사람이 <b>부표와 함께 있던 마지막 자리</b>. 여기까지가 아는 값이고, 여기서부터가 추정이다.
       *   놓은 적 있음        놓은 자리(releasedFrom)
       *   마지막 수신까지 눌림  마지막으로 받은 자리(lastFixAt) — 그 뒤는 눌림도 위치도 오지 않는다
       *   잡은 적 없음         없음. 익수 지점에서 통째로 점선이다
       *
       * 전에는 놓은 자리만 봤다. 그래서 금호호처럼 "놓은 적은 없고 신호만 끊긴" 경우 실선이 0이 되고
       * 익수 지점부터 전부 점선으로 그려졌다 — 잡고 있던 한 시간까지 추정처럼 보였다(2026-09-18).
       */
      const bm = m.buoy;
      const heldTo = bm?.releasedFrom ?? (bm?.heldAtLastFix ? bm.lastFixAt : null);
      const personFrom = m.mob ?? bm?.lastFixAt ?? null;
      /*
       * 잡고 있던 구간은 <b>부표가 실제로 보낸 위치</b>를 그대로 따라간다 — 그때 사람은 부표에 있었다.
       * 곧은 선으로 이으면 실제로 받은 길을 버리고 추정처럼 그리는 셈이다.
       */
      const heldPath = showPerson && heldTo
        ? noRepeat([...(m.mob ? [m.mob] : []), ...(m.track?.measured ?? []), heldTo])
        : [];
      api.setLine(`pheld${i}`, heldPath);
      api.setLine(`ptrack${i}`, showPerson && person
        ? [heldTo ?? personFrom, person.at].filter(Boolean) as LngLat[]
        : []);

      // 불확실 범위는 추정일 때만. 실측 위치에 원을 씌우면 정확한 값을 부정확하게 보이게 한다.
      // 사람 마커가 따로 서면 부표는 대리 지표로 물러난다(0.2).
      // MOB 이 아니면 조난 대상이 배인데, 배가 어디로 흘러갈지는 그리지 않는다(lib/kind.ts).
      const est = isMob(x) && showBuoy ? v.buoy : null;
      const bb = est?.band;
      // 고리 비율은 입자 4만 개로 쟴 값이다(drift.ts BAND_RAMP). 지도가 가지고 있던 0.68·0.48 은 근거가 없었다.
      api.setBand(`buoy${i}`, bb ? est!.at : null, bb?.a, bb?.b, bb?.bearing, back || apart, BAND_RAMP);
      const pb = showPerson ? person?.band : undefined;
      api.setBand(`person${i}`, pb ? person!.at : null, pb?.a, pb?.b, pb?.bearing, back, BAND_RAMP);

      // 목록·범례와 같은 색 채운 동그라미 번호.
      // em 을 쓴다 — 부표·사람 마커는 i·b 를 마커 그림으로, 라벨의 span 을 둘째 줄로 칠한다.
      const no = noOf(picked, x.id);
      const tag = no > 0 ? `<em class="map-no ${URG_CLASS[x.type.urg]}">${no}</em>` : '';

      label(`mkShipLabel${i}`, `${tag}${ves.name}`,
        isMob(x) ? (x.state === 'live' ? '실시간' : x.day)
          : isAdrift(x) ? '표류 중 · 조종 불능'
            : x.type.label);
      if (m.mob) label(`mkMobLabel${i}`, `${tag}익수 지점`, m.mobText || '');

      if (m.buoy) {
        // Δt 로 앞당겨 그린 것도 추정이다. 형태가 데이터와 어긋나면 안 된다.
        const est = m.buoy.fix === 'estimated' || v.projected;
        // 마커 아래에는 "언제 받았는가"만 적는다. 앞당겨 그렸다는 사실은 슬라이더가 이미 말한다
        const sub = est ? `마지막 수신 ${ago(m.buoy.ageSec)}` : `${ago(m.buoy.ageSec)} 수신`;
        label(`mkBuoyLabel${i}`, `${tag}${est ? '부표 (추정)' : '부표 (실측)'}`, sub);
        const el = api.markers[`buoy${i}`]?.getElement();
        // 마커에 올리면 좌표를 띄운다 — 오른쪽 패널까지 가지 않고 그 자리에서 무전으로 읽을 수 있다
        if (el && v.buoy) el.title = `부표 ${est ? '추정' : '실측'}
${ddm(v.buoy.at)}`;
        el?.classList.toggle('is-estimated', est);
        el?.classList.toggle('is-held', !!m.buoy.heldAt);
        el?.classList.toggle('is-secondary', apart);
        el?.classList.toggle('is-back', back);
      }
      if (person) {
        label(`mkPersonLabel${i}`, `${tag}사람 (추정)`,
          v.person ? ves.name : '버튼 오작동 대비 · 익수 지점 기준');
      }

      const personEl2 = api.markers[`person${i}`]?.getElement();
      if (personEl2 && person) personEl2.title = `사람 추정
${ddm(person.at)}`;
      personEl2?.classList.toggle('is-back', back);
      const shipEl = api.markers[`ship${i}`]?.getElement();
      shipEl?.classList.toggle('is-back', back);
      // .urg-* 클래스는 전역에서 배경까지 칠해 마커에 네모가 생긴다. data 속성으로 색만 넘긴다
      if (shipEl) shipEl.dataset.urg = x.type.urg;
      api.markers[`mob${i}`]?.getElement()?.classList.toggle('is-back', back);

      document.getElementById(`mkShipRot${i}`)
        ?.setAttribute('transform', `translate(13 13) rotate(${m.hdg || 0})`);

      // 선박·익수 지점·부표가 수백 미터 안에 몰려 있다. 기본 축척이면 한 점에 겹쳐 라벨을 못 읽는다.
      const mine: LngLat[] = [m.ship];
      if (m.mob) mine.push(m.mob);
      for (const e of [showBuoy ? v.buoy : null, showPerson ? person : null]) {
        if (!e) continue;
        mine.push(e.at);
        if (e.band) {
          const { a, b, bearing } = e.band;
          mine.push(FloaqMap.offset(e.at, a, bearing), FloaqMap.offset(e.at, a, bearing + 180),
                    FloaqMap.offset(e.at, b, bearing + 90), FloaqMap.offset(e.at, b, bearing - 90));
        }
      }
      pts.push(...mine);
      if (focus) mineOfFocus.push(...mine);
    }

    /*
     * 🔴 <b>지도에 무엇이든 올라가 있으면 누른다.</b> 기준은 "고른 사고가 있나"가 아니라
     * <b>"지금 지도에 그린 것이 있나"</b> 하나뿐이다.
     *
     * <p>전에는 포커스한 사고(incident)를 봤는데, 등록 선박에서 사고가 여러 건인 배를 켜면
     * 포커스 없이 지도에만 올라간다 — 그때 지도가 안 눌려 같은 조작인데 화면이 달라 보였다.
     * 진행 중 사고 · 종결된 사고 · 등록 선박 셋이 제각각이던 이유가 이것이다(2026-09-18).</p>
     *
     * <p>'지도에 표시' 는 한 가지 뜻이어야 한다 — <b>배경이 물러나고 사고가 앞으로 나온다.</b></p>
     */
    api.setDim(shown.length > 0 && mode === 'live');

    // 카드를 누르면 "그 배로 이동"하는 것이 기대 동작이라 화면은 포커스 사고에 맞춘다.
    // 함께 띄운 것까지 담으려면 '전체 보기'를 누른다 — 두 동작을 한 조작에 섞지 않는다.
    allPts.current = pts;
    focusPts.current = mineOfFocus;
  }, [shown, ready, incident, layersOf, mode]);

  // 마커 클릭 → 그 슬롯의 사고로 포커스. 슬롯이 어느 사고인지는 렌더마다 달라지므로
  // 고정된 마커 핸들러가 최신 매핑을 볼 수 있도록 여기서 갈아끼운다.
  useEffect(() => {
    slotClick.fn = (slot) => {
      const s = shown[slot];
      if (s) onFocusIncident(s.x);
    };
    return () => { slotClick.fn = null; };
  }, [shown, onFocusIncident]);

  /**
   * 화면 맞추기는 **사고를 바꿨을 때와 카드를 눌렀을 때만** 한다.
   * 위치가 실시간으로 갱신되므로 그리기 때마다 맞추면 지도를 옮겨 볼 수가 없다.
   */
  useEffect(() => {
    if (!ready) return;
    // 포커스한 사고가 있으면 거기에, 없으면 켜 둔 것 전부에 맞춘다.
    // 토글만 켰을 때도 화면이 그쪽으로 가야 켰다는 걸 알 수 있다.
    const pts = focusPts.current.length ? focusPts.current : allPts.current;
    if (pts.length) apiRef.current?.fitPoints(pts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incident?.id, focusTick, ready, shown.length]);

  const live = incident?.state === 'live';

  /**
   * 범례는 "이 마커가 무슨 뜻인가"가 아니라 **"지금 지도에 뭐가 있나"**를 답해야 한다.
   * 사고를 여러 건 띄우면 마커가 열 개를 넘는데, 그때 필요한 건 기호 설명이 아니라 목록이다.
   */
  return (
    <section className="pane pane-map">
      <div className={`map-wrap${shown.length && mode === 'live' ? ' is-incident' : ''}${mode === 'log' ? ' is-log' : ''}`}
           data-theme={theme}>
        <MapView
          /* 망망대해에서는 타일이 하늘색 한 장이라 지도가 떴는지조차 모른다 — 눈금을 항상 남긴다 */
          grid="always"
          className="map-canvas"
          center={[129.1195, 35.0918]}
          zoom={13.4}
          theme={theme}
          markers={MARKERS}
          onReady={(api) => { apiRef.current = api; onApi(api); setReady(true); }}
        />

        <div className="map-ui tl">
          {/*
            수색 모드 전환. 상세 패널 안쪽에 있으면 못 찾는다 — 지도 위 맨 앞에 둔다.

            🔴 <b>부표가 없어도 띄운다.</b> 전에는 `map.buoy` 를 조건에 넣어, 발사가 실패한 사고에서
            버튼이 사라졌다(2026-09-17). 그런데 바다에 찾을 주황색이 없는 그때가 **수색이 제일 급한 때**다.
            필요한 것은 부표가 아니라 찾을 대상 — 부표든 사람이든 하나라도 있으면 연다.
          */}
          {!readOnly && incident && isMob(incident) && incident.state === 'live'
            && (incident.map.buoy || incident.map.person) ? (
            <button className="floaty map-btn map-search" onClick={onOpenSearch}
                    title="출동한 구조정이 보는 수색 화면으로 전환합니다">
              <i className="map-btn-ico" aria-hidden="true">⌖</i>
              <span>수색 모드로 전환</span>
            </button>
          ) : null}

          {shown.length > 1 ? (
            <button className="floaty map-btn"
                    title="함께 표시한 사고를 모두 화면에 담습니다"
                    onClick={() => apiRef.current?.fitPoints(allPts.current)}>
              <i className="map-btn-ico" aria-hidden="true">⤢</i>
              <span>함께 표시한 {shown.length}건 전체 보기</span>
            </button>
          ) : null}

          {/* 누르면 보고 있는 사고 위치로 지도를 되돌린다. 지도를 끌고 다니다 길을 잃었을 때 쓴다. */}
          <button className="floaty map-btn map-mode" data-live={live ? '1' : '0'}
                  disabled={!incident}
                  title={incident ? '이 사고 위치로 지도 옮기기' : undefined}
                  onClick={() => incident && onFocusIncident(incident)}>
            <i className="map-mode-dot" aria-hidden="true" />
            <span>
              {/*
                누르면 지도가 그 배로 옮겨 간다. 진행 중이든 종결이든 <b>하는 일이 같으니 같은 말</b>을 쓴다 —
                전에는 종결일 때 `기록 조회 · 2026-09-07` 이었는데, 그 날짜의 사고만 보여 주는 화면도
                아니면서 버튼이 <b>누르는 이유</b> 대신 상태를 적고 있었다(2026-09-19).
              */}
              {!incident ? '표시할 사고 없음'
                : `${byVessel[incident.ship]?.name ?? incident.ship}${ro(byVessel[incident.ship]?.name ?? '')} 이동`}
            </span>
          </button>

          {/* 지난 사고가 지도에 떠 있으면 가운데 안내(map-empty)는 그것을 가린다. 그때는 여기 한 줄로 */}
          {liveHere && shown.length > 0 ? (
            // 지도에 다른 배의 사고가 떠 있을 수 있어 배 이름을 꼭 적는다. 한 줄에 다 넣으면 잘려 두 줄로 나눈다
            <button className="floaty map-btn map-live-go" onClick={() => onFocusIncident(liveHere)}
                    title="진행 중인 사고는 사고 탭에서 봅니다">
              <span>
                <b>{byVessel[liveHere.ship]?.name ?? liveHere.ship} · 지금 사고 중</b>
                <small>사고 탭에서 보기 →</small>
              </span>
            </button>
          ) : null}
        </div>

        {/*
          지도 표시 열쇠. <b>범례이면서 스위치다</b> — 주황 점이 부표, 빨간 점선 원이 사람이라는 것을
          여기 말고 적어 둔 데가 없었다. 누르면 그 종류를 띄운 사고 전부에서 내린다.
          부표와 사람이 멀어지면 마커가 겹쳐 보이는데, 그때 한쪽을 잠시 내리려고 있는 것이다.
        */}
        <div className="map-ui tr">
          <div className="map-key floaty" role="group" aria-label="지도 표시">
            <button className="key-row" role="switch" aria-checked={!hide.buoy}
                    title="바다에 떠 있는 구명 부표입니다. 사람 마커와 겹쳐 보이면 잠시 내리세요"
                    onClick={() => setHide((h) => ({ ...h, buoy: !h.buoy }))}>
              <i className="key-mk key-buoy" aria-hidden="true" />
              <span>부표</span>
              <MapEye on={!hide.buoy} />
            </button>
            <button className="key-row" role="switch" aria-checked={!hide.person}
                    title="사람의 추정 위치입니다. 직접 받는 위치가 아니라 조류·바람으로 계산한 값이라 점선입니다"
                    onClick={() => setHide((h) => ({ ...h, person: !h.person }))}>
              <i className="key-mk key-person" aria-hidden="true" />
              <span>사람</span>
              <MapEye on={!hide.person} />
            </button>
          </div>
        </div>

        {/*
          표류 범위 시간 슬라이더(신규 7). 지도 위에 두는 이유는 결과가 지도에만 나타나서다.
          **진행 중일 때만** 띄운다. 이 슬라이더가 답하는 질문은 "지금 어디 있을까"인데,
          종결된 사고에는 그 질문이 없다. 오히려 이미 구조가 끝난 시각의 표류 범위를 그리게 돼
          기록을 잘못 읽힌다. 종결 건 지도에는 궤적과 최종 위치가 그대로 남는다.
        */}
        {/* 흘러가는 것이 하나라도 있으면 띄운다. 발사가 실패해 부표가 없어도 **사람은 흘러간다** —
            오히려 그때가 "10분 뒤 어디쯤인가"가 제일 급하다. 부표 유무로 막으면 안 된다. */}
        {incident && incident.state === 'live'
          && (incident.map.buoy || incident.map.person) ? (
          <div className="map-ui bl">
            <div className="floaty drift-box">
              <DriftSlider value={dt} onChange={onDt} movedM={view.movedM} />
            </div>
          </div>
        ) : null}

        {/* 평시에는 지도에 그릴 좌표 자체가 없다. 빈 지도를 그냥 두면 고장으로 읽힌다. */}
        <div className="map-empty floaty" hidden={shown.length > 0}>
          {liveHere ? (
            <>
              {/* 누르자마자 탭을 바꾸면 잘못 누른 것처럼 읽힌다. 넘어갈지는 사용자가 고른다(2026-09-21) */}
              <b>{byVessel[liveHere.ship]?.name ?? liveHere.ship} · 지금 사고 중</b>
              진행 중인 사고는 사고 탭에서 봅니다.
              <button className="btn primary map-empty-go" onClick={() => onFocusIncident(liveHere)}>
                사고 탭에서 보기 →
              </button>
            </>
          ) : (
            <>
              <b>표시할 위치가 없습니다</b>
              평시에는 선박 위치를 웹으로 보내지 않습니다.
              <b style={{ display: 'inline', fontSize: 'inherit', margin: 0 }}>사고가 발생한 선박만</b> 실시간으로 위치를 보냅니다.
            </>
          )}
        </div>

      </div>
    </section>
  );
}

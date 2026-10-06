import { useEffect, useMemo, useRef, useState } from 'react';
import { FloaqMap, MapView } from '@floaq/shared';
import type { FloaqMapApi, LngLat, MapTheme, MarkerSpec } from '@floaq/shared';
import { BASE_RADIUS_M, LEEWAY_BUOY, drift } from '../lib/drift';
import { advance, incidentView } from '../lib/view';
import { buoyState } from '../lib/buoyState';
import { useSea } from '../lib/useSea';
import { byVessel } from '../lib/fleet';
import {
  CELL_M, SWEEP_R, bearingTo, buildGrid, distM, gridStats, staleAfterSec, sweep,
} from '../lib/searchGrid';
import type { Searched } from '../lib/searchGrid';
import {
  PATTERN_LABEL, TRACK_S, buildPattern, lengthFrom, pickPattern, toGeo, toOffset,
} from '../lib/searchPattern';
import type { Pattern, PatternKind } from '../lib/searchPattern';
import { ddm } from '../lib/ddm';
import { elapsed } from '../lib/time';
import { hhmm, survival } from '../lib/survival';
import { FOUND_LABEL, currentLabel } from '../lib/stages';
import { URG } from '../components/Badges';
import type { Incident, Uncertainty } from '../types';

/**
 * 수색 모드 — **출동한 경비정의 태블릿에서 보는 화면**.
 *
 * 관제 상황판이 "전체가 어떻게 돌아가는가"라면 이 화면은 "지금 어디로 가서 무엇을 훑는가"다.
 * 지도를 크게 두고, 옆에는 현장에서 필요한 것만 둔다.
 *
 *   1. 어느 배의 무슨 사고인가, 부표 통신·버튼 상태는 어떤가 (무전으로 가장 먼저 확인하는 것)
 *   2. 실제 해상 수색 패턴(IAMSAR)으로 경로를 짠다 — 붉은 핵심 구역부터
 *   3. 배가 지나가면 그 칸이 **자동으로** 수색 완료가 된다 (경비정 GPS)
 *   4. 표류로 기록이 만료된 칸은 **노랑**으로 되살아난다 (재수색)
 *   5. 발견·종결을 현장에서 바로 입력한다
 */

/** 시뮬레이션 한 틱이 나타내는 실제 시간(초). 표류·만료가 눈에 보이는 속도로 흐르게 한다. */
const TICK_SEC = 10;
const TICK_MS = 400;
/** 구조정 속력 (m/s). 8노트 남짓 */
const BOAT_MS = 4.1;

/**
 * 구조정이 <b>얼마나 멀리서 출발하나</b>(m).
 *
 * <p>전에는 사고 선박 자리에서 시작했다 — 신고 몇 분 뒤인데 경비정이 이미 조난자 옆에 있는
 * 화면이 나왔다. 그럴 수가 없다(2026-09-18). 8km 면 8노트로 약 33분이고, 그동안 조난자는
 * 계속 흘러가므로 "따라가며 훑는다"는 이 화면의 이유가 그대로 드러난다.</p>
 *
 * <p>방향은 <b>사고 선박이 지나온 쪽</b>이다 — 익수 지점에서 배 쪽으로 이은 선을 그대로 늘린다.
 * 임의의 방위를 쓰면 해역에 따라 육지에서 출발하는 배가 된다.</p>
 */
/** `35° 28.672' N, 129° 28.822' E` → 위도 줄 · 경도 줄 */
const llLines = (at: LngLat) => {
  const [lat, lon] = ddm(at).split(', ');
  return <>{lat}<i>{lon}</i></>;
};

const BOAT_START_M = 8000;

function boatStart(x: Incident): LngLat {
  const from = x.map.mob ?? x.map.buoy?.lastFixAt ?? x.map.ship;
  return FloaqMap.offset(x.map.ship, BOAT_START_M, bearingTo(from, x.map.ship));
}

/**
 * 1차는 핵심 구역(50% 확률 타원)만 돈다. 다 돌면 2차로 전체(95%)를 덮는다 — 붉은 곳부터 본다.
 * 95% 반경을 1.0 으로 볼 때 50% 반경은 0.48 이다(지도 추정 범위 띠와 같은 비율).
 */
const CORE_K = 0.48;

const WHY: Record<PatternKind, string> = {
  sector: '위치가 거의 정확합니다. 추정점을 세 번 지나며 부채꼴로 훑습니다.',
  square: `추정점(가장 붉은 곳)에서 시작해 사각형을 ${TRACK_S}m씩 넓혀 갑니다.`,
  parallel: `범위가 넓습니다. 표류 방향으로 줄을 긋고 ${TRACK_S}m 간격으로 왕복합니다.`,
};

const MARKERS: MarkerSpec[] = [
  { id: 'target', at: [129.1195, 35.0918], cls: 'mk-person',
    html: '<b></b><i></i><div class="mk-label" id="smTargetLabel">조난자 추정<span></span></div>' },
  { id: 'boat', at: [129.1195, 35.0918], cls: 'mk-boat',
    html: '<svg width="30" height="30" viewBox="0 0 30 30">'
        + '<circle cx="15" cy="15" r="14" fill="rgba(47,143,109,.2)"/>'
        + '<g id="smBoatRot" transform="translate(15 15)">'
        + '<path d="M0-9 6 6-6 6Z" fill="#2f8f6d" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>'
        + '</g></svg><div class="mk-label" id="smBoatLabel">구조정<span></span></div>' },
];

interface Datum {
  at: LngLat;
  band: Uncertainty;
  movedM: number;
}

interface Plan {
  pattern: Pattern;
  round: 1 | 2;
}

/** 지금 추정점과 배 위치로 패턴을 짠다. kind 가 없으면 불확실성 크기로 자동 선택한다. */
function planFor(d: Datum, boat: LngLat, round: 1 | 2, kind: PatternKind | null): Plan {
  const k = round === 1 ? CORE_K : 1;
  const chosen = kind ?? pickPattern(d.band.a);
  const from = toOffset(d.at, d.band.bearing, boat);
  return {
    pattern: buildPattern(chosen, d.band.a * k, d.band.b * k, d.band.bearing, from, round),
    round,
  };
}

interface Props {
  x: Incident;
  theme: MapTheme;
  onClose: () => void;
  /** 사고자 발견 — 경비정이 현장에서 사람을 찾았을 때 입력한다 */
  onFound: (x: Incident) => void;
  /** 사고 종결 — 종결되면 수색 모드도 닫히고 종료 리포트가 뜬다 */
  onResolve: (x: Incident) => void;
}

export function SearchMode({ x, theme, onClose, onFound, onResolve }: Props) {
  const apiRef = useRef<FloaqMapApi | null>(null);
  const [ready, setReady] = useState(false);
  const sea = useSea(x);
  /* 관제 화면과 같은 문장을 한 군데에서 받아 쓴다 */
  const bs = x.map.buoy ? buoyState(x) : null;

  /** 시뮬레이션 시각(초). 사고 발생 이후 경과에 더해진다. */
  const [simSec, setSimSec] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [searched, setSearched] = useState<Searched>({});
  /** 구조정은 사고 지점에서 BOAT_START_M 떨어진 곳에서 출발한다(진입 시점 위치) */
  const [boat, setBoat] = useState<LngLat>(() => boatStart(x));
  const [hdg, setHdg] = useState(0);
  /** 지나온 길. 어디를 이미 돌았는지 선으로 남긴다. */
  const [trail, setTrail] = useState<LngLat[]>(() => [boatStart(x)]);
  /** 종결은 한 번 더 확인받는다. 흔들리는 배 위 태블릿이라 잘못 누르기 쉽다. */
  const [confirmClose, setConfirmClose] = useState(false);
  /** 이 화면 설명. 기본은 접힘 — 현장에서는 좌표와 다음 지점이 먼저다 */

  /**
   * 수색 대상은 사람이다. 부표를 잡고 있으면 부표가 곧 사람 위치다.
   *
   * 출발점은 진입 시점 값이다. 거기서 **수색 모드 시계(simSec)만큼 흘려** 지금 위치를 만든다 —
   * 관제 화면의 1초 갱신을 그대로 따라가면 모의 항적의 10초 틱과 시계가 섞인다.
   * 칸은 출발점 기준으로 바다에 고정하고(buildGrid 의 origin), 가능성 분포만 흘러간다.
   */
  /**
   * 🔴 <b>바다 값이 도착한 뒤에 얼린다.</b> `useSea` 는 서버를 다녀오므로 첫 렌더에는 null 이다 —
   * 그때 얼려 버리면 사람 추정이 없는 화면(`incidentView(x, 0, null)`)이 그대로 굳어서,
   * 출발점이 부표 실측 자리가 되고 경과가 0 이 된다. 그러면 범위가 GPS 오차(약 59m)뿐이라
   * <b>격자가 한 칸만 생기고 패턴이 시작하자마자 끝난다</b> — 2026-09-17 에 실제로 그랬다.
   */
  const startRef = useRef<ReturnType<typeof incidentView> | null>(null);
  if (!startRef.current && sea) startRef.current = incidentView(x, 0, sea.sea);
  const start = startRef.current;

  /*
   * 🔴 <b>관제 지도가 그린 것을 그대로 받아 온다.</b> 전에는 여기서 `person 이면 사람 계수` 로
   * 다시 골랐는데, 그러면 <b>잡았는지 모를 때</b> 쓰는 계수(LEEWAY_HELD_UNKNOWN)와
   * 두 경우가 벌어지는 폭(splitOf)이 통째로 빠진다 — 같은 사고인데 지도의 범위와
   * 수색 화면의 범위가 서로 다른 자리에 다른 크기로 떴다(2026-09-18).
   *
   * 이제 `Placed` 가 자기를 만든 계수를 들고 다니고, 여기서는 그것으로 더 흘리기만 한다.
   * 지도가 사람 마커를 personAlt 로 세우는 경우(부표 버튼이 눌린 실측)도 같은 순서로 고른다.
   */
  const origin = start ? start.person ?? start.personAlt ?? start.buoy : null;
  const leeway = origin?.leeway ?? LEEWAY_BUOY;

  const datumAt = (sec: number): Datum | null => {
    // 바다 값이 없으면 어디로 흘렀는지 셀 수 없다. 격자를 펴 봐야 아무 데나 가리킨다
    if (!origin || !sea) return null;
    // 그려 둔 범위를 다시 미는 것이 아니라 **출발점에서 통** 다시 센다 —
    // 두 걸음으로 나누면 같은 불확실성을 두 번 센다(lib/drift.ts).
    const e = advance(origin, sea.sea, sec);
    // 실측이라 흘린 시간이 0 이면 band 가 null 이다 — 그때도 출발점 오차만큼은 훑어야 한다
    return { at: e.at,
             band: e.band ?? { a: BASE_RADIUS_M, b: BASE_RADIUS_M, bearing: 0 },
             movedM: e.movedM };
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const target = useMemo(() => datumAt(simSec), [simSec, sea]);

  /** 패턴 수동 선택. null 이면 자동 */
  const [manualKind, setManualKind] = useState<PatternKind | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  /**
   * 첫 패턴은 바다 값이 도착한 뒤에 짠다. 초기값으로 한 번만 계산하면 그때는 범위가 없어
   * 경유지 한두 개짜리 패턴이 나오고, 열자마자 "패턴 완료"가 뜬다.
   */
  useEffect(() => {
    if (plan) return;
    const d = datumAt(0);
    if (d) setPlan(planFor(d, boat, 1, manualKind));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sea, origin, plan]);
  /** 다음에 갈 경유지 번호 */
  const [wp, setWp] = useState(0);

  const staleAfter = useMemo(() => (sea ? staleAfterSec(sea.sea, leeway, CELL_M) : Infinity), [leeway, sea]);

  const cells = useMemo(
    () => (target && origin
      ? buildGrid(target.at, target.band, searched, simSec, staleAfter, CELL_M, origin.at)
      : []),
    [target, origin, searched, simSec, staleAfter],
  );
  const stats = useMemo(() => gridStats(cells), [cells]);

  /** 경유지를 지금 추정점에 붙인다 — 패턴이 조난자와 함께 흘러간다. */
  const wps = useMemo(
    () => (plan && target ? plan.pattern.points.map((o) => toGeo(target.at, plan.pattern.bearing, o)) : []),
    [plan, target],
  );
  const nextWp = wps[wp] ?? null;
  const legs = Math.max(0, (plan?.pattern.points.length ?? 1) - 1);
  const leftM = plan && nextWp ? distM(boat, nextWp) + lengthFrom(plan.pattern.points, wp) : 0;

  /** 수색 모드의 시계는 진입 시점을 기준으로 흐른다. 관제 화면의 실시간 경과와 섞지 않는다. */
  const baseElapsed = useRef(x.elapsedSec).current;

  function replan(kind: PatternKind | null = manualKind) {
    if (!target) return;
    setPlan(planFor(target, boat, plan?.round ?? 1, kind));
    setWp(0);
  }
  function choose(kind: PatternKind | null) {
    setManualKind(kind);
    replan(kind);
  }

  /** 모의 항적. 실제로는 구조정 GPS 가 이 자리에 들어온다. 경유지를 차례로 따라간다. */
  useEffect(() => {
    if (!playing || !nextWp) return;
    const t = window.setInterval(() => {
      setSimSec((s) => s + TICK_SEC);
      const step = BOAT_MS * TICK_SEC;
      const brg = bearingTo(boat, nextWp);
      setHdg(brg);
      if (distM(boat, nextWp) <= step) {
        setBoat(nextWp);
        setWp((w) => w + 1);
      } else {
        setBoat(FloaqMap.offset(boat, step, brg));
      }
    }, TICK_MS);
    return () => window.clearInterval(t);
  }, [playing, boat, nextWp]);

  // 패턴을 다 돌면 1차(핵심) → 2차(전체)로 넓힌다. 2차까지 끝나면 멈춘다.
  useEffect(() => {
    if (!plan || !target || wp < plan.pattern.points.length) return;
    if (plan.round === 1) {
      setPlan(planFor(target, boat, 2, manualKind));
      setWp(0);
    } else {
      setPlaying(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wp, plan]);

  // 배가 지나간 자리는 자동으로 훑은 것으로 기록하고, 지나온 길로 남긴다.
  useEffect(() => {
    setSearched((prev) => sweep(cells, boat, simSec, prev));
    setTrail((t) => (t[t.length - 1] === boat ? t : [...t, boat].slice(-800)));
    // cells 는 searched 에서 파생되므로 넣으면 순환한다. boat·simSec 만 본다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boat, simSec]);

  // 지도 갱신
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;

    api.setGrid(cells, (id) => {
      // 손으로도 고칠 수 있어야 한다. GPS 가 못 잡는 상황이 실제로 생긴다.
      setSearched((prev) => {
        const nextMap = { ...prev };
        if (nextMap[id] !== undefined) delete nextMap[id];
        else nextMap[id] = simSec;
        return nextMap;
      });
    });

    api.setMarker('target', target?.at ?? null, !!target);
    api.setMarker('boat', boat, !!boat);
    api.setLine('route', nextWp ? [boat, ...wps.slice(wp)] : []);
    api.setLine('wake', trail);

    const el = document.getElementById('smBoatRot');
    if (el) el.setAttribute('transform', `translate(15 15) rotate(${hdg})`);

    const lab = document.getElementById('smBoatLabel');
    if (lab) {
      lab.innerHTML = nextWp
        ? `구조정<span>다음 지점 ${Math.round(distM(boat, nextWp))}m</span>`
        : '구조정<span>패턴 완료</span>';
    }
    const tl = document.getElementById('smTargetLabel');
    if (tl && target) {
      tl.innerHTML = `조난자 추정<span>${target.movedM > 0 ? `진입 후 ${Math.round(target.movedM)}m 표류` : ''}</span>`;
    }
    // ready 가 빠져 있으면 지도가 준비되기 전에 한 번 헛돌고 다시 돌지 않는다 —
    // 수색 모드를 열자마자 격자·마커가 안 보이고, 모의 항적을 눌러야 비로소 그려졌다.
  }, [ready, cells, target, boat, wps, wp, nextWp, trail, hdg, simSec]);

  // 처음 한 번만 화면을 맞춘다. 조난자·배가 움직일 때마다 맞추면 지도가 계속 흔들린다.
  useEffect(() => {
    if (!ready || !target) return;
    // 배까지 담으면 8km 가 한 화면에 들어와 패턴이 점이 된다 — 수색 구역에 맞추고, 배는 다가오며 들어온다
    apiRef.current?.fitPoints(wps.length ? [...wps, target.at] : [target.at]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const surv = survival(x.waterTemp, baseElapsed + simSec);
  const ves = byVessel[x.ship]!;
  const u = URG[x.type.urg];
  /** 통신·버튼 상태는 시뮬레이션 시계가 아니라 **지금 받은 값**이다. 관제 화면과 같은 실시간 데이터를 본다. */
  const buoy = x.map.buoy;
  const found = x.stages.found.at;

  return (
    <div className="search-mode">
      <header className="sm-bar">
        {/* 어느 배의 무슨 사고인지가 화면 맨 위에 있어야 한다. */}
        <div className="sm-title">
          <span className="sm-mode">수색 모드</span>
          <b>{ves.name}</b>
          <span className={`urg-tag ${u[1]}`}>{u[0]}</span>
          <span className="sm-type" title={x.type.dsc ? `DSC ${x.type.dsc}` : undefined}>{x.type.label}</span>
        </div>

        <div className="sm-clock">
          <span className="sm-clock-label">경과</span>
          <b className="mono">{elapsed(baseElapsed + simSec)}</b>
          <span className={`sm-surv${surv.past ? ' is-past' : ''}`}>
            생존 {surv.past ? '상한 초과' : `약 ${hhmm(Math.max(0, surv.consciousLeftMin))} 남음`}
          </span>
        </div>

        <button className="btn primary sm-play" onClick={() => setPlaying((p) => !p)} disabled={!nextWp}>
          {playing ? '■ 항적 정지' : '▶ 모의 항적'}
        </button>
        <button className="btn" onClick={onClose}>수색 모드 닫기</button>
      </header>

      <div className="sm-body">
        <div className="sm-map" data-theme={theme}>
          <MapView
            /*
             * 눈금을 항상 남긴다. 수색 화면은 타일이 하늘색 한 장인 말말대해가 대부분이고,
             * 그 위에서 농는 것이 <b>수백 m 단위의 경유지 이동</b>이다 — 눈금이 없으면
             * 배가 움직이는지도, 얼마나 움직이는지도 가늘이 안 된다(2026-09-18).
             */
            grid="always"
            className="map-canvas"
            center={target?.at ?? x.map.ship}
            zoom={14.5}
            theme={theme}
            markers={MARKERS}
            onReady={(api) => { apiRef.current = api; setReady(true); }}
          />
        </div>

        <aside className="sm-side">
          <div className="sm-side-scroll">
            {/*
              \U0001f534 <b>생기는 일의 상관없이 쓰는 번도 순서다.</b>
              전에는 사고 정보(한 번 보면 끝) · 부표 · 패턴 설정(한 번 정하면 끝)이 위를 다 쓰고,
              배를 모는 동안 계속 보는 다음 지점은 475px, 부를 좌표는 745px 에 있었다 —
              패널 높이가 533px 이니 <b>둘 다 스크롤 밖</b>이었다(2026-09-18).
              자주 보는 수서대로 올리고, 한 번 보면 끝나는 것은 접어 둔다.
            */}

            {/* ① 지금 해야 할 일 하나. 이 화면에서 제일 큰 글싨이어야 한다. */}
            <section className="sm-next">
              <span className="eyebrow">
                다음 지점 · {wp === 0 ? '시작점으로 이동' : `구간 ${Math.min(wp, legs)}/${legs}`}
              </span>
              {nextWp ? (
                <>
                  {/* 방위와 거리는 한 쌍이다 — 줄을 나누면 상자만 커지고 읽는 순서는 같다 */}
                  <span className="sm-next-line">
                    <b className="sm-next-brg mono">{Math.round(bearingTo(boat, nextWp))}°</b>
                    <span className="sm-next-dist mono">{Math.round(distM(boat, nextWp))}m</span>
                  </span>
                  <span className="sm-next-eta">
                    패턴 남은 거리 {(leftM / 1000).toFixed(1)}km · 약 {Math.max(1, Math.round(leftM / BOAT_MS / 60))}분
                  </span>
                </>
              ) : (
                <b className="sm-next-done">패턴 완료 — 다시 짜기로 이어 가세요</b>
              )}
            </section>

            {/* ② 부를 좌표. 무전으로 읽어 주는 값이다 — 다음 지점 바로 아래에 둔다. */}
            <section className="sm-coord">
              <span className="eyebrow">조난자 추정 위치</span>
              {/*
                위도·경도를 <b>두 줄로</b> 끊는다. 한 줄로 두면 좁은 패널에서 마지막 'E' 한 글자가
                다음 줄로 넘어가 지저분해지고, 어차피 무전으로 불러 줄 때도 위도 먼저 읽는다(2026-09-18).
              */}
              <b className="mono sm-ll">{target ? llLines(target.at) : '—'}</b>
              {target && target.movedM > 0
                ? <span className="sm-coord-sub">진입 후 {Math.round(target.movedM)}m 표류</span>
                : null}
            </section>
            {buoy ? (
              <section className="sm-coord">
                <span className="eyebrow">부표 위치 · {buoy.fix === 'measured' ? '실잡' : '추정'}</span>
                <b className="mono">{ddm(buoy.at)}</b>
              </section>
            ) : null}

            {/* ③ 그 좌표를 얼마나 믿을 수 있는가 — 관제 화면과 같은 한 줄(lib/buoyState.ts) */}
            {bs ? (
              <p className="buoy-line sm-buoy">
                {/* 긴 설명은 hover 로만 — 현장에서 읽혀야 하는 것은 상태 한 줄이다 */}
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
            ) : null}

            {/* ④ 얼마나 남았나. 네 값을 한 줄로 — 칸을 나눠 두면 90px 를 쓴다 */}
            <p className="sm-tally">
              <span className="is-todo"><b>{stats.todo}</b>미수색</span>
              <span className="is-done"><b>{stats.done}</b>수색 완료</span>
              <span className="is-stale"><b>{stats.stale}</b>재수색</span>
              <em className="mono">남은 {stats.leftKm2.toFixed(2)}km²</em>
            </p>

            {/* ⑤ 한 번 정하면 끝나는 것들 — 접어 둔다. 접힌 줄에 지금 골람 것만 적는다. */}
            {plan ? (
              <details className="sm-fold">
                <summary>
                  수색 패턴
                  <em>{PATTERN_LABEL[plan.pattern.kind]}{manualKind ? '' : ' · 자동'}</em>
                </summary>
                <div className="sm-fold-body">
                  <span className="eyebrow">{plan.round === 1 ? '1차 · 핵심 구역(50%)' : '2차 · 전체 구역(95%)'}</span>
                  <div className="sm-seg" role="group" aria-label="수색 패턴 선택">
                    <button aria-pressed={!manualKind} onClick={() => choose(null)}>자동</button>
                    {(['sector', 'square', 'parallel'] as PatternKind[]).map((k) => (
                      <button key={k} aria-pressed={manualKind === k} onClick={() => choose(k)}>
                        {PATTERN_LABEL[k]}
                      </button>
                    ))}
                  </div>
                  <p className="sm-pattern-why">{WHY[plan.pattern.kind]}</p>
                  <button className="btn sm" onClick={() => replan()}>지금 위지에서 다시 짜기</button>
                </div>
              </details>
            ) : null}

            <details className="sm-fold">
              <summary>
                사고 정보 · 범례
                {/* 배 이름·사고 유형·경과는 상단 바가 이미 적고 있다 — 여기는 나머지만 */}
                <em>{ves.reg}</em>
              </summary>
              <div className="sm-fold-body">
                <dl className="sm-facts">
                  <div><dt>선박</dt><dd><b>{ves.name}</b><span className="mono">{ves.reg}</span></dd></div>
                  <div><dt>사고</dt><dd title={x.type.dsc ? `DSC ${x.type.dsc}` : undefined}>{x.type.label}</dd></div>
                  <div><dt>발생</dt><dd className="mono">{x.day} {x.stages.detect.at ?? '—'}</dd></div>
                  <div><dt>대응 단계</dt><dd><b>{currentLabel(x)}</b></dd></div>
                </dl>
                <section className="sm-legend">
                  <div><i className="sm-key is-todo" />미수색 — 진할수록 있을 가능성이 높음</div>
                  <div><i className="sm-key is-done" />수색 완료</div>
                  <div><i className="sm-key is-stale" />재수색 — 훑은 기록이 만료됨</div>
                </section>
              </div>
            </details>

          </div>

          {/* 현장 조작. 스크롤과 상관없이 늘 손이 닿는 곳에 둔다. */}
          <div className="sm-side-foot">
            {found ? (
              <p className="sm-found">
                {FOUND_LABEL} · <span className="mono">{found}</span>
                {x.stages.found.note ? ` · ${x.stages.found.note}` : ''}
              </p>
            ) : (
              <button className="sm-act is-found" onClick={() => onFound(x)}>{FOUND_LABEL}</button>
            )}
            {confirmClose ? (
              <div className="sm-confirm">
                <span>이 사고를 종결할까요? 종결하면 신고 발신이 멈춥니다.</span>
                <div>
                  <button className="sm-act is-close" onClick={() => onResolve(x)}>종결</button>
                  <button className="sm-act" onClick={() => setConfirmClose(false)}>취소</button>
                </div>
              </div>
            ) : (
              <button className="sm-act is-close-ghost" onClick={() => setConfirmClose(true)}>사고 종결</button>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

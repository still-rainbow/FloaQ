import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import type { MetricKey } from '../types';
import { FloaqMap, RAMP_FROM_SIGMA, formatAge } from '@floaq/shared';
import { BAND_COLORS, driftSize } from '../drift';
import type { ActiveIncident, BuoyState, MapTheme } from '@floaq/shared';
import type { FloaqMapApi, LngLat, MarkerSpec, PointSpec } from '@floaq/shared';
import type { CurrentArrow, Zones } from '../cloud/zones';
import { IcoTarget, IcoWifiOff } from '../layout/Icons';
import { Joystick } from './Joystick';
import { isPresent } from '../state/store';

/**
 * 중앙 지도.
 *
 * Leaflet 이 DOM 을 직접 소유하므로 React 는 빈 div 하나만 렌더하고 안을 건드리지 않는다.
 * apps/web 의 MapPane 과 같은 구조다.
 *
 * ⚠ StrictMode 는 개발에서 effect 를 두 번 돈다. create() 반환값으로 ref 를 즉시 채우고
 *   cleanup 에서 destroy() 한다 — onReady 를 기다리면 두 번째 effect 시점에 가드가 비어
 *   같은 엘리먼트에 L.map 이 또 만들어진다. (apps/web 이식에서 밟은 함정)
 */
interface Props {
  theme: MapTheme;
  online: boolean;
  incident: ActiveIncident | null;
  buoy: BuoyState | null;
  vesselAt: LngLat;
  headingDeg: number;
  speedKn: number | null;
  vesselName: string;
  metric: MetricKey | null;
  /** 본선 주변 실제 격자로 만든 구역. 없으면 아무것도 그리지 않는다 */
  zones: Zones | null;
  /** 유속 레이어에만 표시하는 실제 ROMS 격자 유향 */
  arrows: CurrentArrow[];
  /** 격자가 아닌 실제 관측 지점. 현재 메인 화면은 파고만 사용 */
  points: PointSpec[];
  /** 격자 자체를 받았나. false 면 본선이 수집 해역 밖이다 */
  gridReady: boolean;
  /** 구역이 없을 때 이유 문구. 없으면 gridReady 로 ROMS 문구를 고른다 — 해구 층은 이유가 다르다 */
  emptyNote?: string;
  /** 본선 위치 수동 지정. <b>가상 모드 전용</b>이다 — 실제 위치는 GPS 가 정한다 */
  picking: boolean;
  manualPos: boolean;
  /** Pi GPS 수신 중. 수동 지정은 GPS 에 밀려 쓰이지 않으므로 버튼을 숨긴다 */
  gps: boolean;
  onTogglePick: () => void;
  onPick: (at: LngLat) => void;
  onResetPos: () => void;
  /** 가상 모드에서만 조이스틱을 띄운다. 실제 위치는 GPS 가 정한다 */
  virtual: boolean;
}

/** 배 아이콘. 회전은 안쪽 g 를 돌린다 — 원(시야)은 그대로 두고 뱃머리만 돌아야 한다 */
const vesselSvg = (headingDeg: number) =>
  '<svg width="28" height="28" viewBox="0 0 28 28">'
  + '<circle cx="14" cy="14" r="13" fill="rgba(127,212,217,.2)"/>'
  + `<g transform="translate(14 14) rotate(${headingDeg.toFixed(0)})">`
  + '<path d="M0-10 6.5 7-6.5 7Z" fill="#7fd4d9" stroke="#04202e" stroke-width="1.4" stroke-linejoin="round"/>'
  + '</g></svg>';

/**
 * 부표·사람 범위를 둘 다 지운다.
 *
 * 🔴 `setBand` 는 id 별 레이어라 한쪽만 지우면 다른 쪽이 화면에 남는다. 부표를
 *    잡았는지 모르는 동안(명세 §7) 대상이 BUOY 에서 PERSON 으로 바뀌는데,
 *    그때 옛 타원이 안 지워지면 범위가 두 개로 보인다.
 */
function clearBands(api: FloaqMapApi) {
  api.setBand('buoy', null);
  api.setBand('person', null);
}

const hourKst = (iso: string) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', hour12: false, timeZone: 'Asia/Seoul' });

export function MapPane(p: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<FloaqMapApi | null>(null);
  /** 지도가 따라갈 대상. 마커를 눌러 고른다 */
  const [focus, setFocus] = useState<'vessel' | 'buoy'>('vessel');

  // 지도는 한 번만 만든다. 클릭 콜백은 ref 로 들어 최신 props 를 본다
  const pick = useRef({ picking: p.picking, onPick: p.onPick });
  pick.current = { picking: p.picking, onPick: p.onPick };

  useEffect(() => {
    if (!boxRef.current) return;
    // ⚠ 마커는 create 시점에 등록해야 한다. setMarker 는 등록된 것을 움직일 뿐이라
    //    넘기지 않으면 모든 호출이 조용히 무시된다 — 배도 부표도 안 보인다
    const markers: MarkerSpec[] = [
      {
        id: 'vessel', at: p.vesselAt, cls: 'mk-vessel', title: '클릭하면 배를 따라갑니다',
        click: () => setFocus('vessel'),
        html: vesselSvg(p.headingDeg)
          + `<div class="mk-label" data-role="vessel">${p.vesselName}<span></span></div>`,
      },
      {
        id: 'buoy', at: p.vesselAt, cls: 'mk-buoy', hidden: true, title: '클릭하면 부표를 따라갑니다',
        click: () => setFocus('buoy'),
        html: '<b></b><i></i><div class="mk-label" data-role="buoy">구명 부표<span>—</span></div>',
      },
    ];
    const api = FloaqMap.create({
      container: boxRef.current,
      theme: p.theme,
      data: { center: p.vesselAt, zoom: 13 },
      markers,
      // 지정 모드일 때만 받는다. 평소 클릭은 마커 선택·이동에 쓰인다
      onClick: (at) => { if (pick.current.picking) pick.current.onPick(at); },
    });
    apiRef.current = api;          // onReady 가 아니라 즉시 채운다
    return () => { api.destroy(); apiRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { apiRef.current?.setTheme(p.theme); }, [p.theme]);
  useEffect(() => { apiRef.current?.setManualOffline(!p.online); }, [p.online]);

  // 사고 중에는 지도를 어둡게 깔고 부표만 밝게 남긴다
  useEffect(() => { apiRef.current?.setDim(!!p.incident); }, [p.incident]);

  // 합성 등치선을 그리지 않는다. 격자 칸을 그대로 칠한다 — 3km 라 굵지만 정직하다
  useEffect(() => {
    apiRef.current?.setContours(p.zones ? p.zones.bands : null);
  }, [p.zones]);

  useEffect(() => {
    const arrows: PointSpec[] = p.arrows.map((a) => ({
      at: a.at, cls: 'mk-arrow terminal-current-arrow', size: 18,
      html: `<svg viewBox="0 0 16 16" style="transform:rotate(${Math.round(a.deg)}deg)">`
        + '<path d="M8 1.5 12.5 13 8 10.4 3.5 13Z"/></svg>',
      title: `ROMS 유향 ${Math.round(a.deg)}° · 유속 ${a.speedMs.toFixed(2)} m/s`,
    }));
    apiRef.current?.setPoints([...arrows, ...p.points]);
  }, [p.arrows, p.points]);

  // 마커 안쪽 요소를 직접 고친다. 전역 id 를 쓰면 web 과 kiosk 가 같은 문서에 있을 때 충돌한다
  const markerEl = useCallback((id: string) => apiRef.current?.markers[id]?.getElement() ?? null, []);

  useEffect(() => {
    apiRef.current?.setMarker('vessel', p.vesselAt, true);
  }, [p.vesselAt]);

  // 뱃머리. svg 를 다시 그리지 않고 transform 만 바꾼다 — 매 텔레메트리마다 재생성하면 깜빡인다
  useEffect(() => {
    markerEl('vessel')?.querySelector('svg g')
      ?.setAttribute('transform', `translate(14 14) rotate(${p.headingDeg.toFixed(0)})`);
  }, [p.headingDeg, markerEl]);

  useEffect(() => {
    const el = markerEl('vessel')?.querySelector('[data-role="vessel"]');
    if (el) el.innerHTML = `${p.vesselName}<span>${p.speedKn == null ? '—' : `${p.speedKn.toFixed(1)}kn`}</span>`;
  }, [p.vesselName, p.speedKn, markerEl]);

  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    // 세 번째 인자를 빼면 setMarker 는 "보이기"로 처리한다. 부표가 없으면 명시적으로 숨긴다 —
    // 빠져 있으면 배 자리에 부표 마커가 떠서 배 이름과 '구명 부표' 라벨이 겹쳐 보였다.
    if (!p.buoy) { api.setMarker('buoy', null, false); clearBands(api); return; }
    const at: LngLat = [p.buoy.lon, p.buoy.lat];
    api.setMarker('buoy', at, true);
    const el = markerEl('buoy');
    el?.classList.toggle('is-lost', !!p.buoy.lost);
    const label = el?.querySelector('[data-role="buoy"]');
    if (label) {
      label.innerHTML = p.buoy.lost
        ? `부표 두절<span>${p.buoy.at ? formatAge(p.buoy.at) : '—'}</span>`
        : '구명 부표<span>수신 중</span>';
    }
    // 두절일 때만 표류 추정 범위를 그린다. 수신 중이면 실제 위치가 있다
    const e = p.buoy.lost ? p.buoy.driftEllipse : undefined;
    clearBands(api);
    if (e) {
      // 1σ 축에 §6 배율을 먹여 50·75·95% 고리를 그린다.
      // 부표와 사람은 색이 다르다 — 구조 세력이 향하는 곳은 부표가 아니라 사람이다
      const band = p.buoy.driftTarget === 'PERSON' ? 'person' : 'buoy';
      api.setBand(band, at, e.majorM, e.minorM, e.bearingDeg, false, RAMP_FROM_SIGMA);
    } else if (p.buoy.lost && p.buoy.estimatedRadiusM) {
      // ⚠ 축이 없다. 갱신 전 Pi 가 남긴 retained 다 — 95% 반경으로 원만 그린다.
      //    실제 타원은 한쪽으로 길므로 이 원은 **짧은 쪽을 과대, 긴 쪽을 과소**평가한다
      api.setDrift(at, p.buoy.estimatedRadiusM, p.buoy.estimatedRadiusM, 0);
    }
    api.setLine('rescue', [p.vesselAt, at]);
  }, [p.buoy, p.vesselAt, markerEl]);

  // 부표가 뜨면 그쪽으로 시선을 옮긴다. 사라지면 본선으로 돌아온다
  useEffect(() => { setFocus(p.buoy ? 'buoy' : 'vessel'); }, [!!p.buoy]);

  // 고른 대상을 화면 안에 둔다. follow 는 전환 순간만, 이후는 벗어날 때만 당긴다
  const target: LngLat = focus === 'buoy' && p.buoy ? [p.buoy.lon, p.buoy.lat] : p.vesselAt;
  const [tLon, tLat] = target;
  useEffect(() => { apiRef.current?.follow([tLon, tLat]); }, [focus]);          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { apiRef.current?.keepInView([tLon, tLat]); }, [tLon, tLat]);

  const legend = p.zones?.legend ?? null;
  const reported = p.incident?.status === 'REPORTED';
  const lost = !!p.buoy?.lost;

  return (
    <section className="col col-map">
      {/* is-reported · is-lost 는 kiosk.css 가 배너를 display:none 에서 여는 조건이다 —
          빠져 있어 신고 완료 바(사고 종결 버튼)와 두절 배너가 그려지지 않았다 (2026-09-15) */}
      <div className={`map-wrap${p.picking ? ' picking' : ''}`
        + (focus === 'buoy' ? ' focus-buoy' : '') + (p.incident ? ' is-incident' : '')
        + (reported ? ' is-reported' : '') + (lost ? ' is-lost' : '')}>
        <div className="map-canvas" ref={boxRef} />

        {lost && p.buoy && (
          <div className="map-ui tl">
            <div className="lost-banner">
              <IcoWifiOff size={28} />
              <span>
                <b>부표 통신 두절</b>
                {/* 원이 아니라 타원이다. 지름 하나만 적으면 어느 쪽으로 긴지를 지운다 —
                    수색선이 어느 방향으로 훑어야 하는지가 그 값에 들어 있다 */}
                <span>{driftSize(p.buoy)}</span>
                {/* 3시간 전 조류로 그린 원과 3분 전 조류로 그린 원이 똑같이 생겼다 — 계산 입력의 시각을 같이 둔다 */}
                {p.buoy.driftInputAt !== undefined && (
                  <span>{p.buoy.driftInputAt
                    ? `${formatAge(p.buoy.driftInputAt)} 해양 데이터 기준`
                    : '해양 데이터 없이 추정'}</span>
                )}
                {/* 색은 지도가 실제로 칠한 색이다. 대상이 바뀌면 지도의 색도 바뀌므로
                    여기에 박아 두면 범례가 거짓말을 한다 (floaq-map.js BAND_RAMP) */}
                <span className="prio">
                  {/* Fragment 다. span 으로 싸면 .prio i:first-child 가 칸마다 걸려
                      스와치와 글자 사이 여백이 사라진다 (kiosk.css) */}
                  {BAND_COLORS[p.buoy.driftTarget === 'PERSON' ? 'person' : 'buoy'].map(
                    ([pct, color]) => (
                      <Fragment key={pct}><i style={{ background: color }} />{pct}</Fragment>
                    ),
                  )}
                </span>
              </span>
            </div>
          </div>
        )}

        {/* 신고 완료 바(구조 완료·사고 종료)는 **지도 위가 아니라 화면 상단**으로 옮겼다
            (2026-09-18 요청, `ReportingLayer`). 지도 위에 띄우면 그 바가 덮는 자리에
            부표가 있을 때 정작 볼 것을 가린다. `is-reported` 는 남긴다 — 지도 강조에 쓴다 */}

        {/* 범례 범위도 실제 값에서 나온다. 고정 눈금이면 칸 색이 뭘 뜻하는지 알 수 없다 */}
        {legend && (
          <div className="map-ui tr">
            <div className="zone-legend floaty">
              <h4>
                <span>{legend.name}</span>
                <span>{hourKst(legend.predcDt)} 예측</span>
              </h4>
              <div className="ramp" style={{ background: `linear-gradient(90deg,${legend.ramp.join(',')})` }} />
              <div className="ramp-axis">
                <span>{legend.min.toFixed(legend.dec)}</span>
                <span>{legend.unit}</span>
                <span>{legend.max.toFixed(legend.dec)}</span>
              </div>
              <div className="ramp-note">
                {legend.note ?? '한 칸 약 3km'}{legend.source ? ` · ${legend.source}` : ''}
              </div>
              {p.arrows.length > 0 && (
                <div className="ramp-note arrow-note">
                  {/* 바람은 기상 관례(불어오는 쪽)를 180° 돌려 그렸다 — 유향과 같은 "가는 쪽" 읽기다 */}
                  <i /> {p.metric === 'wind' ? '바람이 가는 쪽' : '물이 가는 쪽'}
                </div>
              )}
            </div>
          </div>
        )}
        {/* 빈 지도를 그냥 두면 "값이 0"으로 읽힌다. 이유를 갈라서 적는다 */}
        {p.metric && !legend && (
          <div className="map-ui tr">
            <div className="zone-legend floaty">
              <h4><span>{p.points.length ? '파고 관측소' : '구역 없음'}</span></h4>
              <div className="ramp-note">
                {p.points.length
                  ? `${p.points.length}곳 · 점을 누르면 값`
                  : p.emptyNote
                  ? p.emptyNote
                  : p.gridReady
                  ? '격자 데이터 없음 · 지점 관측만'
                  : '수집 해역 밖 · 옮겨 받는 중 (10~20초)'}
              </div>
            </div>
          </div>
        )}

        <div className="map-ui bl">
          <span className="focus-chip floaty">
            <IcoTarget size={18} />
            <b>{focus === 'buoy' ? '부표' : '본선'}</b> 추적
          </span>
          {/* 가상 모드에서만. 실제 운항에서 사람이 배를 끌면 그 좌표가 신고에 실린다.
              발표 화면(?present)에서는 숨긴다 — 배를 손으로 끄는 조작이 보이면 실제 단말이 아니다 */}
          {p.virtual && !p.picking && !isPresent && (
            <Joystick at={p.vesselAt} onMove={p.onPick}
              onFollow={(at) => apiRef.current?.keepInView(at)} />
          )}
          {/* 좌표는 상단 바에 있다. 여기는 위치의 출처와 지정 버튼만.
              발표 화면은 이 줄을 통째로 뺀다 — `기본 위치`·`위치 지정` 이 곧 "GPS 가 없다"는 표시다.
              `GPS 위치` 로 바꾸지 않는 이유는 store.tsx isPresent 참고 (없는 말을 지어내지 않는다)

              🔴 **GPS 일 때는 이 칩을 아예 안 그린다** (2026-09-18 요청).
                 정상 상태를 굳이 말하는 칩이었다 — 그리고 그때는 버튼도 안 달린다
                 (`위치 지정` 은 `virtual && !gps`, `초기화` 는 `manualPos`(= !gps) 조건).
                 즉 GPS 면 글자 하나짜리 상자가 지도를 가리고 있었다.
                 ⚠ `수동 위치`·`기본 위치` 는 그대로 남긴다 — **그쪽이 경고다.** */}
          {!isPresent && !p.gps && (
            <div className="pos-chip floaty">
              {/* GPS 가 아니라는 사실은 버튼이 사라져도 보여야 한다 */}
              <span className="pos-src">{p.manualPos ? '수동 위치' : '기본 위치'}</span>
              {/* 가상에서만. 실제 운항에서 사람이 지도를 눌러 배를 옮기면 **그 좌표가 조난 신고에
                  그대로 실리고 구조대가 그리로 간다.** 위치는 GPS 가 정할 일이다 (useVesselAt) */}
              {p.virtual && (
                <button className="pos-btn" aria-pressed={p.picking} onClick={p.onTogglePick}>
                  {p.picking ? '지도를 누르세요 · 취소' : '위치 지정'}
                </button>
              )}
              {p.manualPos && !p.picking && (
                <button className="pos-btn" onClick={p.onResetPos}>초기화</button>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

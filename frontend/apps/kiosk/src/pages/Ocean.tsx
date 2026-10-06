import { useEffect, useMemo, useRef, useState } from 'react';
import { MapView } from '@floaq/shared';
import type { AlertType, FloaqMapApi, LngLat, Urgency } from '@floaq/shared';
import { useOcean } from '../cloud/useOcean';
import { buildArrows, buildZones, rangeFor, type ZoneKey } from '../cloud/zones';
import { buildIsolines } from '../cloud/contours';
import { useGridFrame } from '../cloud/useGridFrame';
import { dayTicks, frameLabel } from '../cloud/timeline';
import { buildWindArrows, buildZoneLayer, zoneRangeFor, type ZoneMetric } from '../cloud/zoneLayer';
import { useZones } from '../cloud/useZones';
import { shipIndexNow, waterTemp } from '../cloud/readings';
import type {
  FishingGroundPayload, JellyfishPayload, OceanSource, RedTidePayload, SeaObsPayload,
  RomsGrid, ShipIndexPayload, WarningPayload,
} from '../cloud/ocean';
import { isNoneText } from '../cloud/ocean';
import type { NavigateFunction } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { coldWater } from '../survival';
import { useRoute } from '../hooks/useRoute';
import { useLook } from '../hooks/useLook';
import { useOnline } from '../hooks/useOnline';
import { useVesselAt } from '../hooks/useVesselAt';
import { useVessel } from '../hooks/useVessel';
import { useCommands, useKiosk, useMode } from '../state/store';
import { LineChart } from '../charts/LineChart';
import { BarChart, type Bar } from '../charts/BarChart';
import { TopBar } from '../layout/TopBar';
import { SettingsSheet } from '../panels/SettingsSheet';
import { SosSheet } from '../panels/SosSheet';
import { AlertLayer } from '../panels/AlertLayer';
import { rejectText } from '../pi/reject';
import {
  IcoClock,
  IcoBoat, IcoBuoy, IcoCamera, IcoChip, IcoCompass, IcoFish, IcoGear, IcoSpark,
  IcoTarget, IcoWarn, IcoWaves,
} from '../layout/Icons';

/**
 * 해양 상황판 (`#/ocean`).
 *
 * 본 화면(§9.18 조업 지원)은 "지금 나가도 되나"를 좁은 패널에서 답한다.
 * 여기는 같은 데이터를 **넓게 펼쳐** 보는 자리다 — 예측이 어떻게 흐르는지, 어느 지점 값인지,
 * 근거가 무엇인지.
 *
 * 새로 만든 것은 화면뿐이다. 수집·정규화·해역 추종은 본 화면과 같은 모듈을 쓴다.
 */

/** 순차 램프. 값이 커질수록 진해진다 — 밝은 종이 배경에서 진한 쪽이 "많다"로 읽힌다 */
const TIDE = '#2d6b85';
const TEMP = '#d1683a';

type AnalysisView = 'overview' | 'map' | 'forecast' | 'stations' | 'advisories' | 'index';

const localClock = () => {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((v) => v.toString().padStart(2, '0')).join(':');
};

/** 해양 분석의 외곽 기능키 → 메인 화면의 대응 서랍. */
/**
 * 본 화면으로 돌아가며 그 서랍을 연다. 해양 화면에는 서랍이 없으므로 여기서 여는 것이 아니라
 * **주소로 넘긴다** — 본 화면의 `initialDrawer()` 가 이 쿼리를 읽는다.
 *
 * ⚠ 값을 늘리면 `Kiosk.tsx` 의 `initialDrawer()` 도 같이 늘려야 한다. 안 그러면
 * 서랍이 닫힌 채 본 화면만 뜨고 **버튼이 아무것도 안 한 것처럼 보인다** (2026-09-18 camera 추가 때 겪음).
 */
const openMainPanel = (navigate: NavigateFunction, drawer: 'vessel' | 'ocean' | 'devices' | 'camera') => {
  // ⚠ `location.hash = …` 로 옮기지 않는다. react-router 7 의 hash history 는 `hashchange` 를
  //    듣지 않아(useRoute.ts `HashSync`) 주소만 바뀌고 화면이 안 따라온다.
  //    쿼리 모양(`#/?drawer=…`)은 `Kiosk.tsx initialDrawer()` 가 읽는 그대로 유지한다.
  navigate(`/?drawer=${drawer}`);
};

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });

/** 며칠에 걸친 목록용 — 시각만 두면 어제 발표가 오늘로 읽힌다 */
const dayClock = (iso: string) => {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${clock(iso)}`;
};

/** 운항지수 열 머리 — "14일 오후" */
const slotHead = (at: string, slot: string | null) => `${new Date(at).getDate()}일 ${slot ?? ''}`;

/** 화면이 여는 링크. 백엔드도 거르지만 옛 캐시가 있을 수 있어 한 번 더 — https 외 차단 */
const safeLinks = (files?: string[] | null) => (files ?? []).filter((u) => /^https:\/\//.test(u));

/** 지도 툴팁은 innerHTML 로 들어간다. 지점명은 외부 API 문자열이라 이스케이프 */
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/**
 * 지도를 맞출 범위 — **언제나 본선 중심**이다 (2026-09-18 요청).
 *
 * ±0.3° ≈ 가로 55km · 세로 66km (위도 35° 기준, 경도 1° = 91km). 연안 조업 반경이
 * 한 화면에 들어오는 폭이고, ROMS 3km 칸이 약 18×22개로 색이 또렷하게 갈린다.
 *
 * 층 범위(`zoneBounds`·ROMS 격자 경계)에 맞추던 것을 버렸다 —
 *   · 전국 해구에 맞추면 남해 전체가 들어와 **본선이 점이 된다**. "내 배 주변이 어떤가"를 못 본다.
 *   · ROMS 는 첫 진입 때 격자가 아직 없어서 맞출 것이 없고, 화면이 전국인 채로 남았다.
 * 본선 좌표는 격자보다 먼저 있으므로 이 방식은 데이터 도착 순서를 안 탄다.
 */
const FIT_DEG = 0.3;
const aroundVessel = (at: LngLat): LngLat[] =>
  [[at[0] - FIT_DEG, at[1] - FIT_DEG], [at[0] + FIT_DEG, at[1] + FIT_DEG]];

function pick<T>(sources: OceanSource[], name: string): T | null {
  return (sources.find((s) => s.source === name)?.payload as T | undefined) ?? null;
}

export function Ocean() {
  const [, go] = useRoute();
  // 서랍 쿼리를 실어 본 화면으로 보낼 때만 쓴다. 단순 화면 이동은 위 `go`
  const navigate = useNavigate();
  const s = useKiosk();
  const { manualAlert } = useCommands();
  const { virtual, setVirtual, playing, replay } = useMode();
  const { vessel, save, wipe } = useVessel();
  const { theme, setTheme } = useLook();
  // vesselAt 은 화면용, queryAt 은 해양 조회용 — Pi GPS 면 0.01° 로 묶여 1Hz 마다 조회하지 않는다
  const { vesselAt, queryAt } = useVesselAt();
  // 실제 인터넷 연결을 본다. 강제 오프라인은 시연용 스위치다 (useOnline)
  const { online, forcedOffline, toggleForcedOffline } = useOnline();
  const [view, setView] = useState<AnalysisView>('overview');
  const [sheet, setSheet] = useState<'none' | 'settings' | 'sos'>('none');
  const [busy, setBusy] = useState<string | null>(null);
  const [hudClock, setHudClock] = useState(localClock);
  // 등치선을 그리려면 넓은 격자가 필요하다. 8겹이면 0.3° 해역이 다 들어온다
  const ocean = useOcean(online, queryAt, 8);
  const [layer, setLayer] = useState<'both' | 'cells' | 'iso'>('both');
  const [metric, setMetric] = useState<ZoneKey>('tide');

  useEffect(() => {
    const id = setInterval(() => setHudClock(localClock()), 1000);
    return () => clearInterval(id);
  }, []);

  const warn = pick<WarningPayload>(ocean.sources, 'weather-warning');
  const obs = pick<SeaObsPayload>(ocean.sources, 'sea-obs');
  const fg = pick<FishingGroundPayload>(ocean.sources, 'fishing-ground');
  const red = pick<RedTidePayload>(ocean.sources, 'red-tide');
  const jelly = pick<JellyfishPayload>(ocean.sources, 'jellyfish');
  const ship = pick<ShipIndexPayload>(ocean.sources, 'ship-index');
  // 상단바가 사고 없을 때 말하는 값. 본 화면과 같은 출처·같은 문구여야 한다
  const voyage = useMemo(
    () => shipIndexNow(Object.fromEntries(ocean.sources.map((x) => [x.source, x]))),
    [ocean.sources]);
  const water = useMemo(
    () => waterTemp(Object.fromEntries(ocean.sources.map((s) => [s.source, s])), ocean.current),
    [ocean.sources, ocean.current]);

  // 지도 층. roms = 본선 주변 KHOA ROMS(1시간 · 8일) · zone = 기상청 해구별 예측(3시간 · 75시간, 해양포털과 같은 원자료)
  const [source, setSource] = useState<'roms' | 'zone'>('roms');
  const [zoneMetric, setZoneMetric] = useState<ZoneMetric>('wave');
  // 시간 슬라이더. null 이면 "지금" — ROMS 는 지금 이후 가장 이른 예측, 해구는 지금을 덮는 3시간 구간
  const [frameAt, setFrameAt] = useState<string | null>(null);
  // 층·항목을 바꾸면 시각 목록이 달라진다. 옛 시각을 새 목록에서 찾지 않고 지금으로 돌린다
  useEffect(() => { setFrameAt(null); }, [source, zoneMetric]);
  // 오프라인 전환 뒤 고른 시각을 유지하면 현재 격자를 과거·미래 프레임으로 오해한다.
  useEffect(() => { if (!online) setFrameAt(null); }, [online]);
  // 수온은 소해구(본선 주변)에만 있다. 파고·풍속은 전국 대해구
  const zoneLevel = zoneMetric === 'temp' ? 'small' : 'large';
  const zone = useZones(online && source === 'zone', zoneLevel, frameAt);
  const frame = useGridFrame(queryAt, online && source === 'roms' ? frameAt : null, 8);
  const romsTimes = useMemo(() => ocean.grid?.times ?? [], [ocean.grid]);
  const times = useMemo(() => (source === 'roms' ? romsTimes : zone.grid?.times ?? []),
    [source, romsTimes, zone.grid]);
  // 한 시간이 지나 고른 시각이 목록에서 빠지면 "지금"으로 돌린다. 지난 예측을 보고 있다고 착각하지 않게
  useEffect(() => {
    if (frameAt && times.length > 0 && !times.includes(frameAt)) setFrameAt(null);
  }, [frameAt, times]);
  // 고른 프레임을 받는 동안에는 지금 프레임을 남긴다 — 비우면 지도가 깜빡인다
  const grid = frameAt && source === 'roms' ? frame.grid ?? ocean.grid : ocean.grid;
  // 색·등치선 기준은 앞으로 전 시각의 범위다. 프레임마다 다시 잡으면 같은 색이 시각마다 다른 값이 된다
  const range = useMemo(() => rangeFor(ocean.grid, metric), [ocean.grid, metric]);
  const zoneRange = useMemo(() => zoneRangeFor(zone.grid, zoneMetric), [zone.grid, zoneMetric]);
  const zones = useMemo(() => (source === 'roms'
    ? buildZones(grid, metric, range)
    : buildZoneLayer(zone.grid, zoneMetric, zoneRange)),
  [source, grid, metric, range, zone.grid, zoneMetric, zoneRange]);
  // 등치선은 ROMS 만. 해구는 55km 칸이라 선을 이으면 연안 50km 가 한 값으로 뭉개진다
  const iso = useMemo(() => (source === 'roms' ? buildIsolines(grid, metric, 5, range) : null),
    [source, grid, metric, range]);
  // 화살표 — ROMS 유속 보기는 유향, 해구 풍속 보기는 풍향. 수온 칸 위에는 겹치지 않는다(두 값을 한 그림으로 읽는다).
  // 전국 1,330칸에 다 올리면 선내 PC 에서 지도가 끌린다 — 해구는 본선 ±3° 만
  const arrows = useMemo(() => (source === 'roms'
    ? (metric === 'tide' ? buildArrows(grid) : [])
    : (zoneMetric === 'wind' ? buildWindArrows(zone.grid, vesselAt, 3) : [])),
  [source, grid, metric, zone.grid, zoneMetric, vesselAt]);
  const ticks = useMemo(() => dayTicks(times), [times]);
  // "지금"의 슬라이더 위치. ROMS 는 첫 시각이 지금이고, 해구는 발표 시각부터라 지금이 목록 중간에 있다
  const nowIndex = useMemo(() => {
    if (source === 'roms') return 0;
    const t0 = Date.now();
    let i = 0;
    times.forEach((t, n) => { if (new Date(t).getTime() <= t0) i = n; });
    return i;
  }, [source, times]);
  const frameIndex = frameAt ? Math.max(0, times.indexOf(frameAt)) : nowIndex;

  // 권역마다 구간 수가 다를 수 있어 열은 전체 구간 시각의 합집합으로 만든다
  const shipCols = useMemo(() => {
    const byAt = new Map<string, string | null>();
    ship?.areas?.forEach((a) => a.slots.forEach((s) => byAt.set(s.at, s.slot)));
    return [...byAt.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([at, slot]) => ({ at, slot }));
  }, [ship]);

  // 지도는 한 번만 만들고 그 뒤에는 API 로 갱신한다.
  // onReady 안에서만 그리면 그 시점의 값으로 굳는다 — 데이터는 그 뒤에 온다
  const mapRef = useRef<FloaqMapApi | null>(null);
  useEffect(() => {
    // 해구는 칸만 그린다 — 칸+선·등치선 선택은 ROMS 에만 뜻이 있다
    const cells = source === 'zone' || layer !== 'iso';
    mapRef.current?.setContours(cells && zones ? zones.bands : null);
    mapRef.current?.setIsolines(source === 'roms' && layer !== 'cells' && iso ? iso.levels : null);
  }, [zones, iso, layer, source]);
  // 층(본선 주변 ↔ 전국 해구)을 **바꿀 때만** 본선 주변으로 되맞춘다.
  // 한 번만 맞춘다 — 60초 폴링이나 1Hz GPS 마다 맞추면 사용자가 옮겨 놓은 화면이 계속 되돌아간다.
  const fittedTo = useRef<string | null>(null);
  useEffect(() => {
    const api = mapRef.current;
    if (!api) return;
    if (fittedTo.current === source) return;
    fittedTo.current = source;
    api.fitPoints(aroundVessel(vesselAt));
  }, [source, vesselAt]);
  useEffect(() => { mapRef.current?.setMarker('vessel', vesselAt, true); }, [vesselAt]);

  const speed = ocean.series?.points.map((p) => ({ at: p.at, value: p.currentSpeedMs })) ?? [];
  const temp = ocean.series?.points.map((p) => ({ at: p.at, value: p.waterTempC })) ?? [];
  // 조위는 ROMS 격자가 아니라 KHOA 예보지점 값이다 — 같은 차트 문법으로 그리되 출처를 따로 밝힌다
  const tideLevel = ocean.tide?.points.map((p) => ({ at: p.at, value: p.tideLevelM })) ?? [];
  const now = new Date().toISOString();

  const waveBars: Bar[] = (obs?.stations ?? [])
    .filter((s) => s.waveHeightM != null)
    .sort((a, b) => b.waveHeightM! - a.waveHeightM!)
    .map((s) => ({ label: s.name, value: s.waveHeightM!, note: `${s.name} · ${s.distanceKm}km · ${s.stn}` }));

  const windBars: Bar[] = (obs?.stations ?? [])
    .filter((s) => s.windSpeedMs != null)
    .sort((a, b) => b.windSpeedMs! - a.windSpeedMs!)
    .map((s) => ({ label: s.name, value: s.windSpeedMs!, note: `${s.name} · ${s.distanceKm}km · ${s.stn}` }));

  const tempBars: Bar[] = (fg?.stations ?? [])
    .filter((s) => s.waterTempC != null)
    .sort((a, b) => b.waterTempC! - a.waterTempC!)
    .map((s) => ({ label: s.name, value: s.waterTempC!, note: `${s.name} · ${s.distanceKm}km · ${s.sea}` }));

  const active = warn?.activeMarineWarnings ?? [];
  const areas = warn?.activeAreas ?? [];
  const focus = warn?.focus;
  // 조업 해역 판정이 있으면 그것이 타일 값. 전국은 문구로 물러선다
  const tileWarn = focus ? focus.activeMarineWarnings ?? [] : active;
  const nationalCount = new Set(areas.map((a) => a.areaName)).size;
  const jellyLinks = safeLinks(jelly?.files);
  const markers = useMemo(() => [{
    id: 'vessel', at: vesselAt, cls: 'mk-vessel',
    html: '<svg width="24" height="24" viewBox="0 0 24 24">'
      + '<circle cx="12" cy="12" r="11" fill="rgba(127,212,217,.22)"/>'
      + '<path d="M12 3 17.5 19 6.5 19Z" fill="#7fd4d9" stroke="#04202e" stroke-width="1.3"'
      + ' stroke-linejoin="round"/></svg>',
  }], [vesselAt]);

  // 막대그래프의 지점이 지도 어디인지. "파고 0.4m 가 어디 값이냐"를 그림으로 답한다
  const points = useMemo(() => [
    // 화살표를 먼저 넣는다 — 나중에 넣은 관측 점이 위에 그려져 가려지지 않는다
    ...arrows.map((a) => ({
      at: a.at, cls: 'mk-arrow', size: 16,
      // 북쪽이 위인 화살표를 유향만큼 돌린다. 크기로 유속을 말하지 않는다 — 값은 툴팁과 칸 색이 말한다
      html: `<svg viewBox="0 0 16 16" style="transform:rotate(${Math.round(a.deg)}deg)">`
        + '<path d="M8 1.5 12.5 13 8 10.4 3.5 13Z"/></svg>',
      title: source === 'zone'
        ? `기상청 해구 · 바람이 불어가는 쪽 ${Math.round(a.deg)}° · 풍속 ${a.speedMs.toFixed(1)} m/s`
        : `ROMS 유향 ${Math.round(a.deg)}° · 유속 ${a.speedMs.toFixed(2)} m/s`,
    })),
    ...(obs?.stations ?? []).map((s) => {
      const vals = [
        s.waveHeightM != null ? `파고 ${s.waveHeightM.toFixed(1)}m` : null,
        s.windSpeedMs != null ? `풍속 ${s.windSpeedMs.toFixed(1)}m/s` : null,
        s.windGustMs != null ? `돌풍 ${s.windGustMs.toFixed(1)}m/s` : null,
        s.waterTempC != null ? `수온 ${s.waterTempC.toFixed(1)}°C` : null,
      ].filter(Boolean);
      const label = s.waveHeightM != null ? `${s.waveHeightM.toFixed(1)}m`
        : s.windSpeedMs != null ? `${s.windSpeedMs.toFixed(1)}m/s` : '';
      return {
        at: [s.lon, s.lat] as LngLat, cls: 'mk-pt is-obs', size: 14,
        html: `<i></i><b>${label}</b>`,
        title: `기상청 ${esc(s.name)}(${esc(s.stn)}) · ${s.distanceKm}km${vals.length ? ` · ${vals.join(' · ')}` : ''}`,
      };
    }),
    ...(fg?.stations ?? []).map((s) => ({
      at: [s.lon, s.lat] as LngLat, cls: 'mk-pt is-fg', size: 14,
      html: `<i></i><b>${s.waterTempC != null ? `${s.waterTempC.toFixed(1)}°` : ''}</b>`,
      title: `수과원 ${esc(s.name)} · ${s.distanceKm}km${s.waterTempC != null ? ` · 수온 ${s.waterTempC.toFixed(1)}°C` : ''}`,
    })),
  ], [obs, fg, arrows, source]);
  // 데이터가 지도 준비보다 먼저 오면 effect 가 빈 ref 에 부른다 — onReady 에서 한 번 더 넣는다
  const pointsRef = useRef(points);
  pointsRef.current = points;
  useEffect(() => { mapRef.current?.setPoints(points); }, [points]);

  // 선택 화면만 마운트한다. 숨긴 Leaflet 캔버스는 복귀할 때 크기를 잘못 재므로 참조도 함께 비운다.
  useEffect(() => { if (view !== 'map') mapRef.current = null; }, [view]);

  // 등록 관문은 App 이 잡는다 — ship_id 가 없으면 여기까지 오지 않는다 (ref/kiosk_시연.md §4).
  // 표시용 이름이 아직 없으면 빈 값으로 그린다 — 화면을 막을 이유가 없다
  // Pi 가 이름을 알려주기 전의 표시값. 화면을 막지 않는다 — 등록은 이미 끝났다
  const vesselView = vessel ?? { name: '', regno: '', camH: '', launchOff: '' };

  const viewMeta: Record<AnalysisView, { eyebrow: string; title: string }> = {
    overview: { eyebrow: 'SEA OVERVIEW', title: '해양 상황 종합' },
    map: { eyebrow: 'OCEAN MAP', title: '해역 분포 분석' },
    forecast: { eyebrow: '48H FORECAST', title: '유속·수온 예측 추이' },
    stations: { eyebrow: 'OBSERVATION', title: '관측 지점 비교' },
    advisories: { eyebrow: 'ADVISORY', title: '특보·적조·해파리' },
    index: { eyebrow: 'SHIP INDEX', title: '권역별 선박운항지수' },
  };

  const sendManual = async (_urgency: Urgency, alertType: AlertType) => {
    setBusy('발신 요청 중…');
    try {
      const result = await manualAlert({ alertType, lon: vesselAt[0], lat: vesselAt[1] });
      if (result.accepted) { setBusy(null); setSheet('none'); }
      else setBusy(`발신 거절 — ${rejectText(result.reason)}`);
    } catch {
      setBusy('발신 실패 — Pi 응답 없음. 다시 시도하세요');
    }
  };

  return (
    <>
      <div className="shell terminal-shell terminal-analysis-shell">
        <TopBar
          vessel={vesselView} link={s.link}
          online={online} forcedOffline={forcedOffline} onToggleOffline={toggleForcedOffline}
          onSettings={() => setSheet('settings')} clock={hudClock}
          virtual={virtual} onToggleVirtual={() => setVirtual(!virtual)}
          playing={playing} onReplay={replay}
          vesselAt={vesselAt}
          headingDeg={s.telemetry?.headingDeg ?? 0}
          speedKn={s.telemetry?.speedKn ?? null}
          incidentActive={!!s.incident} voyage={voyage}
        />

        {(s.link !== 'OPEN' || s.piOnline === false) && (
          <div className="pi-down" role="alert">
            <IcoWarn size={22} />
            {s.link !== 'OPEN' ? 'Pi 연결 끊김 · 마지막 값 표시 중' : 'Pi 응답 없음 · 마지막 값 표시 중'}
          </div>
        )}

        <div className="terminal-body">
          {/* 🔴 아이콘 크기를 본 화면과 **같은 30** 으로 (2026-09-18). 24 로 달라서
              해양으로 넘어오는 순간 왼쪽 레일만 쪼그라들었다 — 같은 버튼이 화면마다
              다른 크기면 "다른 것"으로 읽힌다. `.rail-action` CSS 는 원래부터 같았고
              차이는 이 size prop 하나였다 */}
          <nav className="terminal-rail" aria-label="주요 기능">
            <button className="rail-action" onClick={() => openMainPanel(navigate, 'vessel')}>
              <IcoTarget size={30} /><span>본선</span>
            </button>
            <button className="rail-action" onClick={() => openMainPanel(navigate, 'ocean')}>
              <IcoFish size={30} /><span>조업</span>
            </button>
            <button className="rail-action" onClick={() => openMainPanel(navigate, 'devices')}>
              <IcoChip size={30} /><span>장비</span>
            </button>
            {/* 본 화면 레일과 같은 여섯 칸으로 맞춘다 (2026-09-18 요청) — 카메라만 빠져 있었다.
                영상은 본 화면 스테이지를 통째로 쓰므로 여기서 여는 것이 아니라 그쪽으로 넘긴다 */}
            <button className="rail-action" onClick={() => openMainPanel(navigate, 'camera')}>
              <IcoCamera size={30} /><span>카메라</span>
            </button>
            <button className="rail-action" aria-pressed="true">
              <IcoWaves size={30} /><span>해양</span>
            </button>
            <button className="rail-action" onClick={() => go('history')}>
              <IcoClock size={30} /><span>지난 사고</span>
            </button>
            <span className="rail-spacer" />
            <button className="rail-action" onClick={() => setSheet('settings')}>
              <IcoGear size={30} /><span>설정</span>
            </button>
          </nav>

          <main className="terminal-stage terminal-analysis-stage">
            <header className="analysis-head">
              <div>
                <span className="eyebrow">{viewMeta[view].eyebrow}</span>
                <h1>{viewMeta[view].title}</h1>
              </div>
              <p className="mono">
                본선 {vesselAt[1].toFixed(4)}, {vesselAt[0].toFixed(4)}
                {ocean.cloudAt ? ` · ${clock(ocean.cloudAt)} 육상 수신` : ' · 육상 수신 없음'}
                {/* 🔴 Pi 중계가 옛 값을 준 상태. 숫자·그림은 그대로 두고 "지금 값이 아니다"만 붙인다 —
                    3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 화면에서 똑같이 생겼다 */}
                {ocean.relayFresh === false && (
                  <span className="pill alert relay-stale">
                    캐시 · 인터넷 끊김
                    {ocean.relayCachedAt != null
                      && ` · ${clock(new Date(ocean.relayCachedAt * 1000).toISOString())} 값`}
                  </span>
                )}
              </p>
            </header>

            <div className={`analysis-view is-${view}`}>
              {view === 'overview' && (
                <>
                  {/* 값 넷을 먼저 크게 — 나머지는 이 넷을 설명하는 그림이다 */}
                  <section className="stat-grid">
                    <StatTile
                      label={focus ? '조업 해역 특보' : '해상 특보'}
                      value={tileWarn.length ? tileWarn.join(' · ') : '없음'}
                      tone={tileWarn.length ? 'alert' : 'ok'}
                      note={[
                        focus ? `기상청 · ${(focus.names ?? []).join('·')}` : '기상청',
                        nationalCount ? `전국 ${nationalCount}개 해역 발효` : null,
                      ].filter(Boolean).join(' · ')} />
                    <StatTile label="유의파고"
                      value={waveBars[0] ? waveBars[0].value.toFixed(1) : '—'} unit="m"
                      note={waveBars[0] ? waveBars[0].note! : '값 없음'} />
                    <StatTile label="표층 수온" value={water ? water.c.toFixed(1) : '—'} unit="°C"
                      note={water ? `${water.where}${water.forecast ? ' · 예측' : ''}` : '값 없음'} />
                    <StatTile label="저체온 한계" value={water ? coldWater(water.c).exh : '—'}
                      note={water ? `수온 ${water.c.toFixed(1)}°C · 미 해안경비대 생존표` : '수온 없음'} />
                  </section>

                  {ocean.summary ? (
                    <section className="card summary-card analysis-summary">
                      <div className="summary-head">
                        <IcoSpark size={18} />
                        <span className="eyebrow">오늘의 바다</span>
                        <span className={`pill ${ocean.summary.mock ? 'warn' : 'ok'}`}>
                          {ocean.summary.mock ? '목 응답' : ocean.summary.model}
                        </span>
                        {/* 기본 위치 기준이면 문장 속 지점·거리가 이 배와 무관하다 — 숨기면 화면이 아는 척을 한다 */}
                        {ocean.summary.shipBased === false && <span className="pill warn">기본 위치 기준</span>}
                        {/*
                          🔴 **누를 때마다 크레딧이 나간다.** 폴링에 붙이지 않는 이유가 그것이다 —
                             서버는 10분 틱 + 30분 상한으로 부르고, 이 버튼만 그 상한을 건너뛴다.
                             본선 좌표로 부른다 — 누른 사람이 보고 있는 바다의 문장이어야 한다.

                             ⚠ 조건이 `hasKioskKey()` 에서 `ocean.canRefresh` 로 바뀌었다 (2026-09-20).
                             키가 있어도 **실제 모드에는 이 경로가 없다** — Pi 중계는 GET 한 세그먼트뿐이라
                             `summary/refresh` 가 404 였다. 눌러도 안 되는 버튼을 띄우지 않는다.
                        */}
                        {ocean.canRefresh && (
                          <button className="btn btn-ghost summary-refresh" disabled={ocean.refreshing}
                            onClick={ocean.refreshSummary}
                            title="LLM provider 를 지금 호출해 이 자리 기준으로 다시 씁니다 · 크레딧이 소모됩니다">
                            {ocean.refreshing ? '부르는 중…' : '지금 다시 쓰기'}
                          </button>
                        )}
                      </div>
                      <h2>{ocean.summary.headline}</h2>
                      <p>{ocean.summary.body}</p>
                      <ul className="fact-list">
                        {ocean.summary.facts.map((fact) => <li key={fact}>{fact}</li>)}
                      </ul>
                      {/* 실패 이유를 삼키지 않는다. 삼키면 "버튼이 안 먹는다"가 된다 */}
                      {ocean.refreshNote && (
                        <p className="summary-note" role="alert">다시 쓰기 실패 — {ocean.refreshNote}</p>
                      )}
                      <footer>출항 판단은 기상특보 기준 · {clock(ocean.summary.generatedAt)} 생성</footer>
                    </section>
                  ) : <section className="card analysis-summary"><p className="chart-empty">해양 요약을 받는 중입니다</p></section>}
                </>
              )}

              {view === 'map' && <div className="card map-card analysis-map-card">
          <div className="card-head">
            <span className="chart-title">{zones ? zones.legend.name : '해역'} 분포</span>
            <span className="panel-head-right">
              <span className="chart-read mono">
                {zones ? (zones.legend.note ?? `격자 ${zones.bands.length}칸 · 한 칸 약 3km`)
                  : source === 'zone' ? (zone.error ? '해구 예측 없음 · 수집 전' : '해구 예측 받는 중')
                    : ocean.areaPending ? '해역 이동 중 · 격자 받는 중'
                      : ocean.areaBlocked ? '수집 해역 밖 · 해역 이동 권한 없음 (kiosk 키 확인)' : '격자 없음'}
              </span>
              <span className="seg">
                {([['roms', '본선 주변'], ['zone', '전국 해구']] as const).map(([k, label]) => (
                  <button key={k} aria-pressed={source === k} onClick={() => setSource(k)}>{label}</button>
                ))}
              </span>
              {source === 'roms' ? (
                <>
                  <span className="seg">
                    {([['tide', '유속'], ['temp', '수온']] as const).map(([k, label]) => (
                      <button key={k} aria-pressed={metric === k} onClick={() => setMetric(k)}>{label}</button>
                    ))}
                  </span>
                  <span className="seg">
                    {([['both', '칸+선'], ['cells', '칸'], ['iso', '등치선']] as const).map(([k, label]) => (
                      <button key={k} aria-pressed={layer === k} onClick={() => setLayer(k)}>{label}</button>
                    ))}
                  </span>
                </>
              ) : (
                <span className="seg">
                  {([['wave', '파고'], ['wind', '풍속'], ['temp', '수온']] as const).map(([k, label]) => (
                    <button key={k} aria-pressed={zoneMetric === k} onClick={() => setZoneMetric(k)}>{label}</button>
                  ))}
                </span>
              )}
            </span>
          </div>
          {/* 칸은 받은 값 그대로, 등치선은 바다 격자점 사이만 잇는다.
              육지에 닿은 칸은 통째로 건너뛰어 해안에서 선이 끊긴다 — 끊긴 자리가 "모른다"는 뜻이다 */}
          <MapView className="map-canvas" center={vesselAt} zoom={11} theme={theme}
            markers={markers}
            onReady={(api: FloaqMapApi) => {
              mapRef.current = api;
              api.setPoints(pointsRef.current);
              const cells = source === 'zone' || layer !== 'iso';
              api.setContours(cells && zones ? zones.bands : null);
              api.setIsolines(source === 'roms' && layer !== 'cells' && iso ? iso.levels : null);
              // 첫 진입도 본선 주변. 격자가 아직 없어도 본선 좌표는 있다
              fittedTo.current = source;
              api.fitPoints(aroundVessel(vesselAt));
            }} />
          {/* 해양포털 방식의 시간 슬라이더. 수집한 8일치 ROMS 예측을 넘겨 본다 — 추가 호출 없이 DB 에 있는 값이다 */}
          {times.length > 1 && (
            <div className="time-bar">
              <span className="seg">
                <button aria-pressed={frameAt === null} onClick={() => setFrameAt(null)}>지금</button>
              </span>
              <div className="time-track">
                <input type="range" min={0} max={times.length - 1} step={1} value={frameIndex}
                  aria-label="예측 시각" aria-valuetext={times[frameIndex] ? frameLabel(times[frameIndex]!) : undefined}
                  onChange={(e) => {
                    const i = Number(e.target.value);
                    setFrameAt(i === nowIndex ? null : times[i] ?? null);
                  }} />
                <div className="time-ticks" aria-hidden="true">
                  {ticks.map((t) => <span key={t.index} style={{ left: `${t.pct}%` }}>{t.label}</span>)}
                </div>
              </div>
              <span className="time-read mono">
                {zones ? `${frameLabel(zones.legend.predcDt)} 예측` : '—'}
                {(source === 'roms' ? frame.loading : zone.loading) ? ' · 받는 중' : ''}
              </span>
            </div>
          )}
          {zones && (
            <>
              <div className="ramp-row">
                <span className="mono">{zones.legend.min.toFixed(zones.legend.dec)}</span>
                <i className="ramp" style={{ background: `linear-gradient(90deg,${zones.legend.ramp.join(',')})` }} />
                <span className="mono">{zones.legend.max.toFixed(zones.legend.dec)} {zones.legend.unit}</span>
              </div>
              {range && times.length > 1 && (
                <p className="chart-note">
                  색 기준은 {frameLabel(times[0]!)} ~ {frameLabel(times[times.length - 1]!)} 전체 범위입니다.
                  시간을 넘겨도 같은 색이 같은 값입니다.
                </p>
              )}
              <p className="chart-note">
                {source === 'zone'
                  ? `기상청 해구별 예측(KIM 지역파랑모델) · ${zone.grid?.issuedAt ? `${frameLabel(zone.grid.issuedAt)} 발표` : '발표 시각 없음'} · `
                    + (zoneMetric === 'temp'
                      ? '수온은 소해구에만 있어 본선 주변 약 4° 만 칠합니다. '
                      : '전국 대해구 칸 값 그대로입니다. ')
                    + '빈 칸은 육지이거나 결측입니다.'
                  : layer === 'cells'
                  ? '칸 하나가 ROMS 격자 한 점입니다. 받은 값 그대로입니다.'
                  : iso && iso.levels.length > 0
                    ? `등치선 ${iso.levels.length}개 · 바다 격자 ${iso.cellCount}칸에서만 그립니다. `
                      + '육지에 닿은 칸은 건너뛰어 해안에서 선이 끊깁니다 — 거기는 값을 모릅니다.'
                    : '값이 고르게 퍼져 있어 그릴 등치선이 없습니다.'}
              </p>
            </>
          )}
          {points.length > 0 && (
            <p className="chart-note point-legend">
              <span><i className="pt-key is-obs" />기상청 관측 지점 (파고·바람)</span>
              <span><i className="pt-key is-fg" />수과원 관측소 (수온)</span>
              {arrows.length > 0 && (
                <span><i className="pt-key is-arrow" />{source === 'zone'
                  ? '바람이 불어가는 쪽 — 풍향(불어오는 쪽)을 180° 돌렸습니다 · 본선 ±3° 만'
                  : 'ROMS 유향 — 가이드에 방향 관례가 없어 흘러가는 쪽으로 그렸습니다'}</span>
              )}
              <span>점에 올리면 지점 값 · 칸·등치선은 ROMS 예측, 점은 관측입니다</span>
            </p>
          )}
              </div>}

              {view === 'forecast' && <div className="analysis-card-grid cols-3">
                <div className="card">
                  {/* 축이 하나다. 유속과 수온을 겹치면 두 축의 교차를 상관관계로 읽는다 */}
                  <LineChart title="표층 유속 예측 · 48시간" unit=" m/s" points={speed}
                    color={TIDE} dec={2} markerAt={now} height={260} />
                  <p className="chart-note">
                    약 6시간마다 유향이 뒤집히고 유속이 0 근처로 떨어지는 조석 반일주기를 확인합니다.
                  </p>
                </div>
                <div className="card">
                  <LineChart title="표층 수온 예측 · 48시간" unit=" °C" points={temp}
                    color={TEMP} dec={1} markerAt={now} height={260} />
                  <p className="chart-note">
                    오후에 높고 새벽에 낮은 일주기를 확인합니다. 예측은 관측값과 다를 수 있습니다.
                  </p>
                </div>
                {/* 조위는 유속과 같은 조석 현상이지만 지점 값이다 — 격자(ROMS)와 섞지 않고 카드를 나눈다 */}
                <div className="card">
                  <LineChart title="조위 예보 · 48시간" unit=" m" points={tideLevel}
                    color={TIDE} dec={2} markerAt={now} height={260} />
                  {ocean.tide ? (
                    <>
                      <ul className="fact-list">
                        {ocean.tide.extremes.slice(0, 4).map((e) => (
                          <li key={e.at}>
                            {e.kind === 'HIGH' ? '만조' : '간조'} {dayClock(e.at)} · {e.levelM.toFixed(2)}m
                          </li>
                        ))}
                      </ul>
                      <p className="chart-note">
                        {ocean.tide.name} {ocean.tide.distanceKm}km · KHOA 조석예보입니다.
                        만마다 만조 시각이 다르므로 본선 항구 값과 차이가 납니다.
                        1시간 간격 예보라 만조·간조 시각은 ±30분 어긋날 수 있습니다.
                      </p>
                    </>
                  ) : (
                    <p className="chart-note">
                      반경 60km 안에 조석예보 지점이 없습니다. 예보지점이 전국 166곳(연안)뿐입니다.
                    </p>
                  )}
                </div>
              </div>}

              {view === 'stations' && <div className="analysis-card-grid cols-3">
                <div className="card">
                  <BarChart title="지점별 유의파고" unit="m" bars={waveBars} color={TIDE}
                    emptyText="이 해역에 파고를 주는 지점이 없습니다" />
                  <p className="chart-note">파고부이는 파고·수온만 제공합니다.</p>
                </div>
                <div className="card">
                  <BarChart title="지점별 풍속" unit="m/s" bars={windBars} color={TIDE}
                    emptyText="이 해역에 바람을 주는 지점이 없습니다" />
                </div>
                <div className="card">
                  <BarChart title="관측소별 표층 수온" unit="°C" bars={tempBars} color={TEMP}
                    emptyText="이 해역에 수과원 관측소가 없습니다" />
                  <p className="chart-note">표층만 사용하며 점검 중인 관측소는 제외했습니다.</p>
                </div>
              </div>}

              {view === 'index' && <div className="card index-card analysis-index-card">
          <div className="card-head">
            <span className="chart-title">선박운항지수 · 권역별 약 6일</span>
            <span className="chart-read mono">{ship?.focusName ? `조업 권역 ${ship.focusName}` : '—'}</span>
          </div>
          {ship?.areas?.length ? (
            <div className="index-scroll">
              <table className="index-table">
                <thead>
                  <tr>
                    <th>권역</th>
                    {shipCols.map((c) => <th key={c.at}>{slotHead(c.at, c.slot)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {ship.areas.map((a) => {
                    const byAt = new Map(a.slots.map((s) => [s.at, s]));
                    return (
                      <tr key={a.name} className={a.code === ship.focusCode ? 'is-focus' : undefined}>
                        <th>{a.name}</th>
                        {shipCols.map((c) => {
                          const s = byAt.get(c.at);
                          return s ? (
                            <td key={c.at} className={`lv-${s.level ?? 0}`}
                              title={`${a.name} ${slotHead(s.at, s.slot)} · ${s.score ?? '—'}`
                                + ` · 파고 ${s.waveHeightM ?? '—'}m · 풍속 ${s.windSpeedMs ?? '—'}m/s`}>
                              {s.score ?? '—'}
                            </td>
                          ) : <td key={c.at} className="lv-0">—</td>;
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <p className="chart-empty">수신된 운항지수가 없습니다</p>}
          <p className="chart-note">
            KHOA 선박운항지수(권역 평균 참고 지수)입니다. 출항 판단은 기상특보가 우선합니다.
            권역 좌표가 없어 조업 권역은 설정값이고, 굵은 줄이 그 권역입니다.
          </p>
              </div>}

              {view === 'advisories' && <div className="analysis-card-grid cols-3 advisories">
                <div className="card">
          <div className="card-head">
            <span className="chart-title">해상 특보</span>
            <span className="chart-read mono">{warn ? `이벤트 ${warn.eventCount ?? 0}건 · 최근 6일` : '—'}</span>
          </div>
          {focus && (
            <dl className="status-list">
              <dt>조업 해역</dt>
              <dd>
                {(focus.names ?? []).join(' · ')} —{' '}
                {focus.activeAreas?.length
                  ? focus.activeAreas.map((a) => `${a.areaName} ${a.name}`).join(', ')
                  : '발효 없음'}
              </dd>
            </dl>
          )}
          {warn?.status ? (
            <dl className="status-list">
              <dt>전국 발효</dt><dd>{warn.status.current ?? '—'}</dd>
              <dt>예비특보</dt><dd>{warn.status.preliminary ?? '—'}</dd>
              {/* "없음"이면 줄을 늘리지 않는다 — 기타 사항은 대부분 비어 온다 */}
              {!isNoneText(warn.status.note) && <><dt>기타</dt><dd>{warn.status.note}</dd></>}
            </dl>
          ) : <p className="chart-empty">기상청 특보현황 미수신</p>}
          {warn?.events?.length ? (
            <ol className="notice-list is-wide">
              {warn.events.slice(0, 10).map((e, i) => (
                <li key={`${e.announcedAt}-${e.areaName}-${i}`}>
                  <span className="mono">{e.announcedAt ? dayClock(e.announcedAt) : '—'}</span>
                  <span>{e.areaName} · {e.name} {e.action}</span>
                </li>
              ))}
            </ol>
          ) : <p className="chart-empty">최근 6일 해상 특보 발표 없음</p>}
          <p className="chart-note">
            기상청 특보코드·특보현황 기준입니다. 조업 해역은 설정한 특보구역과 그 상위 구역
            (예: 남해동부앞바다·남해동부전해상)으로 판정합니다. 본선 좌표 판정은 아닙니다 —
            기상청이 특보구역 경계를 제공하지 않습니다.
            {focus && !focus.hierarchy && ' 특보구역 계층을 받지 못해 지금은 설정 구역만 봅니다.'}
          </p>
                </div>

                <div className="card">
          <div className="card-head">
            <span className="chart-title">적조</span>
            <span className="chart-read mono">{red?.dayReport ?? '—'}</span>
          </div>
          {red ? (
            <>
              {red.breaking && <p className="notice-warn"><IcoWarn size={14} />{red.breaking}</p>}
              <ul className="fact-list">
                {red.organisms.map((o, i) => (
                  <li key={`${o.name}-${i}`}>
                    {o.name} · {o.area}
                    {o.maxDensity != null ? ` · 최대 ${o.maxDensity} 개체/mL` : ''}
                  </li>
                ))}
              </ul>
              {red.progress && <p className="detail-text"><b>진행 상황</b>{red.progress}</p>}
              {red.afterview && <p className="detail-text"><b>금후 전망</b>{red.afterview}</p>}
              {red.request && <p className="detail-text"><b>당부 사항</b>{red.request}</p>}
            </>
          ) : <p className="chart-empty">수신된 적조 보고가 없습니다</p>}
          <p className="chart-note">조사해역이 텍스트라 지도에 영역을 그리지 못합니다.</p>
                </div>

                <div className="card">
          <div className="card-head">
            <span className="chart-title">해파리</span>
            <span className="chart-read mono">{jelly?.subject ?? '—'}</span>
          </div>
          {jelly ? (
            <>
              {/* 제공기관이 직접 적어 둔 한계. 반드시 함께 띄운다 */}
              <p className="detail-text">{jelly.caveat}</p>
              {jellyLinks.length ? (
                <ul className="link-list">
                  {jellyLinks.map((u, i) => (
                    <li key={u}><a href={u} target="_blank" rel="noopener noreferrer">주간보고 원문 {i + 1}</a></li>
                  ))}
                </ul>
              ) : <p className="chart-empty">첨부 원문 없음</p>}
            </>
          ) : <p className="chart-empty">수신된 해파리 보고가 없습니다</p>}
          <p className="chart-note">
            지역별 출현율 수치는 API 가 주지 않아 원문(PDF)으로 연결합니다. 여는 데 인터넷이 필요합니다.
          </p>
                </div>
              </div>}
            </div>
          </main>
        </div>

        <footer className="terminal-dock analysis-dock">
          <span className="dock-title"><IcoWaves size={18} /><b>해양 분석</b></span>
          {([
            ['overview', '종합 상황', IcoTarget],
            ['map', '해역 지도', IcoCompass],
            ['forecast', '예측 추이', IcoWaves],
            ['stations', '관측 비교', IcoBuoy],
            ['advisories', '특보 · 생물', IcoWarn],
            ['index', '운항 지수', IcoBoat],
          ] as const).map(([key, label, Icon]) => (
            <button key={key} className="dock-action" aria-pressed={view === key}
              onClick={() => setView(key)}>
              <Icon size={20} /><span>{label}</span>
            </button>
          ))}
          <span className="dock-spacer" />
          <button className="dock-action dock-detail" onClick={() => go('main')}>
            <IcoBoat size={20} /><span>본선 화면</span>
          </button>
          <button className="dock-action dock-sos" onClick={() => setSheet('sos')}>
            <IcoWarn size={36} /><span>긴급 신고</span>
          </button>
        </footer>
      </div>

      {/* 해양 화면에 있어도 익수 경보는 덮는다 — 없으면 이 화면을 보는 동안 사고가 조용히 지나간다 */}
      <AlertLayer waterTemp={water} />

      {sheet === 'settings' && (
        <SettingsSheet vessel={vesselView} theme={theme} setTheme={setTheme}
          onClose={() => setSheet('none')} onWipe={wipe} onComms={() => go('comms')}
          onOcean={() => setSheet('none')} />
      )}

      {sheet === 'sos' && (
        <SosSheet busy={busy} onClose={() => { setSheet('none'); setBusy(null); }}
          onSend={(urgency, alertType) => void sendManual(urgency, alertType)} />
      )}
    </>
  );
}

interface TileProps {
  label: string;
  value: string;
  unit?: string;
  note: string;
  tone?: 'ok' | 'warn' | 'alert';
  /** 0~1. 임계 대비 어디인가. 없으면 막대를 안 그린다 — 임계가 없는 값(저체온 한계 등) */
  ratio?: number;
  /** 진입 애니메이션 시차(ms). 넷이 동시에 튀면 어디를 볼지 모른다 */
  delay?: number;
}

/**
 * 지표 하나.
 *
 * `ratio` 를 주면 값 아래에 막대가 찬다 — <b>숫자만으로는 "3.2m 가 높은 건지"를 모른다.</b>
 * 임계는 우리가 만들지 않는다: 파고는 풍랑주의보(3m), 풍속은 14m/s 가 기준이다(§6).
 *
 * ⚠ 막대는 <b>값을 대신하지 않는다.</b> 숫자를 그대로 두고 그 아래 깔기만 한다 —
 * 막대만 남기면 "2.9m 와 3.1m"가 화면에서 같아 보인다.
 */
function StatTile({ label, value, unit, note, tone, ratio, delay = 0 }: TileProps) {
  return (
    <div className="stat-tile is-anim" style={{ animationDelay: `${delay}ms` }}>
      <span className="stat-label">{label}</span>
      <span className={`stat-value${tone ? ` is-${tone}` : ''}`}>
        {value}{unit && <small>{unit}</small>}
      </span>
      {ratio != null && (
        <span className="stat-gauge" aria-hidden="true">
          <i className={tone ? `is-${tone}` : undefined}
             style={{ width: `${Math.min(100, Math.max(0, ratio * 100))}%` }} />
        </span>
      )}
      <span className="stat-note">{note}</span>
    </div>
  );
}

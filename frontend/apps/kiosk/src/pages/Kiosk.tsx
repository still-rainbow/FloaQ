import { useCallback, useEffect, useMemo, useState } from 'react';
import type { AlertType, LngLat, PointSpec, Urgency } from '@floaq/shared';
import type { MetricKey } from '../types';
import { useCommands, useKiosk, useMode } from '../state/store';
import type { CommandResult } from '@floaq/shared';
import { rejectText } from '../pi/reject';
import { useLook } from '../hooks/useLook';
import { useOnline } from '../hooks/useOnline';
import { useVessel } from '../hooks/useVessel';
import { useRoute } from '../hooks/useRoute';
import { useVesselAt } from '../hooks/useVesselAt';
import { TopBar } from '../layout/TopBar';
import { DevicePane } from '../panels/DevicePane';
import { MapPane } from '../panels/MapPane';
import { CameraPane } from '../panels/CameraPane';
import { FramesPane } from '../panels/FramesPane';
import { OceanPane } from '../panels/OceanPane';
import { SHIP_CAT } from '../mock/data';
import { useOcean } from '../cloud/useOcean';
import { buildCategories, shipIndexNow, waterTemp } from '../cloud/readings';
import type { SeaObsPayload } from '../cloud/ocean';
import { buildArrows, buildZones, type ZoneKey } from '../cloud/zones';
import { buildWindArrows, buildZoneLayer, zoneRangeFor } from '../cloud/zoneLayer';
import { useZones } from '../cloud/useZones';
import { AlertLayer } from '../panels/AlertLayer';
import { ReportingLayer } from '../panels/ReportingLayer';
import { SosSheet } from '../panels/SosSheet';
import { SettingsSheet } from '../panels/SettingsSheet';
import {
  IcoClock,
  IcoBoat, IcoBuoy, IcoCamera, IcoCheck, IcoChip, IcoCompass, IcoFilm, IcoFish, IcoGear,
  IcoTarget, IcoWarn, IcoWaves,
} from '../layout/Icons';

const localClock = () => {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((v) => v.toString().padStart(2, '0')).join(':');
};

const DRAWER_TITLE = {
  devices: '장비 상태', ocean: '조업 정보', camera: '카메라 라이브', frames: '사고 기록',
} as const;

type TerminalDrawer = 'devices' | 'ocean' | 'camera' | 'frames' | null;

/**
 * 분석 화면의 외곽 기능키가 요청한 메인 서랍을 바로 연다.
 * 쿼리가 없으면 닫힌 채 시작 — 첫 화면은 지도 전체 (2026-09-15 사용자 요청)
 */
const initialDrawer = (): TerminalDrawer => {
  const query = location.hash.split('?')[1] ?? '';
  const requested = new URLSearchParams(query).get('drawer');
  if (requested === 'devices') return 'devices';
  if (requested === 'ocean') return 'ocean';
  // 해양 화면 레일의 `카메라` 가 이 값으로 넘어온다 (2026-09-18). 빠지면 서랍이 닫힌 채
  // 본 화면만 떠서 **버튼이 아무것도 안 한 것처럼 보인다**
  if (requested === 'camera') return 'camera';
  return null;
};

export function Kiosk() {
  const s = useKiosk();
  // 구조 완료·사고 종료는 ReportingLayer 가 직접 부른다. 여기서는 수동 신고만 쓴다
  const { manualAlert } = useCommands();
  const { theme, setTheme } = useLook();
  const { vessel, save, wipe } = useVessel();
  const [, go] = useRoute();
  const { virtual, setVirtual, playing, replay } = useMode();
  // vesselAt 은 지도·신고용, queryAt 은 해양 조회용 — Pi GPS 면 0.01° 로 묶여 1Hz 마다 조회하지 않는다
  const {
    vesselAt, queryAt, source: posSource, manual: manualPos, set: setVesselAt, reset: resetVesselAt,
  } = useVesselAt();
  const [picking, setPicking] = useState(false);
  /**
   * Jetson 생존. <b>LWT 가 없다</b> — `jetson/status` 를 5초마다 내는 것이 생존 신호라
   * 마지막 수신 15초로 판단한다 (`ref/mqtt.md` §5.12).
   *
   * 매초 다시 세지 않는다. 장비 서랍을 열 때와 상태가 바뀔 때 다시 계산되면 충분하다 —
   * 이 값으로 경보를 울리는 것이 아니라 칸 하나를 흐리게 하는 것이다.
   */
  const jetsonDown = s.jetsonAt != null && Date.now() - s.jetsonAt > 15_000;

  // 실제로 바뀌면 위치 지정을 내린다. 값은 useVesselAt 이 막지만 지도 커서·하이라이트가 남는다
  useEffect(() => { if (!virtual) setPicking(false); }, [virtual]);

  // 실제 인터넷 연결을 본다. 강제 오프라인은 시연용 스위치다 (useOnline)
  const { online, forcedOffline, toggleForcedOffline } = useOnline();
  // 해양 데이터. 오프라인 토글이 폴링을 멈추고, 마지막 캐시는 남는다 (§9.10).
  // 전체 지도형 단말에서는 한 겹(3x3)보다 넓은 문맥이 필요하다. DB에 모인 해역만 읽는다.
  const ocean = useOcean(online, queryAt, 8);
  const [metric, setMetric] = useState<MetricKey | null>(null);
  const [drawer, setDrawer] = useState<TerminalDrawer>(initialDrawer);
  const [sheet, setSheet] = useState<'none' | 'settings' | 'sos'>('none');
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [clock, setClock] = useState(localClock);

  useEffect(() => {
    const id = setInterval(() => setClock(localClock()), 1000);
    return () => clearInterval(id);
  }, []);

  // Escape 로 열려 있는 시트·위치 지정을 닫는다. 경보는 닫지 않는다 — 취소는 명시적 선택이어야 한다
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setSheet('none'); setPicking(false); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  /** 명령 결과를 화면에 남긴다. 거절 사유를 삼키면 중복 가드가 보이지 않는다 */
  const run = useCallback(async (label: string, fn: () => Promise<CommandResult>) => {
    setBusy(`${label} 요청 중…`);
    try {
      const r = await fn();
      if (r.accepted) { setBusy(null); setToast(`${label} 처리됨`); setSheet('none'); }
      else setBusy(`${label} 거절 — ${rejectText(r.reason)}`);
    } catch {
      // 실패를 조용히 넘기면 "눌렀는데 안 나갔다"를 사용자가 모른다
      setBusy(`${label} 실패 — Pi 응답 없음. 다시 누르세요`);
    }
  }, []);

  const onAlertAccepted = useCallback((label: string) => setToast(`${label} 처리됨`), []);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(id);
  }, [toast]);

  // clock 이 1초마다 바뀌어 "N분 전" 이 자연히 흐른다. 안전·조업·항해는 EC2, 내 배는 Pi 다
  const cats = useMemo(
    () => ({ ...buildCategories(ocean.sources, new Date(), ocean.current), ship: SHIP_CAT }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ocean.sources, ocean.current, clock]);
  // 상단바가 사고 없을 때 말하는 값. 조업 표의 '운항지수' 줄과 같은 출처를 본다
  const voyage = useMemo(
    () => shipIndexNow(Object.fromEntries(ocean.sources.map((s) => [s.source, s]))),
    [ocean.sources]);
  // 조업 탭과 익수 경보가 같은 수온을 써야 한다. 두 곳이 다른 값을 보이면 어느 쪽을 믿을지 모른다
  const water = useMemo(
    () => waterTemp(Object.fromEntries(ocean.sources.map((s) => [s.source, s])), ocean.current),
    [ocean.sources, ocean.current]);
  /**
   * 파고·바람을 **대해구(0.5°, 약 55km)** 로 칠한다 — 해양 상황판의 `전국 해구` 와 같은 층이다.
   *
   * ~~소해구(1/6°, 약 18km)~~ 에서 옮겼다 (2026-09-18). 소해구가 더 촘촘해서 골랐는데
   * **그 층에는 파고·풍속이 아예 없다.** 기상청이 층마다 다른 요소를 준다 —
   * 실측(2026-09-18, `/api/ocean/zones`):
   *
   *   `small` 360칸 — 시정·강수·수온만. `waveHeightM`·`windSpeedMs` 가 **360칸 전부 null**
   *   `large` 1330칸 — 파고·주기·파향·풍속·풍향 1313칸. 시정·강수·수온·너울은 전부 null
   *
   * 그래서 파고·바람을 눌러도 지도가 영영 안 칠해졌다(`buildZoneLayer` 가 값 없는 칸을 걸러
   * `null` 을 냈다). 칸이 커지는 것은 데이터가 그렇게 생겨서지 고를 수 있는 게 아니다.
   */
  const zoneOn = online && (metric === 'wave' || metric === 'wind');
  const zoneGrid = useZones(zoneOn, 'large', null);
  const zones = useMemo(() => {
    if (metric === 'tide' || metric === 'temp') return buildZones(ocean.grid, metric as ZoneKey);
    if (metric === 'wave' || metric === 'wind') {
      return buildZoneLayer(zoneGrid.grid, metric, zoneRangeFor(zoneGrid.grid, metric));
    }
    return null;
  }, [ocean.grid, metric, zoneGrid.grid]);
  const arrows = useMemo(
    () => (metric === 'tide' ? buildArrows(ocean.grid)
      // 전국 1,330칸에 화살표를 다 올리면 선내 PC 에서 지도가 끌린다 — 본선 ±3° 만 (Ocean.tsx 와 같은 값)
      : metric === 'wind' ? buildWindArrows(zoneGrid.grid, vesselAt, 3) : []),
    [ocean.grid, metric, zoneGrid.grid, vesselAt]);
  // 구역이 없을 때의 이유. 해구 층은 "해역 밖"이 아니라 발표본 수신 문제다
  const emptyNote = metric === 'wave' || metric === 'wind'
    ? (!online ? '오프라인 · 해구 예측 없음'
      : zoneGrid.error ? '해구 예측 수신 실패 · 수집 전이거나 발표본 없음'
        : '해구 예측 받는 중')
    // 기다려도 안 들어오는 경우다. "옮겨 받는 중"으로 두면 설정 누락이 묻힌다
    : ocean.areaBlocked && !ocean.grid ? '수집 해역 밖 · 이동 권한 없음 (kiosk 키 확인)'
      // 기다리면 들어온다. 이 문구가 없으면 "값 없음"과 구분이 안 돼 사람이 계속 눌러 본다
      // (상황판 Ocean.tsx 에는 있었는데 본 화면에만 빠져 있었다 — 2026-09-17)
      : ocean.areaPending ? '해역 이동 중 · 격자 받는 중 (10~20초)'
        : undefined;
  const stationPoints = useMemo<PointSpec[]>(() => {
    if (metric !== 'wave') return [];
    const obs = ocean.sources.find((source) => source.source === 'sea-obs')?.payload as SeaObsPayload | null;
    return (obs?.stations ?? [])
      .filter((station) => station.waveHeightM != null)
      .map((station) => ({
        at: [station.lon, station.lat] as LngLat, cls: 'mk-pt is-obs terminal-wave-point', size: 16,
        html: `<i></i><b>${station.waveHeightM!.toFixed(1)}m</b>`,
        title: `기상청 ${station.name} · 파고 ${station.waveHeightM!.toFixed(1)}m · ${station.distanceKm}km`,
      }));
  }, [ocean.sources, metric]);

  // 등록 관문은 App 이 잡는다 — ship_id 가 없으면 여기까지 오지 않는다 (ref/kiosk_시연.md §4).
  // 표시용 이름이 아직 없으면 빈 값으로 그린다 — 화면을 막을 이유가 없다
  // Pi 가 이름을 알려주기 전의 표시값. 화면을 막지 않는다 — 등록은 이미 끝났다
  const vesselView = vessel ?? { name: '', regno: '', camH: '', launchOff: '' };

  const inc = s.incident;

  /**
   * 사진을 볼 사고. <b>끝난 뒤에도 남긴다.</b>
   *
   * Pi 가 `rescue`·`close` 때 retained 를 지우면 `s.incident` 가 null 이 되는데,
   * 사고 사진을 실제로 찬찬히 보는 시점은 대개 <b>그 뒤</b>다.
   * ⚠ 새로고침하면 잊는다 — 이 세션 동안만이다. 영구 보관은 관제 웹(R2)의 몫이다
   */
  const [lastInc, setLastInc] = useState<string | null>(null);
  useEffect(() => { if (inc) setLastInc(inc.incidentId); }, [inc]);
  const framesOf = inc?.incidentId ?? lastInc;

  return (
    <>
      {/*
        🔴 `has-repbar` 는 장식이 아니라 **레이아웃 계약**이다.
        `.terminal-shell` 그리드는 3트랙(상단바·본문·독)이고 자식이 순서대로 들어간다 —
        신고 바를 하나 더 넣으면 바가 본문의 `1fr` 을 가져가고 지도가 독 높이로 찌그러진다
        (2026-09-18 화면 확인). 바가 뜰 때만 트랙을 4개로 늘린다.
        조건은 ReportingLayer 의 렌더 조건과 같아야 한다 — 어긋나면 트랙 수가 안 맞는다.
      */}
      <div className={`shell terminal-shell${inc?.status === 'REPORTED' ? ' has-repbar' : ''}`}>
        <TopBar
          vessel={vesselView} link={s.link}
          online={online} forcedOffline={forcedOffline} onToggleOffline={toggleForcedOffline}
          onSettings={() => setSheet('settings')} clock={clock}
          virtual={virtual}
          onToggleVirtual={() => setVirtual(!virtual)}
          playing={playing} onReplay={replay}
          vesselAt={vesselAt}
          headingDeg={s.telemetry?.headingDeg ?? 0}
          speedKn={s.telemetry?.speedKn ?? null}
          incidentActive={!!inc} voyage={voyage}
        />

        {/* Pi 두절은 시스템 정지다. 브로커(link)와 Pi 생존(pi/online)은 다른 층이라 문구를 가른다.
            ⚠ Pi 비정상 종료는 LWT 가 약 22초 뒤에 와서 그동안은 배너가 뜨지 않는다 */}
        {/*
          🔴 사고가 나기 **전에** 알아야 하는 둘 (ref/mqtt.md §5.12).
          - gpsReceived false: 탐지는 되지만 **추락 위치가 안 나온다**
          - cameraDirty: 렌즈에 물방울이 맺힌 채로 사고가 나면 **탐지 자체가 안 된다**
          사고 순간에 알면 이미 늦다.
        */}
        {s.jetson && !jetsonDown && (!s.jetson.gpsReceived || s.jetson.cameraDirty) && (
          <div className="ai-warn" role="alert">
            <IcoWarn size={20} />
            {!s.jetson.gpsReceived && <b>AI 가 선박 위치를 못 받고 있습니다 — 탐지돼도 추락 지점이 안 나옵니다</b>}
            {!s.jetson.gpsReceived && s.jetson.cameraDirty && ' · '}
            {s.jetson.cameraDirty && <b>카메라 렌즈 이물질 — 탐지가 안 될 수 있습니다</b>}
          </div>
        )}

        {(s.link !== 'OPEN' || s.piOnline === false) && (
          <div className="pi-down" role="alert">
            <IcoWarn size={22} />
            {s.link !== 'OPEN' ? 'Pi 연결 끊김 · 마지막 값 표시 중' : 'Pi 응답 없음 · 마지막 값 표시 중'}
          </div>
        )}

        {/* DETECT·WAIT 은 AlertLayer(전체 화면), REPORT 는 이 상단 바. 둘은 서로 배타적이다 —
            각자 상태를 보고 스스로 뜨고, 아니면 null 을 낸다.
            🔴 본문 **위**에 둔다. 지도를 덮으면 신고 뒤에 부표를 못 본다 (2026-09-18 요청) */}
        <ReportingLayer onAccepted={onAlertAccepted} />

        <div className="terminal-body">
          <nav className="terminal-rail" aria-label="주요 기능">
            <button className="rail-action" aria-pressed={drawer === null}
              onClick={() => setDrawer(null)}><IcoTarget size={30} /><span>본선</span></button>
            <button className="rail-action" aria-pressed={drawer === 'ocean'}
              onClick={() => setDrawer((v) => v === 'ocean' ? null : 'ocean')}>
              <IcoFish size={30} /><span>조업</span>
            </button>
            <button className="rail-action" aria-pressed={drawer === 'devices'}
              onClick={() => setDrawer((v) => v === 'devices' ? null : 'devices')}>
              <IcoChip size={30} /><span>장비</span>
            </button>
            <button className="rail-action" aria-pressed={drawer === 'camera'}
              onClick={() => setDrawer((v) => v === 'camera' ? null : 'camera')}>
              <IcoCamera size={30} /><span>카메라</span>
            </button>
            <button className="rail-action" onClick={() => go('ocean')}>
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

          <div className="terminal-stage">
            <MapPane
              theme={theme} online={online} incident={inc} buoy={s.buoy}
              vesselAt={vesselAt} headingDeg={s.telemetry?.headingDeg ?? 0}
              speedKn={s.telemetry?.speedKn ?? null} vesselName={vesselView.name}
              metric={metric} zones={zones} arrows={arrows} points={stationPoints} gridReady={!!ocean.grid}
              emptyNote={emptyNote}
              picking={picking} manualPos={manualPos} gps={posSource === 'gps'} virtual={virtual}
              onTogglePick={() => setPicking((v) => !v)}
              // 지도 클릭은 한 번이라 토스트를 띄우고, 조이스틱은 연속이라 안 띄운다
              onPick={(at) => {
                setVesselAt(at);
                if (picking) { setPicking(false); setToast('본선 위치 지정됨'); }
              }}
              onResetPos={resetVesselAt}
            />

            {/*
              카메라만 서랍이 아니라 **스테이지를 통째로** 쓴다 (2026-09-18 요청).
              400px 서랍에서는 640x480 두 대가 한 대당 190px 남짓이라 물에 뜬 사람이
              몇 픽셀이 된다 — 이 화면의 쓸모가 거기서 끝난다.
              상단바·레일·독은 남긴다. 사고 중에 다른 버튼에 손이 닿아야 한다.
            */}
            {drawer === 'camera' && (
              <section className="terminal-cam" aria-label={DRAWER_TITLE.camera}>
                <header>
                  <b>{DRAWER_TITLE.camera}</b>
                  <button onClick={() => setDrawer(null)} aria-label="패널 닫기">×</button>
                </header>
                <CameraPane virtual={virtual} />
              </section>
            )}

            {/* 사고 사진도 스테이지를 통째로 쓴다. 서랍 폭에서는 익수자가 몇 픽셀이 된다 —
                카메라를 서랍에서 빼낸 이유(2026-09-18)와 같다 */}
            {drawer === 'frames' && (
              <section className="terminal-cam" aria-label={DRAWER_TITLE.frames}>
                <header>
                  <b>{DRAWER_TITLE.frames}</b>
                  <button onClick={() => setDrawer(null)} aria-label="패널 닫기">×</button>
                </header>
                <FramesPane incidentId={framesOf} virtual={virtual} />
              </section>
            )}

            {drawer && drawer !== 'camera' && drawer !== 'frames' && (
              <aside className="terminal-drawer" aria-label={DRAWER_TITLE[drawer]}>
                <header>
                  <b>{DRAWER_TITLE[drawer]}</b>
                  <button onClick={() => setDrawer(null)} aria-label="패널 닫기">×</button>
                </header>
                {drawer === 'devices' && (
                  <DevicePane health={s.health} telemetry={s.telemetry} buoyFired={!!s.buoy}
                    jetson={s.jetson} jetsonDown={jetsonDown} />)}
                {drawer === 'ocean' && (
                  <OceanPane cats={cats} metric={metric} onExpand={() => go('ocean')}
                    onMetric={(m) => setMetric((cur) => (cur === m ? null : m))} />)}
              </aside>
            )}
          </div>
        </div>

        <footer className="terminal-dock">
          {([
            [null, '해도', IcoBoat],
            ['tide', '유속', IcoCompass],
            ['temp', '수온', IcoWaves],
            ['wave', '파고', IcoBuoy],
            ['wind', '바람', IcoCompass],
          ] as const).map(([key, label, Icon]) => (
            <button key={key ?? 'base'} className="dock-action" aria-pressed={metric === key}
              onClick={() => setMetric(key)}><Icon size={24} /><span>{label}</span></button>
          ))}
          <span className="dock-spacer" />
          {/*
            사고 전후 사진 (2026-09-21 요청으로 레일 → 독). 비상 키 **왼쪽**이다 —
            사고가 난 뒤 손이 가는 순서가 `긴급 신고` 옆이고, 레일은 화면을 고르는 자리라
            기록을 되감아 보는 것과 성격이 달랐다.

            ⚠ 사고가 없으면 띄우되 죽인다. 숨기면 기능이 있는지조차 모른다 —
              전에 레일에서 조건부로 띄우다 정작 만든 사람이 못 찾았다.
          */}
          <button className="dock-action" aria-pressed={drawer === 'frames'}
            disabled={!framesOf}
            title={framesOf ? undefined : '사고가 발생하면 전후 사진을 볼 수 있습니다'}
            onClick={() => setDrawer((v) => v === 'frames' ? null : 'frames')}>
            <IcoFilm size={24} /><span>기록</span>
          </button>
          {/* 비상 키. 하단 오른쪽 끝 고정 — 손이 먼저 가는 자리이고 다른 버튼과 크기·색으로 갈린다 */}
          <button className="dock-action dock-sos" onClick={() => setSheet('sos')}>
            <IcoWarn size={36} /><span>긴급 신고</span>
          </button>
        </footer>
      </div>

      {/* 사고 상태만 보고 스스로 뜬다 — DETECT(발사 중)부터 */}
      <AlertLayer waterTemp={water} onAccepted={onAlertAccepted} />

      {sheet === 'sos' && (
        <SosSheet busy={busy} onClose={() => { setSheet('none'); setBusy(null); }}
          onSend={(_urgency: Urgency, alertType: AlertType) =>
            void run('발신', () => manualAlert({
              alertType,
              // 조난 좌표라 0,0 으로 채우지 않고 화면이 아는 값(GPS 우선)을 그대로 싣는다
              lon: vesselAt[0], lat: vesselAt[1],
            }))} />
      )}

      {sheet === 'settings' && (
        <SettingsSheet vessel={vesselView} theme={theme} setTheme={setTheme}
          onClose={() => setSheet('none')} onWipe={wipe} onComms={() => go('comms')}
          onOcean={() => go('ocean')} />
      )}

      {toast && (
        <div className="toast" role="status">
          <IcoCheck size={28} />
          <b>{toast}</b>
        </div>
      )}
    </>
  );
}

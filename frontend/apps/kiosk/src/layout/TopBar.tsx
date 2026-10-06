import type { LinkState, LngLat } from '@floaq/shared';
import type { Vessel } from '../types';
import type { VoyageNow } from '../cloud/readings';
import { IcoGear, IcoWarn, IcoWifi, IcoWifiOff } from './Icons';
import { isDemo, isPresent } from '../state/store';

/**
 * 상단 바. 시각 · 본선 · 운항 HUD · 연결 상태.
 *
 * Pi 연결만 칩으로 남긴다 — Pi 두절은 **시스템 정지**라 다른 것과 층이 다르다(§9.13).
 * 육상(EC2) 수신 시각과 부표 상태는 여기서 뺐다(2026-09-16) — 상단이 칩으로 붐볐고,
 * 둘 다 원래 자리가 따로 있다: 육상은 해양 패널·상황판의 "N분 전 수신", 부표는 지도와 경보 화면.
 *
 * 좌측 상단은 로고가 아니라 **시각**이다. 선내 단말에서 늘 보는 값이고, 로고는 조업에 쓸모가 없다.
 *
 * 영문 머리표(DATE·LAT·HDG…)를 두지 않는다 — 값의 단위(°N·kn)가 곧 이름이고, 선내 단말은 멀리서 읽는다.
 */
interface Props {
  vessel: Vessel;
  link: LinkState;
  /** 실제 연결 && 강제 오프라인 아님 (useOnline) */
  online: boolean;
  /** 사람이 끈 것인가. "끊김"과 "내가 껐음"을 문구로 가른다 */
  forcedOffline: boolean;
  onToggleOffline: () => void;
  onSettings: () => void;
  clock: string;
  vesselAt: LngLat;
  headingDeg: number;
  speedKn: number | null;
  incidentActive: boolean;
  /**
   * 지금 운항지수. 사고가 없을 때 이 칸이 이걸 말한다 (2026-09-18).
   * null 이면 예전처럼 `이상 없음` — <b>모르는 것을 좋다고 말하지 않는다.</b>
   */
  voyage?: VoyageNow | null;
  /** 가상(녹화 재생) 모드인가. false 면 실제 Pi */
  virtual: boolean;
  /** Pi 칩을 누르면 가상 ↔ 실제가 바뀐다 */
  onToggleVirtual: () => void;
  /** 사고 시나리오 재생 중인가 */
  playing: boolean;
  /** 재생 버튼. 재생 중에 누르면 처음부터 다시 */
  onReplay: () => void;
}

const LINK_TEXT: Record<LinkState, string> = {
  CONNECTING: '연결 중', OPEN: '연결됨', RECONNECTING: '재연결 중', CLOSED: '끊김',
};

const coord = (value: number, positive: string, negative: string) =>
  `${Math.abs(value).toFixed(4)}°${value >= 0 ? positive : negative}`;

export function TopBar(p: Props) {
  const piOk = p.link === 'OPEN';
  const wifiTitle = p.forcedOffline
    ? '강제 오프라인(시연) · 누르면 해제'
    : p.online ? '인터넷 연결됨 · 누르면 오프라인으로 시연' : '인터넷 끊김';

  return (
    <header className="topbar">
      {/* 로고 자리를 시각이 쓴다. 그리드 열 구조는 그대로라 나머지 칸이 밀리지 않는다 */}
      <div className="brand">
        <b className="mono brand-clock">{p.clock}</b>
      </div>

      <div className="vessel">
        <span className="vessel-name">{p.vessel.name}</span>
      </div>

      <div className="hud-readouts" aria-label="운항 정보">
        <span className="hud-cell hud-pos" title="본선 위치">
          <b className="mono">{coord(p.vesselAt[1], 'N', 'S')}</b>
          <b className="mono">{coord(p.vesselAt[0], 'E', 'W')}</b>
        </span>
        <span className="hud-cell" title="선수 방향 · 속력">
          <b className="mono">
            {Math.round(p.headingDeg).toString().padStart(3, '0')}°
            {' · '}{p.speedKn == null ? '—' : p.speedKn.toFixed(1)}<i>kn</i>
          </b>
        </span>
        {/*
          사고가 있으면 사고가 이긴다 — 운항지수는 "나가도 되나"이고 사고는 "지금 사람이 물에 있다"다.
          사고가 없을 때만 운항지수를 말한다. 색은 KHOA 등급 그대로(1~5), 보통(3)은 칠하지 않는다 —
          색으로 말할 상태가 아니다(`SHIP_PILL` 과 같은 규칙).
        */}
        <span className={`hud-alarm${p.incidentActive ? ' is-active' : ''}`
          + (!p.incidentActive && p.voyage?.level != null ? ` is-lv${p.voyage.level}` : '')}
          title={!p.incidentActive && p.voyage
            ? `운항지수 ${p.voyage.score}${p.voyage.areaName ? ` · ${p.voyage.areaName}` : ''}`
              + `${p.voyage.slot ? ` ${p.voyage.slot}` : ''} · KHOA 참고지수 (출항 판정 근거 아님)`
            : undefined}>
          <IcoWarn size={26} />
          <b>{p.incidentActive ? '익수 사고' : p.voyage ? `운항 ${p.voyage.score}` : '이상 없음'}</b>
        </span>
      </div>

      <div className="topbar-right">
        {/* 실제 연결을 보여준다. 누르면 강제 오프라인 — 시연에서 두절 화면을 만드는 스위치다 */}
        <button className="wifi-btn" data-on={String(p.online)} aria-pressed={p.online}
          onClick={p.onToggleOffline} title={wifiTitle} aria-label="인터넷 연결 상태">
          {p.online ? <IcoWifi className="on" /> : <IcoWifiOff className="off" />}
        </button>

        {/* 가상일 때만. 실제 Pi 에 붙은 채 녹화 사고를 흘리면 진짜 경보처럼 보인다.
            발표 화면(?present)에서는 숨기고 R 키로 연다 (store.tsx isPresent) */}
        {p.virtual && !isPresent && (
          <button className="link-chip as-btn" onClick={p.onReplay} aria-pressed={p.playing}
            title={p.playing
              ? '누르면 처음부터 다시 재생'
              : '익수 시나리오 — 3초 뒤 감지 → 부표 발사 → 30초 유예 → 자동 신고 → 부표 두절'}>
            <i className="dot stale" /><b>{p.playing ? '재생 중' : '사고 재생'}</b>
          </button>
        )}
        {/* 시연판은 누를 수 없는 표시로 바꾼다. 공개 URL 에서 '실제' 로 가면
            HTTPS 페이지가 ws:// 를 못 열어 두절 화면에 갇힌다 (store.tsx isDemo) */}
        {/* 발표 화면은 이 칩을 통째로 뺀다. 가짜 '연결됨' 으로 바꾸지 않는 이유는 store.tsx 참고 */}
        {isPresent ? null : isDemo ? (
          <span className="link-chip" title="공개 시연판 — 녹화된 사고를 재생한다. 실제 Pi 연결은 선내 단말에서만">
            <i className="dot stale" />
            Pi <b>가상</b>
          </span>
        ) : (
          <button className="link-chip as-btn" onClick={p.onToggleVirtual} aria-pressed={p.virtual}
            title={p.virtual ? '누르면 실제 Pi(MQTT)에 연결' : '누르면 가상 모드(녹화 재생)'}>
            {/* ⚠ `lost` 가 아니라 `down` 이다. CSS 에 정의된 빨강이 `.dot.down` 뿐이라
                  `lost` 로 쓰던 동안 **Pi 끊김 점에 색이 없었다** (2026-09-21 발견) */}
            <i className={`dot ${p.virtual ? 'stale' : piOk ? 'live' : 'down'}`} />
            Pi <b>{p.virtual ? '가상' : LINK_TEXT[p.link]}</b>
          </button>
        )}

        <button className="icon-btn" onClick={p.onSettings} title="설정" aria-label="설정">
          <IcoGear />
        </button>
      </div>
    </header>
  );
}

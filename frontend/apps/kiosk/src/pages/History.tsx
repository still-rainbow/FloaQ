/**
 * 지난 사고 조회.
 *
 * 화면이 답해야 하는 것은 하나다 — **그때 무슨 일이 있었고, 신고는 나갔는가.**
 * 그래서 목록 한 줄이 "언제 · 무엇 · 어떻게 끝났나" 를 다 말하고, 오른쪽이
 * 그 사고 하나를 펼친다.
 *
 * ⚠ 좌우 2단인 이유: 선내 단말은 서서 1m 에서 보고 화면이 800px 고정이다.
 *   목록↔상세를 화면 전환으로 두면 뒤로 가기를 손으로 눌러야 하고, 여러 건을
 *   훑는 동작이 느려진다. 1180px 아래에서는 한 단으로 접는다.
 *
 * ⚠ 데이터는 **Pi** 에서 온다 (`pi/accidents.ts`). cloud 가 아니다 — 배에
 *   인터넷이 없어도 봐야 하고 사진은 Pi 에만 있다.
 */

import { useEffect, useState } from 'react';
import { useNavigate, type NavigateFunction } from 'react-router-dom';

import type { AlertType, Urgency } from '@floaq/shared';

import { useRoute } from '../hooks/useRoute';
import { useLook } from '../hooks/useLook';
import { useOnline } from '../hooks/useOnline';
import { useVessel } from '../hooks/useVessel';
import { useVesselAt } from '../hooks/useVesselAt';
import { useCommands, useKiosk, useMode } from '../state/store';
import { rejectText } from '../pi/reject';
import { snapshotSrc } from '../pi/accidents';
import type { AccidentStatus } from '../pi/accidents';
import { useAccidentDetail, useAccidentList } from '../pi/useHistory';
import { TopBar } from '../layout/TopBar';
import { AlertLayer } from '../panels/AlertLayer';
import { FramesPane } from '../panels/FramesPane';
import { SettingsSheet } from '../panels/SettingsSheet';
import { SosSheet } from '../panels/SosSheet';
import {
  IcoBoat, IcoBuoy, IcoCamera, IcoCheck, IcoChip, IcoClock, IcoFish, IcoGear,
  IcoTarget, IcoWarn, IcoWaves,
} from '../layout/Icons';

/**
 * 본 화면으로 돌아가며 그 서랍을 연다. `Ocean.tsx` 와 같은 함수다 — 기록 화면에도
 * 서랍이 없으므로 주소로 넘기고 `Kiosk.tsx initialDrawer()` 가 읽는다.
 *
 * ⚠ 값을 늘리면 그쪽도 같이 늘려야 한다. 안 그러면 서랍이 닫힌 채 본 화면만 뜨고
 *   버튼이 아무것도 안 한 것처럼 보인다.
 */
const openMainPanel = (navigate: NavigateFunction, drawer: 'vessel' | 'ocean' | 'devices' | 'camera') => {
  navigate(`/?drawer=${drawer}`);
};

/* ── 표시용 ───────────────────────────────────────────────────────── */

/** 며칠에 걸친 목록이라 날짜를 붙인다 — 시각만 두면 어제 사고가 오늘로 읽힌다. */
const dayClock = (sec: number): string => {
  const d = new Date(sec * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}`
    + `:${String(d.getMinutes()).padStart(2, '0')}`;
};

const fullClock = (sec: number): string => {
  const d = new Date(sec * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-`
    + `${String(d.getDate()).padStart(2, '0')} `
    + `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    + `:${String(d.getSeconds()).padStart(2, '0')}`;
};

/** 경과 초 → 사람이 읽는 길이. 신고까지 몇 초 걸렸나가 이 시스템의 요지다. */
const span = (sec: number | null): string => {
  if (sec === null || !Number.isFinite(sec)) return '—';
  if (sec < 60) return `${Math.round(sec)}초`;
  const m = Math.floor(sec / 60);
  return m < 60 ? `${m}분 ${Math.round(sec % 60)}초` : `${Math.floor(m / 60)}시간 ${m % 60}분`;
};

const coord = (lat: number | null, lon: number | null): string =>
  lat === null || lon === null ? '위치 없음' : `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

/** DSC 조난 종류. ITU-R M.493 을 우리가 쓰는 8종으로 좁힌 것이다. */
const TYPE_LABEL: Record<string, string> = {
  MOB: '익수', FIRE: '화재', FLOODING: '침수', COLLISION: '충돌',
  GROUNDING: '좌초', ENGINE_FAILURE: '기관 고장', MEDICAL: '응급 환자',
  OTHER_DISTRESS: '기타 조난',
};

const STATUS_LABEL: Record<AccidentStatus, string> = {
  DETECT: '감지', WAIT: '유예', REPORT: '신고 중',
  RESCUE: '구조 완료', CLOSE: '종료', CANCEL: '신고 취소',
};

/** `.pill` 의 색. 끝난 사고와 진행 중인 사고가 한눈에 갈려야 한다. */
const STATUS_TONE: Record<AccidentStatus, string> = {
  DETECT: 'alert', WAIT: 'alert', REPORT: 'alert',
  RESCUE: 'ok', CLOSE: '', CANCEL: 'warn',
};

const SOURCE_LABEL: Record<string, string> = {
  AI: 'AI 감지', KIOSK: '사람이 누름', MANUAL: '사람이 누름',
};

const CHANNEL_LABEL: Record<string, string> = {
  DSC: 'DSC', AIS_MOB: 'AIS 익수자', AIS_SART: 'AIS 조난',
};

const REASON_LABEL: Record<string, string> = {
  AI_DETECT: 'AI 가 사람을 봤다',
  COUNTDOWN_START: '유예 시작',
  TIMEOUT: '유예가 끝나 자동 신고',
  MANUAL_REPORT: '사람이 즉시 신고',
  CANCEL: '사람이 신고 취소',
  RESCUE: '구조 확정',
  CLOSE: '사고 종료',
};

/** 목록 필터. dock 탭이 곧 이것이다. */
const FILTERS = [
  [null, '전체', IcoWaves],
  ['REPORT', '신고 중', IcoWarn],
  ['CLOSE', '종료', IcoCheck],
  ['CANCEL', '취소', IcoChip],
] as const;

/* ── 화면 ─────────────────────────────────────────────────────────── */

export function History() {
  const [, go] = useRoute();
  const navigate = useNavigate();
  const s = useKiosk();
  const { virtual, setVirtual, playing, replay } = useMode();
  const { manualAlert } = useCommands();
  const { vessel, wipe } = useVessel();
  const { theme, setTheme } = useLook();
  const { vesselAt } = useVesselAt();
  const { online, forcedOffline, toggleForcedOffline } = useOnline();

  const [filter, setFilter] = useState<AccidentStatus | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [sheet, setSheet] = useState<'none' | 'settings' | 'sos'>('none');
  const [busy, setBusy] = useState<string | null>(null);
  const [hudClock, setHudClock] = useState(() => dayClock(Date.now() / 1000));

  const list = useAccidentList(filter);
  const one = useAccidentDetail(picked);

  useEffect(() => {
    const id = setInterval(() => setHudClock(dayClock(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  // 목록이 처음 오면 맨 위를 연다. 빈 오른쪽을 보여줄 이유가 없다
  useEffect(() => {
    const first = list.rows[0];
    if (!picked && first) setPicked(first.accidentId);
  }, [list.rows, picked]);

  // 기록을 보다가도 긴급 신고는 눌린다. Ocean 과 같은 흐름이다
  const sos = async (urgency: Urgency, alertType: AlertType) => {
    setBusy('발신 중');
    try {
      const r = await manualAlert({ alertType, lon: vesselAt[0], lat: vesselAt[1] });
      if (r.accepted) { setBusy(null); setSheet('none'); }
      else setBusy(`발신 거절 — ${rejectText(r.reason)}`);
    } catch {
      setBusy('발신 실패 — Pi 응답 없음. 다시 시도하세요');
    }
  };

  // 등록 관문은 App 이 잡는다 — ship_id 가 없으면 여기까지 오지 않는다.
  // 이름이 아직 없어도 화면을 막지 않는다 (Ocean 과 같은 판단)
  const vesselView = vessel ?? { name: '', regno: '', camH: '', launchOff: '' };

  return (
    <>
      <div className="shell terminal-shell terminal-analysis-shell">
        <TopBar
          vessel={vesselView} link={s.link}
          online={online} forcedOffline={forcedOffline}
          onToggleOffline={toggleForcedOffline}
          onSettings={() => setSheet('settings')} clock={hudClock}
          virtual={virtual} onToggleVirtual={() => setVirtual(!virtual)}
          playing={playing} onReplay={replay}
          vesselAt={vesselAt}
          headingDeg={s.telemetry?.headingDeg ?? 0}
          speedKn={s.telemetry?.speedKn ?? null}
          incidentActive={!!s.incident}
        />

        {/* 본 화면·해양 화면과 **같은 문구·같은 마크업**이다. 화면마다 다르게 쓰면
            같은 상태를 다른 일로 읽는다. 목록은 실패해도 지우지 않으므로
            (`useHistory`) 여기서도 "마지막 값 표시 중" 이 맞다.
            아무것도 못 받은 경우는 목록 자리가 따로 말한다 */}
        {(s.link !== 'OPEN' || s.piOnline === false) && (
          <div className="pi-down" role="alert">
            <IcoWarn size={22} />
            {s.link !== 'OPEN' ? 'Pi 연결 끊김 · 마지막 값 표시 중' : 'Pi 응답 없음 · 마지막 값 표시 중'}
          </div>
        )}

        <div className="terminal-body">
          {/* 🔴 본 화면·해양 화면과 **똑같은 일곱 칸**이다 (Ocean.tsx 와 같은 판단).
              여기만 네 칸에 아이콘 24 였다 — 화면을 옮기는 순간 레일이 쪼그라들고
              장비·카메라가 사라져서, 같은 버튼이 "다른 것"으로 읽혔다.
              조업·장비·카메라는 본 화면 서랍이라 주소로 넘긴다(openMainPanel). */}
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
            <button className="rail-action" onClick={() => openMainPanel(navigate, 'camera')}>
              <IcoCamera size={30} /><span>카메라</span>
            </button>
            <button className="rail-action" onClick={() => go('ocean')}>
              <IcoWaves size={30} /><span>해양</span>
            </button>
            <button className="rail-action" aria-pressed="true">
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
                <span className="eyebrow">HISTORY</span>
                <h1>지난 사고</h1>
              </div>
              <p className="mono">
                {list.loading && !list.rows.length ? '받는 중'
                  : list.error ? list.error
                    : `${list.total}건`}
              </p>
            </header>

            <div className="analysis-view hist-split">
              <HistList
                list={list} picked={picked} onPick={setPicked} filter={filter} />
              <HistDetail one={one} picked={picked} />
            </div>
          </main>
        </div>

        <footer className="terminal-dock analysis-dock">
          <span className="dock-title"><IcoClock size={18} /><b>지난 사고</b></span>
          {FILTERS.map(([key, label, Icon]) => (
            <button key={label} className="dock-action" aria-pressed={filter === key}
              onClick={() => { setFilter(key); setPicked(null); }}>
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

      {/* 기록을 보는 동안에도 새 사고는 덮는다 — 없으면 사고가 조용히 지나간다 */}
      <AlertLayer waterTemp={null} />

      {sheet === 'settings' && (
        <SettingsSheet vessel={vesselView} theme={theme} setTheme={setTheme}
          onClose={() => setSheet('none')} onWipe={wipe}
          onComms={() => go('comms')} onOcean={() => go('ocean')} />
      )}
      {sheet === 'sos' && (
        <SosSheet onClose={() => setSheet('none')} busy={busy} onSend={sos} />
      )}
    </>
  );
}

/* ── 목록 ─────────────────────────────────────────────────────────── */

function HistList({ list, picked, onPick, filter }: {
  list: ReturnType<typeof useAccidentList>;
  picked: string | null;
  onPick: (id: string) => void;
  filter: AccidentStatus | null;
}) {
  const empty = !list.loading && !list.rows.length;
  return (
    <section className="card hist-list-card">
      <div className="chart-head">
        <span className="chart-title">기록</span>
        <span className="chart-read mono">
          {list.loading ? '받는 중' : `${list.rows.length} / ${list.total}`}
        </span>
      </div>

      {list.error && !list.rows.length ? (
        // ⚠ "Pi 가 켜져 있는지 확인하세요" 라고 쓰지 않는다. Pi 가 꺼져 있으면
        //    MQTT 도 지도도 죽어서 이 화면까지 오지도 못한다 — 여기까지 왔다는
        //    것은 조회 한 번이 실패했다는 뜻이고, 할 일은 다시 받아보는 것이다
        <>
          <p className="chart-empty">{list.error}</p>
          {/* 더 보기와 같은 자리·같은 모양이다. 실패한 화면에서 새 배치를 배우게
              하지 않는다 */}
          <button type="button" className="btn btn-ghost hist-more"
            onClick={list.reload} disabled={list.loading}>
            {list.loading ? '받는 중' : '다시 받기'}
          </button>
        </>
      ) : empty ? (
        <p className="chart-empty">
          {filter ? '이 상태의 사고가 없습니다' : '기록된 사고가 없습니다'}
        </p>
      ) : (
        <ol className="hist-rows">
          {list.rows.map((a) => (
            <li key={a.accidentId}>
              <button type="button" className="hist-row"
                aria-pressed={picked === a.accidentId}
                onClick={() => onPick(a.accidentId)}>
                <span className="hist-when mono">{dayClock(a.createdAt)}</span>
                <span className="hist-what">
                  {TYPE_LABEL[a.accidentType] ?? a.accidentType}
                </span>
                <span className={`pill ${STATUS_TONE[a.status] ?? ''}`}>
                  {STATUS_LABEL[a.status] ?? a.status}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}

      {list.hasMore && (
        <button type="button" className="btn btn-ghost hist-more"
          onClick={list.loadMore} disabled={list.loading}>
          {list.loading ? '받는 중' : `더 보기 (${list.total - list.rows.length}건)`}
        </button>
      )}
    </section>
  );
}

/* ── 상세 ─────────────────────────────────────────────────────────── */

function HistDetail({ one, picked }: {
  one: ReturnType<typeof useAccidentDetail>;
  picked: string | null;
}) {
  const d = one.detail;

  if (!picked) {
    return (
      <section className="card hist-detail-card">
        <p className="chart-empty">왼쪽에서 사고를 고르세요</p>
      </section>
    );
  }
  if (one.error && !d) {
    return (
      <section className="card hist-detail-card">
        <p className="chart-empty">{one.error} — 다시 고르면 재시도합니다</p>
      </section>
    );
  }
  if (!d) {
    return (
      <section className="card hist-detail-card">
        <p className="chart-empty">받는 중</p>
      </section>
    );
  }

  // 이 시스템의 요지는 "사람이 없어도 신고가 나갔는가" 다. 그 숫자를 맨 위에 둔다
  const firstReport = d.reports.reduce<number | null>(
    (min, r) => (r.firstSentAt !== null && (min === null || r.firstSentAt < min)
      ? r.firstSentAt : min), null);
  const toReport = firstReport === null ? null : firstReport - d.createdAt;
  const acked = d.reports.filter((r) => r.ackedAt !== null).length;
  // 마지막 수신 위치. 수색은 여기서 시작한다
  const last = one.track.length ? one.track[one.track.length - 1] : null;

  return (
    <section className="card hist-detail-card">
      <div className="chart-head">
        <span className="chart-title">
          {TYPE_LABEL[d.accidentType] ?? d.accidentType}
          {' · '}
          {SOURCE_LABEL[d.triggerSource] ?? d.triggerSource}
        </span>
        <span className="chart-read mono">{fullClock(d.createdAt)}</span>
      </div>

      {/* 🔴 **통계 타일보다 위다.** 지난 사고를 여는 이유가 "그때 무슨 일이
          있었나" 라 이게 본문이다. 아래 두면 800px 단말에서 재생 버튼까지
          스크롤해야 닿는다 (2026-09-21 1024×768 실측) */}
      {/* 🔴 한 장이 아니라 **재생**이다. 본 화면과 같은 `FramesPane` 을 그대로 쓴다 —
          앞 15초·뒤 10초가 Pi 에 있는데 감지 순간 한 장만 보여주면, 지난 사고를
          다시 보는 이유(그때 무슨 일이 있었나)를 화면이 답하지 못한다.
          ⚠ 사고가 안 끝났을 수도 있어 폴링은 그대로 둔다 — 훅이 수가 안 늘면 멈춘다 */}
      {/* 🔴 `virtual` 은 **항상 false** 다. 그 값은 "MQTT 를 안 쓰고 녹화를
          재생한다"는 뜻이고, 본 화면에서는 사고 id 가 가짜라 Pi 에 물으면 영원히
          404 라서 막는다. 여기는 다르다 — 이 id 는 방금 Pi 가 준 것이고 목록도
          같은 HTTP 로 받았다. 그대로 넘기면 목록은 뜨는데 사진만 "가상 모드라
          안 받는다"가 된다 (2026-09-21 화면에서 걸림) */}
      {d.fileCount > 0 ? (
        // 🔴 `begin` 이다. 지난 사고는 **앞 15초부터** 봐야 무슨 일이 있었는지 안다.
        //    기본값 `detect` 로 두면 사고 후 프레임이 없을 때 곧바로 맨 끝에 서서
        //    재생을 눌러도 아무 일도 안 일어난다
        <FramesPane incidentId={d.accidentId} virtual={false} start="begin" autoPlay />
      ) : d.snapshotPath ? (
        // 파일 수가 0 인데 대표 사진은 있는 경우. 타르볼로 올라가고 목록이 빈 때다
        <img className="hist-shot" src={snapshotSrc(d.snapshotPath)}
          alt="감지 순간 화면" loading="lazy" />
      ) : null}

      <div className="stat-grid hist-stats">
        <div className="stat-tile">
          <span className="stat-label">신고까지</span>
          <span className={`stat-value ${toReport === null ? 'is-alert' : 'is-ok'}`}>
            {span(toReport)}
          </span>
          <span className="stat-note">
            {toReport === null ? '신고 기록 없음' : '감지 시점 기준'}
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-label">부표 투하</span>
          <span className={`stat-value ${d.launch?.result === 'SUCCESS' ? 'is-ok' : 'is-alert'}`}>
            {d.launch ? (d.launch.result === 'SUCCESS' ? '성공' : '실패') : '없음'}
          </span>
          <span className="stat-note">{d.launch?.failReason ?? ' '}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-label">저장된 사진</span>
          <span className="stat-value">{d.fileCount}<small>장</small></span>
          <span className="stat-note">앞 15초 · 뒤 10초</span>
        </div>
      </div>

      <dl className="status-list hist-facts">
        <dt>위치</dt><dd className="mono">{coord(d.lat, d.lon)}</dd>
        <dt>상태</dt><dd>{STATUS_LABEL[d.status] ?? d.status}</dd>
        <dt>신고</dt>
        <dd>
          {d.reports.length === 0 ? '없음'
            : `${d.reports.length}개 채널 · 응답 ${acked}건`}
        </dd>
        {d.closedAt !== null && (<><dt>종료</dt><dd className="mono">{fullClock(d.closedAt)}</dd></>)}
      </dl>

      {d.reports.length > 0 && (
        <ol className="notice-list is-wide hist-reports">
          {d.reports.map((r) => (
            <li key={r.channel}>
              <span className="mono">
                {r.firstSentAt === null ? '—' : dayClock(r.firstSentAt)}
              </span>
              <span>
                {CHANNEL_LABEL[r.channel] ?? r.channel} · {r.sentCount}회 발신
                {r.ackedAt !== null && ` · ${r.ackedBy ?? '수신처'} 응답`}
                {r.failReason && ` · ${r.failReason}`}
              </span>
            </li>
          ))}
        </ol>
      )}

      {one.timeline.length > 0 && (
        <ol className="notice-list is-wide hist-timeline">
          {one.timeline.map((t, i) => (
            <li key={`${t.createdAt}-${t.status}-${i}`}>
              <span className="mono">{dayClock(t.createdAt)}</span>
              <span>{REASON_LABEL[t.reason] ?? t.reason}</span>
            </li>
          ))}
        </ol>
      )}

      {last && (
        <p className="chart-note">
          <IcoBuoy size={14} /> 부표 위치 {one.track.length}점 기록됨 ·
          마지막 {coord(last.lat, last.lon)}
        </p>
      )}
      {d.commLosses.length > 0 && (
        <p className="chart-note">
          부표 두절 {d.commLosses.length}회 ·
          가장 길게 {span(Math.max(...d.commLosses.map(
            (c) => (c.recoveredAt ?? d.closedAt ?? c.detectedAt) - c.detectedAt)))}
        </p>
      )}
    </section>
  );
}

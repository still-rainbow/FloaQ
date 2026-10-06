import { useState } from 'react';
import { brokerUrl, formatAge } from '@floaq/shared';
import type { CommandResult } from '@floaq/shared';
import { useCommands, useKiosk, useMode } from '../state/store';
import { remainingMs } from '../state/reducer';
import { useRoute } from '../hooks/useRoute';
import { driftSize } from '../drift';

/**
 * 통신 확인 화면. 본 화면과 분리된 경로(`#/comms`)에 둔다.
 *
 * 본 화면 안의 탭이 아닌 이유: 시연 중에 실수로 열리면 안 되고,
 * 점검할 때는 주소만으로 바로 갈 수 있어야 한다.
 *
 * 여기서 보는 것은 **배관이 도는가**다. 화면이 예쁜가가 아니다 —
 * 그래서 원시 페이로드를 그대로 찍는다.
 */
const LINK_LABEL: Record<string, string> = {
  CONNECTING: '연결 중', OPEN: '연결됨', RECONNECTING: '재연결 중', CLOSED: '끊김',
};

export function Comms() {
  const s = useKiosk();
  // 런타임 모드다. 빌드 모드(isFixtureMode)는 기본값일 뿐 — 상단 Pi 칩으로 바뀐다
  const { virtual } = useMode();
  const { cancelReport, reportNow, resolveIncident } = useCommands();
  const [, go] = useRoute();
  const [cmd, setCmd] = useState('');

  const run = async (label: string, fn: () => Promise<CommandResult>) => {
    setCmd(`${label} 요청 중…`);
    try {
      const r = await fn();
      setCmd(r.accepted ? `${label} 접수됨` : `${label} 거절 — ${r.reason ?? '사유 없음'}`);
    } catch (e) {
      setCmd(`${label} 실패 — ${(e as Error).message}`);
    }
  };

  const left = s.incident?.deadline
    ? Math.max(0, Math.ceil(remainingMs(s.incident.deadline, s.clockOffsetMs) / 1000))
    : null;

  return (
    <main className="comms">
      <header className="comms-head">
        <div>
          <h1>통신 확인</h1>
          <p className="mono">{virtual ? '가상 모드 — Pi 에 붙지 않는다' : `MQTT ${brokerUrl()}`}</p>
        </div>
        <button className="btn btn-ghost" onClick={() => go('main')}>선내 단말로</button>
      </header>

      {virtual && (
        <p className="comms-warn">
          가상 모드입니다. <b>렌더링과 상태 전이만 검증됩니다</b> —
          재연결·하트비트·CORS·시계 오프셋은 실제 Pi 에 붙어야 확인됩니다.
        </p>
      )}

      <section className="chips">
        <Chip label="브로커" value={LINK_LABEL[s.link] ?? s.link} tone={s.link === 'OPEN' ? 'ok' : 'bad'} />
        {/* 브로커와 Pi 는 다른 층이다. Pi 가 비정상 종료하면 약 22초 뒤에야 두절로 바뀐다(LWT) */}
        <Chip label="Pi 생존" value={s.piOnline === null ? '모름' : s.piOnline ? '살아 있음' : '두절'}
          tone={s.piOnline === null ? 'warn' : s.piOnline ? 'ok' : 'bad'} />
        <Chip label="선박 위치" value={s.vesselFix ? `GPS ${s.vesselFix.lat.toFixed(4)}, ${s.vesselFix.lon.toFixed(4)}` : '단말 설정값'}
          tone={s.vesselFix ? 'ok' : 'warn'} />
        <Chip label="스냅샷" value={s.synced ? '동기화됨' : '모름'} tone={s.synced ? 'ok' : 'warn'} />
        <Chip label="선박" value={s.vesselName ?? '—'} />
        {/* PC 시계가 Pi(GPS 기준)와 얼마나 벌어졌나. 크면 카운트다운이 그만큼 틀린다 */}
        <Chip label="시계 오프셋" value={`${s.clockOffsetMs} ms`}
          tone={Math.abs(s.clockOffsetMs) > 2000 ? 'warn' : 'ok'} />
      </section>

      {s.health && (
        <section className="chips">
          <Chip label="카메라" value={s.health.camera} tone={tone(s.health.camera)} />
          <Chip label="AI" value={s.health.ai} tone={tone(s.health.ai)} />
          <Chip label="IMU" value={s.health.imu} tone={tone(s.health.imu)} />
          <Chip label="부표 링크" value={s.health.buoy} tone={tone(s.health.buoy)} />
        </section>
      )}

      <section className="comms-box">
        <h2>사고</h2>
        {s.incident ? (
          <>
            <p className="mono">
              {s.incident.incidentId} · {s.incident.status} · {s.incident.urgency} / {s.incident.alertType}
              {left !== null && ` · 남은 ${left}초`}
            </p>
            <div className="comms-actions">
              <button onClick={() => void run('취소', () => cancelReport(s.incident!.incidentId))}>취소</button>
              <button onClick={() => void run('즉시 신고', () => reportNow(s.incident!.incidentId))}>즉시 신고</button>
              <button onClick={() => void run('종결', () => resolveIncident(s.incident!.incidentId))}>종결</button>
            </div>
            {cmd && <p className="comms-result">{cmd}</p>}
          </>
        ) : (
          <p className="dim">{s.synced ? '진행 중인 사고 없음' : '상태 미확인 — 스냅샷을 받지 못했다'}</p>
        )}
      </section>

      {s.buoy && (
        <section className="comms-box">
          <h2>부표</h2>
          <p className="mono">
            {s.buoy.buoyId} · {s.buoy.lat.toFixed(4)}, {s.buoy.lon.toFixed(4)} · {formatAge(s.buoy.at)}
            {s.buoy.lost && ` · 두절 (${driftSize(s.buoy)})`}
          </p>
        </section>
      )}

      <section className="comms-box">
        <h2>수신 로그 ({s.log.length})</h2>
        <div className="comms-log">
          {s.log.length === 0 && <span className="dim">아직 없음</span>}
          {s.log.map((e, i) => (
            <div key={i}>
              <span className="dim">{e.at.slice(11, 19)}</span> <b>{e.type}</b>{' '}
              <span className="dim">{e.raw.slice(0, 160)}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

const tone = (v: string) => (v === 'OK' ? 'ok' : v === 'WARN' ? 'warn' : 'bad');

function Chip({ label, value, tone = 'ok' }:
  { label: string; value: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <span className="comms-chip">
      <span className="dim">{label} </span><b data-tone={tone}>{value}</b>
    </span>
  );
}

import { useCallback, useEffect, useState } from 'react';
import type { CommandResult } from '@floaq/shared';
import { remainingMs } from '../state/reducer';
import { useCommands, useKiosk, useMode } from '../state/store';
import { rejectText } from '../pi/reject';
import { useAccidentFiles } from '../pi/useAccidentFiles';
import type { WaterTemp } from '../cloud/readings';
import { coldWater } from '../survival';
import { IcoWarn } from '../layout/Icons';
import { SnapshotView } from './SnapshotView';

/** 유예 전체 길이. 진행 막대 비율에만 쓴다 — 실제 만료는 Pi 의 deadline 이 정한다 (§9.3) */
const GRACE_MS = 30_000;

/**
 * 익수 감지 경보 (§9.3). 사고 상태만 보고 스스로 뜬다 — 본 화면·해양 화면 어디에 있든 덮는다.
 *
 * - DETECT: 감지 즉시 띄운다. Pi 는 DETECT 발행 → 부표 조준·발사 → WAIT 순서라
 *   WAIT 만 기다리면 발사 시간만큼 경보가 늦는다 (IoT core/orchestrator.py on_detection)
 * - WAIT: 카운트다운 + 신고 취소·즉시 신고
 *
 * **발사는 되돌리지 않는다** (2026-09-15 사용자 확인). 취소할 수 있는 것은 신고뿐이라
 * 버튼 이름을 "신고 취소"로 둔다 — "취소"만 쓰면 부표 발사를 멈추는 것으로 읽힌다.
 * DETECT 동안 버튼을 잠그는 것도 같은 이유다 (IoT contracts/kiosk.py 도 WAIT 에서만 받는다).
 *
 * 선택지는 둘뿐 — 스누즈 없음. 연장이 가능하면 "무응답 = 신고" fail-safe 를 사람이 미룬다.
 *
 * ⚠ 카운트다운은 Pi 의 `deadline`(절대 시각)에서 그린다. 남은 초를 받지 않는다 —
 *   재연결 시 다시 계산할 수 없다. PC 시계 차는 clockOffsetMs 로 보정한다 (§9.5).
 */
interface Props {
  /**
   * 지금 수온. 저체온 생존 추정의 입력.
   * 🔴 없으면 없다고 적는다. 지어낸 수온으로 "탈진까지 3시간"을 말하면 그 숫자로 수색 우선순위를 정하게 된다
   */
  waterTemp: WaterTemp | null;
  /** 명령이 받아들여졌을 때. 경보는 상태가 바뀌며 닫히므로 결과는 호출부가 토스트로 알린다 */
  onAccepted?: (label: string) => void;
}

const hms = (iso: string) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function AlertLayer({ waterTemp, onAccepted }: Props) {
  const s = useKiosk();
  const { cancelReport, reportNow } = useCommands();
  const { virtual } = useMode();
  const inc = s.incident;
  const [busy, setBusy] = useState<string | null>(null);
  const [, tick] = useState(0);

  /**
   * 감지 사진을 <b>Pi 에서</b> 받아 온다 (2026-09-20).
   *
   * `jetson/snapshot`(MQTT)은 계약에만 있고 발행하는 코드가 없어 이 자리가 늘 비어 있었다.
   * 같은 사진이 Pi 디스크에는 있다 — Jetson 이 `DETECT_SNAPSHOT` 을 PUT 으로 올린다.
   *
   * ⚠ MQTT 로 오면 그쪽을 쓴다(bbox·확신도가 같이 온다). 그래서 `enabled` 에서 뺀다 —
   *   이미 있는데 125장 목록을 두드릴 이유가 없다.
   * 🔴 가상 모드에서는 끈다. Pi 가 없는 모드라 전부 실패로 쌓인다
   */
  const snap = useAccidentFiles(inc && !s.snapshot ? inc.incidentId : null,
    { enabled: !virtual, fileType: 'DETECT_SNAPSHOT' });
  const shotFile = snap.files[0] ?? null;

  // 남은 초를 상태로 들지 않는다 — 탭이 백그라운드로 가면 타이머가 밀린다
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 200);
    return () => clearInterval(id);
  }, []);

  // 사고·상태가 바뀌면 이전 명령 문구를 걷는다
  useEffect(() => { setBusy(null); }, [inc?.incidentId, inc?.status]);

  /** 거절·실패를 삼키면 "취소를 눌렀는데 신고가 나갔다"를 사용자가 모른다 */
  const run = useCallback(async (label: string, fn: () => Promise<CommandResult>) => {
    setBusy(`${label} 요청 중…`);
    try {
      const r = await fn();
      if (r.accepted) { setBusy(null); onAccepted?.(label); }
      else setBusy(`${label} 거절 — ${rejectText(r.reason)}`);
    } catch {
      setBusy(`${label} 실패 — Pi 응답 없음. 다시 누르세요`);
    }
  }, [onAccepted]);

  if (!inc) return null;
  const launching = inc.status === 'DETECTED';
  const counting = inc.status === 'PENDING' && !!inc.deadline;
  if (!launching && !counting) return null;

  const left = inc.deadline ? remainingMs(inc.deadline, s.clockOffsetMs) : 0;
  const sec = Math.max(0, Math.ceil(left / 1000));
  const pct = Math.max(0, Math.min(100, (left / GRACE_MS) * 100));
  const cold = waterTemp ? coldWater(waterTemp.c) : null;
  const locked = launching || !!busy;

  return (
    <div className="alert-layer" role="alertdialog" aria-modal="true" aria-labelledby="alertTitle">
      <div className="alert-card">
        <header className="alert-top">
          <IcoWarn size={44} />
          <h2 id="alertTitle">익수 사고 발생</h2>
        </header>

        <div className="alert-count" aria-live="assertive">
          {launching
            ? <b className="alert-launch">구명 부표 발사 중</b>
            : <><b className="count">{sec}<small>초</small></b><span>뒤 자동 신고</span></>}
        </div>
        {counting && <div className="count-track"><i className="count-fill" style={{ width: `${pct}%` }} /></div>}

        <p className="alert-info">
          <span>감지 <b className="mono">{hms(inc.detectedAt)}</b></span>
          {/* 저체온 생존 추정. 출처 없는 자체 계산식은 쓰지 않는다 (§6) */}
          <span className={cold ? 'is-cold' : undefined}>
            {waterTemp
              ? <>수온 <b>{waterTemp.c.toFixed(1)}°C</b>{cold && <> · 탈진까지 <b>{cold.exh}</b></>}</>
              : '수온 모름'}
          </span>
        </p>

        {/* 감지 사진 — 취소를 누를지 판단하는 근거다. 버튼 바로 위에 둔다 */}
        <SnapshotView shot={s.snapshot} file={shotFile}
          pending={!s.snapshot && !shotFile && !snap.settled} />

        <div className="alert-actions">
          <button className="alert-btn is-cancel" disabled={locked}
            onClick={() => void run('신고 취소', () => cancelReport(inc.incidentId))}>
            신고 취소<small>오탐지</small>
          </button>
          <button className="alert-btn is-report" disabled={locked}
            onClick={() => void run('신고', () => reportNow(inc.incidentId))}>
            지금 신고
          </button>
        </div>

        {launching && !busy && <p className="alert-note">발사 후 신고를 취소하거나 바로 보낼 수 있습니다</p>}
        {busy && <p className="alert-busy">{busy}</p>}
      </div>
    </div>
  );
}

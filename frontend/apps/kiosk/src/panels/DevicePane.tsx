import type { DeviceHealthData, JetsonStatusMsg, TelemetryData } from '@floaq/shared';
import { IcoBuoy, IcoCamera, IcoChip, IcoWaves } from '../layout/Icons';

/**
 * 좌측 — 센서·영상 이상 탐지 (§9.15).
 *
 * 장비 "관리" 가 아니다. 부표 배터리 잔량·발사 장치 재장전은 **그리지 않는다** —
 * 읽어 올 경로가 없고, 없는 값을 그리면 그 자리가 곧 거짓말이 된다. 감지하는 것은 링크 두절이다.
 * 판정은 선내에서 한다 — 인터넷이 끊겨도 이상을 바로 안다.
 */
interface Props {
  health: DeviceHealthData | null;
  telemetry: TelemetryData | null;
  buoyFired: boolean;
  /** AI 상태 (`jetson/status`). null 이면 Jetson 소식이 없다 */
  jetson: JetsonStatusMsg | null;
  /** Jetson 이 죽었나. LWT 가 없어 마지막 수신 15초로 판단한다 (ref/mqtt.md §5.12) */
  jetsonDown: boolean;
}

const state = (v: string | undefined) =>
  v === 'OK' ? 'ok' : v === 'WARN' ? 'warn' : v === undefined ? 'unknown' : 'bad';

/** 원시 코드(OK·WARN·ERROR)를 그대로 두면 읽는 데 한 번 더 걸린다 */
const HEALTH_TEXT: Record<string, string> = { OK: '정상', WARN: '주의', ERROR: '고장', LOST: '두절' };
const healthText = (v: string | undefined) => (v ? HEALTH_TEXT[v] ?? v : '—');

export function DevicePane({ health, telemetry, buoyFired, jetson, jetsonDown }: Props) {
  const worst = !health
    ? null
    : [health.camera, health.ai, health.imu].includes('ERROR') || health.buoy === 'LOST'
      ? 'bad'
      : [health.camera, health.ai, health.imu].includes('WARN') || health.buoy === 'WARN'
        ? 'warn' : 'ok';

  return (
    <section className="col">
      <div className="rail-head">
        <span className={`pill ${worst ?? 'warn'}`}>
          {worst === 'ok' ? '이상 없음' : worst === 'warn' ? '주의' : worst === 'bad' ? '이상' : '확인 중'}
        </span>
      </div>

      <div className="devices">
        <div className="device" data-state={state(health?.camera)}>
          <IcoCamera className="device-icon" size={28} />
          <div className="device-name">카메라</div>
          <div className="device-val">{healthText(health?.camera)}</div>
        </div>

        <div className="device" data-state={state(health?.ai)}>
          <IcoChip className="device-icon" size={28} />
          <div className="device-name">AI 감지</div>
          <div className="device-val">
            {jetsonDown ? '응답 없음' : healthText(health?.ai)}
            {/* 모델 버전·FPS 는 오탐 분석의 단서다. 사고 뒤 "그때 뭘로 돌고 있었나"에 답한다 */}
            {jetson && !jetsonDown && (
              <small className="device-sub mono">
                {jetson.inferenceFps != null && `${jetson.inferenceFps.toFixed(1)} fps`}
                {jetson.modelVersion && ` · ${jetson.modelVersion}`}
              </small>
            )}
          </div>
        </div>

        <div className="device" data-state={state(health?.imu)}>
          <IcoWaves className="device-icon" size={28} />
          <div>
            <div className="device-name">흔들림</div>
            <div className="device-note mono">
              롤 {telemetry?.rollDeg?.toFixed(1) ?? '—'}° · 피치 {telemetry?.pitchDeg?.toFixed(1) ?? '—'}°
            </div>
          </div>
          <div className="device-val">{healthText(health?.imu)}</div>
        </div>

        <div className="device" data-state={health?.buoy === 'LOST' ? 'bad' : state(health?.buoy)}>
          <IcoBuoy className="device-icon" size={28} />
          <div>
            <div className="device-name">부표</div>
            <div className="device-note">{buoyFired ? '발사됨' : '대기'}</div>
          </div>
          <div className="device-val">{healthText(health?.buoy)}</div>
        </div>
      </div>
    </section>
  );
}

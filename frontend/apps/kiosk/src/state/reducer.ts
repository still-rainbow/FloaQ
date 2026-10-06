import type {
  ActiveIncident, BuoyState, DeviceHealthData, JetsonStatusMsg,
  ReportChannelState, SnapshotMsg,
  ServerMessage, Snapshot, TelemetryData,
} from '@floaq/shared';
import type { LinkState } from '@floaq/shared';

/**
 * 화면 상태. WS 메시지와 스냅샷이 같은 리듀서로 들어온다 —
 * 두 경로가 상태를 따로 만들면 재연결 직후에만 어긋나는 버그가 난다.
 */
export interface KioskState {
  /** 브로커 연결. Pi 생존과 다른 층이다 */
  link: LinkState;
  /** 스냅샷을 한 번이라도 받았나. 못 받았으면 "상태 모름"이지 "사고 없음"이 아니다 */
  synced: boolean;
  /**
   * Pi 생존 (`pi/online`). null 이면 아직 모름.
   * ⚠ Pi 가 비정상 종료하면 약 22초 뒤에야 false 가 된다 — 그동안은 true 로 보인다
   */
  piOnline: boolean | null;

  vesselId: string | null;
  vesselName: string | null;

  incident: ActiveIncident | null;
  /**
   * 신고 채널별 발신 상태. Pi 가 채널마다 retained 로 하나씩 보낸다 —
   * 셋을 여기 모은다(키가 채널명이라 재전송이 덮어쓴다).
   *
   * 사고가 끝나면 비운다. 남겨 두면 <b>다음 사고에 옛 신고 기록이 붙는다.</b>
   */
  reports: Record<string, ReportChannelState>;
  /**
   * 감지 스틸컷. 경보 화면에서 <b>취소 여부를 판단하는 근거</b>다 (기획서 §11 3위).
   *
   * 🔴 retained 라 <b>끝난 사고의 것이 남아 있다</b> — `accident_id` 가 다르면 버린다.
   */
  snapshot: SnapshotMsg | null;
  /**
   * AI 상태. <b>사고와 무관하게</b> 5초마다 온다 — 사고가 끝나도 비우지 않는다.
   *
   * 🔴 `gpsReceived: false` 와 `cameraDirty` 는 <b>사고가 나기 전에</b> 알아야 하는 값이다.
   * 사고 순간에 알면 이미 늦다(`ref/mqtt.md` §5.12).
   */
  jetson: JetsonStatusMsg | null;
  /** 마지막 AI 상태 수신 시각(ms). 15초 넘으면 Jetson 이 죽은 것으로 본다 — LWT 가 없다 */
  jetsonAt: number | null;
  buoy: BuoyState | null;
  telemetry: TelemetryData | null;
  health: DeviceHealthData | null;
  /** Pi GPS 선박 위치. 없으면 단말 수동 위치를 쓴다 (hooks/useVesselAt) */
  vesselFix: { lat: number; lon: number; accuracyM: number | null; at: string } | null;

  /**
   * PC 시계 − Pi 시계 (ms). deadline 을 그릴 때 뺀다.
   *
   * 바다에는 NTP 가 없어 PC 시계가 드리프트한다(§9.5). 보정하지 않으면
   * 30초 카운트다운이 시계 차만큼 틀린다.
   */
  clockOffsetMs: number;

  /** 수신 로그. 통신이 실제로 도는지 화면에서 보기 위한 것 */
  log: LogEntry[];
}

export interface LogEntry {
  at: string;
  type: string;
  raw: string;
}

/** 로그 상한. 무한히 쌓으면 장시간 켜 둔 단말의 메모리를 먹는다 */
const LOG_MAX = 200;

export const initialState: KioskState = {
  link: 'CONNECTING',
  synced: false,
  piOnline: null,
  vesselId: null,
  vesselName: null,
  incident: null,
  reports: {},
  snapshot: null,
  jetson: null,
  jetsonAt: null,
  buoy: null,
  telemetry: null,
  health: null,
  vesselFix: null,
  clockOffsetMs: 0,
  log: [],
};

export type Action =
  | { kind: 'LINK'; state: LinkState }
  | { kind: 'SNAPSHOT'; snapshot: Snapshot; receivedAt: number }
  | { kind: 'MESSAGE'; msg: ServerMessage }
  /**
   * 시계 오프셋 갱신. Pi 메시지의 Envelope `ts` 로 잰다 (mqtt.md §3 · §5.1 주석).
   *
   * 스냅샷의 `serverNow` 가 하던 일을 대신한다 — MQTT 로 옮기면서 그 응답이 없어졌다.
   * retained 메시지는 과거 발행이라 호출부가 걸러서 보낸다.
   */
  | { kind: 'CLOCK'; serverTsMs: number; receivedAt: number }
  /** 두절. 상태를 지우지 않고 "모른다"로만 표시한다 — 마지막 값이 마지막 단서다 */
  | { kind: 'DESYNC' }
  /** 가상 → 실제 전환. 녹화 상태를 지운다 — 브로커 retained 가 다시 채운다 */
  | { kind: 'RESET' };

function pushLog(log: LogEntry[], type: string, raw: unknown): LogEntry[] {
  const next = [
    { at: new Date().toISOString(), type, raw: JSON.stringify(raw) },
    ...log,
  ];
  return next.length > LOG_MAX ? next.slice(0, LOG_MAX) : next;
}

/**
 * 같은 사고의 새 상태를 합친다.
 *
 * 사고 상태 메시지마다 사고 전체가 오지만(decode.ts) 감지 시각과 좌표는 처음 알던 값이 진실이다 —
 * IoT 코드 형식은 감지 시각 대신 이번 전이 시각(changed_at)을, 좌표 대신 0 을 싣는다.
 */
function mergeIncident(prev: ActiveIncident | null, next: ActiveIncident): ActiveIncident {
  if (!prev || prev.incidentId !== next.incidentId) return next;
  const unknownFix = next.lat === 0 && next.lon === 0;
  const { deadline: _d, ...rest } = next;
  return {
    ...rest,
    detectedAt: prev.detectedAt,
    lat: unknownFix ? prev.lat : next.lat,
    lon: unknownFix ? prev.lon : next.lon,
    // deadline 은 이번 메시지 기준이다. WAIT 를 벗어나면 없어야 카운트다운이 멈춘다
    ...(next.deadline ? { deadline: next.deadline } : {}),
  };
}

export function reducer(s: KioskState, a: Action): KioskState {
  switch (a.kind) {
    case 'LINK':
      return { ...s, link: a.state };

    case 'RESET':
      return initialState;

    case 'DESYNC':
      // incident·buoy 를 null 로 비우지 않는다. 두절 중 마지막으로 알던 상태를
      // 지우면 화면이 "사고 없음"으로 보인다 — 그게 가장 위험한 오표시다.
      // 브로커가 끊기면 Pi 생존도 모른다
      return { ...s, synced: false, piOnline: null };

    case 'SNAPSHOT': {
      const { snapshot: snap } = a;
      return {
        ...s,
        synced: true,
        vesselId: snap.vesselId,
        vesselName: snap.vesselName,
        incident: snap.incident,
        buoy: snap.buoy,
        telemetry: snap.telemetry,
        health: snap.health,
        // 왕복 지연의 절반을 빼지 않는다. 선내 유선이라 왕복이 밀리초 단위이고,
        // 보정해서 얻는 정밀도가 30초 타이머에서 의미가 없다.
        clockOffsetMs: a.receivedAt - new Date(snap.serverNow).getTime(),
        log: pushLog(s.log, 'SNAPSHOT', snap),
      };
    }

    case 'CLOCK':
      /**
       * ⚠ `ts` 는 **Unix 초**라 오프셋 해상도가 1초다. 30초 카운트다운에서 ±1초는
       *    감수할 수 있지만, 더 정밀해지려면 Pi 가 ms 를 싣거나 전용 시각 토픽이 필요하다
       *    (`ref/mqtt.md` §7 결정필요 #5).
       *
       * 왕복 지연의 절반을 빼는 보정은 하지 않는다 — 선내 유선이라 왕복이 밀리초 단위이고
       * 위의 1초 양자화에 묻힌다.
       */
      return { ...s, clockOffsetMs: a.receivedAt - a.serverTsMs };

    case 'MESSAGE': {
      const m = a.msg;
      const log = pushLog(s.log, m.type, m);
      // Pi 메시지가 하나라도 왔으면 현재 상태를 아는 것이다.
      // "모름"(synced=false)과 "사고 없음"을 가르는 값이라 여기서 세운다
      s = { ...s, synced: true };

      switch (m.type) {
        case 'INCIDENT_DETECTED':
          return { ...s, incident: mergeIncident(s.incident, m.incident), vesselId: m.vesselId, log };

        case 'INCIDENT_STATE': {
          // 다른 사고의 상태가 올 수 있다. 지금 보고 있는 사고가 아니면 무시한다
          if (!s.incident || s.incident.incidentId !== m.incidentId) return { ...s, log };
          const incident = { ...s.incident, status: m.status };
          // 종결·취소된 사고는 deadline 을 지운다 — 남아 있으면 카운트다운이 계속 그려진다
          if (m.status === 'CANCELLED' || m.status === 'RESOLVED' || m.status === 'REPORTED') {
            delete incident.deadline;
          }
          return { ...s, incident, log };
        }

        case 'INCIDENT_CLEARED':
          // Pi 가 사고 retained 를 지웠다 — 사고가 끝나 정리된 것.
          // 부표·신고 기록도 그 사고의 것이다. 남기면 다음 사고에 옛 기록이 붙는다
          return { ...s, incident: null, reports: {}, snapshot: null, buoy: null, log };

        case 'JETSON_STATUS':
          // 사고와 무관한 장비 상태다 — INCIDENT_CLEARED 에서도 비우지 않는다
          return { ...s, jetson: m, jetsonAt: Date.now(), log };

        case 'SNAPSHOT': {
          // 🔴 retained 는 끝난 사고의 것일 수 있다. 지금 사고가 아니면 버린다 —
          //    안 버리면 **새 사고에 옛 사진이 붙어** 사람이 그걸 보고 취소를 판단한다
          if (m.incidentId && s.incident && s.incident.incidentId !== m.incidentId) return { ...s, log };
          return { ...s, snapshot: m, log };
        }

        case 'REPORT_STATUS': {
          // 다른 사고의 신고가 올 수 있다(retained 가 늦게 도착). 지금 사고가 아니면 무시한다
          if (m.incidentId && s.incident && s.incident.incidentId !== m.incidentId) return { ...s, log };
          // 채널명이 키다 — 같은 채널이 다시 오면 덮어쓴다(sent_count 가 누적이라 최신이 맞다)
          return { ...s, reports: { ...s.reports, [m.report.channel]: m.report }, log };
        }

        case 'BUOY_POS':
        case 'BUOY_LOST':
          return { ...s, buoy: m.buoy, log };

        case 'BUOY_DRIFT_CLEARED': {
          // LoRa 복구. 타원을 걷고, 다음 실측이 오기 전까지는 마지막 실제 수신 위치에 둔다
          // ⚠ 추정에 딸린 필드를 **하나라도** 남기면 복구 뒤에도 지도에 타원이 남는다
          if (!s.buoy) return { ...s, log };
          const {
            estimatedRadiusM: _r, driftInputAt: _i,
            driftEllipse: _e, driftTarget: _g, lastFix, ...rest
          } = s.buoy;
          const buoy: BuoyState = lastFix
            ? { ...rest, lat: lastFix.lat, lon: lastFix.lon, lost: false }
            : { ...rest, lost: false };
          return { ...s, buoy, log };
        }

        case 'TELEMETRY': {
          const { type: _t, vesselId: _v, at: _a, ...data } = m;
          // 합친다 — IMU(자세)와 GPS(속력)가 따로 와서, 덮어쓰면 서로의 값을 지운다
          return { ...s, telemetry: { ...s.telemetry, ...data }, log };
        }

        case 'VESSEL_FIX': {
          const telemetry: TelemetryData = {
            ...s.telemetry,
            ...(m.speedKn !== null ? { speedKn: m.speedKn } : {}),
            ...(m.headingDeg !== null ? { headingDeg: m.headingDeg } : {}),
          };
          return {
            ...s,
            vesselFix: { lat: m.lat, lon: m.lon, accuracyM: m.accuracyM, at: m.measuredAt },
            telemetry,
            log,
          };
        }

        case 'DEVICE_HEALTH': {
          const { type: _t, vesselId: _v, at: _a, ...data } = m;
          return { ...s, health: data, log };
        }

        case 'PI_ONLINE':
          return { ...s, piOnline: m.online, log };

        default:
          return { ...s, log };
      }
    }

    default:
      return s;
  }
}

/**
 * 카운트다운 남은 밀리초. 음수면 이미 자동 신고가 나갔다.
 * PC 시계를 Pi 기준으로 보정해서 뺀다.
 */
export function remainingMs(deadline: string, clockOffsetMs: number, now = Date.now()): number {
  return new Date(deadline).getTime() - (now - clockOffsetMs);
}

// 런타임 의존은 서브패스로. barrel 은 지도·React 를 끌고 와 이 파일을 브라우저 전용으로 만든다
import { parseEnvelope, type Envelope } from '@floaq/shared/mqtt';
import type {
  AlertType, BuoyLink, DeviceHealthData, HealthLevel, IncidentStatus,
  ReportChannel, ReportFailReason, ReportSendState, ServerMessage, Urgency,
} from '@floaq/shared';
import type { Topics } from './topics';

/**
 * MQTT 토픽·페이로드 → 앱 메시지(`@floaq/shared/messages`).
 *
 * 정본: IoT `iot/pi/floaq/contracts/*.py` (2026-09-15 수령). 웹 안내 `ref/mqtt-연동-웹.md` 와
 * 필드가 다른 곳이 있다(아래 accident/state) — **둘 다 받는다.** 어느 쪽이 맞는지는 IoT 팀 확인 대기.
 *
 * ⚠ **이 파일이 명세 변경을 흡수하는 자리다.** 페이로드 필드가 바뀌면 여기만 고친다 —
 *    리듀서·화면·지도는 앱 타입만 보므로 그대로 간다.
 *
 * 앱 타입을 snake_case 로 바꾸지 않은 이유: 화면 코드 전체가 camelCase 이고,
 * 변환이 없어서 얻는 이점(mqtt.md §3.5)은 **Pi·DB 쪽 것**이지 브라우저 쪽 것이 아니다.
 * 변환은 이 파일 한 곳에만 있다.
 */

/** contracts/enums.py AccidentStatus → messages.ts. 이름만 다르고 상태 기계는 같다 */
const STATUS: Record<string, IncidentStatus> = {
  DETECT: 'DETECTED',
  WAIT: 'PENDING',
  REPORT: 'REPORTED',
  CANCEL: 'CANCELLED',
  CLOSE: 'RESOLVED',
};

export const toIncidentStatus = (raw: unknown): IncidentStatus | undefined => STATUS[String(raw)];

/**
 * contracts/enums.py AccidentType → 앱 유형. **8종으로 같다** `확정` 2026-09-17.
 *
 * 모르는 값이 오면 비운다 — 호출부가 MOB 로 떨어뜨린다. 지워진 `HAZARD`·`ABANDON_SHIP` 이
 * 옛 Pi 에서 올라와도 화면이 죽지 않는다.
 */
const ALERT: Record<string, AlertType> = {
  MOB: 'MOB',
  FIRE: 'FIRE',
  FLOODING: 'FLOODING',
  COLLISION: 'COLLISION',
  GROUNDING: 'GROUNDING',
  ENGINE_FAILURE: 'DISABLED',
  OTHER_DISTRESS: 'UNDESIGNATED',
  MEDICAL: 'MEDICAL',
};

/** contracts/enums.py ReportType. SAFETY 는 IoT 쪽에서 사라졌다 — 오면 폴백(DISTRESS)이 받는다 */
const URGENCY: Record<string, Urgency> = { DISTRESS: 'DISTRESS', URGENCY: 'URGENCY' };

/** DeviceHealth 는 OK|ERROR|UNKNOWN 이다. UNKNOWN 을 OK 로 읽으면 거짓말이 된다 */
const health = (v: unknown): HealthLevel =>
  v === 'OK' ? 'OK' : v === 'ERROR' ? 'ERROR' : 'WARN';

const worse = (a: HealthLevel, b: HealthLevel): HealthLevel =>
  a === 'ERROR' || b === 'ERROR' ? 'ERROR' : a === 'WARN' || b === 'WARN' ? 'WARN' : 'OK';

const iso = (unixSec: number): string => new Date(unixSec * 1000).toISOString();

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);

/** Unix 초 → ISO. null 이면 null — 0 으로 채우면 "1970년에 보냈다"가 된다 */
const iso0 = (v: number | null): string | null => (v == null ? null : iso(v));

/**
 * 마지막으로 본 사고 좌표.
 *
 * IoT 코드의 `AccidentState` 에는 좌표가 없고(웹 안내 문서에는 lat·lon 이 있다),
 * `jetson/detection` · `pi/launch/result`(retained) 에만 있다. 셋 중 먼저 오는 쪽이 채운다.
 *
 * 구멍: 좌표 없는 accident/state 형식이면 **키오스크가 발사 전에 재시작했을 때** 좌표를 복구할 수 없다
 * (`jetson/detection` 이 retain 이 아니다). 발사 후면 launch/result 가 retained 라 복구된다.
 */
let lastFix: { lat: number; lon: number } | null = null;

/**
 * 이 단말이 수동 신고로 연 사고의 유형·긴급도.
 *
 * IoT 코드의 `AccidentState` 에 accident_type·report_type 이 없어서, 없으면 이 기억으로 채운다.
 * 없으면 AI 감지로 보고 MOB·DISTRESS — ⚠ 다른 단말이 연 수동 신고는 MOB 로 보인다(한 선박 한 단말 전제).
 */
const manualMeta = new Map<string, { alertType: AlertType; urgency: Urgency }>();

export function rememberManual(accidentId: string, alertType: AlertType, urgency: Urgency): void {
  manualMeta.set(accidentId, { alertType, urgency });
}

export interface Decoded {
  /** 리듀서로 올릴 앱 메시지. 화면이 쓰지 않는 토픽이면 null */
  msg: ServerMessage | null;
  /**
   * Pi 시계 기준 발행 시각(ms). 시계 오프셋 산출에 쓴다.
   * retained 는 과거에 발행된 것이라 제외한다 — 넣으면 오프셋이 통째로 틀어진다.
   */
  serverTsMs: number | null;
  /** 화면에 안 올리는 토픽도 통신 로그에는 남긴다 */
  topic: string;
  /**
   * QoS 1 중복 제거용 (§3.3).
   *
   * ⚠ **retained 에는 적용하면 안 된다.** 재접속마다 같은 request_id 로 다시 오는데,
   *    그걸 중복으로 버리면 복구 자체가 안 된다. 판정은 호출부가 한다.
   */
  requestId: string | null;
}

/** `pi/online` · `kiosk/online` — 봉투 없는 `{online, ts}`. 깨졌으면 null */
function parseOnline(raw: string): boolean | null {
  try {
    const o = JSON.parse(raw) as { online?: unknown } | null;
    return typeof o?.online === 'boolean' ? o.online : null;
  } catch {
    return null;
  }
}

export function decode(TOPIC: Topics, topic: string, raw: string, retained: boolean): Decoded {
  const out: Decoded = { msg: null, serverTsMs: null, topic, requestId: null };
  const receivedAt = new Date().toISOString();

  // 0바이트 = retained 삭제 알림. 봉투로 파싱하면 조용히 버려져 **끝난 사고가 화면에 남는다**
  if (raw.length === 0) {
    if (topic === TOPIC.accidentState) {
      resetFix();
      out.msg = { type: 'INCIDENT_CLEARED', vesselId: TOPIC.shipId, at: receivedAt };
    } else if (topic === TOPIC.buoyDrift) {
      out.msg = { type: 'BUOY_DRIFT_CLEARED', vesselId: TOPIC.shipId, at: receivedAt };
    }
    return out;
  }

  // */online 은 봉투가 없다 (contracts/topics.py RAW_TOPICS). 봉투로 읽으면 깨진다
  if (topic === TOPIC.piOnline) {
    const online = parseOnline(raw);
    if (online !== null) out.msg = { type: 'PI_ONLINE', vesselId: TOPIC.shipId, at: receivedAt, online };
    return out;
  }
  if (topic === TOPIC.kioskOnline) return out;

  const env = parseEnvelope<Record<string, unknown>>(raw);
  if (!env) return out;
  out.requestId = env.request_id;

  // ts 는 Unix 초다. retained 는 과거 발행이라 시계 보정에 쓸 수 없다
  if (!retained && typeof env.ts === 'number') out.serverTsMs = env.ts * 1000;

  const d = env.data[0];
  if (!d) return out;

  const at = typeof env.ts === 'number' ? iso(env.ts) : receivedAt;
  const base = { vesselId: TOPIC.shipId, at };

  switch (topic) {
    case TOPIC.jetsonDetection: {
      // 탐지 자체는 화면에 올리지 않는다 — 사고 판정은 Pi 가 하고
      // pi/accident/state 가 유일한 진실이다. 좌표만 받아 둔다
      const lat = num(d.lat), lon = num(d.lon);
      if (lat !== null && lon !== null) lastFix = { lat, lon };
      return out;
    }

    case TOPIC.launchResult: {
      // 목표 착수 위치가 사고 좌표에 가장 가깝다. 조준 해가 없으면(NO_SOLUTION) null 이다
      const lat = num(d.target_lat), lon = num(d.target_lon);
      if (lat !== null && lon !== null) lastFix = { lat, lon };
      return out;
    }

    case TOPIC.accidentState: {
      const status = STATUS[String(d.status)];
      if (!status) return out;
      const incidentId = String(d.accident_id);

      // 끝난 사고는 전이만 올린다. 재접속 때 retained CLOSE·CANCEL 로 "진행 중 사고"를 새로 세우지 않게
      if (status === 'CANCELLED' || status === 'RESOLVED') {
        out.msg = { type: 'INCIDENT_STATE', ...base, incidentId, status };
        return out;
      }

      // 진행 중이면 **매번 사고 전체를 올린다.** prev_status 로 "최초 생성"만 골라 올리면
      // 새로고침 때 retained WAIT(prev=DETECT) 가 모르는 사고의 전이로 버려져 경보가 안 뜬다
      const lat = num(d.lat), lon = num(d.lon);   // 웹 안내 문서 형식에만 있다
      if (lat !== null && lon !== null) lastFix = { lat, lon };
      const meta = manualMeta.get(incidentId);
      const due = num(d.report_due_at);
      // 감지 시각: 문서 형식 created_at → 코드 형식 changed_at(이 상태로 바뀐 시각). 리듀서가 처음 값을 지킨다
      const createdAt = num(d.created_at) ?? num(d.changed_at);

      out.msg = {
        type: 'INCIDENT_DETECTED',
        ...base,
        incident: {
          incidentId,
          status,
          // ⚠ 좌표를 모르면 0 — 리듀서가 같은 사고의 알던 좌표로 되돌린다
          lat: lastFix?.lat ?? 0,
          lon: lastFix?.lon ?? 0,
          detectedAt: createdAt !== null ? iso(createdAt) : at,
          ...(due !== null ? { deadline: iso(due) } : {}),
          // AI 감지는 긴급도를 고르지 않는다 — 익수는 언제나 조난이다 (계획.md §9.21)
          urgency: URGENCY[String(d.report_type)] ?? meta?.urgency ?? 'DISTRESS',
          alertType: ALERT[String(d.accident_type)] ?? meta?.alertType ?? 'MOB',
        },
      };
      return out;
    }

    case TOPIC.buoyPosition: {
      const lat = num(d.lat), lon = num(d.lon);
      if (lat === null || lon === null) return out;
      const measured = num(d.measured_at);
      out.msg = {
        type: 'BUOY_POS',
        ...base,
        incidentId: String(d.accident_id ?? ''),
        buoy: {
          // buoy_log_id 는 행 번호다. 사고당 부표 1개 전제라 고정 이름을 쓴다
          buoyId: 'buoy',
          lat,
          lon,
          // 지도에는 측정 시각을 쓴다. 발행 시각(ts)과 LoRa 지연만큼 벌어진다
          at: measured !== null ? iso(measured) : at,
          lost: false,
        },
      };
      return out;
    }

    case TOPIC.buoyDrift: {
      // 두절 중 표류 추정 (contracts/pi.py BuoyDrift). 중심·축을 그대로 그린다 — 계산은 Pi 가 한다
      const cLat = num(d.center_lat), cLon = num(d.center_lon), radius = num(d.radius_m);
      if (cLat === null || cLon === null || radius === null) return out;
      const bLat = num(d.base_lat), bLon = num(d.base_lon);
      const lastRx = num(d.last_received_at);
      const inputAt = num(d.input_observed_at);
      // 1σ 타원. ⚠ 갱신 전 Pi 가 남긴 retained 에는 축이 없다 — 그때는 반경으로 원을 그린다.
      //   축이 일부만 오면 버린다. 반쪽짜리 타원은 원보다 더 틀린 모양이다
      const major = num(d.axis_major_m), minor = num(d.axis_minor_m);
      const axisBearing = num(d.axis_bearing_deg);
      const ellipse = major !== null && minor !== null && axisBearing !== null
        && major >= minor && minor > 0
        ? { majorM: major, minorM: minor, bearingDeg: axisBearing }
        : undefined;
      const target = d.target === 'PERSON' || d.target === 'BUOY' ? d.target : undefined;
      out.msg = {
        type: 'BUOY_LOST',
        ...base,
        incidentId: String(d.accident_id ?? ''),
        buoy: {
          buoyId: 'buoy',
          lat: cLat,
          lon: cLon,
          at: lastRx !== null ? iso(lastRx) : at,
          lost: true,
          estimatedRadiusM: Math.round(radius),
          ...(ellipse ? { driftEllipse: ellipse } : {}),
          ...(target ? { driftTarget: target } : {}),
          ...(bLat !== null && bLon !== null ? { lastFix: { lat: bLat, lon: bLon } } : {}),
          driftInputAt: inputAt !== null ? iso(inputAt) : null,
        },
      };
      return out;
    }

    case TOPIC.sensorGps: {
      // 선박 위치 (contracts/pi.py SensorGps). 1Hz, retained
      const lat = num(d.lat), lon = num(d.lon);
      if (lat === null || lon === null) return out;
      const measured = num(d.measured_at);
      out.msg = {
        type: 'VESSEL_FIX',
        ...base,
        lat,
        lon,
        speedKn: num(d.speed_kn),
        headingDeg: num(d.heading_deg),
        accuracyM: num(d.accuracy_m),
        measuredAt: measured !== null ? iso(measured) : at,
      };
      return out;
    }

    case TOPIC.sensorImu: {
      const roll = num(d.roll), pitch = num(d.pitch), heading = num(d.heading_deg);
      out.msg = {
        type: 'TELEMETRY',
        ...base,
        ...(roll !== null ? { rollDeg: roll } : {}),
        ...(pitch !== null ? { pitchDeg: pitch } : {}),
        ...(heading !== null ? { headingDeg: heading } : {}),
        // speedKn 은 pi/sensor/gps 에서 온다
      };
      return out;
    }

    case TOPIC.jetsonStatus: {
      out.msg = {
        ...base,
        type: 'JETSON_STATUS',
        modelVersion: str(d.model_version),
        inferenceFps: num(d.inference_fps),
        cameraL: health(d.camera_l),
        cameraR: health(d.camera_r),
        cameraDirty: d.camera_dirty === true,
        // ⚠ 기본값을 true 로 두지 않는다. 필드가 없으면 "GPS 안 옴"으로 보는 쪽이 안전하다 —
        //    반대로 두면 좌표가 안 나오는 상태를 조용히 지나친다
        gpsReceived: d.gps_received === true,
        uptimeSec: num(d.uptime_sec),
      };
      return out;
    }

    case TOPIC.jetsonSnapshot: {
      const data = str(d.data);
      if (!data) return out;
      const bb = Array.isArray(d.bbox) && d.bbox.length === 4
        && d.bbox.every((n: unknown) => typeof n === 'number')
        ? (d.bbox as [number, number, number, number]) : null;
      out.msg = {
        ...base,
        type: 'SNAPSHOT',
        // 🔴 retained 라 끝난 사고의 것이 남아 있다. 대조는 리듀서가 한다 (ref/mqtt.md §2.2)
        incidentId: String(d.accident_id ?? ''),
        data,
        format: str(d.format) ?? 'jpeg',
        width: num(d.width),
        height: num(d.height),
        confidence: num(d.confidence),
        bbox: bb,
        camera: str(d.camera),
        capturedAt: iso0(num(d.captured_at)),
      };
      return out;
    }

    case TOPIC.reportStatus: {
      // 채널마다 하나씩 retained 로 온다 — 셋을 모으는 것은 리듀서가 한다
      const ch = str(d.channel);
      const st = str(d.status);
      if (!ch || !st) return out;
      out.msg = {
        ...base,
        type: 'REPORT_STATUS',
        incidentId: String(d.accident_id ?? ''),
        report: {
          channel: ch as ReportChannel,
          status: st as ReportSendState,
          sentCount: num(d.sent_count) ?? 0,
          firstSentAt: iso0(num(d.first_sent_at)),
          lastSentAt: iso0(num(d.last_sent_at)),
          ackedAt: iso0(num(d.acked_at)),
          ackedBy: str(d.acked_by),
          failReason: (str(d.fail_reason) ?? null) as ReportFailReason | null,
        },
      };
      return out;
    }

    case TOPIC.deviceStatus: {
      const cam = worse(health(d.camera_l), health(d.camera_r));
      const data: DeviceHealthData = {
        // 이물질은 고장이 아니라 경고다. ERROR 로 올리면 멀쩡한 카메라가 죽은 것으로 보인다
        camera: d.camera_dirty === true ? worse(cam, 'WARN') : cam,
        ai: health(d.ai),
        imu: health(d.imu),
        // LoRa 링크 상태가 곧 부표 링크다 (§1.4 부표 하트비트)
        buoy: (health(d.lora) === 'ERROR' ? 'LOST' : health(d.lora)) as BuoyLink,
        ...(typeof d.internet === 'boolean' ? { internet: d.internet } : {}),
      };
      out.msg = { type: 'DEVICE_HEALTH', ...base, ...data };
      return out;
    }

    default:
      // pi/report/status · jetson/snapshot · jetson/status 는
      // 아직 화면에 자리가 없다. 로그에는 남고 상태는 바꾸지 않는다
      return out;
  }
}

/** 사고가 끝나면 좌표 래치를 비운다 — 다음 사고에 옛 좌표가 새지 않게 */
export function resetFix(): void {
  lastFix = null;
}

export type { Envelope };

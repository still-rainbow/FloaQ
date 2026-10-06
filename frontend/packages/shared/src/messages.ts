/**
 * FloaQ 통신 규약 — kiosk ↔ Raspberry Pi.
 *
 * STOMP를 쓰지 않는다 — 수신자 전원이 같은 선박의 같은 상태를 본다.
 * 구독을 나눌 대상이 없으므로 라우팅 계층 대신 `type` 필드 하나로 충분하다.
 * 선박이 여러 척이 되고 사용자가 자기 선박만 구독해야 할 때 STOMP를 도입한다.
 *
 * **전송은 전부 MQTT 다 (2026-09-11 개정).** Pi 가 브로커다 (`ref/mqtt.md`).
 *
 *   Pi → kiosk   구독        `ship/{id}/pi/#` · `ship/{id}/jetson/#`
 *   kiosk → Pi   publish     `ship/{id}/kiosk/command/*`
 *   접속·재연결   retained    브로커가 마지막 상태를 즉시 밀어 준다 (mqtt.md §2.4)
 *
 * 명령의 성패는 `pi/command/response` 가 `request_id` 로 짝지어 돌려준다 —
 * REST 를 골랐던 이유("눌렀는데 먹었는지 안다")가 이 토픽으로 그대로 유지된다.
 *
 * 페이로드 정본은 IoT `iot/pi/floaq/contracts/*.py` (2026-09-15 수령, 웹 안내 `ref/mqtt-연동-웹.md`).
 *
 * ⚠ **아래 타입은 화면이 쓰는 앱 타입이다.** MQTT 페이로드(snake_case)와 모양이 다르고,
 *    변환은 `apps/kiosk/src/pi/decode.ts` 한 곳에서만 한다.
 */

export type IncidentStatus =
  | 'DETECTED'
  | 'PENDING'
  | 'REPORTED'
  | 'CANCELLED'
  | 'RESOLVED';

export type HealthLevel = 'OK' | 'WARN' | 'ERROR';

/** 부표 LoRa 링크. 두절은 표류 범위 추정을 발동시키는 사고 신호다 (§1.4) */
export type BuoyLink = 'OK' | 'WARN' | 'LOST';

/**
 * 긴급도. 우리가 만든 구분이 아니라 DSC category 규격이다 (§9.21).
 * 받는 쪽의 행동이 달라서 한 버튼으로 묶을 수 없다.
 *
 * ⚠ **SAFETY 를 뺐다** (2026-09-18). IoT `contracts/enums.py ReportType` 이 둘뿐이고
 *   백엔드 `AccidentType` 도 8종이다 — 익수자 구조 시스템에서 항행경보를 누를 일이 없었다.
 *   남겨 두면 화면에만 있고 어디로도 못 나가는 버튼이 된다.
 */
export type Urgency = 'DISTRESS' | 'URGENCY';

/**
 * 사고 유형. ITU-R M.493 nature of distress 코드에 대응한다 (§9.21).
 * 분류를 우리가 정의하면 "그 근거가 뭐냐"에 답할 수 없다.
 *
 * FLOODING 은 UI 한 버튼, DSC 코드 둘이다 — `101` 침수 / `104` 전복 위험을
 * Pi 가 IMU 롤 각으로 가른다. 클라이언트는 고르지 않는다.
 */
export type AlertType =
  | 'MOB'            // 110 man overboard        — AIS-MOB
  | 'FIRE'           // 100 fire, explosion
  | 'FLOODING'       // 101 flooding / 104 listing — IMU 가 결정
  | 'COLLISION'      // 102 collision
  | 'DISABLED'       // 106 disabled and adrift
  | 'GROUNDING'      // 103 grounding
  | 'UNDESIGNATED'   // 107 undesignated distress
  | 'MEDICAL';       // URGENCY. 조난 코드에 의료가 없다
// ⚠ OBSTRUCTION(위험물 발견)을 뺐다 (2026-09-18). IoT `AccidentType` 에서 HAZARD 가 사라져
//   보낼 곳이 없다 — 보내면 Pi 가 ValidationError 로 버리고 **응답도 주지 않아** 5초 타임아웃만 뜬다.

/* ────────────────────────────────────────────────────────────
   페이로드 — WS 메시지와 스냅샷이 같은 모양을 공유한다.
   두 벌로 두면 한쪽만 고쳐져 화면이 조용히 어긋난다.
   ──────────────────────────────────────────────────────────── */

export interface TelemetryData {
  headingDeg?: number;
  speedKn?: number;
  rollDeg?: number;
  pitchDeg?: number;
}

/**
 * 이상 탐지 결과. 장비 "관리"가 아니다 (§9.15).
 * 배터리 잔량·재장치 상태는 읽어올 경로가 없어 뺐다 —
 * 없는 값을 화면에 그리면 그 자리가 곧 거짓말이 된다.
 */
export interface DeviceHealthData {
  camera: HealthLevel;
  ai: HealthLevel;
  imu: HealthLevel;
  buoy: BuoyLink;
  /**
   * Pi 의 인터넷. false 면 시연 신고(UDP)가 나가지 않는다 — 화면이 밝혀야 한다 (IoT contracts/pi.py DeviceStatus).
   * 옛 fixture·페이로드에는 없다
   */
  internet?: boolean;
}

export interface BuoyState {
  buoyId: string;
  lat: number;
  lon: number;
  /** 마지막 수신 시각 */
  at: string;
  /** 두절 판정. 이때만 추정 범위를 그린다 */
  lost: boolean;
  /** 표류 추정 반경(m). 95% 타원의 장축이다 — 타원을 못 그리는 화면이 수색 범위를 과소평가하지 않게 큰 쪽을 준다 */
  estimatedRadiusM?: number;
  /**
   * 1σ 표류 타원. **배율을 먹이기 전 값이다** — 50/75/95% 는 같은 타원에 배율만
   * 다르므로(표류 명세 §6) 미리 곱해 두면 화면이 어느 배율인지 모르고 또 곱한다.
   *
   * 🔴 **표류는 원이 아니다.** crosswind 불확실성이 바람 방향 불확실성보다 3배 커서
   *    타원은 보통 바람 **직각**으로 길다. 원으로 그리면 수색선이 엉뚱한 쪽을 훑는다.
   *
   * ⚠ 없을 수 있다. 갱신 전 Pi 가 남긴 retained 에는 축이 없다 — 그때는 반경으로 원을 그린다.
   */
  driftEllipse?: { majorM: number; minorM: number; bearingDeg: number };
  /** 무엇의 표류인가. 부표와 사람은 풍력 표류 계수가 3배 차이나 같은 타원을 못 쓴다 */
  driftTarget?: 'BUOY' | 'PERSON';
  /** 두절일 때 마지막 실제 수신 위치. lat·lon 은 표류 예상 중심이다 (pi/buoy/drift base_*) */
  lastFix?: { lat: number; lon: number };
  /**
   * 표류 계산에 쓴 해양 데이터의 관측 시각. null 이면 해양 데이터 없이 추정했다.
   * 3시간 전 조류로 그린 원과 3분 전 조류로 그린 원이 화면에서 똑같이 생겼다 — 반드시 같이 띄운다
   */
  driftInputAt?: string | null;
}

export interface ActiveIncident {
  incidentId: string;
  status: IncidentStatus;
  lat: number;
  lon: number;
  detectedAt: string;
  /**
   * 자동 신고 시각(ISO 8601 절대 시각). PENDING 일 때만 있다.
   *
   * 남은 초를 보내지 않는다 — 네트워크 지연만큼 어긋나고 재연결 시 다시 계산할 수 없다.
   * ⚠ 이 값은 **Pi 의 GPS 시계** 기준이다. PC 시계로 그대로 빼면 시계 차만큼 틀린다.
   *    Snapshot.serverNow 로 오프셋을 재서 보정할 것.
   */
  deadline?: string;
  urgency: Urgency;
  alertType: AlertType;
}

/* ────────────────────────────────────────────────────────────
   Pi → kiosk
   ──────────────────────────────────────────────────────────── */

interface Base {
  vesselId: string;
  /** ISO 8601. Pi 생성 시각 (GPS 기준) */
  at: string;
}

/**
 * 진행 중 사고 전체. 익수 확정 때만이 아니라 **진행 중 상태 메시지마다** 온다 —
 * 새로고침 뒤 retained 한 건으로 사고를 다시 세워야 하기 때문이다. 같은 사고면 리듀서가 합친다
 */
export interface IncidentDetected extends Base {
  type: 'INCIDENT_DETECTED';
  incident: ActiveIncident;
}

export interface IncidentStateMsg extends Base {
  type: 'INCIDENT_STATE';
  incidentId: string;
  status: IncidentStatus;
  /** 종결 주체. 선박·관제·자동 종결은 경위상 다른 사건이다 (§9.20) */
  resolvedBy?: 'KIOSK' | 'ADMIN' | 'TIMEOUT';
}

/** 사고 retained 가 지워졌다(0바이트 발행). 화면의 사고·부표를 걷는다 */
export interface IncidentCleared extends Base {
  type: 'INCIDENT_CLEARED';
}

export interface BuoyPos extends Base {
  type: 'BUOY_POS';
  incidentId: string;
  buoy: BuoyState;
}

/** 통신 두절. 마지막 위치와 표류 추정 범위를 함께 보낸다 */
export interface BuoyLost extends Base {
  type: 'BUOY_LOST';
  incidentId: string;
  buoy: BuoyState;
}

/** 표류 추정 retained 가 지워졌다 — LoRa 복구. 원을 걷고 실측 표시로 돌아간다 */
export interface BuoyDriftCleared extends Base {
  type: 'BUOY_DRIFT_CLEARED';
}

export interface TelemetryMsg extends Base, TelemetryData {
  type: 'TELEMETRY';
}

/** 선박 위치 — Pi GPS (`pi/sensor/gps`, 1Hz). 들어오면 단말 수동 위치보다 이긴다 */
export interface VesselFix extends Base {
  type: 'VESSEL_FIX';
  lat: number;
  lon: number;
  speedKn: number | null;
  headingDeg: number | null;
  accuracyM: number | null;
  /** GPS 측정 시각 */
  measuredAt: string;
}

export interface DeviceHealthMsg extends Base, DeviceHealthData {
  type: 'DEVICE_HEALTH';
}

/**
 * 신고 채널 셋 (`ref/mqtt.md` §5.11).
 *
 * <p>⚠ <b>ACK 동작이 서로 다르다.</b> `DSC` 만 수신처가 ACK 을 보내고, 그 ACK 은 단순 수신확인이 아니라
 * <b>종료 신호</b>다 — 받는 즉시 조난경보 재송이 멈춘다. AIS 둘은 ACK 이 없다.</p>
 */
export type ReportChannel = 'AIS_MOB' | 'AIS_SART' | 'DSC';

export type ReportSendState = 'SENDING' | 'ACKED' | 'STOPPED' | 'FAILED';

/** 왜 못 보냈나. `NO_INTERNET` 은 §9.1 "인터넷 두절 시 신고 불가"가 실제로 난 것 */
export type ReportFailReason = 'NO_INTERNET' | 'NO_RECEIVER' | 'TIMEOUT';

/** 채널 하나의 발신 상태. Pi 가 <b>채널마다 하나씩</b> retained 로 발행한다 */
export interface ReportChannelState {
  channel: ReportChannel;
  status: ReportSendState;
  /** 지금까지 보낸 횟수(누적). 재송 중이면 계속 는다 */
  sentCount: number;
  firstSentAt: string | null;
  lastSentAt: string | null;
  /** ⚠ DSC 만 값이 들어올 수 있다 */
  ackedAt: string | null;
  /** ACK 을 보낸 국의 MMSI */
  ackedBy: string | null;
  failReason: ReportFailReason | null;
}

/**
 * 신고 발신 상태 (`pi/report/status`, retained · 채널당 1건).
 *
 * <p>🔴 <b>`NO_INTERNET` 은 반드시 화면에 띄워야 한다</b> — 안 그러면 사용자는 신고가 나간 줄 안다
 * (`ref/mqtt.md` §5.11).</p>
 */
/**
 * 감지 스틸컷 (`jetson/snapshot`, retained · 사고당 1회).
 *
 * <p>기획서 §11 우선순위 3위 — <b>없으면 대기·취소 판단이 불가능하다.</b>
 * 경보 화면에서 선원이 "오탐인가 진짜인가"를 가르는 유일한 근거다.</p>
 *
 * <p>🔴 <b>`accident_id` 를 반드시 대조한다.</b> retained 라 <b>이미 끝난 사고의 스틸컷이
 * 남아 있을 수 있다</b> — 대조하지 않으면 새 사고에 옛 사진이 붙는다(`ref/mqtt.md` §2.2).</p>
 *
 * <p>⚠ 최대 300KB. 다른 토픽(4KB)과 상한이 다르다 — 브로커·클라이언트 설정이 둘 다 받쳐야 하고,
 * 기본값에 걸리면 <b>조용히 끊긴다</b>.</p>
 */
/**
 * AI 상태 (`jetson/status`, retained · 5초).
 *
 * <p><b>Jetson 은 LWT 를 쓰지 않는다.</b> 이 메시지를 5초마다 내는 것으로 생존 신호를 겸한다 —
 * 마지막 수신 후 15초가 지나면 죽은 것으로 본다(`ref/mqtt.md` §5.12).</p>
 *
 * <p>🔴 화면이 반드시 알려야 할 둘:</p>
 * <ul>
 *   <li><b>`gpsReceived: false`</b> — Jetson 이 키오스크 GPS 를 못 받고 있다.
 *       <b>탐지는 되지만 추락 위치가 안 나온다.</b> 이 필드가 없으면 사고 순간에야 안다</li>
 *   <li><b>`cameraDirty`</b> — 렌즈에 물방울이 맺힌 채로 사고가 나면 <b>탐지 자체가 안 된다</b></li>
 * </ul>
 */
export interface JetsonStatusMsg extends Base {
  type: 'JETSON_STATUS';
  /** 오탐 분석·재현용 */
  modelVersion: string | null;
  /** 실측 추론 FPS */
  inferenceFps: number | null;
  cameraL: HealthLevel;
  cameraR: HealthLevel;
  /** AI-06 이물질 감지 */
  cameraDirty: boolean;
  /** 키오스크 GPS 를 받고 있나. false 면 좌표를 못 낸다 */
  gpsReceived: boolean;
  uptimeSec: number | null;
}

export interface SnapshotMsg extends Base {
  type: 'SNAPSHOT';
  incidentId: string;
  /** base64 (data: 접두사 없음) */
  data: string;
  format: string;
  width: number | null;
  height: number | null;
  /** 0~1. 모델 확신도 — 낮으면 사람이 더 봐야 한다 */
  confidence: number | null;
  /** x, y, w, h. 화면에 박스로 그린다 */
  bbox: [number, number, number, number] | null;
  camera: string | null;
  capturedAt: string | null;
}

export interface ReportStatusMsg extends Base {
  type: 'REPORT_STATUS';
  incidentId: string;
  report: ReportChannelState;
}


/**
 * Pi 생존 (`pi/online`, LWT).
 *
 * ⚠ 브로커 연결(link)과 다른 층이다 — 브로커는 붙어 있어도 Pi 가 죽었을 수 있다.
 * ⚠ Pi 가 비정상 종료하면 Keep Alive 15초 × 1.5 ≈ 22초 뒤에야 false 가 온다
 */
export interface PiOnline extends Base {
  type: 'PI_ONLINE';
  online: boolean;
}

/**
 * 전송 계층 하트비트 (§1.4).
 *
 * 브라우저 JS 는 WebSocket ping/pong 제어 프레임에 접근할 수 없어
 * 애플리케이션 메시지로 보낸다. STOMP 를 포기해서 생기는 실질 손해는 이것뿐이다.
 *
 * ⚠ 부표 LoRa 하트비트와 다른 층이다. 이건 "소켓이 살아 있나",
 *    저건 "부표가 통신 범위 안인가" — 뭉개면 오경보가 된다.
 */
export interface Ping extends Base { type: 'PING' }

export type ServerMessage =
  | IncidentDetected
  | IncidentStateMsg
  | IncidentCleared
  | BuoyPos
  | BuoyLost
  | BuoyDriftCleared
  | TelemetryMsg
  | VesselFix
  | DeviceHealthMsg
  | ReportStatusMsg
  | SnapshotMsg
  | JetsonStatusMsg
  | PiOnline
  | Ping;

/** kiosk → Pi (WebSocket). 하트비트 응답 하나뿐이다 — 명령은 REST 로 간다 */
export type ClientMessage = { type: 'PONG'; at: string };

/* ────────────────────────────────────────────────────────────
   스냅샷
   ──────────────────────────────────────────────────────────── */

/**
 * 접속 직후의 현재 상태를 한 덩어리로 담은 것.
 *
 * ⚠ **MQTT 로 옮기면서 Pi 에서 오는 경로가 없어졌다.** 실제 복구는 retained 메시지
 *    여러 개가 따로 도착해 리듀서에 차례로 쌓이는 방식이다 (mqtt.md §2.4).
 *    이 타입은 이제 **fixture 재생 전용**이다 — 녹화 시나리오의 시작 상태를 한 번에 세운다.
 *
 * `serverNow` 가 하던 시계 오프셋 산출은 Envelope 의 `ts` 가 대신한다
 * (retained 가 아닌 Pi 메시지마다 갱신 — `decode.ts`).
 */
export interface Snapshot {
  /** Pi 의 현재 시각. PC 시계 오프셋 산출용 — 바다에는 NTP 가 없다 (§9.5) */
  serverNow: string;
  vesselId: string;
  vesselName: string;
  incident: ActiveIncident | null;
  buoy: BuoyState | null;
  telemetry: TelemetryData | null;
  health: DeviceHealthData | null;
}

/**
 * 명령 거절 사유. 중복 가드(§9.3·§9.20)에 걸린 결과를 화면이 알아야 한다.
 * "취소를 눌렀는데 이미 신고가 나갔다"를 사용자에게 말해 주는 값이다.
 *
 * IoT 코드(contracts/envelope.py ErrorCode)와 웹 안내 문서(§5)의 이름이 다르다 — 둘 다 받는다.
 */
export type CommandRejection =
  | 'ALREADY_REPORTED'
  | 'ALREADY_RESOLVED'
  | 'ALREADY_CANCELLED'
  | 'NO_ACTIVE_INCIDENT'
  /** Pi 가 상태 기계로 거부 (예: WAIT 아닌데 cancel) */
  | 'INVALID_STATE'
  /** 진행 중 사고가 있어 수동 신고를 새로 열지 않음 */
  | 'ACCIDENT_IN_PROGRESS'
  /** IoT 코드 이름 */
  | 'ACCIDENT_NOT_FOUND'
  | 'DEVICE_ERROR'
  /** 웹 안내 문서 이름 */
  | 'NOT_FOUND'
  | 'BAD_REQUEST'
  | 'REJECTED'
  /** 전송 실패. 아래 둘은 Pi 가 보낸 값이 아니라 클라이언트가 스스로 판정한 것이다 */
  | 'TIMEOUT'
  | 'OFFLINE';

export interface CommandResult {
  accepted: boolean;
  reason?: CommandRejection;
  /** Pi 가 보낸 문장 (`error.message`). ⚠ 영어 로그용이라 화면 분기는 reason 으로 한다 */
  message?: string;
  /** 응답 시점 Pi 가 아는 사고 상태. 거부됐을 때 화면을 무엇으로 되돌릴지의 근거 */
  status?: IncidentStatus;
}

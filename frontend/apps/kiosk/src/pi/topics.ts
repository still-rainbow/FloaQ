/**
 * 토픽 이름 — IoT `iot/pi/floaq/contracts/topics.py` (2026-09-15 수령) · `ref/mqtt-연동-웹.md` §2.
 *
 *   ship/{ship_id}/{발행자}/{주제}
 *                     ↑ pi | jetson | kiosk
 *
 * 발행자 세그먼트가 있어야 3자 통신에서 "누가 보낸 것인가"를 토픽만 보고 안다.
 * mosquitto ACL 도 이 접두어로 쓰기 범위를 막는다 — 키오스크 버그가 Pi 인 척
 * 상태를 발행하는 사고를 브로커가 원천 차단한다. (ACL 은 아직 꺼져 있다 — 켜지면 어긴 발행이 조용히 막힌다)
 */

/**
 * ~~`ship_id` 주입 절차는 미정~~ — **해소 (2026-09-17).** 선박 등록(`POST /api/ship`)이
 * 발급한 값을 <b>런타임에</b> 받는다(`useShipRegistration`). 환경변수는 개발용 폴백으로만 남는다.
 *
 * <p>🔴 <b>모듈 상수가 아니어야 한다.</b> 등록 전에는 `ship_id` 가 없고, 등록 뒤에 생긴다 —
 * 상수로 두면 그 순간을 표현할 방법이 없어 `'ship-unset'` 으로 토픽을 만들고
 * <b>브로커는 아무 말 없이 다른 방에 말하게 된다</b>(`ref/kiosk_시연.md` §9).</p>
 */
export const DEV_SHIP_ID: string | null = import.meta.env.VITE_SHIP_ID ?? null;

/** 구독 필터. Pi 와 Jetson 이 내는 것 전부 */
export const subscriptionsFor = (shipId: string) => [`ship/${shipId}/pi/#`, `ship/${shipId}/jetson/#`];

/** 이 선박의 토픽 한 벌. `shipId` 를 같이 들고 다닌다 — decode 가 `vesselId` 로 쓴다 */
export function topicsFor(shipId: string) {
  const root = `ship/${shipId}`;
  return {
  shipId,
  /** 재접속 복구의 기준점. 진행 중 사고의 유일한 진실이다 */
  accidentState: `${root}/pi/accident/state`,
  launchResult: `${root}/pi/launch/result`,
  buoyPosition: `${root}/pi/buoy/position`,
  /** 두절 중 표류 추정 범위. retained — 재접속하면 바로 원을 그린다. LoRa 복구 시 0바이트로 지워진다 */
  buoyDrift: `${root}/pi/buoy/drift`,
  reportStatus: `${root}/pi/report/status`,
  sensorImu: `${root}/pi/sensor/imu`,
  /** 선박 GPS. **Pi 가 발행한다** — 키오스크 GPS 발행(kiosk/sensor/gps)은 없어졌다 */
  sensorGps: `${root}/pi/sensor/gps`,
  deviceStatus: `${root}/pi/device/status`,
  commandResponse: `${root}/pi/command/response`,
  /** LWT. 봉투 없음 */
  piOnline: `${root}/pi/online`,

  jetsonDetection: `${root}/jetson/detection`,
  jetsonSnapshot: `${root}/jetson/snapshot`,
  jetsonStatus: `${root}/jetson/status`,

  /** LWT. 봉투 없음 */
  kioskOnline: `${root}/kiosk/online`,
  command: (name: CommandName) => `${root}/kiosk/command/${name}`,
  } as const;
}

export type Topics = ReturnType<typeof topicsFor>;

/**
 * 명령 5종.
 *
 * ⚠ `rescue`(구조 확정)와 `close`(사고 종료)가 **둘로 갈려 있다.**
 *    계획.md §9.20 은 "사고 종결" 하나였다 — 화면 버튼을 둘로 나눌지는 앱 결정이다.
 */
export type CommandName = 'cancel' | 'report_now' | 'report_manual' | 'rescue' | 'close';

/**
 * `pi/online` · `kiosk/online` 페이로드 — **봉투를 쓰지 않는다** (contracts/topics.py RAW_TOPICS).
 * LWT 는 접속 시점에 고정돼 request_id·ts 를 의미 있게 채울 수 없다.
 * 봉투로 보내면 수신 측이 `{online, ts}` 로 읽지 못한다.
 */
export const onlinePayload = (online: boolean, ts = Math.floor(Date.now() / 1000)) =>
  JSON.stringify({ online, ts });

/** kiosk LWT. Pi 가 "경보를 띄울 화면이 살아있나"를 이 값으로 판단한다. ts 는 의미가 없어 0 */
export const kioskWillFor = (shipId: string) => ({
  topic: `ship/${shipId}/kiosk/online`,
  payload: onlinePayload(false, 0),
});

/**
 * MQTT clientId. **탭마다 다르다.**
 *
 * 🔴 `kiosk-{shipId}` 하나로 두면 한 배에 화면이 둘일 때 서로를 끊는다. MQTT 는
 *    clientId 가 유일해야 해서 브로커가 나중 접속을 받고 앞 연결을 끊는데,
 *    끊긴 쪽이 바로 재접속하면서 상대를 끊는다 — 초당 한 번씩 무한 핑퐁이고
 *    양쪽 다 화면이 계속 깜빡인다 (2026-09-21 브로커 로그로 확인).
 *    시연은 배 한 척에 키오스크와 노트북이 같이 붙는다.
 *
 * ⚠ ACL 은 이 이름이 아니라 **MQTT username** 으로 건다(`mosquitto.conf`).
 *   접미사를 붙여도 쓰기 범위 제한은 그대로다.
 *
 * ⚠ `sessionStorage` 에 담는다 — 같은 탭에서 새로고침하면 같은 id 로 돌아오고,
 *   새 탭은 새 id 를 받는다. 매번 새로 만들면 브로커에 죽은 세션이 쌓인다.
 */
export function clientIdFor(shipId: string): string {
  const key = `floaq.clientId.${shipId}`;
  try {
    const kept = sessionStorage.getItem(key);
    if (kept) return kept;
    const made = `kiosk-${shipId}-${tabTag()}`;
    sessionStorage.setItem(key, made);
    return made;
  } catch {
    // 사생활 보호 모드 등으로 sessionStorage 가 막힐 수 있다. 그래도 붙어야 한다
    return `kiosk-${shipId}-${tabTag()}`;
  }
}

/** 탭 구분용 짧은 무작위. 충돌해도 피해가 "그 둘이 서로 끊는다" 뿐이라 6자면 된다 */
const tabTag = () => Math.random().toString(36).slice(2, 8);

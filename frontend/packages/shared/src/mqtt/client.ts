import mqtt, { type MqttClient } from 'mqtt';
import type { LinkState } from '../link';

/**
 * MQTT 클라이언트 — kiosk ↔ Raspberry Pi (`ref/mqtt.md`).
 *
 * **FloaQ 의미를 갖지 않는다.** 토픽 문자열과 문자열 페이로드만 오간다.
 * 무엇이 어떤 토픽으로 오는지는 `apps/kiosk/src/pi/` 가 안다 —
 * 명세(mqtt.md)가 아직 `제안` 단계라, 바뀌는 것을 한 곳에 가둬 둔다.
 *
 * ⚠ 브라우저는 raw MQTT(1883)에 붙지 못한다. TCP 소켓을 열 수 없다.
 *    Pi 의 mosquitto 에 `listener 8080` + `protocol websockets` 가 있어야 한다.
 *    1883 은 Pi 자신·Jetson(네이티브 클라이언트)용으로 그대로 남는다 — 양자택일이 아니다.
 */

export interface MqttWill {
  topic: string;
  payload: string;
}

export interface MqttOptions {
  /** `ws://127.0.0.1:8080/ws` */
  url: string;
  /** `kiosk-{ship_id}` (mqtt.md §1.1). ACL 이 이 이름으로 쓰기 범위를 막는다 */
  clientId: string;
  /** 구독 필터. 접속·재접속마다 다시 건다 */
  topics: string[];
  onMessage: (topic: string, payload: string, retained: boolean) => void;
  onState: (state: LinkState) => void;
  /** 연결이 열릴 때마다. 재연결에도 매번 온다 */
  onOpen?: () => void;
  will?: MqttWill;
  /** mqtt.md §1 — 15초 */
  keepaliveSec?: number;
}

export interface MqttLink {
  publish: (topic: string, payload: string, opts?: { qos?: 0 | 1; retain?: boolean }) => boolean;
  stop: () => void;
}

const DEFAULTS = {
  keepaliveSec: 15,
  /**
   * 재연결 간격 1초 고정. **지수 백오프를 쓰지 않는다.**
   *
   * Pi 두절은 시스템 정지다(계획.md §9.2) — 랜선을 다시 꽂았는데 화면이
   * 한참 죽어 있으면 안 된다. 클라이언트가 1대라 동시 재접속 폭주도 없어서
   * 백오프가 보호할 대상이 없다.
   */
  reconnectPeriodMs: 1_000,
  connectTimeoutMs: 8_000,
};

export function connectMqtt(opts: MqttOptions): MqttLink {
  let stopped = false;

  const client: MqttClient = mqtt.connect(opts.url, {
    clientId: opts.clientId,
    /**
     * Clean Session (mqtt.md §1). 재접속했을 때 필요한 건 끊긴 동안 쌓인
     * IMU 300개가 아니라 "지금 사고가 어떤 상태인가"다 — 그건 세션 큐가 아니라
     * retained 메시지로 온다.
     */
    clean: true,
    keepalive: opts.keepaliveSec ?? DEFAULTS.keepaliveSec,
    reconnectPeriod: DEFAULTS.reconnectPeriodMs,
    connectTimeout: DEFAULTS.connectTimeoutMs,
    /**
     * MQTT 3.1.1. mqtt.md §3.5 #3 이 `request_id` 를 **페이로드**에 넣기로 확정해서
     * 5.0 의 Correlation Data 속성이 필요 없다 — 낮은 쪽에 맞춰 두면 브로커 설정을 안 탄다.
     */
    protocolVersion: 4,
    /** 구독은 connect 핸들러에서 직접 건다. 둘 다 켜면 SUBSCRIBE 가 두 번 나간다 */
    resubscribe: false,
    will: opts.will
      ? { topic: opts.will.topic, payload: opts.will.payload, qos: 1, retain: true }
      : undefined,
  });

  client.on('connect', () => {
    if (stopped) return;
    // clean: true 라 구독이 남지 않는다. 재접속마다 다시 건다
    client.subscribe(opts.topics, { qos: 1 }, (err) => {
      if (err) {
        // 구독 실패는 조용히 넘기면 "붙었는데 아무것도 안 온다"가 된다.
        // 끊어서 재연결 경로로 보낸다 — 시끄러운 실패가 낫다
        client.reconnect();
        return;
      }
      opts.onState('OPEN');
      opts.onOpen?.();
    });
  });

  client.on('reconnect', () => { if (!stopped) opts.onState('RECONNECTING'); });
  client.on('offline', () => { if (!stopped) opts.onState('RECONNECTING'); });
  client.on('close', () => { if (stopped) opts.onState('CLOSED'); });
  // error 뒤에는 close·reconnect 가 온다. 상태 전이는 그쪽에서만 잡는다
  client.on('error', () => { /* noop */ });

  client.on('message', (topic, payload, packet) => {
    opts.onMessage(topic, payload.toString(), packet.retain === true);
  });

  opts.onState('CONNECTING');

  return {
    publish(topic, payload, o) {
      if (!client.connected) return false; // 조용히 삼키지 않는다. 호출부가 실패를 안다
      client.publish(topic, payload, { qos: o?.qos ?? 1, retain: o?.retain ?? false });
      return true;
    },
    stop() {
      stopped = true;
      client.end(true);
      opts.onState('CLOSED');
    },
  };
}

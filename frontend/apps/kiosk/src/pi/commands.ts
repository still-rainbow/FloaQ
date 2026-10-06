import { newRequestId } from '@floaq/shared/mqtt';
import type { MqttLink, ResponseEnvelope } from '@floaq/shared';
import type { AlertType, CommandResult, Urgency } from '@floaq/shared';
import type { CommandName, Topics } from './topics';
import { rememberManual, toIncidentStatus } from './decode';

/**
 * 키오스크 → Pi 명령. IoT `contracts/kiosk.py` · `ref/mqtt-연동-웹.md` §5.
 *
 * REST 를 버렸지만 **"눌렀는데 먹었는지 안다"는 성질은 버리지 않았다.**
 * 그게 REST 를 골랐던 유일한 이유였다([[260910_kiosk-comms]]).
 *
 *   publish → `pi/command/response` 의 request_id 로 짝을 찾는다 → 성패를 화면에 띄운다
 *
 * 응답이 안 오면 타임아웃으로 드러난다. 브로커에 못 붙어 있으면 publish 가 즉시 실패한다.
 * 어느 쪽이든 **조용히 사라지지 않는다** — 이 시스템에서 최악은
 * "취소를 눌렀는데 신고가 나갔고 사용자가 그걸 모르는 것"이다.
 *
 * ⚠ retain 을 절대 걸지 않는다. 걸면 Pi 가 재접속할 때마다 브로커가
 *    옛 명령을 다시 배달한다 — 30분 전에 누른 [즉시 신고]가 재부팅 때 되살아난다.
 */

/**
 * 응답이 없으면 **같은 request_id 로** 다시 발행하는 간격.
 * 2초 근거: IoT 안내 §5 "2초 안에 응답이 없으면 같은 request_id 로 다시 발행".
 * 새 request_id 면 Pi 가 별개 명령으로 처리해 신고가 두 번 나간다 — 같은 값이면 실행은 건너뛰고 응답만 다시 준다
 */
const RETRY_MS = 2_000;

/** 선내 유선이라 왕복이 밀리초 단위다. 5초(재발행 2회)면 죽은 것으로 본다 */
const TIMEOUT_MS = 5_000;

/** 명령 결과 페이로드 (contracts/kiosk.py `CommandResult`) — 앱 타입과 이름이 겹쳐 여기서만 쓴다 */
interface PiCommandResult {
  accident_id: string;
  command: CommandName;
  status: string;
}

/**
 * 앱 유형 → contracts/enums.py `AccidentType`. **양쪽 다 8종이다** `확정` 2026-09-17.
 *
 * 이름이 둘 다르다(DISABLED·UNDESIGNATED) — 그래서 이 표가 필요하다.
 *
 * ⚠ 전에는 `OBSTRUCTION: 'HAZARD'` 가 있었다. IoT 가 `HAZARD`·`ABANDON_SHIP` 을 빼면서
 *    보낼 곳이 없어졌고, 그대로 두면 Pi 가 ValidationError 로 버린다 —
 *    **거부 응답조차 오지 않아** 키오스크에는 5초 뒤 타임아웃만 뜬다(2026-09-18 확인).
 */
const ALERT_TYPE: Record<AlertType, string> = {
  MOB: 'MOB',
  FIRE: 'FIRE',
  FLOODING: 'FLOODING',
  COLLISION: 'COLLISION',
  GROUNDING: 'GROUNDING',
  DISABLED: 'ENGINE_FAILURE',
  UNDESIGNATED: 'OTHER_DISTRESS',
  MEDICAL: 'MEDICAL',
};

/** 유형 → 긴급도. contracts/enums.py ACCIDENT_ROUTING 과 같은 표 — 사고 상태에 긴급도가 없을 때 화면이 쓴다 */
const urgencyOf = (t: AlertType): Urgency => (t === 'MEDICAL' ? 'URGENCY' : 'DISTRESS');

export interface ManualAlertInput {
  alertType: AlertType;
  /** 신고에 담길 좌표. 없는 값을 0,0 으로 채우지 않는다 — 조난 좌표가 거짓이 된다 */
  lat: number;
  lon: number;
}

export interface CommandBus {
  /** 스토어가 `pi/command/response` 를 받으면 넘긴다 */
  handleResponse: (raw: string) => void;
  /** 연결이 끊기면 대기 중인 약속을 전부 깨운다 — 영원히 매달리지 않게 */
  abortAll: () => void;

  cancelReport: (incidentId: string) => Promise<CommandResult>;
  reportNow: (incidentId: string) => Promise<CommandResult>;
  /** 구조 확정 (APP-10). 신고 중지 + CLOSE */
  rescue: (incidentId: string) => Promise<CommandResult>;
  /** 사고 종료 (APP-11). 계획.md §9.20 의 "종결" */
  resolveIncident: (incidentId: string) => Promise<CommandResult>;
  manualAlert: (input: ManualAlertInput) => Promise<CommandResult>;
}

export function createCommandBus(publish: MqttLink['publish'], topics: () => Topics | null): CommandBus {
  const pending = new Map<string, {
    settle: (r: CommandResult) => void;
    timer: ReturnType<typeof setTimeout>;
    retry: ReturnType<typeof setInterval>;
  }>();

  function finish(requestId: string, result: CommandResult): void {
    const p = pending.get(requestId);
    if (!p) return; // 이미 타임아웃됐거나 중복 응답(QoS 1)이다
    clearTimeout(p.timer);
    clearInterval(p.retry);
    pending.delete(requestId);
    p.settle(result);
  }

  function send(name: CommandName, data: Record<string, unknown>): Promise<CommandResult> {
    const requestId = newRequestId();
    // 한 번 만든 페이로드를 그대로 재발행한다 — ts 도 바꾸지 않는다(같은 명령이다)
    const payload = JSON.stringify({
      request_id: requestId,
      v: 1,
      ts: Math.floor(Date.now() / 1000),
      // 🔴 data 는 항상 배열. 객체면 Pi 가 거부하고 응답도 주지 않는다 (안내 §3)
      data: [{ ...data, issued_by: 'TABLET' }],
    });
    // 등록 전에는 토픽이 없다. 보낼 곳이 없으면 보내지 않는다 —
    // 'ship-unset' 으로 쏘면 브로커가 조용히 받아 다른 방에 둔다
    const t = topics();
    if (!t) return Promise.resolve({ accepted: false, reason: 'OFFLINE' });
    const topic = t.command(name);

    // QoS 1 · retain false. 명령은 한 번은 반드시 닿아야 하고 되살아나면 안 된다
    if (!publish(topic, payload, { qos: 1, retain: false })) {
      return Promise.resolve({ accepted: false, reason: 'OFFLINE' });
    }

    return new Promise<CommandResult>((resolve) => {
      const retry = setInterval(() => {
        // 끊겨 있으면 false — 재발행을 건너뛰고 타임아웃·abortAll 이 결론을 낸다
        publish(topic, payload, { qos: 1, retain: false });
      }, RETRY_MS);
      const timer = setTimeout(() => finish(requestId, { accepted: false, reason: 'TIMEOUT' }), TIMEOUT_MS);
      pending.set(requestId, { settle: resolve, timer, retry });
    });
  }

  return {
    handleResponse(raw) {
      let env: ResponseEnvelope<PiCommandResult | PiCommandResult[]>;
      try {
        env = JSON.parse(raw) as ResponseEnvelope<PiCommandResult | PiCommandResult[]>;
      } catch {
        return; // 깨진 응답 하나로 다른 명령을 깨우지 않는다. 해당 명령은 타임아웃으로 드러난다
      }
      if (typeof env?.request_id !== 'string') return;

      // 코드 정본은 단건 객체다. 옛 형식(배열)도 받는다
      const result = Array.isArray(env.data) ? env.data[0] : env.data;
      const status = toIncidentStatus(result?.status);

      finish(
        env.request_id,
        env.is_success
          ? { accepted: true, ...(status ? { status } : {}) }
          : {
              accepted: false,
              reason: (env.error?.code ?? 'REJECTED') as CommandResult['reason'],
              ...(env.error?.message ? { message: env.error.message } : {}),
              ...(status ? { status } : {}),
            },
      );
    },

    abortAll() {
      for (const [id] of pending) finish(id, { accepted: false, reason: 'OFFLINE' });
    },

    cancelReport: (incidentId) => send('cancel', { accident_id: incidentId }),
    reportNow: (incidentId) => send('report_now', { accident_id: incidentId }),
    rescue: (incidentId) => send('rescue', { accident_id: incidentId }),
    resolveIncident: (incidentId) => send('close', { accident_id: incidentId }),

    manualAlert: (input) => {
      // accident_id 를 키오스크가 만든다. 재전송해도 같은 ID 라 사고가 중복 생성되지 않는다
      const accidentId = newRequestId();
      // 사고 상태 메시지에 유형이 없을 수 있어(IoT 코드 형식) 화면이 쓸 유형을 기억해 둔다
      rememberManual(accidentId, input.alertType, urgencyOf(input.alertType));
      return send('report_manual', {
        accident_id: accidentId,
        accident_type: ALERT_TYPE[input.alertType],
        lat: input.lat,
        lon: input.lon,
      });
    },
  };
}

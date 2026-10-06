import type { ClientMessage, ServerMessage } from '../messages';

/**
 * FloaQ WebSocket 클라이언트. 재연결 · 하트비트 · 연결 상태.
 *
 * ⚠ **대상은 EC2 뿐이다 (2026-09-11).** kiosk↔Pi 는 MQTT 로 옮겼다(`../mqtt/client`) —
 *    Pi 의 8080 이 mosquitto websockets 리스너가 되면서 일반 WebSocket 서버가 없어졌다.
 *    여기 남은 재연결·하트비트는 web↔EC2 경로용이며 아직 소비자가 없다.
 *
 * ⚠ 단일 연결 전제. 한 앱이 두 곳에 동시에 붙을 일이 생기면 인스턴스를 나눈다.
 */

// MQTT(Pi) 와 같은 어휘를 쓴다 — 화면이 분기를 두 벌 갖지 않게
export type { LinkState } from '../link';
import type { LinkState } from '../link';

export interface SocketOptions {
  url: string;
  onMessage: (msg: ServerMessage) => void;
  onState: (state: LinkState) => void;
  /**
   * 연결이 열릴 때마다 호출. 재연결에도 매번 온다.
   *
   * 여기서 스냅샷을 다시 받아야 한다 — 끊긴 동안의 이벤트는 다시 오지 않는다.
   * 최초 1회만 받으면 두절 구간의 사고 상태가 통째로 비어 버린다.
   */
  onOpen?: () => void;
  /**
   * 이 시간 동안 아무 메시지도 없으면 죽은 것으로 보고 끊는다.
   *
   * readyState === OPEN 이어도 TCP 가 half-open 이면 계속 열린 것으로 보인다 —
   * 선내 유선이 뽑혀도 브라우저는 한동안 모른다. 그 창을 이 값이 닫는다.
   *
   * 잠정 15초. Pi 의 PING 주기가 정해지면 그 2~3배로 맞출 것 (§10 미결).
   */
  idleTimeoutMs?: number;
  /** 재연결 간격. 지수 백오프 상한 */
  backoffMinMs?: number;
  backoffMaxMs?: number;
}

export interface FloaqSocket {
  send: (msg: ClientMessage) => boolean;
  stop: () => void;
}

const DEFAULTS = {
  idleTimeoutMs: 15_000,
  backoffMinMs: 1_000,
  /**
   * 상한 10초. Pi 두절은 시스템 정지라 복구가 급하다(§9.2) —
   * 분 단위로 벌리면 랜선을 다시 꽂고도 화면이 한참 죽어 있다.
   */
  backoffMaxMs: 10_000,
};

export function connect(opts: SocketOptions): FloaqSocket {
  const idleTimeoutMs = opts.idleTimeoutMs ?? DEFAULTS.idleTimeoutMs;
  const backoffMinMs = opts.backoffMinMs ?? DEFAULTS.backoffMinMs;
  const backoffMaxMs = opts.backoffMaxMs ?? DEFAULTS.backoffMaxMs;

  let ws: WebSocket | null = null;
  let stopped = false;
  let attempt = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const setState = (s: LinkState) => opts.onState(s);

  const clearTimers = () => {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  };

  /** 메시지가 올 때마다 연장. 만료되면 살아 있는 척하는 연결을 직접 끊는다 */
  const bumpIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      // close() 가 onclose 를 부르고 거기서 재연결이 잡힌다
      ws?.close();
    }, idleTimeoutMs);
  };

  const scheduleRetry = () => {
    if (stopped) return;
    setState('RECONNECTING');
    // 지수 백오프. 지터는 넣지 않는다 — 클라이언트가 1대라 동시 재접속 폭주가 없다
    const delay = Math.min(backoffMinMs * 2 ** attempt, backoffMaxMs);
    attempt += 1;
    retryTimer = setTimeout(open, delay);
  };

  function open() {
    if (stopped) return;
    setState(attempt === 0 ? 'CONNECTING' : 'RECONNECTING');

    let sock: WebSocket;
    try {
      sock = new WebSocket(opts.url);
    } catch {
      // 잘못된 URL 등 생성 자체가 실패. 조용히 멈추지 않고 재시도로 넘긴다
      scheduleRetry();
      return;
    }
    ws = sock;

    sock.onopen = () => {
      attempt = 0;
      setState('OPEN');
      bumpIdle();
      opts.onOpen?.();
    };

    sock.onmessage = (ev) => {
      bumpIdle();
      let msg: ServerMessage;
      try {
        msg = JSON.parse(ev.data as string) as ServerMessage;
      } catch {
        // 깨진 프레임 하나로 연결을 끊지 않는다. 다음 메시지는 정상일 수 있다
        return;
      }
      // 하트비트는 앱에 올리지 않는다 — 화면이 쓸 값이 아니다
      if (msg.type === 'PING') {
        trySend({ type: 'PONG', at: new Date().toISOString() });
        return;
      }
      opts.onMessage(msg);
    };

    sock.onclose = () => {
      if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
      if (stopped) { setState('CLOSED'); return; }
      scheduleRetry();
    };

    // onerror 뒤에는 항상 onclose 가 온다. 재연결은 그쪽 한 곳에서만 잡는다
    sock.onerror = () => { /* noop */ };
  }

  function trySend(msg: ClientMessage): boolean {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
  }

  open();

  return {
    send: trySend,
    stop() {
      stopped = true;
      clearTimers();
      ws?.close();
      setState('CLOSED');
    },
  };
}

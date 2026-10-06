import { useEffect, useRef, useState } from 'react';
import type { ServerMessage } from '../messages';
import { connect, type FloaqSocket, type LinkState, type SocketOptions } from './client';

/**
 * WS 클라이언트를 React 수명주기에 붙인다.
 *
 * ⚠ StrictMode 는 개발에서 effect 를 두 번 돈다. connect() 가 즉시 소켓을 만들므로
 *    cleanup 에서 반드시 stop() 한다 — 안 하면 연결이 두 벌 남아
 *    같은 메시지가 두 번 처리되고 재연결 타이머도 두 개가 된다.
 *    apps/web 의 지도에서 이미 밟은 함정과 같은 구조다.
 *
 * 콜백은 ref 로 받는다. 부모가 매 렌더 새 함수를 넘겨도 재연결하지 않게 한다 —
 * 의존성에 콜백을 넣으면 렌더마다 소켓이 끊겼다 붙는다.
 */
export interface UseFloaqSocketOptions
  extends Omit<SocketOptions, 'onMessage' | 'onState'> {
  onMessage: (msg: ServerMessage) => void;
  /** false 면 연결하지 않는다. fixture 재생 모드에서 쓴다 */
  enabled?: boolean;
}

export function useFloaqSocket(opts: UseFloaqSocketOptions): LinkState {
  const { url, enabled = true } = opts;
  const [state, setState] = useState<LinkState>(enabled ? 'CONNECTING' : 'CLOSED');

  const cb = useRef(opts);
  cb.current = opts;

  const sockRef = useRef<FloaqSocket | null>(null);

  useEffect(() => {
    if (!enabled) { setState('CLOSED'); return; }

    const sock = connect({
      url,
      idleTimeoutMs: cb.current.idleTimeoutMs,
      backoffMinMs: cb.current.backoffMinMs,
      backoffMaxMs: cb.current.backoffMaxMs,
      onMessage: (m) => cb.current.onMessage(m),
      onState: setState,
      onOpen: () => cb.current.onOpen?.(),
    });
    sockRef.current = sock;

    return () => {
      sock.stop();
      sockRef.current = null;
    };
    // url·enabled 가 바뀔 때만 다시 연결한다
  }, [url, enabled]);

  return state;
}

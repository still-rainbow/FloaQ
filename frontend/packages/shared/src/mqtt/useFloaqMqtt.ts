import { useEffect, useRef, useState } from 'react';
import type { LinkState } from '../link';
import { connectMqtt, type MqttLink, type MqttOptions } from './client';

/**
 * MQTT 클라이언트를 React 수명주기에 붙인다.
 *
 * ⚠ StrictMode 는 개발에서 effect 를 두 번 돈다. cleanup 에서 반드시 stop() 한다 —
 *    안 하면 같은 clientId 로 두 번 붙어 브로커가 앞의 연결을 끊는다.
 *    MQTT 는 clientId 가 유일해야 해서 WebSocket 때보다 증상이 더 나쁘다
 *    (두 연결이 서로를 계속 쫓아내며 재연결 루프가 된다).
 *
 * 콜백은 ref 로 받는다. 부모가 매 렌더 새 함수를 넘겨도 재연결하지 않게 한다.
 */
export interface UseFloaqMqttOptions extends Omit<MqttOptions, 'onState'> {
  /** false 면 붙지 않는다. fixture 재생 모드에서 쓴다 */
  enabled?: boolean;
}

export function useFloaqMqtt(opts: UseFloaqMqttOptions): {
  link: LinkState;
  publish: MqttLink['publish'];
} {
  const { url, clientId, enabled = true } = opts;
  const [link, setLink] = useState<LinkState>(enabled ? 'CONNECTING' : 'CLOSED');

  const cb = useRef(opts);
  cb.current = opts;

  const linkRef = useRef<MqttLink | null>(null);

  useEffect(() => {
    if (!enabled) { setLink('CLOSED'); return; }

    const l = connectMqtt({
      url,
      clientId,
      topics: cb.current.topics,
      keepaliveSec: cb.current.keepaliveSec,
      will: cb.current.will,
      onMessage: (t, p, r) => cb.current.onMessage(t, p, r),
      onState: setLink,
      onOpen: () => cb.current.onOpen?.(),
    });
    linkRef.current = l;

    return () => { l.stop(); linkRef.current = null; };
    // url·clientId·enabled 가 바뀔 때만 다시 붙는다. topics 변경은 재연결 사유가 아니다
  }, [url, clientId, enabled]);

  /** 끊긴 상태의 publish 는 false 를 돌려준다 — 호출부가 실패를 화면에 띄운다 */
  const publish: MqttLink['publish'] = (topic, payload, o) =>
    linkRef.current?.publish(topic, payload, o) ?? false;

  return { link, publish };
}

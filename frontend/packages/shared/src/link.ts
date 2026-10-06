/**
 * 연결 상태. WebSocket(EC2) 과 MQTT(Pi) 가 같은 어휘를 쓴다.
 *
 * 두 전송이 상태 이름을 따로 가지면 화면이 분기를 두 벌 갖게 된다 —
 * 사용자가 보는 것은 "붙었나 아닌가" 하나다.
 */
export type LinkState =
  | 'CONNECTING'
  | 'OPEN'
  /** 재연결 대기 중 */
  | 'RECONNECTING'
  /** stop() 으로 끈 상태. 자동 재연결하지 않는다 */
  | 'CLOSED';

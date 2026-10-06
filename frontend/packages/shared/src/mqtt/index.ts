/**
 * MQTT 전송 계층의 **런타임 진입점**.
 *
 * barrel(`@floaq/shared`)이 아니라 이 서브패스로 들여오는 이유:
 * barrel 은 지도(Leaflet)와 React 컴포넌트를 함께 끌고 온다. Envelope 파싱에는
 * 둘 다 필요 없고, 딸려 오면 **브라우저 없이 테스트할 수 없게 된다**
 * (Leaflet 이 import 시점에 `window` 를 읽는다).
 *
 * 타입은 barrel 에서 가져와도 된다 — `import type` 은 런타임에 지워진다.
 */
export { newRequestId, makeDedupe, parseEnvelope } from './envelope';
export type { Envelope, ResponseEnvelope, ErrorInfo } from './envelope';

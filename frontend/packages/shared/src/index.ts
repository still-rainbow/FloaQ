export * from './messages';
export * from './staleness';
export * from './origins';
// 표류 고리 배율. Pi(floaq/drift.py SIGMA_SCALE) 와 같은 숫자여야 한다
export { RING_K, RAMP_FROM_SIGMA, BAND_RAMP } from './drift';
export type { LinkState } from './link';

// MQTT — kiosk ↔ Raspberry Pi. 브로커가 Pi 에 있다 (ref/mqtt.md §1).
export { connectMqtt } from './mqtt/client';
export type { MqttOptions, MqttLink, MqttWill } from './mqtt/client';
export { useFloaqMqtt } from './mqtt/useFloaqMqtt';
export type { UseFloaqMqttOptions } from './mqtt/useFloaqMqtt';
export { newRequestId, makeDedupe, parseEnvelope } from './mqtt/envelope';
export type { Envelope, ResponseEnvelope, ErrorInfo } from './mqtt/envelope';

// WebSocket — web ↔ EC2. Pi 경로는 위 MQTT 다.
export { connect } from './ws/client';
export type { SocketOptions, FloaqSocket } from './ws/client';
export { useFloaqSocket } from './ws/useFloaqSocket';

// 지도 — kiosk 도 같은 모듈을 쓴다. 구현을 갈아끼워도 앱 코드는 그대로다.
export { MapView } from './map/MapView';
export { COASTLINES } from './map/floaq-map';
export { FloaqMap } from './map/floaq-map.js';
export type {
  LngLat, MapTheme, MarkerSpec, MarkerHandle, PointSpec, FloaqMapApi, CreateOptions, ContourBand, Isoline, GridCell,
} from './map/floaq-map.js';

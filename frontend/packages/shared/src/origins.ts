/**
 * 백엔드 오리진.
 *
 * kiosk 는 두 곳에 붙는다. 오리진 이름이 중요도를 드러낸다.
 *
 *   pi     끊기면 시스템 정지 — 감지·경보·카운트다운·신고·부표 추적
 *   cloud  끊기면 해당 영역만 비활성 — 해양 데이터·LLM 요약·과거 기록
 *
 * ⚠ 사고 경로 코드는 cloud 를 호출하지 않는다.
 *    "선내 PC는 EC2 없이 동작한다"(계획.md §9.2)가 이 규칙으로 성립한다.
 *    grep -rn "cloudUrl\|/cloud" apps/kiosk/src/pi apps/kiosk/src/state  → 비어야 한다
 *
 * ~~**Pi 쪽 REST 는 없다.**~~ — **뒤집혔다 (2026-09-17, `ref/kiosk_시연.md`).**
 * Pi 가 페이지를 내려주고 <b>해양 데이터까지 중계한다</b>. 명령·상태는 여전히 MQTT 다.
 */

const env = import.meta.env as Record<string, string | undefined>;

/** dev 에서는 vite proxy 가 받으므로 상대 경로, 빌드에서는 전체 URL */
const base = (origin: string | undefined, devPrefix: string): string =>
  import.meta.env.DEV ? devPrefix : (origin ?? '').replace(/\/$/, '');

export const cloudUrl = (path: string): string =>
  `${base(env.VITE_CLOUD_ORIGIN, '/cloud')}${path}`;

/**
 * Pi 의 HTTP — 해양 중계 · 사진 · 선박 등록 (`ref/kiosk_시연.md` §6).
 *
 * <b>오리진을 만들지 않는다.</b> 페이지를 Pi 가 내려주므로 배포판에서는 <b>같은 오리진</b>이다 —
 * 문서가 못 박은 *"Pi 주소를 하드코딩하지 말고 `location.hostname` 을 쓴다"* 가 이 뜻이다.
 * 상대 경로를 그대로 두면 선내판은 Pi 로, EC2 시연판은 nginx 로 간다(그쪽엔 Pi 가 없으니 EC2 가 답한다).
 *
 * dev 만 vite 프록시(`/pi`)를 탄다 — 브라우저가 5174 하고만 대화하게 된다.
 *
 * ⚠ <b>kiosk 키를 싣지 않는다.</b> 중계로 바꾼 이유의 절반이 그것이다 —
 * 키가 브라우저 번들에 들어가면 안 된다(§0). 키는 Pi 가 들고 EC2 에 낸다.
 */
export const piUrl = (path: string): string =>
  import.meta.env.DEV ? `/pi${path}` : path;

/** mosquitto WebSocket 리스너. 1883 은 raw TCP 라 브라우저가 못 연다 (IoT `mosquitto.conf`) */
const BROKER_PORT = 9001;

/** Jetson MJPEG 서버 (IoT `JetSon/floaq_jetson/_stream.py` `PORT = 8080`) */
const JETSON_PORT = 8080;

const wsScheme = (): string => (location.protocol === 'https:' ? 'wss' : 'ws');

/**
 * MQTT-over-WebSocket 브로커 주소.
 *
 * dev 는 vite proxy(`ws: true`)를 거친다 — 브라우저가 5174 하고만 대화하게 된다.
 *
 * 빌드판은 **`location.hostname` 에서 만든다** (2026-09-18).
 * 페이지를 Pi 가 내려주므로(`:8000` 의 `/kiosk`) 브라우저가 이미 Pi 주소를 알고 있다 —
 * `ref/kiosk_시연.md` §A 가 "Pi 주소를 하드코딩하지 말고 `location.hostname` 을 쓴다"고
 * 못 박은 그 자리다. 이걸로 `.env` 의 `VITE_PI_ORIGIN` 이 없어도 된다.
 *
 * `VITE_PI_ORIGIN` 은 **덮어쓰기 전용**으로 남긴다 — IoT 테스트 브로커에 붙을 때
 * `.env.local` 에 넣어 쓴다. 커밋되는 기본값으로는 두지 않는다.
 *
 * ~~경로 `/ws` 가 되는지 모른다~~ — **확인 (2026-09-20).** Pi(127.0.0.1:9001)에
 *    업그레이드 요청을 직접 보내 `101 Switching Protocols` + `Sec-WebSocket-Protocol: mqtt`
 *    를 받았다. mosquitto 는 websocket 경로를 가리지 않는다 — `/ws` 그대로 둔다.
 */
export const brokerUrl = (path = '/ws'): string => {
  if (import.meta.env.DEV) return `${wsScheme()}://${location.host}${path}`;
  const override = env.VITE_PI_ORIGIN;
  if (override) return `${override.replace(/^http/, 'ws')}${path}`;
  return `${wsScheme()}://${location.hostname}:${BROKER_PORT}${path}`;
};

/**
 * Jetson — 카메라 라이브만 (`ref/kiosk_시연.md` §7).
 *
 * <b>Pi 가 아니다.</b> 영상만 Jetson 이 직접 내보낸다 — Pi 를 거치면 프레임이 한 번 더 복사되고
 * 그만큼 늦는다. MJPEG 이라 {@code <img>} 로 받고, 이미지 표시에는 CORS 가 걸리지 않는다.
 *
 * ⚠ <b>HTTPS 페이지에서는 열리지 않는다.</b> `http://<jetson>` 이 mixed content 로 막힌다 —
 * EC2 공개 시연판이 그렇다. 그쪽은 가상 모드라 애초에 부르지 않는다(CameraPane).
 *
 * 기본값은 <b>페이지를 내려준 호스트의 :8080</b> 이다 (2026-09-18) — 지금 시험 구성이
 * Pi 와 Jetson 이 같은 기계다. <b>둘을 다른 기계로 분리하면 반드시 `VITE_JETSON_ORIGIN` 을 준다.</b>
 * 안 주면 Pi 의 8080 을 두드리다 실패하는데, CameraPane 이 `/health` 로 확인해
 * <b>"카메라 없음"을 화면에 띄우므로 조용히 틀리지는 않는다.</b>
 */
export const jetsonUrl = (path: string): string => {
  if (import.meta.env.DEV) return `/jetson${path}`;
  const override = env.VITE_JETSON_ORIGIN;
  const origin = override
    ? override.replace(/\/$/, '')
    : `${location.protocol}//${location.hostname}:${JETSON_PORT}`;
  return `${origin}${path}`;
};

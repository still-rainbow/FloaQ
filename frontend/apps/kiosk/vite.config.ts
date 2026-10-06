import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// 선내 PC 단말.
//
// 🔴 **`.env` 를 없앴다** (2026-09-18). 아래 폴백이 그 자리를 대신한다.
//
//    지우기 전의 문제: `.env` 는 커밋 대상이라 `VITE_SHIP_ID=ship-dev` 가 모든 빌드에 박혔고,
//    Pi 응답을 못 받은 단말이 그 값으로 없는 배의 토픽을 구독했다. 브로커는 에러를 주지 않는다 —
//    화면은 멀쩡하고 사고만 영영 안 왔다(2026-09-17 시험). 주소 기본값을 코드에 두면
//    적어도 한 곳에만 있고, 여기 주석이 왜 그 값인지 같이 말한다.
//
//    배포판이 실제로 쓰는 주소는 이제 `location.hostname` 에서 나온다(packages/shared/origins.ts) —
//    페이지를 Pi 가 내려주므로 브라우저가 이미 Pi 주소를 안다(`ref/kiosk_시연.md` §A).
//    아래 값은 **dev 프록시 타깃**일 뿐이다.
//
// 자리마다 주소가 다르면 `.env.local` 을 만든다 (`.gitignore` 가 잡는다).
// 그쪽 값이 여기 폴백을 이긴다.
//
//   VITE_PI_ORIGIN      mosquitto WebSocket **9001**. 1883 은 raw TCP 라 브라우저가 못 연다
//   VITE_PI_HTTP_ORIGIN Pi 의 HTTP(해양 중계·사진·선박 등록) **8000**
//   VITE_JETSON_ORIGIN  Jetson 카메라 MJPEG **8080**. Pi 가 아니다 — 다른 기계로 분리하면 필수
//   VITE_CLOUD_ORIGIN   EC2. kiosk 는 이제 안 부른다(해양도 Pi 가 중계) — /cloud 프록시에만 쓴다
//   VITE_SHIP_ID        개발 폴백 전용. 실제 모드는 선박 등록이 런타임에 발급한다
//
// training 내부망에서만 닿는다. 밖에서는 Pi 에 붙을 수 없으므로 화면 작업은
// `pnpm --filter @floaq/kiosk dev:fixture` 로 한다 — 상단 "재생" 이 익수 시나리오를 돌린다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const pi = env.VITE_PI_ORIGIN || 'http://127.0.0.1:9001';
  const piHttp = env.VITE_PI_HTTP_ORIGIN || 'http://127.0.0.1:8000';
  const jetson = env.VITE_JETSON_ORIGIN || 'http://127.0.0.1:8080';
  const cloud = env.VITE_CLOUD_ORIGIN || 'http://localhost:8080';

  // EC2 공개 시연판(VITE_DEMO=1)에 kiosk 키가 구워지는 것을 막는다.
  //
  // loadEnv 는 .env.local 까지 읽고, Vite 는 VITE_ 로 시작하는 값을 번들에 문자열로 넣는다.
  // CI 는 git clone 이라 .env.local 이 없지만, 로컬에서 시연판을 빌드하면 개발자 키가
  // 그대로 공개 URL 로 나간다 — 번들을 열어보기 전에는 아무도 모른다.
  //
  // 조용히 지우지 않고 빌드를 끊는 이유: 지우면 '해역 이동이 왜 안 되지' 를 선내판에서도 의심하게 된다.
  // 키가 없는 시연판은 정상이다 — 조회는 되고 해역 이동만 거부된다 (api.md 1.1).
  if (env.VITE_DEMO === '1' && env.VITE_KIOSK_KEY) {
    throw new Error(
      '시연판(VITE_DEMO=1)은 VITE_KIOSK_KEY 를 번들에 넣지 않는다. '
      + '.env.local 의 VITE_KIOSK_KEY 를 지우거나 다른 디렉터리에서 빌드할 것.',
    );
  }

  return {
    plugins: [react()],
    // 선내 PC 는 루트에서 서빙한다. EC2 시연판만 /kiosk/ 하위라 여기서 갈린다.
    //   VITE_BASE=/kiosk/ 로 빌드하면 asset 경로가 /kiosk/assets/... 가 된다.
    //   안 주면 /assets/... 를 찾다 404 — nginx 의 apps/web 쪽 /assets/ 블록과도 겹친다.
    // 환경 변수로 받는 이유: 선내판과 시연판이 같은 소스에서 나오는 다른 빌드다.
    base: env.VITE_BASE || '/',
    server: {
      // 이 포트가 그대로 CORS 허용 목록의 문자열이 된다.
      // strictPort 없이 5174 가 잡혀 있으면 vite 가 5175 로 조용히 옮겨가고,
      // 목록에 없는 origin 이 되어 요청이 전부 차단된다.
      port: 5174,
      strictPort: true,
      proxy: {
        // MQTT-over-WebSocket
        '/ws': { target: pi.replace(/^http/, 'ws'), ws: true },
        // fixture 모드에서만 해양 중계를 EC2 로 우회한다 (2026-09-18).
        //
        // `dev:fixture` 는 정의상 **Pi 없이 화면을 검증하는 모드**다(src/dev/fixture.ts).
        // 그런데 해양값은 `piUrl()` 을 타 `/pi` → 선내망 Pi(8000)로 가고,
        // training 망 밖에서는 그게 안 닿아 수온·파고가 전부 "값 없음"으로 그려졌다.
        // 화면 작업을 그 모드로 하라고 위에 적어 놓고 정작 해양 패널은 못 보던 상태였다.
        //
        // EC2 는 kiosk 키 없이 답한다 — `/api/ocean/sources`·`/current` 200 확인(2026-09-18).
        // 키가 걸린 것은 **수집 해역 이동**뿐이고(api.md §1.1), 조회는 막히지 않는다.
        //
        // ⚠ 한계: 이 경로에는 Pi 중계가 붙이는 `fresh`·`cached_at` 이 없다.
        //    `relayFresh` 가 `null`(모름)로 남아 "캐시 · 인터넷 끊김" 알약이 안 뜬다 —
        //    <b>중계 신선도 표시는 fixture 로 검증되지 않는다.</b> 실제 Pi 에 붙어야 한다.
        //
        // `pnpm dev`(실제 모드)는 건드리지 않는다. 그쪽이 Pi 의 OceanProxy(60초 캐시·fresh)를
        // 계속 지나가야 "dev 에선 됐는데 선내판에서 안 된다" 가 안 생긴다.
        // 무조건 우회하고 싶으면 아래 조건을 지우면 된다.
        ...(mode === 'fixture'
          ? { '/pi/api/ocean': { target: cloud, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/pi/, '') } }
          : {}),
        // Pi 의 HTTP 중계 (2026-09-17 부활). 배포판은 Pi 가 페이지를 내려줘 같은 오리진이라
        // 프록시가 필요 없다 — dev 만 브라우저가 5174 하고만 대화하게 한다
        // ⚠ 위의 `/pi/api/ocean` 보다 뒤에 와야 한다. vite 는 먼저 걸리는 키를 쓴다
        '/pi': { target: piHttp, changeOrigin: true, rewrite: (p) => p.replace(/^\/pi/, '') },
        '/jetson': { target: jetson, changeOrigin: true, rewrite: (p) => p.replace(/^\/jetson/, '') },
        '/cloud': { target: cloud, changeOrigin: true, rewrite: (p) => p.replace(/^\/cloud/, '') },
      },
    },
    // dev 와 배포판이 같은 origin 을 쓰게 포트를 고정한다.
    // 기본값 4173 이면 Pi·EC2 양쪽 CORS 목록에 5174 와 4173 을 둘 다 넣어야 하고,
    // "dev 에선 됐는데 시연에서 막힌다" 가 나온다.
    preview: {
      port: 5174,
      strictPort: true,   // 포트가 잡혀 있으면 조용히 옮겨가지 말고 실패할 것
    },
  };
});

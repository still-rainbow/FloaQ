# FloaQ frontend

pnpm workspace 안에 React 앱 두 개와 공유 패키지가 있습니다.

| 경로 | 역할 |
| --- | --- |
| apps/web | JWT 로그인, 관제 지도, 선박·사고 검색과 기록 조회 |
| apps/kiosk | 선내 경보, 사고 진행, 장치 상태와 수동 명령 |
| packages/shared | 메시지 타입, 지도와 공용 UI |

```bash
pnpm install --frozen-lockfile
cp apps/web/.env.example apps/web/.env.local
pnpm --filter @floaq/kiosk dev:fixture
# 별도 터미널에서 관제 웹 실행
pnpm --filter @floaq/web dev
```

fixture는 장비 없이 합성 시나리오를 재생하는 모드입니다.
실제 모드에서는 Pi MQTT WebSocket(9001), Pi HTTP(8000), Jetson MJPEG(8080)를 사용합니다.
실장비의 주소가 다르면 `apps/kiosk/.env.example`을 `.env.local`로 복사해 설정합니다.
관제 웹은 로컬 서버 `http://localhost:8080`을 기본 대상으로 사용합니다.
VITE_ 환경변수는 브라우저 번들에 포함되므로 서버용 비밀키를 넣지 않습니다.

```bash
pnpm typecheck
pnpm build
pnpm --filter @floaq/kiosk check:mqtt
pnpm --filter @floaq/kiosk check:ocean
pnpm --filter @floaq/kiosk check:nav
pnpm --filter @floaq/kiosk check:chart
```

MQTT 명령·상태 변환은 `apps/kiosk/src/pi/`,
HTTP 중계는 `packages/shared/src/origins.ts`에서 확인합니다.

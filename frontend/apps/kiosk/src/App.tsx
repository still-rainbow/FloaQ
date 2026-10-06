/**
 * 서체를 self-host 한다. kiosk 는 인터넷 없이 전부 동작해야 하므로(§9.13)
 * CDN 서체를 쓸 수 없다 — 못 받으면 `tabular-nums` 가 빠져 숫자 자릿수가 흔들리고,
 * 카운트다운·좌표가 매 프레임 폭이 변한다. apps/web 은 인터넷 전제라 CDN 을 쓴다.
 */
// subset 을 korean·latin 으로 좁힌다. 전체를 넣으면 쓰지도 않는 키릴·그리스·베트남어
// @font-face 수백 개가 따라와 CSS 가 436KB 가 된다 (실측).
import '@fontsource/noto-sans-kr/korean-400.css';
import '@fontsource/noto-sans-kr/korean-500.css';
import '@fontsource/noto-sans-kr/korean-700.css';
import '@fontsource/noto-sans-kr/latin-400.css';
import '@fontsource/noto-sans-kr/latin-500.css';
import '@fontsource/noto-sans-kr/latin-700.css';
import '@fontsource/jua/korean-400.css';
import '@fontsource/jua/latin-400.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-700.css';

// 순서가 중요하다: leaflet → 토큰 → 화면. 토큰이 뒤에 와야 .leaflet-container 색을 우리 변수로 덮는다.
// ⚠ 이게 빠지면 타일이 절대 배치를 잃고 흩어진다 — 2026-09-13 화면 확인에서 잡혔다. apps/web 은 있었다
import 'leaflet/dist/leaflet.css';
import '@floaq/shared/tokens.css';
import './styles/kiosk.css';
// 관제 웹과 같은 모습으로 덮는 디자인 전용 층. kiosk.css 뒤에 와야 이긴다.
import './styles/web-look.css';
// 메인 키오스크만 해상 단말기형으로 재조립. 등록·통신·해양 상세 화면은 건드리지 않는다.
import './styles/terminal.css';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { KioskProvider } from './state/store';
import { HashSync } from './hooks/useRoute';
import { Kiosk } from './pages/Kiosk';
import { Comms } from './pages/Comms';
import { Ocean } from './pages/Ocean';
import { History } from './pages/History';
import { Register } from './pages/Register';
import { Splash } from './pages/Splash';
import { useShipRegistration } from './hooks/useShipRegistration';
import { isDemo, isFixture } from './state/store';
import { DEV_SHIP_ID } from './pi/topics';
import { useVessel } from './hooks/useVessel';

/**
 * `react-router` 의 `HashRouter` (2026-09-18 도입. 그 전에는 직접 만든 해시 라우팅).
 *
 *   #/         선내 단말
 *   #/ocean    해양 상황판
 *   #/comms    통신 확인
 *
 * 해시를 고른 이유와 `HashSync` 가 필요한 이유는 `hooks/useRoute.ts` 에 적었다.
 *
 * 라우터는 등록 관문·Provider 보다 바깥이다 — 관문 화면에서도 주소가 성립해야 하고,
 * `<Routes>` 가 Provider 안쪽이어야 통신 화면으로 갔다 와도 소켓이 끊기지 않는다.
 */
export default function App() {
  return (
    <HashRouter>
      <HashSync />
      <Shell />
    </HashRouter>
  );
}

function Shell() {
  const reg = useShipRegistration();
  const { vessel, save } = useVessel();

  // Pi 가 승인된 선박을 알려주면 단말 표시값도 맞춘다 — 두 곳이 다른 이름을 말하지 않게
  if (reg.shipId && reg.status?.name && vessel?.name !== reg.status.name) {
    save({ name: reg.status.name, regno: vessel?.regno ?? '', camH: '', launchOff: '' });
  }

  /**
   * 🔴 **가상 모드는 관문을 지나지 않는다.** Pi 가 없어서 등록할 곳이 없다 —
   * 관문을 세우면 EC2 공개 시연판이 등록 화면에서 영영 멈춘다. 화면 작업용 dev:fixture 도 같다.
   * 그래도 토픽은 있어야 하므로(가상도 같은 리듀서를 지난다) 개발 폴백을 쓴다.
   */
  const bypass = isFixture || isDemo;

  /*
    🔴 **Pi 에 못 붙은 것은 관문으로 막지 않는다** (2026-09-21).

    전에는 `reg.shipId` 가 없으면 무조건 관문이었다. 그래서 Pi 가 꺼져 있으면 화면 전체가
    "Pi 에 연결할 수 없습니다" 로 덮였고, 해도·해양 같은 Pi 와 무관한 화면까지 못 봤다.

    막을 이유가 있는 것과 없는 것을 가른다.

      Pi 가 답했고 등록·승인이 안 됐다   →  관문. **고칠 방법이 화면 안에 있다**(양식·대기)
      Pi 가 아예 안 답한다               →  통과. 고칠 곳은 배선이고 화면이 할 일이 없다

    통과시켜도 안전한 이유는 `shipId` 가 `null` 이기 때문이다 — 브로커에 아예 안 붙는다
    (`store.tsx` `enabled: !virtual && !!shipId`). 없는 배의 토픽을 구독하던
    2026-09-17 버그는 `ship-dev` 라는 **가짜 값**을 넣어서 난 것이지 `null` 때문이 아니다.

    상태는 상단이 말한다 — `pi-down` 배너(빨강)와 TopBar 의 `Pi 끊김` 칩.
    Pi 가 돌아오면 폴링이 `ACTIVE` 를 받아 그대로 붙는다. 사람이 누를 것이 없다.
  */
  if (!bypass && !reg.shipId) {
    // 첫 조회 전. 여기서 바로 화면을 띄우면 Pi 가 멀쩡한데도 등록 폼이 한 번 깜빡인다.
    // 진입 화면(demo-v2 의 스플래시)을 그대로 쓴다 — 맨 텍스트보다 이쪽이 원래 설계다
    if (!reg.checkedAt) return <Splash />;
    // Pi 가 답했다 = 등록·승인 문제다. 이건 화면에서 푼다
    if (reg.status) return <RegisterGate reg={reg} />;
  }

  return (
    <KioskProvider shipId={reg.shipId ?? (bypass ? DEV_SHIP_ID ?? 'ship-dev' : null)}>
      <Routes>
        <Route path="/" element={<Kiosk />} />
        <Route path="/ocean" element={<Ocean />} />
        <Route path="/history" element={<History />} />
        <Route path="/comms" element={<Comms />} />
        {/* 모르는 주소는 본 화면으로 되돌린다. 시연 중 오타가 빈 화면이 되면 안 된다 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </KioskProvider>
  );
}

/**
 * 등록 관문. 상태 다섯을 그대로 화면으로 옮긴다 (`ref/kiosk_시연.md` §4).
 *
 * `WAIT` 는 <b>기다리면 풀린다</b> — 관제 웹에서 사람이 누르고, 몇 분에서 몇 시간 걸린다.
 * `REJECTED` 는 <b>자동 재시도로 안 풀린다</b> — 사람이 고쳐서 다시 낸다. 둘을 같은 문구로 두면
 * 기다려도 안 되는 화면 앞에서 계속 기다린다.
 */
function RegisterGate({ reg }: { reg: ReturnType<typeof useShipRegistration> }) {
  const st = reg.status?.state;

  // 🔴 기다려도 안 풀린다. Pi 에 배는 있는데 ship_key 가 없고, **서버는 같은 키를 다시 주지 않는다**
  //    (IoT `enroll._check_approval`). 등록 화면을 띄워 봐야 Pi 가 409 로 막는다 —
  //    아래 '승인 대기' 와 같은 문구로 두면 풀리지 않을 화면 앞에서 계속 기다리게 된다.
  if (st === 'NO_KEY') {
    return (
      <div className="screen reg-wait">
        <h1>등록 정보 손상</h1>
        <p>선박은 등록됐지만 인증 키가 없습니다. 기다려도 복구되지 않습니다.</p>
        <p className="hint">Pi 의 선박 데이터를 초기화하고 다시 등록해야 합니다 — 관리자에게 문의하세요.</p>
        <p className="hint mono">
          상태 {st}
          {reg.status?.ship_id ? ` · ${reg.status.ship_id}` : ''}
        </p>
      </div>
    );
  }

  if (st === 'WAIT' || st === 'PENDING') {
    return (
      <div className="screen reg-wait">
        <h1>승인 대기</h1>
        <p>{reg.status?.name ? `${reg.status.name} · ` : ''}관제에서 승인하면 자동으로 시작합니다.</p>
        <p className="hint">
          {st === 'PENDING' ? '신청을 접수했습니다. 서버 등록을 기다리는 중입니다.'
            : '몇 분에서 몇 시간 걸릴 수 있습니다. 화면을 켜 둔 채로 두세요.'}
        </p>
        {/* 🔴 "안 바뀐다"를 구분할 수 있게 한다 — 기다리는 중인지, 물어보는 것 자체가 실패인지 */}
        <p className="hint mono">
          상태 {st}
          {reg.checkedAt && ` · ${reg.checkedAt.toTimeString().slice(0, 8)} 확인`}
          {reg.error ? ` · ${reg.error}` : ''}
        </p>
        <button className="btn btn-ghost" onClick={() => void reg.refresh()}>지금 확인</button>
      </div>
    );
  }

  return (
    <>
      {st === 'REJECTED' && (
        <p className="reg-rejected" role="alert">
          등록이 반려되었습니다{reg.status?.reason ? ` — ${reg.status.reason}` : ''}.
          내용을 고쳐 다시 신청하세요.
        </p>
      )}
      <Register
        busy={reg.busy}
        onSubmit={(f) => reg.register({
          name: f.name, registration_no: f.regno, mmsi: f.mmsi, has_buoy: f.hasBuoy,
        })} />
    </>
  );
}

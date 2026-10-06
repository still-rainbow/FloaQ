import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * 해시 라우팅. `react-router` 의 `HashRouter` 위에 얹은 얇은 층이다 (2026-09-18 전환).
 *
 *   #/         선내 단말 본 화면
 *   #/ocean    해양 상황판 (넓게 펼쳐 보는 화면)
 *   #/history  지난 사고 조회
 *   #/comms    통신 확인 (개발·점검용)
 *
 * 통신 화면을 본 화면 안의 탭이 아니라 별도 경로로 둔 이유:
 * 시연 중에 실수로 열리면 안 되고, 점검할 때는 주소만으로 바로 갈 수 있어야 한다.
 *
 * ⚠ **경로형(`BrowserRouter`)이 아니라 해시인 이유.** 이 번들이 서빙되는 자리가 셋이다 —
 *   선내는 Pi 가 `http://<pi>:8000/kiosk/` 로 내려주고(ref/kiosk_시연.md),
 *   공개 시연판은 `floaq.example.com` 루트, dev 는 5174 루트다.
 *   해시는 base 경로와 무관하고 서버 SPA fallback 도 필요 없다 —
 *   Pi 정적 서버에 fallback 이 있는지 확인되지 않았다. 경로형으로 가려면 Pi 쪽부터 확인해야 한다.
 *
 * `[route, go]` 모양을 유지하는 이유: 화면들이 이미 이 모양으로 부른다.
 * 라우트를 늘리는 곳은 `App.tsx` 의 `<Routes>` 하나다.
 */
export type Route = 'main' | 'ocean' | 'history' | 'comms';

const PATH: Record<Route, string> = {
  main: '/', ocean: '/ocean', history: '/history', comms: '/comms',
};

/** 경로 → 화면 이름. 모르는 경로는 본 화면으로 본다 (`<Routes>` 의 `*` 와 같은 판단) */
export const toRoute = (pathname: string): Route => {
  const seg = pathname.replace(/^\/+/, '').split('/')[0];
  // ⚠ 여기 없는 값은 조용히 본 화면이 된다. 라우트를 늘리면 이 줄도 고칠 것
  return seg === 'comms' || seg === 'ocean' || seg === 'history' ? seg : 'main';
};

export function useRoute(): [Route, (r: Route) => void] {
  const loc = useLocation();
  const navigate = useNavigate();
  return [toRoute(loc.pathname), (r: Route) => navigate(PATH[r])];
}

/**
 * 주소창에서 해시만 고쳐 들어오는 경우를 라우터에 이어 준다.
 *
 * 🔴 **react-router 7 의 hash history 는 `popstate` 만 듣는다** (7.18.4 dist 에 `hashchange`
 *    문자열이 아예 없다 — 확인함). 그런데 주소창에서 `#/comms` 로 고쳐 Enter 를 치거나
 *    `location.hash = …` 로 옮기면 브라우저는 `hashchange` 만 쏜다 →
 *    주소는 바뀌는데 화면이 그대로다. 점검 동선이 조용히 죽는 종류의 함정이다.
 *
 * 루프는 나지 않는다 — `navigate()` 는 `pushState` 라 `hashchange` 를 쏘지 않고,
 * 폴백으로 `location.assign` 이 돌더라도 목적지가 같아 아래 비교에서 걸러진다.
 */
export function HashSync() {
  const loc = useLocation();
  const navigate = useNavigate();
  const current = `${loc.pathname}${loc.search}`;

  useEffect(() => {
    const onHash = () => {
      const next = location.hash.replace(/^#/, '') || '/';
      if (next !== current) navigate(next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [current, navigate]);

  return null;
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FloaqMapApi } from '@floaq/shared';
import { TopBar } from './layout/TopBar';
import type { View } from './layout/TopBar';
import { SettingsSheet } from './layout/SettingsSheet';
import { VesselListPane } from './panels/VesselListPane';
import { MapPane } from './panels/MapPane';
import { DetailPane } from './panels/DetailPane';
import { CloseReport } from './components/CloseReport';
import { ReportAlert } from './components/ReportAlert';
import { StageBoard } from './components/StageBoard';
import { SuperAdmin } from './pages/SuperAdmin';
import { SearchMode } from './pages/SearchMode';
import { AuthGate } from './pages/AuthGate';
import { FOUND_LABEL } from './lib/stages';
import { useLook } from './hooks/useLook';
import { ackIncident, closeIncident, fetchIncidentBuoy, fetchIncidentDetail, fetchIncidents, keepDetail, rescueIncident, withBuoy } from './lib/api/accidents';
import { byVessel, mergeFleet } from './lib/fleet';
import { VIEW_KEY, forgetSticky, readSticky, useSticky } from './lib/sticky';
import { shipRequests } from './lib/shipRequests';
import { tick } from './lib/live';
import { useSeaOf } from './lib/useSea';
import { byRecent, byUrgent, incidentsOf } from './lib/history';
import { secOfClock } from './lib/facts';
import { elapsed } from './lib/time';
import { AUTH_EXPIRED_EVENT, applications, currentSession, logout, refreshSession } from './lib/auth';
import type { Session } from './lib/auth';
import type { DetailTab, Incident } from './types';

// 웹 role 은 2종이다(계획.md §9.13).
//   OWNER 제거 — 선주가 보는 화면은 선내 단말이다. 웹에 또 만들면 같은 화면을 두 벌 유지한다.
//   COAST_GUARD 제거 — 웹에 들어오는 것은 시스템 운영자다.
//     실제 해경은 §9.4 의 조난 신호를 받는 쪽이지 이 웹의 로그인 사용자가 아니다.

const hms = (sec: number) => {
  const p = (n: number) => String(n).padStart(2, '0');
  const w = ((sec % 86400) + 86400) % 86400;
  return `${p(Math.floor(w / 3600))}:${p(Math.floor(w / 60) % 60)}:${p(w % 60)}`;
};

/**
 * 지금 몇 시인가. 화면이 찍는 시각은 전부 이 값이다.
 *
 * <p>전에는 <b>사고 자기 시계</b>(감지 시각 + 경과)를 썼다. 목데이터 시절에는 사고가
 * "12:03 에 났고 2시간 경과" 같은 고정값이라, 벽시계로 찍으면
 * {@code 구조대 대응 17:33 · 종료 12:03} 처럼 순서가 거꾸로 보였기 때문이다.</p>
 *
 * <p>🔴 <b>이제는 그 보정이 오히려 틀린다.</b> 사고가 서버에서 진짜 시각으로 들어오므로
 * 감지 시각도 지금 시각도 같은 시계 위에 있다. 사고 자기 시계를 쓰면 접수 시각이
 * 감지보다 이르게 찍혀({@code 20:41 감지 · 17:22 접수}) 단계 순서가 뒤집힌다(2026-09-19).</p>
 */
const nowOf = (_x?: Incident) => {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

/**
 * 서버에서 사고 목록을 다시 받는 주기(ms).
 *
 * <p>WebSocket(api.md §6 `ACCIDENT_REPORTED`)이 붙으면 이 폴링은 사라진다. 그때까지는
 * <b>새 신고가 들어온 것을 알 길이 이것뿐</b>이라 짧게 잡는다 — 목록 한 페이지라 가볍다.</p>
 */
const POLL_MS = 5000;

/** 사고 탭 · 기록 탭. 계정 관리는 사고를 안 들어 여기 없다 */
type TabKey = 'live' | 'log';

/** 한 탭이 들고 있는 것 전부 — 지도에 올린 사고들, 보고 있는 사고, 고른 배 */
interface TabState {
  picked: string[];
  incident: string | null;
  vessel: string | null;
}

/** 이 사고는 어느 탭 것인가. 상태 하나로 정해진다 */
const tabOf = (x: Incident): TabKey => (x.state === 'live' ? 'live' : 'log');

export default function App() {
  const { look, setUi, setTheme, setText } = useLook();
  /** 로그인한 계정. 없으면 관제 화면 대신 로그인 화면만 뜬다(WEB-01). 역할은 여기서만 온다. */
  const [session, setSession] = useState<Session | null>(currentSession);
  /**
   * 최상위 화면 — 사고 · 기록 · 계정 관리. 계정 관리는 관리자(SA)만 본다.
   *
   * <p>새로고침 전에 보던 탭이 있으면 그대로 연다({@link readView}). 없으면 사고 탭이고,
   * 로그인 직후에도 사고 탭이다(아래 첫 화면 효과).</p>
   */
  const [view, setView] = useSticky<View>(VIEW_KEY, ['live', 'log', 'accounts'], 'live');
  /** 새로고침으로 들어왔나. 그렇다면 아래 첫 화면 효과가 탭을 덮으면 안 된다 */
  const restored = useRef(readSticky(VIEW_KEY, ['live', 'log', 'accounts']) !== null);
  /**
   * 운영 관리자인가.
   *
   * <p><b>관리자는 사고를 보되 손대지 않는다</b>(2026-09-19 결정). 두 역할이 묻는 질문이 다르다 —
   * 해경은 "지금 누구를 먼저 구하러 가나", 관리자는 "감지가 얼마나 헛돌았나". 그래서 관리자에게는
   * 취소된 사고까지 보이지만(AccidentQueryService.scopeOf), 대응 동작은 전부 막는다.</p>
   *
   * <p>막는 이유가 예의가 아니라 <b>기록이다.</b> 관리자가 구경하려고 사고를 열었을 뿐인데
   * 접수 시각이 찍히면 종료 리포트에 "해경이 12:31 에 접수함"이 남는다 — 사실이 아니다.
   * 신고에서 접수까지 걸린 시간이 그 기록의 핵심인데 구경이 그것을 덮는다.</p>
   *
   * <p>관리자가 해경 화면을 그대로 보고 싶으면 <b>해경 계정으로 로그인</b>한다. 그때는 진짜
   * 해경으로서 행동한 것이라 기록이 참이 된다.</p>
   */
  const isAdmin = session?.role === 'superadmin';
  const canAccounts = isAdmin;
  // 해경이 주소를 손보거나 권한이 바뎀 수 있다. 계정 관리를 못 보면 사고 화면으로 돌린다
  const shown: View = view === 'accounts' && !canAccounts ? 'live' : view;
  /** 종결에 남는 이름 */
  const closer = session ? session.name : '관제 웹';
  /**
   * 🔴 <b>사고 탭과 기록 탭의 선택은 완전히 따로다</b>(2026-09-19).
   *
   * <p>전에는 `picked`·`selIncident`·`selVessel` 이 각각 하나씩이고, 볼 때마다 {@code inView()} 로
   * "지금 탭 것만" 걸러 썼다. 거르는 자리가 다섯 군데였고 <b>한 군데만 빠뜨려도 샜다</b> —
   * 탭을 오갈 때 선택만 되살리고 picked 를 안 건드려, 눈은 꺼졌는데 지도엔 떠 있었다.</p>
   *
   * <p>섞어 놓고 거르는 대신 <b>애초에 안 섞는다.</b> 탭마다 제 슬롯을 쓰므로
   * "사고 탭에 종결 건이 올라간다" 같은 상태가 만들어질 수 없다.</p>
   */
  const [tabs, setTabs] = useState<Record<TabKey, TabState>>({
    live: { picked: [], incident: null, vessel: null },
    log: { picked: [], incident: null, vessel: null },
  });
  const key: TabKey = view === 'log' ? 'log' : 'live';
  const here = tabs[key];
  const selIncident = here.incident;
  const selVessel = here.vessel;

  /** 한 탭만 고쳐 쓴다. 다른 탭은 건드리지 않는다 */
  const patchTab = useCallback((k: TabKey, fn: (t: TabState) => TabState) => {
    setTabs((prev) => ({ ...prev, [k]: fn(prev[k]) }));
  }, []);
  const setSelIncident = useCallback((id: string | null) => {
    patchTab(key, (t) => ({ ...t, incident: id }));
  }, [patchTab, key]);
  const setSelVessel = useCallback((id: string | null) => {
    patchTab(key, (t) => ({ ...t, vessel: id }));
  }, [patchTab, key]);
  const [tab, setTab] = useState<DetailTab>('ship');
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** 표류 슬라이더의 Δt(초). 지도와 좌표 표시가 같은 값을 봐야 해서 여기 둔다. */
  const [dt, setDt] = useState(0);
  /** 수색 모드 — 출동한 구조정이 보는 화면. 관제 화면을 덮는다. */
  const [searchOpen, setSearchOpen] = useState(false);
  /**
   * 지도에 함께 띄운 사고들. 포커스(selIncident)와 별개다.
   *
   * <p>처음 들어오면 <b>진행 중인 사고가 전부 올라가 있다.</b> 관제가 화면을 켜고 제일 먼저
   * 묻는 것은 "지금 바다에 뭐가 있나"인데, 빈 지도로 시작하면 그 답을 손으로 켜서 만들어야 했다.
   * 켠 뒤에 내리는 것(전부 해제)은 한 번이면 되지만, 하나씩 올리는 것은 건수만큼 걸린다.</p>
   */
  const picked = here.picked;
  /** 첫 목록이 올 때 진행 중을 전부 올렸는가. 폴링마다 다시 올리면 사용자가 내린 것이 되살아난다 */
  const pickedOnce = useRef(false);
  /** 이미 본 사고 id. 폴링에서 처음 보는 진행 중 사고가 곧 '새 신고'다 */
  const seenRef = useRef<Set<string>>(new Set());
  /** 사고 목록을 한 번이라도 받았나. 첫 적재에는 경광등을 띄우지 않는다 — 켜자마자 있던 사고가 다 '새 신고'일 수는 없다 */
  const feedLoaded = useRef(false);
  /** 카드를 누를 때마다 오른다. 같은 사고를 다시 눌러도 지도가 그 위치로 돌아오게 하는 신호다. */
  const [focusTick, setFocusTick] = useState(0);

  /**
   * 사고 배열. <b>서버에서 받는다</b> — 하드코딩 목데이터(mock/data.ts `INCIDENTS`)를 걷어낸 자리다(2026-09-18).
   *
   * <p>App 이 들고 있는 이유는 해경 접수 확인이 목록과 상세 양쪽에 동시에 보여야 해서다.</p>
   */
  const [incidents, setIncidents] = useState<Incident[]>([]);
  /** 아직 한 번도 못 받았나. 빈 목록과 '못 불러옴'은 화면에서 다른 말이어야 한다 */
  const [loaded, setLoaded] = useState(false);

  /** 이 화면에서 종결한 사고. 중복 종결 가드가 여기 대응한다(§9.20). */
  const [resolvedBy, setResolvedBy] = useState<Record<string, string>>({});
  /** 종료 리포트(신규 5) — 종결 직후 한 번 띄운다. */
  const [report, setReport] = useState<Incident | null>(null);
  /** 방금 들어온 신고. 띄우고 닫으면 그 사고 화면이 이미 열려 있다 */
  const [alert, setAlert] = useState<Incident | null>(null);
  /**
   * 종결·발견을 서버에 <b>못 남겼을 때</b> 띄우는 한 줄.
   *
   * <p>전에는 실패해도 아무 말이 없었다. 화면은 누르는 순간 '종결'로 바뀌는데, 5초 뒤 폴링이
   * 서버의 '진행 중'을 가져오면 <b>조용히 되돌아갔다</b> — 누른 사람은 끝낸 줄 알고 다른 일을
   * 보다가 사고가 되살아난 것을 나중에 본다(2026-09-21).</p>
   */
  const [saveFail, setSaveFail] = useState<string | null>(null);

  const mapApi = useRef<FloaqMapApi | null>(null);

  // 새로고침 직후 저장해 둔 로그인이 아직 유효한지 서버에 한 번 묻는다.
  // 첫 화면은 저장해 둔 값으로 바로 그리고(로그인 화면이 번쩍이지 않게), 비활성화된 계정이면 여기서 끊긴다.
  useEffect(() => {
    if (!currentSession()) return;
    let alive = true;
    refreshSession().then((s) => { if (alive) setSession(s); });
    return () => { alive = false; };
  }, []);

  // 요청 중에 토큰이 만료·무효로 판정되면(401) 어느 화면에서든 로그인 화면으로 돌아간다(lib/auth.ts authFetch)
  useEffect(() => {
    const onExpired = () => setSession(null);
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, []);

  // 관제 화면을 숨겼다 되돌리면 지도 크기가 어긋난다.
  // 언마운트하지 않고 hidden 으로 두는 이유는 지도를 다시 만들면 타일 캐시가 통째로 날아가서다.
  useEffect(() => {
    if (shown !== 'accounts') {
      const id = window.setTimeout(() => mapApi.current?.invalidate(), 0);
      return () => window.clearTimeout(id);
    }
    return;
  }, [shown]);

  // 사고를 바꾸면 Δt 를 0 으로 돌린다. 다른 사고에서 끌어 둔 시간이 남아 있으면 안 된다.
  useEffect(() => { setDt(0); }, [selIncident]);

  /** 사고 지점의 실제 조류·바람. 실측 부표를 흘리는 입력이다(lib/live.ts) */
  const seaOf = useSeaOf(incidents);
  const seaRef = useRef(seaOf);
  useEffect(() => { seaRef.current = seaOf; }, [seaOf]);

  /**
   * 사고 목록을 서버에서 받아 온다. 로그인한 뒤에만 돌고, {@link POLL_MS} 마다 다시 묻는다.
   *
   * <p>못 받으면 <b>가진 목록을 그대로 둔다.</b> 빈 배열로 덮으면 서버가 잠깐 끊긴 사이
   * 화면에서 사고가 통째로 사라진다 — 관제 화면에서 제일 나쁜 실패다.</p>
   */
  useEffect(() => {
    if (!session) return;
    let alive = true;

    const load = async () => {
      const feed = await fetchIncidents();
      if (!alive || !feed) return;
      mergeFleet(feed.vessels.map((v) => ({
        id: v.id, name: v.name, reg: v.reg, dev: '', devWarn: 0 as const,
      })));
      /*
       * 처음 보는 진행 중 사고가 있으면 경광등을 띄운다. 목록에 카드를 한 장 더하는 것만으로는
       * 부족하다 — 다른 사고를 보고 있으면 눈이 그쪽에 있다(components/ReportAlert.tsx).
       * 첫 적재 때는 띄우지 않는다. 화면을 켜자마자 있던 사고 전부가 '새 신고'일 수는 없다.
       */
      const fresh = feed.incidents.filter((x) => x.state === 'live' && !seenRef.current.has(x.id));
      /*
       * 🔴 "처음 받았나"를 <b>본 사고 수로 가르지 않는다.</b> 전에는 {@code seenRef.size === 0} 이었는데,
       * 목록이 텅 빈 채로 시작하면 본 사고가 계속 0 이라 <b>다음에 들어온 첫 신고도 '처음'으로</b>
       * 취급돼 경광등이 안 떴다 — 깨끗한 DB 로 시연을 시작하면 첫 신고가 조용히 지나갔다(2026-09-21).
       * 받았는지는 받았다는 사실로만 센다.
       */
      const first = !feedLoaded.current;
      feedLoaded.current = true;
      for (const x of feed.incidents) seenRef.current.add(x.id);
      // 경광등은 <b>대응할 사람</b>에게만 뜻이 있다. 누를 버튼이 없는 화면을 덮으면
      // 알림을 끄는 습관만 생기고, 그러면 정작 해경 계정에서도 무시하게 된다
      if (!first && fresh[0] && !isAdmin) {
        setView('live');
        setAlert(fresh[0]);
      }

      // 목록에는 부표·궤적·경위·접수가 없다. 갖고 있던 상세를 남기고 아는 것만 갈아 끼운다
      setIncidents((prev) => {
        const had = new Map(prev.map((x) => [x.id, x]));
        return feed.incidents.map((x) => keepDetail(had.get(x.id), x));
      });
      setLoaded(true);
      // 처음 한 번만 진행 중을 전부 지도에 올린다. 폴링마다 하면 내려 둔 것이 되살아난다
      if (!pickedOnce.current) {
        pickedOnce.current = true;
        const live = feed.incidents.filter((x) => x.state === 'live').map((x) => x.id);
        patchTab('live', (t) => ({ ...t, picked: live }));
      }
    };

    load();
    const t = window.setInterval(load, POLL_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, [session]);

  /**
   * 등록 선박. 사고에 딸려 오는 배는 <b>사고가 난 배뿐</b>이라, 기록 → 등록 선박 목록은
   * 선박 API 에서 따로 받아야 한다. 관리자만 볼 수 있는 경로라 실패해도 조용히 넘긴다 —
   * 해경 계정은 사고에 나온 배 이름만 보면 된다.
   */
  useEffect(() => {
    if (!session) return;
    let alive = true;
    shipRequests().then((r) => {
      if (!alive || !r.ok) return;
      // 승인된 배만 등록 선박이다. 대기·반려 건은 계정 관리 화면의 일이다
      mergeFleet(r.list.filter((v) => v.status === 'approved').map((v) => ({
        id: v.id,
        name: v.name,
        reg: v.regNo,
        // 감지 장치 상태는 서버가 아직 안 준다. 빈 값이면 화면이 그 줄을 비운다
        dev: '',
        devWarn: 0 as const,
      })));
    });
    return () => { alive = false; };
  }, [session]);

  /**
   * 진행 중 사고를 1초마다 흘려보낸다 — 경과가 흐르고, 두절 중인 부표는 추정 위치가 움직인다.
   *
   * <p>서버는 {@link POLL_MS} 마다만 답한다. 그 사이를 이 tick 이 메운다 —
   * 경과 시각이 5초씩 튀면 "실시간으로 보고 있다"가 아니라 "가끔 갱신된다"로 읽힌다.
   * 다음 폴링이 오면 서버 값이 이 추정을 덮는다(lib/live.ts).</p>
   */
  useEffect(() => {
    const t = window.setInterval(() => setIncidents((prev) => prev.map((x) => (
      x.state === 'live' ? tick(x) : x
    ))), 1000);
    return () => window.clearInterval(t);
  }, []);

  /**
   * 지도에 함께 올린 사고의 <b>부표만</b> 따로 받는다 — 요청 둘씩(lib/api/accidents.ts).
   *
   * <p>목록에 부표가 없어서, 전에는 보고 있는 사고 하나만 부표·궤적이 그려지고 나머지는
   * 배 마커만 떴다. 지도에 여러 건을 올리는 이유가 "지금 바다에 뭐가 있나"인데 그 답이
   * 반쪽이었다(2026-09-18).</p>
   *
   * <p>보고 있는 사고는 아래 상세 요청이 더 많은 것을 가져오므로 여기서 뺀다.</p>
   */
  const pickedKey = picked.join(',');
  useEffect(() => {
    if (!session) return;
    let alive = true;
    const ids = pickedKey ? pickedKey.split(',').filter((id) => id !== selIncident) : [];
    if (!ids.length) return;

    const load = async () => {
      const got = await Promise.all(ids.map(async (id) => [id, await fetchIncidentBuoy(id)] as const));
      if (!alive) return;
      setIncidents((prev) => prev.map((x) => {
        const hit = got.find(([id]) => id === x.id);
        return hit && hit[1] ? withBuoy(x, hit[1]) : x;
      }));
    };

    load();
    const t = window.setInterval(load, POLL_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, [session, pickedKey, selIncident]);

  /**
   * 보고 있는 사고의 상세를 따로 받는다 — 목록에는 부표·궤적·경위가 없다.
   * 목록 폴링과 주기를 맞춰 둘이 어긋나지 않게 한다.
   */
  useEffect(() => {
    if (!session || !selIncident) return;
    let alive = true;
    const load = async () => {
      const full = await fetchIncidentDetail(selIncident);
      if (!alive || !full) return;
      /*
       * 🔴 상세도 <b>통째로 갈아 끼우면 안 된다.</b> 해경 접수는 웹이 먼저 화면에 찍고 서버로 보내는데(아래 ack),
       *   그 사이에 5초마다 오는 `ack: null` 이 그걸 지웠다 —
       *   단계 바가 `구조대 대응` ↔ `탐지 · 부표 발사` 로 깜빡였다(2026-09-18).
       *   서버가 값을 주면 그쪽이 이긴다(keepDetail 이 그렇게 고른다).
       */
      setIncidents((prev) => prev.map((x) => (x.id === full.id ? keepDetail(x, full) : x)));
    };
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, [session, selIncident]);

  const byIncident = useMemo(
    () => Object.fromEntries(incidents.map((x) => [x.id, x])) as Record<string, Incident>,
    [incidents],
  );

  /**
   * 🔴 <b>탭이 어긋난 선택을 걷어낸다.</b> 슬롯을 나눠도 사고의 상태는 나중에 바뀐다 —
   * 선내에서 종결하거나 취소하면 진행 중이던 사고가 기록 것이 된다. 그대로 두면
   * 사고 탭 지도에 종결된 사고가 남는다.
   *
   * <p>거르는 자리를 다섯 군데 두는 대신 <b>여기 한 곳에서만</b> 맞춘다.
   * 목록이 새로 올 때마다 돌고, 맞을 때는 상태를 건드리지 않아 렌더가 늘지 않는다.</p>
   */
  useEffect(() => {
    if (!incidents.length) return;
    setTabs((prev) => {
      let moved = false;
      const next = { ...prev };
      for (const k of ['live', 'log'] as TabKey[]) {
        const t = prev[k];
        const okId = (id: string) => { const x = byIncident[id]; return !!x && tabOf(x) === k; };
        const picked = t.picked.filter(okId);
        const incident = t.incident && okId(t.incident) ? t.incident : null;
        const vessel = incident ? t.vessel : (t.incident ? null : t.vessel);
        if (picked.length === t.picked.length && incident === t.incident && vessel === t.vessel) continue;
        next[k] = { picked, incident, vessel };
        moved = true;
      }
      return moved ? next : prev;
    });
    // byIncident 는 incidents 에서 나온다 — 목록이 바뀔 때만 돌면 된다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents]);


  /*
   * 🔴 <b>지도는 보고 있는 탭의 것만 띄운다.</b>
   *
   * <p>지도가 답하는 질문은 "지금 바다에 뭐가 있나"이다. 끝난 사고의 마지막 자리가
   * 진행 중 사고와 <b>같은 주황 부표·같은 빨간 삼각형</b>으로 섞여 있으면 그 답이 흐려진다 —
   * 마커에 "이건 9월 6일 것" 이라고 적혀 있지도 않다(2026-09-18).</p>
   *
   * <p>선택 자체는 버리지 않는다 — 탭마다 마지막에 보던 것을 기억해 두었다가 돌아오면 그대로 펼친다.</p>
   */
  /**
   * 함께 띄울 사고들. useMemo 가 없으면 매 렌더마다 새 배열이 되고,
   * 그때마다 지도 effect 가 다시 돌아 화면을 포커스 기준으로 되돌린다 —
   * '전체 보기'로 맞춰 놓은 축척이 타일 상태 변화 한 번에 풀려 버린다.
   *
   * <b>거를 것이 없다</b> — 이 탭의 picked 에는 이 탭 사고만 들어 있다.
   */
  const others = useMemo(
    () => incidents.filter((x) => picked.includes(x.id) && x.id !== selIncident),
    [incidents, picked, selIncident],
  );

  /** 상단 사고 탭 옆 숫자 · 기본 탭 결정에 둘 다 쓴다 */
  const liveCount = useMemo(() => incidents.filter((x) => x.state === 'live').length, [incidents]);

  /**
   * 계정 관리 탭 옆 숫자 — <b>손대야 할 신청</b>의 합(해경 가입 + 선박 등록).
   *
   * <p>사고 탭에는 진행 중 건수가 붙는데 계정 관리에는 없어서, 승인 기다리는 신청이 있어도
   * 탭을 열어 봐야만 알 수 있었다. 관제는 사고 탭에 머무는 화면이라 그쪽은 영영 안 열린다.</p>
   *
   * <p>세는 것은 <b>대기 중</b>뿐이다. 승인·반려한 건까지 세면 숫자가 줄지 않아,
   * 다 처리해도 배지가 남아 "아직 할 일이 있다"고 거짓말한다.</p>
   */
  const [pendingCount, setPendingCount] = useState(0);
  useEffect(() => {
    if (!session || !isAdmin) { setPendingCount(0); return; }
    let alive = true;
    const load = async () => {
      const [users, ships] = await Promise.all([applications(), shipRequests()]);
      if (!alive) return;
      const a = users.ok ? users.list.filter((u) => u.status === 'wait').length : 0;
      const b = ships.ok ? ships.list.filter((v) => v.status === 'wait').length : 0;
      setPendingCount(a + b);
    };
    load();
    // 승인은 관리자가 직접 누르는 일이라 사고처럼 급하지 않다. 사고 폴링과 같은 주기면 충분하다
    const t = window.setInterval(load, POLL_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, [session, isAdmin]);

  /** 이 탭이 보고 있는 사고. 탭마다 슬롯이 따로라 거를 것이 없다 */
  const incident = selIncident ? byIncident[selIncident] ?? null : null;

  /**
   * 오른쪽 패널에 설 배.
   *
   * <p>🔴 <b>사고 탭에서는 보고 있는 사고의 배만 서게 한다.</b> 그 탭에는 등록 선박 목록이
   * 없어 배를 따로 고를 길이 없다 — 그런데도 selVessel 이 남아 있으면 기록에서 보던 배가
   * 사고 탭 패널에 그대로 서 있게 된다(2026-09-18). 어떤 경로로 들어왔든 막는다.</p>
   *
   * <p>기록 탭은 다르다 — 거기서는 등록 선박을 눌러 사고 없이 배만 보는 것이 정상이다.</p>
   */
  /*
   * 규칙은 하나다 — <b>'보는 중' 칩이 붙은 것이 오른쪽에 뜨다.</b>
   * 칩은 selIncident 로 붙고, 보고 있는 탭에 없는 사고는 incident 가 null 이 된다.
   *
   * <p>예외는 하나 — 기록 · 등록 선박에서는 <b>사고 없이 배만</b> 골라 사고 이력을 본다.
   * 그때는 고른 사고 자체가 없다(selIncident === null). 사고를 골랐는데 그게 이 탭에서
   * 안 보이는 것이라면 배도 보여 주지 않는다 — 칩이 어디에도 안 붙어 있으니까(2026-09-18).</p>
   */
  const shipOf = incident ? incident.ship
    : (view === 'log' && !selIncident ? selVessel : null);
  const vessel = shipOf ? byVessel[shipOf] ?? null : null;

  /**
   * 탭 전환. <b>슬롯을 바꿔 읽을 뿐이다</b> — 저장도 복원도 없다.
   * 탭마다 제 선택을 늘 들고 있으므로 돌아오면 그대로 펼쳐진다.
   */
  function goView(v: View) {
    setView(v);
  }

  const patch = useCallback((id: string, fn: (x: Incident) => Incident) => {
    setIncidents((prev) => prev.map((x) => (x.id === id ? fn(x) : x)));
  }, []);

  /**
   * 사고 카드 클릭 하나로 두 가지를 한다.
   *   처음 누르면  → 지도를 그 사고로 옮기고(포커스) 표시 목록에도 넣는다
   *   보던 걸 또 누르면 → 지도에서 내린다
   * 선택 해제를 위한 별도 조작(체크박스·× 버튼)을 두지 않기 위한 규칙이다.
   */
  /**
   * 카드 본문 클릭.
   *   토글이 꺼져 있으면 → 켜면서 그 위치로 이동
   *   켜져 있으면        → 그 위치로 이동
   * 끄는 것은 토글로만 한다. 카드를 누르다 실수로 지도에서 내려가면 안 되기 때문이다.
   */
  function focusIncident(x: Incident) {
    /*
     * 🔴 <b>사고가 제 탭으로 들어간다.</b> 진행 중이면 사고 탭, 끝났으면 기록 탭 —
     * 올린 쪽이 아니라 <b>올린 것</b>이 탭을 정한다. 그래서 사고 탭에 종결 건이 얹히는 일이 없다.
     */
    const k = tabOf(x);
    setFocusTick((t) => t + 1);
    patchTab(k, (t) => ({
      picked: t.picked.includes(x.id) ? t.picked : [...t.picked, x.id],
      incident: x.id,
      vessel: x.ship,
    }));
    setTab('incident');
    setView(k);
  }


  /**
   * 화면을 열면 **가장 급한 사고를 자동으로 열어 둔다.**
   *
   * <p>전에는 로그인 직후 지도도 오른쪽 패널도 비어 있었다. 진행 중인 사고가 여러 건인데
   * 지도가 비어 있으니 <b>고장으로 읽힌다</b> — 카드를 눌러야 시작된다는 안내는
   * 오른쪽 구석의 작은 회색 글씨 한 줄뿐이었다(2026-09-17).</p>
   *
   * <p>관제사가 화면을 여는 이유가 그거다. 목록의 맨 위와 같은 기준(byUrgent)을 써
   * 열린 사고와 맨 위 카드가 어긋나지 않게 한다.</p>
   *
   * ⚠ 한 번만 한다. 사고가 늘거나 시계가 흘러 순서가 바뀔 때마다 화면이 뛰어다니면
   *   보던 사고를 뺏긴다 — 그쪽이 더 나쁘다.
   */
  /** 누구로 로그인했을 때 열었는지. 로그아웃 후 다시 들어오면 새로 연다 */
  const opened = useRef<string | null>(null);
  useEffect(() => {
    if (!session) { opened.current = null; return; }
    if (opened.current === session.id || selIncident) return;
    opened.current = session.id;
    /*
     * 첫 화면은 <b>누구든 사고 탭</b>이다. 전에는 관리자는 기록으로, 해경도 진행 중 사고가
     * 없으면 기록으로 열었는데 — 같은 제품을 두 사람이 다른 자리에서 시작하게 된다.
     * "지금 무슨 일이 벌어지고 있나"가 이 화면의 첫 질문이고, 그 답이 없다는 것도 답이다
     * (사고 탭의 빈 칸이 그렇게 말한다).
     */
    // 새로고침으로 돌아온 것이면 보던 탭을 그대로 둔다. 여기서 덮으면 F5 가 곧 '처음으로'가 된다
    if (!restored.current) setView('live');
    const first = incidents.filter((x) => x.state === 'live').sort(byUrgent)[0];
    if (first) focusIncident(first);
    // 들어온 직후 한 번만 여는 것이라 사고 목록의 매 변화를 따라가지 않는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, incidents.length]);

  /**
   * 전부 해제. 포커스한 사고는 늘 지도에 올라가 있으므로 포커스도 같이 내린다.
   * 선택만 비우면 지도에는 남아 있는데 카드는 꺼진 것으로 보여 서로 어긋난다.
   */
  /** 지금 보는 탭의 것만 내린다 — 사고 탭의 '전부 해제'가 기록의 선택까지 지우면 안 된다 */
  function clearPicks() {
    patchTab(key, () => ({ picked: [], incident: null, vessel: null }));
  }

  /**
   * 토글. 켜면 **카드를 누른 것과 똑같다** — 지도에 올리고, 그 사고로 포커스를 옮기고, 지도도 그리로 간다.
   * 켜는 방법에 따라 결과가 달라지면 같은 조작을 두 번 배워야 한다. 끄면 지도에서 내리고 포커스를 옆으로 넘긴다.
   * 왼쪽 목록·선박 카드·오른쪽 패널 카드와 사고 이력 — 어디의 스위치든 같다.
   */
  function togglePick(x: Incident) {
    if (!picked.includes(x.id)) {
      focusIncident(x);
      return;
    }
    unpick(x);
  }

  /**
   * 지도에서 내리기만 한다. 지도 위 목록의 × 가 쓴다.
   * 토글을 쓰지 않는 이유 — 선박을 골라 연 사고는 picked 에 없이 지도에 떠 있어서, 토글하면 오히려 올라간다.
   */
  /** 지도에서 내린다. 포커스였으면 같은 탭에 남은 것 중 마지막으로 넘긴다 */
  function unpick(x: Incident) {
    const k = tabOf(x);
    patchTab(k, (t) => {
      const rest = t.picked.filter((id) => id !== x.id);
      if (t.incident !== x.id) return { ...t, picked: rest };
      const next = rest[rest.length - 1] ?? null;
      return { picked: rest, incident: next, vessel: next ? byIncident[next]?.ship ?? null : null };
    });
  }

  /**
   * 선박 한 척을 지도에 올릴 때 켤 사고 — 한 건이면 그것, 여러 건이면 가장 최근 것.
   * 이미 그 배의 사고가 하나라도 켜져 있으면 null. 사용자가 골라 둔 것을 덮지 않는다.
   */
  function vesselPickOf(id: string): Incident | null {
    /*
     * 지도에 올릴 것은 <b>보고 있는 탭의 사고</b> 중에서 고른다. 전에는 그 배의
     * 제일 마지막 사고를 상태 상관없이 집어서, 기록 · 등록 선박에서 배를 골랐는데
     * 그 배의 <b>진행 중</b> 사고가 사고 탭 지도에 올라갔다(2026-09-18).
     */
    const hist = incidentsOf(incidents, id).filter((h) => tabOf(h) === key);
    if (!hist.length || hist.some((h) => picked.includes(h.id))) return null;
    return [...hist].sort(byRecent)[0]!;
  }

  /**
   * 기록 탭에서 고른 배에 <b>진행 중 사고</b>가 있으면 그 사고.
   *
   * <p>기록 지도에는 끝난 사고만 올라간다(위 vesselPickOf). 그래서 이런 배를 누르면 지도에
   * 아무것도 안 뜨고 오른쪽에 배 이름만 섰다(2026-09-21). 누르자마자 사고 탭으로 보내 봤더니
   * 누른 곳과 다른 탭이 열려 잘못 누른 것처럼 읽혔다. 그래서 기록에 그대로 두고, 빈 지도 자리에
   * 사고 탭으로 가는 버튼만 띄운다(MapPane liveHere). 넘어가는 것은 사용자가 고른다.</p>
   */
  /*
   * 지난 사고가 있는 배도 띄운다 — 그 배의 지난 사고가 지도에 떠 있어도 지금 사고 중이라는 건
   * 알아야 한다. 다른 배의 사고를 보는 중이면 띄우지 않는다(그 배의 일이 아니다).
   */
  const liveHere = useMemo(() => {
    if (view !== 'log' || !selVessel) return null;
    if (selIncident && byIncident[selIncident]?.ship !== selVessel) return null;
    return incidentsOf(incidents, selVessel).find((h) => h.state === 'live') ?? null;
  }, [view, selVessel, selIncident, incidents, byIncident]);

  /** 선박 카드의 지도 스위치. 꺼져 있으면 위 규칙으로 켜고, 켜져 있으면 그 배의 사고를 전부 내린다. */
  function toggleVesselPick(id: string) {
    const top = vesselPickOf(id);
    if (top) {
      // 켜면 선박 카드를 누른 것과 똑같다 — 사고 카드 스위치와 같은 규칙이다.
      selectVessel(id);
      return;
    }
    const mine = new Set(incidentsOf(incidents, id).map((h) => h.id));
    patchTab(key, (t) => {
      const rest = t.picked.filter((k) => !mine.has(k));
      if (!t.incident || !mine.has(t.incident)) return { ...t, picked: rest };
      const next = rest[rest.length - 1] ?? null;
      return { picked: rest, incident: next, vessel: next ? byIncident[next]?.ship ?? null : null };
    });
  }

  function selectVessel(id: string, wantTab?: 'incident') {
    /*
     * 고를 사고도 <b>보고 있는 탭의 것</b> 중에서만 고른다.
     *
     * <p>기록 · 등록 선박은 진행 중인 배도 목록에 넣는다. 그 배를 누를 때 상태를 안 보고
     * 마지막 사고를 집었더니, 기록 탭인데 <b>진행 중 사고</b>가 골려 그 사고는 기록 지도에
     * 올라가지도 못한 채 오른쪽 패널에 배 이름만 남았다(2026-09-18).</p>
     */
    const hist = incidentsOf(incidents, id).filter((h) => tabOf(h) === key);
    // 스위치가 꺼진 배를 누르면 바로 지도에 올린다(한 건이면 그것, 여러 건이면 가장 최근 것).
    // 누르면 지도에 뜨는데 스위치는 꺼진 채로 남으면 둘이 어긋나 보인다.
    const top = vesselPickOf(id);
    patchTab(key, (t) => ({
      ...t,
      picked: top && !t.picked.includes(top.id) ? [...t.picked, top.id] : t.picked,
      incident: hist.length === 1 ? hist[0]!.id : null,
      vessel: id,
    }));
    if (wantTab) setTab(wantTab);
    // 사고가 여러 건이면 사고 탭의 카드 목록부터 연다 — 건마다 지도 스위치가 거기 있다.
    // 선박 탭에 머물면 가장 최근 것만 켜진 채 나머지를 켤 길이 안 보인다.
    else if (!hist.length) setTab('ship');
  }

  /**
   * 해경 접수 확인(신규 3). W-03 진입이 트리거다 — ⚠ 결정 필요 4.
   * 이미 찍혀 있으면 덮지 않는다. 최초 열람 시각이 통계(신규 6)의 원재료라서다.
   */
  /**
   * 해경 접수 — <b>관제 목록에 뜨는 순간이 곰 접수다.</b>
   *
   * <p>전에는 그 사고를 열었을 때만 찍었다(W-03 진입). 그러면 열지 않은 사고는
   * 목록에 서 있으면서도 ② 구조 요청 단계로 남는다 — <b>신고가 관제에 닿았는데
   * 아직 안 닿은 것처럼</b> 보여 선내 단말의 선원에게도 그렇게 전해진다(2026-09-17).</p>
   *
   * <p>관제 웹은 신고된 사고만 본다(api.md §3.4). 목록에 있다 = 서버가 받았다 이므로
   * 접수는 여는 사람이 아니라 도착 자체가 정한다.</p>
   */
  const ack = useCallback((x: Incident) => {
    if (x.stages.ack.at) return;
    // 화면에 먼저 찍고 서버에 남긴다 — 다음 폴링이 서버 값으로 덮으며 둘이 맞는다.
    // 요청이 실패해도 화면은 접수로 두고, 다음 폴링에서 다시 보낸다(멱등이라 안전하다)
    patch(x.id, (p) => ({
      ...p,
      stages: { ...p.stages, ack: { at: nowOf(p), note: '관제 접수' } },
    }));
    ackIncident(x.id);
  }, [patch]);

  // 진행 중인 사고가 목록에 오르면 바로 접수로 찍는다. 새 신고도 들어오자마자 같이 찍힌다
  useEffect(() => {
    // 🔴 관리자는 찍지 않는다. 해경이 받은 것이 아닌데 리포트에 접수로 남으면 거짓이다
    if (isAdmin) return;
    incidents.filter((x) => x.state === 'live' && !x.stages.ack.at).forEach(ack);
  }, [incidents, ack]);

  /**
   * 영상 그만 받기 — 사고 후 구간을 종결 전에 끝낸다. 원래는 종결하거나 1시간이 지나야 끝난다.
   * ⚠ API 미정. 백엔드·Pi 에 해당 명령이 아직 없어 화면 상태만 바꾼다.
   */
  const stopVideo = useCallback((x: Incident) => {
    patch(x.id, (p) => (p.clip.stoppedAt ? p : { ...p, clip: { ...p.clip, stoppedAt: nowOf(p) } }));
  }, [patch]);

  /**
   * 사고자 발견 — 수색 모드에서 경비정이 입력한다(단계 ④).
   * 이미 찍혀 있으면(부표 잡음 등) 덮지 않는다. 최초 시각이 통계와 리포트의 원재료다.
   */
  const markFound = useCallback((x: Incident) => {
    // 화면을 먼저 바꾸고 서버에 보낸다 — 누른 사람이 기다릴 이유가 없다.
    // 못 보내면 다음 폴링에서 서버 값이 이기므로 화면이 조용히 되돌아간다(접수와 같은 방식)
    rescueIncident(x.id).then((ok) => {
      if (ok === null) {
        setSaveFail(`${byVessel[x.ship]?.name ?? '이 배'} 사고의 발견을 저장하지 못했습니다. 다시 눌러 주세요.`);
      }
    });
    patch(x.id, (p) => {
      if (p.stages.found.at) return p;
      const at = nowOf(p);
      const ev: Incident['timeline'][number] = ['resolve', at, FOUND_LABEL, '수색 모드에서 경비정이 입력'];
      return {
        ...p,
        stages: { ...p.stages, found: { at, note: '경비정 발견' } },
        timeline: [...p.timeline, ev],
      };
    });
  }, [patch]);

  // 중복 종결 가드 — kiosk·웹·1시간 타이머가 경합한다. 먼저 누른 쪽만 성립한다(§9.20).
  //   UPDATE incidents SET resolved_at=now(), resolved_by=?
  //   WHERE incident_id=? AND resolved_at IS NULL   -- 영향 행 0 이면 이미 종결
  function resolveIncident(x: Incident) {
    if (resolvedBy[x.id]) return;
    // 🔴 <b>서버에 남긴다.</b> 전에는 화면만 '완료'로 바뀌고 새로고침하면 사고가 되살아났다 —
    //    다른 관제사 화면에서는 처음부터 진행 중이었다(2026-09-21)
    // 누른 순간의 사고. 서버에 못 남기면 이 모습으로 곧바로 되돌린다
    const before = x;
    closeIncident(x.id).then((ok) => {
      if (ok !== null) return;
      // 5초 뒤 폴링을 기다리면 그동안 사고가 목록에서 사라져 있다 — 끝나지 않은 사고가 안 보이는 5초다
      patch(x.id, () => before);
      // 못 남겼다. 버튼을 다시 누를 수 있게 풀고, 무엇이 안 됐는지 말한다.
      // 종료 리포트도 거둔다 — 끝나지 않은 사고를 "몇 분 만에 종결"이라고 적은 채로 두면 안 된다
      setResolvedBy((prev) => { const n = { ...prev }; delete n[x.id]; return n; });
      setReport(null);
      setSaveFail(`${byVessel[x.ship]?.name ?? '이 배'} 사고의 종결을 저장하지 못했습니다. 다시 눌러 주세요.`);
    });
    const at = nowOf(x);
    setResolvedBy((prev) => ({ ...prev, [x.id]: closer }));
    patch(x.id, (p) => ({
      ...p,
      state: 'closed',
      // ⚠ 종결 시각을 사고에 찍지 않아 기록 화면의 결과가 "종결 · 12:03 → —" 로 비어 있었다.
      //   리포트 스냅샷에만 넣고 목록 쪽을 빠뜨렸던 것이다(2026-09-17).
      stages: { ...p.stages, close: { at, note: '관제 웹에서 종결' } },
      timeline: [...p.timeline, ['close', at, '사고 종결', `${closer} 처리`] as Incident['timeline'][number]],
      // 배지는 완료/취소 둘만 쓴다(2026-09-17). '종결'은 카드의 숨김 목록에 있어 아무것도 안 보였다
      badge: ['완료', 'resolved'],
      // 헤드를 그대로 두면 기록 목록에 "· 진행 중"이 남아 종결된 사고가 진행 중으로 읽힌다
      head: `${p.head.split(' · ')[0]} · ${elapsed(p.elapsedSec)} 만에 종결`,
      send: null,
    }));
    /*
     * 종결하면 <b>지도에서 내리고 선택도 놀아준다.</b> 사고 탭에서 지금 보이는 것은
     * 진행 중인 사고여야 하는데, 끝난 사고가 그대로 잡혀 있으면 다음에 봐야 할 사고가 아니라
     * 방금 끝난 사고를 가리킨 채로 생는다 — 기록 탭에서 다시 여는 것은 언제든 된다(2026-09-18).
     */
    patchTab('live', (t) => ({
      picked: t.picked.filter((k) => k !== x.id),
      incident: t.incident === x.id ? null : t.incident,
      vessel: t.incident === x.id ? null : t.vessel,
    }));

    // 종료 리포트는 스냅샷이다. 방금 찍은 종결 시각이 들어가도록 패치된 값을 만들어 넘긴다.
    setReport({
      ...x,
      state: 'closed',
      stages: { ...x.stages, close: { at, note: '관제 웹에서 종결' } },
    });
  }

  // 로그인 전에는 관제 화면을 아예 그리지 않는다. 훅은 모두 위에서 부른 뒤라 호출 순서가 흔들리지 않는다.
  if (!session) {
    return <AuthGate onLogin={(s) => { setSession(s); setView('live'); }} />;
  }

  const signOut = () => {
    logout();
    // 다음 사람이 앞사람이 보던 화면에서 시작하면 안 된다 — 한 대를 여럿이 쓰는 관제실이다
    forgetSticky();
    restored.current = false;
    // 다음 사람의 첫 적재는 다시 '처음'이다. 안 비우면 앞사람이 못 본 사고가 전부 새 신고로 뜬다
    seenRef.current = new Set();
    feedLoaded.current = false;
    setSession(null);
    setTabs({ live: { picked: [], incident: null, vessel: null },
              log: { picked: [], incident: null, vessel: null } });
    setSearchOpen(false);
    setReport(null);
  };

  return (
    <>
      <TopBar
        session={session}
        view={shown}
        onView={goView}
        canAccounts={canAccounts}
        liveCount={liveCount}
        pendingCount={pendingCount}
        onLogout={signOut}
        onSettings={() => setSettingsOpen(true)}
      />

      {/*
        사고를 보는 내내 붙어 있어야 하는 정보라 지도·상세보다 위, 전체 폭에 깐다.
        여러 건을 함께 띄웠을 때 어느 사고의 단계인지 헷갈릴 수 있어 **배 이름을 앞에 박는다** —
        숨기는 대신 누구 것인지 밝히는 쪽이 낫다. 포커스한 사고가 없으면 보여줄 것도 없다.
      */}
      {/*
        기록에는 단계 띠를 두지 않는다. 끝난 사고의 다섯 칸은 이미 다 채워져 있어 진행을 말하지 않고,
        같은 시각을 리포트의 '대응 단계'가 더 자세히 적는다 — 화면 위쪽만 차지했다(2026-09-18).
      */}
      {/*
        기록 탭에서는 띄를 두지 않는다. 다만 기록에서 고른 종결 사고를 든 채 사고 탭으로
        넘어오면 그 사고의 띄가 붙는다 — 그때 띄의 높이는 진행 중일 때와 <b>같아야 한다</b>.
        버튼 유무로 칸 높이가 바뀌면 사고를 갈아끼울 때마다 화면 전체가 위아래로 뛰다(web.css .stage-cell).
      */}
      {/*
        🔴 <b>단계 바는 두 탭에 다 선다.</b> 기록에서 빼 두었더니 탭을 바꿀 때 화면이 위로 떠서,
        바뀐 것을 "단계 바가 사라졌다"로 알아채야 했다 — 없는 것은 눈에 안 띈다.

        종결된 사고도 다섯 단계 시각이 한눈에 보이는 편이 낫다. 대신 <b>색이 다르다</b> —
        진행 중은 지금 칸이 빨강, 종결은 마지막 칸이 짙은 남색이다(web.css .stage-bar.is-log).
        같은 모양에 다른 색이라 탭이 바뀐 것이 그 자리에서 읽힌다(2026-09-19).
      */}
      {/* ⚠ 계정 관리에는 서지 않는다. 아래 .layout 은 숨기는데 이 줄에만 조건이 빠져 있어,
          계정 승인 화면 위에 남의 사고 단계가 떠 있었다 — 그 화면에 사고는 아무 상관이 없다 */}
      {incident && shown !== 'accounts' ? (
        <StageBoard
          x={incident}
          onFound={markFound}
          onResolve={resolveIncident}
          /* 색은 사고 상태가, 버튼 유무는 권한이 정한다 — 둘을 한 값으로 묶으면
             관리자가 볼 때 진행 중 사고가 종결된 색으로 뜬다(2026-09-19).

             ⚠ <b>지금 탭이 아니라 사고의 상태로 정한다.</b> 종결을 누르면 카드는 기록으로
             옮겨가지만 목록이 갱신될 때까지 몇 초 걸린다 — 그동안 탭 기준으로 그리면
             방금 끝낸 사고가 여전히 빨갛게 뛴다. resolvedBy 는 그 몇 초를 메운다 */
          kind={incident.state === 'live' && !resolvedBy[incident.id] ? 'live' : 'log'}
          readOnly={isAdmin}
        />
      ) : null}

      {saveFail ? (
        <div className="save-fail" role="alert">
          <span>{saveFail}</span>
          <button onClick={() => setSaveFail(null)}>닫기</button>
        </div>
      ) : null}

      <div className="layout" hidden={shown === 'accounts'}>
        <VesselListPane
          view={shown === 'log' ? 'log' : 'live'}
          incidents={incidents}
          selVessel={selVessel}
          selIncident={selIncident}
          picked={picked}
          onSelect={selectVessel}
          onFocusIncident={focusIncident}
          onTogglePick={togglePick}
          onToggleVessel={toggleVesselPick}
          onClearPicks={clearPicks}
        />
        <MapPane
          incident={incident}
          others={others}
          picked={picked}
          mode={shown === 'log' ? 'log' : 'live'}
          theme={look.theme}
          onApi={(api) => { mapApi.current = api; }}
          dt={dt}
          onDt={setDt}
          focusTick={focusTick}
          onFocusIncident={focusIncident}
          onOpenSearch={() => setSearchOpen(true)}
          readOnly={isAdmin}
          liveHere={liveHere}
        />
        <DetailPane
          vessel={vessel}
          incident={incident}
          history={selVessel ? incidentsOf(incidents, selVessel) : []}
          onPickIncident={focusIncident}
          picked={picked}
          onTogglePick={togglePick}
          tab={tab}
          onTab={setTab}
          resolvedBy={resolvedBy}
          onResolve={resolveIncident}
          onAck={ack}
          onStopVideo={stopVideo}
          onReport={setReport}
          readOnly={isAdmin}
          dt={dt}
        />
      </div>

      {shown === 'accounts' ? <SuperAdmin /> : null}

      <SettingsSheet
        open={settingsOpen}
        ui={look.ui}
        theme={look.theme}
        text={look.text}
        onUi={setUi}
        onText={setText}
        onTheme={setTheme}
        onClose={() => setSettingsOpen(false)}
      />

      {searchOpen && incident
        ? (
          <SearchMode
            x={incident}
            theme={look.theme}
            onClose={() => setSearchOpen(false)}
            onFound={markFound}
            // 종결하면 수색할 이유가 없다. 수색 모드를 닫고 종료 리포트를 띄운다.
            onResolve={(x) => { resolveIncident(x); setSearchOpen(false); }}
          />
        )
        : null}

      <ReportAlert x={alert} onClose={() => setAlert(null)} />
      <CloseReport x={report} closedBy={closer} onClose={() => setReport(null)} />
    </>
  );
}

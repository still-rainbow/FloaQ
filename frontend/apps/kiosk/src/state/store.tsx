import {
  createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState,
  type ReactNode,
} from 'react';
import { brokerUrl, makeDedupe, useFloaqMqtt } from '@floaq/shared';
import { clientIdFor, kioskWillFor, onlinePayload, subscriptionsFor, topicsFor } from '../pi/topics';
import { decode, resetFix } from '../pi/decode';
import { createCommandBus, type CommandBus } from '../pi/commands';
import { fixtureDurationMs, fixtureSnapshot, playFixture } from '../dev/fixture';
import { initialState, reducer, type Action, type KioskState } from './reducer';

/**
 * 입력이 하나다 — Pi 의 MQTT 브로커.
 *
 *   구독    ship/{id}/pi/#  ·  ship/{id}/jetson/#
 *   명령    ship/{id}/kiosk/command/*   → pi/command/response 로 성패가 온다
 *
 * **스냅샷 REST 가 없어졌다.** 접속하면 브로커가 retained 를 즉시 밀어 주므로
 * 현재 상태가 메시지 여러 개로 나뉘어 도착한다 (mqtt.md §2.4). 도착 순서는 보장되지 않지만
 * 리듀서가 필드별로 덮어쓰는 구조라 순서에 의존하지 않는다.
 *
 * fixture 모드면 브로커에 붙지 않고 녹화 메시지를 같은 리듀서에 흘린다.
 * 상태 라이브러리를 넣지 않는다 — 소비자가 한 트리이고 useReducer 로 충분하다.
 */

/** 가상(녹화 재생) ↔ 실제(Pi MQTT). 상단 Pi 칩으로 런타임에 바꾼다 */
interface Mode {
  virtual: boolean;
  setVirtual: (v: boolean) => void;
  /** 가상 모드에서 사고 시나리오가 도는 중인가 */
  playing: boolean;
  /** 사고 시나리오를 처음부터 재생. 가상이 아니면 아무것도 안 한다 */
  replay: () => void;
}

const StateCtx = createContext<KioskState>(initialState);
const ModeCtx = createContext<Mode>({
  virtual: false, setVirtual: () => {}, playing: false, replay: () => {},
});
const DispatchCtx = createContext<(a: Action) => void>(() => {});
const CommandCtx = createContext<CommandBus | null>(null);

/**
 * `vite --mode fixture` 면 Pi 에 붙지 않고 녹화 메시지를 재생한다. Pi 구현 전 화면 검증용.
 *
 * .env 파일을 쓰지 않는 이유: `.env.*` 는 .gitignore 대상이라 커밋되지 않는다 —
 * 팀원이 clone 하면 dev:fixture 가 조용히 일반 모드로 돈다.
 */
export const isFixture = import.meta.env.MODE === 'fixture';

/**
 * EC2 시연판(`VITE_DEMO=1`). 가상에 고정하고 Pi 칩을 숨긴다.
 *
 * 공개 URL 이라 방문자가 '실제' 로 바꿀 수 있으면 안 된다 —
 * HTTPS 페이지에서 `ws://<Pi>` 는 브라우저가 mixed content 로 막고,
 * 그 선택이 localStorage 에 남아 다음 방문에도 두절 화면으로 들어온다.
 * 선내 PC 배포판은 이 값을 주지 않으므로 아래 전환이 그대로 살아 있다.
 */
export const isDemo = import.meta.env.VITE_DEMO === '1';

/**
 * 발표용 화면(`?present`). 가상임을 알리는 칩들을 <b>숨긴다</b> — 실제 단말처럼 보이게.
 *
 * <p>빌드 플래그가 아니라 <b>주소</b>인 이유: 공개 URL 의 기본 화면은 정직해야 한다.
 * 그냥 들어온 방문자에게는 `Pi 가상` 이 그대로 보이고, 발표자만 쿼리를 붙여 깨끗한 화면을 쓴다.
 * 빌드로 가르면 시연판 전체가 "가상인데 가상이라고 안 하는" 페이지가 된다.</p>
 *
 * <p>칩을 <b>가짜 '연결됨' 으로 바꾸지 않고 숨기는</b> 이유: 붙지도 않은 브로커를 붙었다고
 * 표시하는 건 화면이 거짓말을 하는 것이다. 빼는 것과 없는 말을 지어내는 것은 다르다.</p>
 *
 * <p><b>둘 다 받는다.</b> 이 앱은 해시 라우팅이라 `#/?present` 로 적기 쉬운데, 그쪽만 보면
 * `?present#/` 가 안 먹고 그 반대도 안 먹는다 — 발표 직전에 안 켜지는 종류의 함정이다.
 * 다만 화면 이동(`location.hash = '#/ocean'`)이 해시 쿼리를 지우므로
 * <b>오래 가는 쪽은 `?present`</b> 다.</p>
 */
export const isPresent = (() => {
  const inHash = location.hash.split('?')[1] ?? '';
  return new URLSearchParams(location.search).has('present')
      || new URLSearchParams(inHash).has('present');
})();

/**
 * 가상/실제는 빌드 모드가 아니라 단말 설정이다. 기본값만 빌드 모드(dev:fixture)가 정한다.
 * 저장해 두는 이유: 새로고침마다 되돌아가면 "실제 Pi 로 테스트 중"인 사람이 매번 다시 누른다.
 */
const VIRTUAL_KEY = 'floaq.kiosk.virtual';
function readVirtual(): boolean {
  // 시연판은 저장값을 읽지 않는다. 플래그가 생기기 전에 '실제' 로 눌러 둔 방문자가
  // 계속 두절 화면으로 들어오는 것을 막는다.
  if (isDemo) return true;
  try {
    const v = localStorage.getItem(VIRTUAL_KEY);
    return v == null ? isFixture : v === '1';
  } catch {
    return isFixture;
  }
}

/**
 * @param shipId 등록으로 받은 선박 식별자. <b>없으면 브로커에 붙지 않는다</b> —
 *               토픽 경로가 성립하지 않아 `'ship-unset'` 으로 쏘면 아무 말 없이 다른 방에 말하게 된다
 *               (`ref/kiosk_시연.md` §9 "아무것도 안 옴. 에러도 없음").
 *
 * ⚠ <b>`null` 이 정상 경로다</b> (2026-09-21). Pi 에 못 붙어 `ship_id` 를 모르면 `App` 이
 *   그대로 `null` 을 넘긴다 — 화면은 뜨고 브로커만 안 붙는다. 상단 `pi-down` 배너가 그 상태를 말한다.
 */
export function KioskProvider({ children, shipId }: { children: ReactNode; shipId: string | null }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  /**
   * QoS 1 은 at-least-once 라 같은 메시지가 두 번 온다 (mqtt.md §3.3).
   * retained 에는 적용하지 않는다 — 재접속마다 같은 request_id 로 다시 오는 게 정상이다.
   */
  const seen = useRef(makeDedupe(100));

  /**
   * publish 는 매 렌더 새 함수지만 내부적으로 같은 연결을 가리킨다.
   * ref 로 감싸서 명령 버스를 한 번만 만든다 — 버스가 재생성되면
   * 응답을 기다리던 약속(pending)이 통째로 사라진다.
   */
  const publishRef = useRef<(t: string, p: string, o?: { qos?: 0 | 1; retain?: boolean }) => boolean>(
    () => false,
  );
  /** 토픽 한 벌. shipId 가 바뀌면 다시 만든다 — 등록 직후가 그 순간이다 */
  const topics = useMemo(() => (shipId ? topicsFor(shipId) : null), [shipId]);
  // ref 로 읽는다 — 버스는 한 번만 만들고(재생성하면 대기 중인 약속이 사라진다) 토픽만 갈아 끼운다
  const topicsRef = useRef(topics);
  topicsRef.current = topics;

  const bus = useMemo(
    () => createCommandBus((t, p, o) => publishRef.current(t, p, o), () => topicsRef.current),
    [],
  );

  const [virtual, setVirtualState] = useState<boolean>(readVirtual);
  const setVirtual = useCallback((v: boolean) => {
    if (isDemo) return;   // 시연판은 전환 자체가 없다. 칩도 숨기지만 호출 경로를 여기서 한 번 더 막는다
    try { localStorage.setItem(VIRTUAL_KEY, v ? '1' : '0'); } catch { /* 저장 못 해도 이번 세션은 돈다 */ }
    setVirtualState(v);
  }, []);

  /**
   * 사고 시나리오는 상단 `재생` 버튼으로만 시작한다. 들어가자마자 돌리지 않는다 —
   * 해양 패널처럼 사고와 무관한 화면을 볼 때 3초 뒤 경보가 덮는 것이 방해가 된다.
   * 이전엔 `?quiet` 로 끄는 방식이었는데, 기본이 조용한 쪽이 맞다.
   */
  const [playing, setPlaying] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);

  const stopPlayback = useCallback(() => {
    stopRef.current?.();
    stopRef.current = null;
    setPlaying(false);
  }, []);

  const replay = useCallback(() => {
    if (!virtual) return;   // 실제 Pi 연결 중에 녹화 사고를 흘리면 진짜 경보처럼 보인다
    stopPlayback();
    // 스냅샷을 다시 넣어 사고·부표를 비운다 — 옛 사고 위에 새 감지가 겹치지 않게
    dispatch({ kind: 'SNAPSHOT', snapshot: fixtureSnapshot(), receivedAt: Date.now() });
    const stop = playFixture((msg) => dispatch({ kind: 'MESSAGE', msg }));
    // 마지막 스텝 뒤에 재생 표시를 끈다. 화면의 사고 상태는 그대로 남는다
    const done = setTimeout(() => { stopRef.current = null; setPlaying(false); }, fixtureDurationMs);
    stopRef.current = () => { stop(); clearTimeout(done); };
    setPlaying(true);
  }, [virtual, stopPlayback]);

  /**
   * 발표 화면은 `사고 재생` 버튼이 숨겨져 있어 누를 것이 없다. `R` 로 연다.
   *
   * 들어가자마자 자동 재생하지 않는다 — 발표자가 말할 준비가 되기 전에 경보가 뜨면
   * 그 뒤를 설명으로 따라가야 한다. 시작 시점은 사람이 쥐는 게 맞다.
   */
  useEffect(() => {
    if (!isPresent) return;
    const onKey = (e: KeyboardEvent) => {
      // 입력 중에는 무시. 지금은 입력이 선박 등록뿐이지만 늘어난다
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (e.key === 'r' || e.key === 'R') replay();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [replay]);

  const mode = useMemo<Mode>(
    () => ({ virtual, setVirtual, playing, replay }),
    [virtual, setVirtual, playing, replay]);

  const { link, publish } = useFloaqMqtt({
    url: brokerUrl(),
    clientId: clientIdFor(shipId ?? 'unset'),
    topics: shipId ? subscriptionsFor(shipId) : [],
    will: kioskWillFor(shipId ?? 'unset'),
    // 가상이거나 **등록 전**이면 붙지 않는다. 바뀌면 훅이 알아서 끊고 다시 붙는다
    enabled: !virtual && !!shipId,

    onOpen: () => {
      // LWT 와 짝을 이룬다. 내가 살아 있음을 retain 으로 덮어쓴다.
      // 봉투 없이 {online, ts} — */online 은 LWT 라 봉투를 쓰지 않는다 (IoT contracts/topics.py RAW_TOPICS)
      if (topics) publishRef.current(topics.kioskOnline, onlinePayload(true), { qos: 1, retain: true });
    },

    onMessage: (topic, payload, retained) => {
      if (!topics) return;
      if (topic === topics.commandResponse) { bus.handleResponse(payload); return; }

      const d = decode(topics, topic, payload, retained);
      if (!retained && d.requestId && !seen.current(d.requestId)) return;

      // 시계 보정을 먼저 적용한다. 같은 배치의 deadline 이 옛 오프셋으로 계산되지 않게
      if (d.serverTsMs !== null) {
        dispatch({ kind: 'CLOCK', serverTsMs: d.serverTsMs, receivedAt: Date.now() });
      }
      if (d.msg) {
        dispatch({ kind: 'MESSAGE', msg: d.msg });
        // 사고가 끝나면 좌표 래치를 비운다 — 다음 사고에 옛 좌표가 새지 않게
        if (d.msg.type === 'INCIDENT_STATE'
          && (d.msg.status === 'RESOLVED' || d.msg.status === 'CANCELLED')) resetFix();
      }
    },
  });

  publishRef.current = publish;

  useEffect(() => {
    if (virtual) return;   // 가상은 위 effect 가 LINK OPEN 을 넣는다. 훅의 CLOSED 로 덮지 않는다
    dispatch({ kind: 'LINK', state: link });
    if (link !== 'OPEN') {
      // 끊기면 그 시점부터 상태는 옛것이다. 화면이 그걸 알아야 한다
      dispatch({ kind: 'DESYNC' });
      // 응답을 기다리던 명령을 깨운다 — 브로커가 죽었는데 버튼이 도는 채로 두지 않는다
      bus.abortAll();
    }
  }, [link, bus, virtual]);

  useEffect(() => {
    if (!virtual) {
      // 실제로 전환. 녹화 사고가 화면에 남으면 진짜처럼 보인다 — 지우고 브로커가 채우게 둔다
      dispatch({ kind: 'RESET' });
      return;
    }
    dispatch({ kind: 'LINK', state: 'OPEN' });
    dispatch({ kind: 'SNAPSHOT', snapshot: fixtureSnapshot(), receivedAt: Date.now() });
    // 가상을 벗어나거나 언마운트되면 남은 타이머를 걷는다 — 실제 모드 화면에 녹화 메시지가 새지 않게
    return stopPlayback;
  }, [virtual, stopPlayback]);

  const value = useMemo(() => state, [state]);

  return (
    <ModeCtx.Provider value={mode}>
      <StateCtx.Provider value={value}>
        <DispatchCtx.Provider value={dispatch}>
          <CommandCtx.Provider value={bus}>{children}</CommandCtx.Provider>
        </DispatchCtx.Provider>
      </StateCtx.Provider>
    </ModeCtx.Provider>
  );
}

export const useKiosk = () => useContext(StateCtx);
export const useMode = () => useContext(ModeCtx);
export const useKioskDispatch = () => useContext(DispatchCtx);

/** 명령 4종. Provider 밖에서 부르면 개발 중에 바로 드러나게 던진다 */
export function useCommands(): CommandBus {
  const bus = useContext(CommandCtx);
  if (!bus) throw new Error('useCommands must be used inside KioskProvider');
  return bus;
}

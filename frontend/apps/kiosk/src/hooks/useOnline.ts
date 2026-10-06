import { useEffect, useState } from 'react';

/**
 * 인터넷 연결 상태 + 강제 오프라인 스위치.
 *
 * <b>실제 연결을 본다</b>(2026-09-16). 이전에는 상단 와이파이 버튼이 그냥 토글이라
 * 랜선을 뽑아도 화면은 계속 "연결됨"이었다.
 *
 * ⚠ `navigator.onLine` 의 한계: **"랜선이 꽂혔나"만 안다.** 공유기에는 붙었는데 인터넷이 죽은 경우
 *   `true` 로 남는다. 그래서 이 값만으로 "육상 데이터가 온다"고 단정하지 않는다 —
 *   해양 화면은 수신 시각(`cloudAt`)을 따로 보여주고, 그쪽이 실제 도달 여부의 근거다.
 *
 * 강제 오프라인은 **시연용**이다. 두절 화면을 보여줘야 하는데 실제로 선을 뽑을 수는 없다.
 * 강제가 걸려 있으면 실제로 연결돼 있어도 오프라인으로 친다 — 사람이 끈 것을 시스템이 되돌리면 안 된다.
 */
export function useOnline() {
  // SSR·구형 환경 방어. navigator 가 없으면 연결된 것으로 본다 — 없다고 화면을 끄면 더 나쁘다
  const [connected, setConnected] = useState(
    () => (typeof navigator === 'undefined' ? true : navigator.onLine));
  const [forcedOffline, setForcedOffline] = useState(false);

  useEffect(() => {
    const up = () => setConnected(true);
    const down = () => setConnected(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    // 이벤트를 놓친 채 마운트될 수 있다(탭 복귀 등). 붙을 때 현재 값으로 한 번 맞춘다
    setConnected(navigator.onLine);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);

  return {
    /** 화면·폴링이 쓰는 값. 실제로 연결됐고 강제 오프라인이 아닐 때만 true */
    online: connected && !forcedOffline,
    /** 사람이 끈 것인가. 버튼 표시가 "끊김"과 "내가 껐음"을 구분한다 */
    forcedOffline,
    toggleForcedOffline: () => setForcedOffline((v) => !v),
  };
}

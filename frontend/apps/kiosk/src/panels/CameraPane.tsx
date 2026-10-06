import { useEffect, useState } from 'react';
import { jetsonUrl } from '@floaq/shared/origins';

/**
 * Jetson 카메라 라이브 (ref/kiosk_시연.md §7).
 *
 * <p>MJPEG 이라 {@code <img>} 하나로 끝난다. 다른 오리진이어도 이미지 표시에는 CORS 가 걸리지 않는다.</p>
 *
 * <p>⚠ <b>Pi 가 아니라 Jetson 주소다.</b> 영상만 Jetson 이 직접 내보낸다 —
 * Pi 를 거치면 프레임이 한 번 더 복사되고 그만큼 늦는다.</p>
 *
 * <p>🔴 <b>스테레오는 둘 다 살아 있어야 한다.</b> 한쪽만 도는 상태는 조준 해가
 * <b>조용히</b> 나빠지는 것이다 — 화면이 멀쩡해 보여서 아무도 모른다. 그래서 크게 경고한다.</p>
 */

/** Jetson `/health` 의 카메라 한 대 */
interface Cam { live: boolean; size: string | null; age_sec: number | null }
interface Health { ok: boolean; size_mismatch: boolean; cameras: Record<string, Cam> }

/** 8초. 스트림이 끊긴 것을 사람이 눈치채기 전에 알려줄 정도면 된다 */
const HEALTH_MS = 8000;

export function CameraPane({ virtual }: { virtual: boolean }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    // 가상 모드는 Jetson 이 없다. 부르면 콘솔이 오류로 덮인다
    if (virtual) return;
    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch(jetsonUrl('/health'), { signal: AbortSignal.timeout(4000) });
        const body = (await res.json()) as Health;
        if (alive) { setHealth(body); setFailed(false); }
      } catch {
        if (alive) { setHealth(null); setFailed(true); }
      }
    };
    void poll();
    const id = setInterval(() => void poll(), HEALTH_MS);
    return () => { alive = false; clearInterval(id); };
  }, [virtual]);

  if (virtual) {
    return (
      <div className="cam-empty">
        <p><b>가상 모드입니다.</b></p>
        <p className="hint">카메라 라이브는 실제 Pi·Jetson 에 붙었을 때만 나옵니다.</p>
      </div>
    );
  }

  const cams = health?.cameras ?? {};
  const dead = Object.entries(cams).filter(([, c]) => !c.live).map(([k]) => k);

  return (
    <div className="cam-pane">
      {/* 한쪽만 죽은 상태를 제일 크게. "영상이 나온다"가 "거리가 맞는다"를 뜻하지 않는다 */}
      {dead.length > 0 && (
        <p className="cam-warn" role="alert">
          카메라 {dead.join('·')} 정지 — <b>스테레오 거리 계산이 나빠집니다</b>
        </p>
      )}
      {health?.size_mismatch && (
        <p className="cam-warn" role="alert">좌우 해상도가 다릅니다 — 거리 계산이 어긋납니다</p>
      )}
      {failed && <p className="cam-warn">Jetson 상태를 받지 못했습니다 · 영상만 표시합니다</p>}

      <div className="cam-grid">
        {(['L', 'R'] as const).map((side) => (
          <figure key={side} className="cam-cell">
            {/* 살아 있지 않으면 스트림을 열지 않는다 — 끊긴 주소를 계속 물면 브라우저 연결이 쌓인다 */}
            {cams[side]?.live !== false ? (
              <img src={jetsonUrl(`/stream.mjpg?camera=${side}`)} alt={`카메라 ${side}`} />
            ) : <div className="cam-off">신호 없음</div>}
            <figcaption>
              <b>{side === 'L' ? '좌현' : '우현'}</b>
              <span className="mono">{cams[side]?.size ?? '—'}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

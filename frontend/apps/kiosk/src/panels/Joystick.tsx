import { useCallback, useEffect, useRef, useState } from 'react';
import type { LngLat } from '@floaq/shared';
import { speedKn, step, timeScale } from '../nav/step';

/**
 * 배를 움직이는 조이스틱. **가상 모드 전용**이다.
 *
 * 실제 운항에서 본선 위치는 GPS 가 정한다 — 사람이 화면에서 배를 끌고 다니면
 * 그 좌표가 신고에 실린다(§9.21 수동 신고). 그래서 실제 모드에서는 아예 렌더하지 않는다.
 *
 * 쓰는 이유: 해역을 옮기면 격자·관측소·특보가 따라 바뀌는지 보려면 배를 움직여야 하는데,
 * 지도 클릭은 한 번에 뛰므로 "움직이는 중"을 못 본다.
 */

interface Props {
  at: LngLat;
  onMove: (at: LngLat) => void;
  /** 지도를 배에 붙여 둔다. 조이스틱으로 밀면 화면 밖으로 나가기 때문 */
  onFollow?: (at: LngLat) => void;
}

/** 스틱 반지름(px). 손가락·마우스 어느 쪽에서도 잡히는 크기 */
const R = 42;

export function Joystick({ at, onMove, onFollow }: Props) {
  const [vec, setVec] = useState<{ x: number; y: number } | null>(null);
  const padRef = useRef<HTMLDivElement>(null);
  // 프레임 루프가 최신 값을 봐야 한다. 상태를 의존성에 넣으면 루프가 매번 다시 선다
  const live = useRef({ at, vec, onMove, onFollow });
  live.current = { at, vec, onMove, onFollow };

  const update = useCallback((e: PointerEvent | React.PointerEvent) => {
    const box = padRef.current?.getBoundingClientRect();
    if (!box) return;
    const dx = e.clientX - (box.left + box.width / 2);
    const dy = e.clientY - (box.top + box.height / 2);
    const len = Math.hypot(dx, dy);
    const k = len > R ? R / len : 1;   // 원 밖으로 나가면 테두리에 붙인다
    setVec({ x: (dx * k) / R, y: (dy * k) / R });
  }, []);

  const stop = useCallback(() => setVec(null), []);

  // 포인터가 지도 위로 나가도 계속 잡는다. pad 에만 걸면 밖에서 뗐을 때 배가 계속 흐른다
  useEffect(() => {
    if (!vec) return;
    const move = (e: PointerEvent) => update(e);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [vec, update, stop]);

  // 프레임마다 경과 시간만큼 민다. setInterval 고정 간격이면 탭이 느릴 때 속력이 달라진다
  useEffect(() => {
    if (!vec) return;
    let raf = 0;
    let prev = performance.now();
    const tick = (now: number) => {
      const dt = (now - prev) / 1000;
      prev = now;
      const v = live.current.vec;
      if (v) {
        const next = step(live.current.at, v.x, v.y, dt);
        if (next) {
          live.current.onMove(next);
          live.current.onFollow?.(next);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [vec]);

  // 키보드로도 민다. 터치가 없는 자리에서 시연할 때 쓴다
  const nudge = useCallback((dx: number, dy: number) => {
    const [lon, lat] = live.current.at;
    const d = 0.01;   // 약 1.1km. 세 번 누르면 격자 한 칸(3km)을 넘어 해역이 옮겨진다
    live.current.onMove([lon + (dx * d) / Math.cos((lat * Math.PI) / 180), lat + dy * d]);
  }, []);

  const kn = vec ? speedKn(vec.x, vec.y) : 0;
  const scale = vec ? timeScale(vec.x, vec.y) : 1;

  return (
    <div className="joy floaty">
      <div
        ref={padRef}
        className="joy-pad"
        role="application"
        aria-label="본선 이동 조이스틱. 방향키로도 움직입니다"
        tabIndex={0}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); update(e); }}
        onPointerUp={stop}
        onKeyDown={(e) => {
          const map: Record<string, [number, number]> = {
            ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
          };
          const d = map[e.key];
          if (!d) return;
          e.preventDefault();
          nudge(d[0], d[1]);
        }}
      >
        <i className="joy-ring" />
        <i
          className="joy-stick"
          style={vec ? { transform: `translate(${vec.x * R}px, ${vec.y * R}px)` } : undefined}
        />
      </div>
      <div className="joy-meta">
        <b>가상 항해</b>
        {/* 배속을 숨기지 않는다. 실제 속력인 척하면 화면이 거짓말을 한다 */}
        <span className="mono">{kn.toFixed(1)}kn{scale > 1 ? ` · ×${scale}` : ''}</span>
        <span className="joy-hint">{scale > 1 ? '바깥 고리 · 시연 배속' : '점선 안 · 실제 속력'}</span>
      </div>
    </div>
  );
}

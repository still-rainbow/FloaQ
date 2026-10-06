import { useEffect, useRef } from 'react';
import { FloaqMap } from './floaq-map.js';
import type { CreateOptions, FloaqMapApi, MapTheme, MarkerSpec } from './floaq-map.js';

// Leaflet 은 DOM 을 직접 소유한다. React 가 그 안을 건드리면 안 되므로
// 빈 div 하나만 렌더하고 내용은 effect 밖에서 관리한다.

interface Props {
  center: [number, number];
  zoom: number;
  theme: MapTheme;
  markers: MarkerSpec[];
  onReady?: (api: FloaqMapApi) => void;
  onOffline?: (offline: boolean) => void;
  className?: string;
  /** 경위도 눈금 — 기본은 오프라인에서만. 'always' 면 타일 위에도 남긴다 */
  grid?: CreateOptions['grid'];
}

export function MapView({ center, zoom, theme, markers, onReady, onOffline, className, grid }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<FloaqMapApi | null>(null);

  // 콜백을 ref 로 들고 있는다. deps 에 넣으면 부모가 리렌더할 때마다 지도가 다시 생성된다.
  const cb = useRef({ onReady, onOffline });
  cb.current = { onReady, onOffline };

  // 지도는 마운트 시 한 번만 만든다. center·zoom·markers 변경은 API 로 반영한다 —
  // 재생성하면 사용자가 움직여 둔 화면과 타일 캐시가 통째로 날아간다.
  //
  // ⚠ apiRef 를 create 의 반환값으로 즉시 채운다. onReady 는 setTimeout(0) 뒤라
  //   그것만 믿으면 StrictMode 의 두 번째 effect 가 같은 엘리먼트에 지도를 또 만들고
  //   Leaflet 이 "Map container is already initialized" 로 던진다.
  useEffect(() => {
    if (!hostRef.current || apiRef.current) return;
    const opts: CreateOptions = {
      container: hostRef.current,
      theme,
      data: { center, zoom },
      markers,
      grid,
      onOffline: (on) => cb.current.onOffline?.(on),
      onReady: (api) => cb.current.onReady?.(api),
    };
    const api = FloaqMap.create(opts);
    apiRef.current = api;
    return () => { api.destroy(); apiRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { apiRef.current?.setTheme(theme); }, [theme]);

  return <div ref={hostRef} className={className} />;
}

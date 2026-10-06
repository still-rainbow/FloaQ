// floaq-map.js 의 타입 선언. 구현은 바닐라 JS 로 두고 경계만 타입으로 막는다.

/** 좌표는 [lng, lat] — MapLibre 순서. Leaflet 의 [lat, lng] 변환은 모듈 안에서만 한다. */
export type LngLat = [number, number];

export type MapTheme = 'chart' | 'abyss' | 'dawn' | 'day';

export interface MarkerSpec {
  id: string;
  at: LngLat;
  html: string;
  cls?: string;
  size?: number;
  title?: string;
  hidden?: boolean;
  click?: () => void;
}

/** 관측 지점 점. 수집마다 목록이 바뀌어 setPoints 로 통째로 갈아 끼운다 */
export interface PointSpec {
  at: LngLat;
  html: string;
  cls?: string;
  size?: number;
  /** hover 툴팁 */
  title?: string;
}

export interface MarkerHandle {
  setLngLat(c: LngLat): MarkerHandle;
  getElement(): HTMLElement | undefined;
}

/** 등치선 한 레벨. 선분을 잇지 않는다 — 순서를 맞추다 틀리면 없는 연결을 그린다 */
export interface Isoline {
  value: number;
  color: string;
  segments: [LngLat, LngLat][];
}

export type BandId = 'buoy' | 'person' | `buoy${number}` | `person${number}`;

export interface GridCell {
  id: string;
  poly: LngLat[];
  /** 존재 가능성 농도 0~1 */
  density: number;
  /** todo 미수색 · done 수색 완료 · stale 표류로 기록이 만료돼 재수색 대상 */
  state: 'todo' | 'done' | 'stale';
}

export interface ContourBand {
  fill: string;
  line: string;
  op: number;
  polys: LngLat[][][];
}

export interface FloaqMapApi {
  map: unknown;
  markers: Record<string, MarkerHandle>;
  setTheme(key: MapTheme): void;
  setOffline(on: boolean): void;
  setManualOffline(on: boolean): void;
  isOffline(): boolean;
  setDim(on: boolean): void;
  setContours(bands: ContourBand[] | null): void;
  setIsolines(levels: Isoline[] | null): void;
  setMarker(id: string, at: LngLat | null, show?: boolean): void;
  setPoints(points: PointSpec[] | null): void;
  /** 부표 범위만 그리던 이전 이름. 새 호출부는 setBand 를 쓴다. */
  setDrift(center: LngLat | null, a?: number, b?: number, bearing?: number): void;
  /** 표류 추정 범위. id 로 부표와 사람을 따로 그린다 — 파지 미확인이면 둘의 위치가 갈린다. */
  /**
   * 표류 추정 범위. id 는 'buoy' | 'person' 이며, 여러 사고를 함께 띄울 때는
   * 뒤에 슬롯 번호를 붙인다('buoy0', 'person1'). 스타일은 숫자를 뗀 앞부분으로 찾는다.
   * dim 을 주면 다른 범위에 주역을 내주고 물러난다.
   */
  setBand(id: BandId, center: LngLat | null, a?: number, b?: number, bearing?: number, dim?: boolean,
          ramp?: readonly number[]): void;
  /**
   * 표류 입자 구름. 점 하나가 "이럴 수도 있다" 한 가지다 — 타원이 못 그리는
   * 두 덩어리·부채꼴 모양이 그대로 나온다. id 규칙은 {@link setBand} 와 같다.
   */
  setCloud(id: BandId, points: LngLat[] | null, dim?: boolean): void;
  /** 수색 구역 격자(신규 11). 지도에서 유일하게 클릭을 받는 층이다. */
  setGrid(cells: GridCell[] | null, onPick?: (id: string) => void): void;
  /** src: 'wake' | 'btrack'(실측·실선) | 'etrack'(추정·점선) | 'route' */
  setLine(src: string, coords: LngLat[]): void;
  /** 숨겼다 다시 보인 뒤 호출. 안 하면 타일이 어긋난다 */
  invalidate(): void;
  /** 컨테이너를 놓아준다. 언마운트 시 필수 — 안 하면 재생성이 던진다 */
  destroy(): void;
  follow(at: LngLat): void;
  keepInView(at: LngLat): void;
  fitPoints(coords: LngLat[], opts?: Record<string, unknown>): void;
}

export interface CreateOptions {
  container: string | HTMLElement;
  theme?: MapTheme;
  data: { center: LngLat; zoom: number };
  markers?: MarkerSpec[];
  onOffline?: (offline: boolean) => void;
  onReady?: (api: FloaqMapApi) => void;
  /** 지도 클릭 좌표 [lng, lat] */
  onClick?: (at: LngLat) => void;
  /**
   * 경위도 눈금을 언제 그리나. 기본 `auto` 는 오프라인에서만 —
   * `always` 면 타일이 보이는 동안에도 남긴다(망망대해에서는 타일이 하늘색 한 장이라
   * 눈금이 없으면 지도가 떴는지조차 모른다).
   */
  grid?: 'auto' | 'always';
}

export declare const FloaqMap: {
  create(opts: CreateOptions): FloaqMapApi;
  THEMES: Record<MapTheme, Record<string, string>>;
  circle(center: LngLat, meters: number, steps?: number): unknown;
  offset(c: LngLat, meters: number, bearingDeg: number): LngLat;
  coastLonAt(lat: number): number;
};

export default FloaqMap;

/**
 * 해안선 — OpenStreetMap `natural=coastline` 을 부산 앞바다 범위로 받아 단순화한 것.
 * 153개 선 · 좌표 1475개, 범위는 lng 128.88~129.31 · lat 34.98~35.33 이다.
 *
 * <p>OSM 규약대로 <b>진행 방향의 왼쪽이 육지</b>다. 육지 판정이 그 규약에 기댄다(apps/web lib/land.ts).</p>
 */
export declare const COASTLINES: LngLat[][];

import { COASTLINES } from '@floaq/shared';
import type { LngLat } from '@floaq/shared';

/**
 * 여기가 육지인가.
 *
 * <p>표류 추정 범위가 <b>산과 논을 덮고 있었다</b>. 사람이 거기 있을 수는 없는데 화면은
 * "여기 있을 수도"라고 말하고, 수색 격자도 육지 칸을 만들어 배를 그리로 보냈다(2026-09-18).</p>
 *
 * <h3>어떻게 판정하나</h3>
 * <p>해안선은 <b>닫힌 도형이 아니라 선</b>이라 점이 안에 있는지 묻는 방식(point-in-polygon)을
 * 쓸 수 없다. 대신 OpenStreetMap 의 규약을 쓴다 — {@code natural=coastline} 은
 * <b>진행 방향의 왼쪽이 육지</b>다. 그래서 가장 가까운 해안선 조각을 찾아 그 왼쪽인지 보면 된다.</p>
 *
 * <h3>못 하는 것</h3>
 * <ul>
 *   <li>🔴 <b>데이터가 부산 앞바다뿐이다</b>(lng 128.88~129.31 · lat 34.98~35.33).
 *       그 밖은 판정하지 않고 <b>바다로 본다</b> — 모르는 곳을 육지라고 하면 멀쩡한 수색 구역이
 *       통째로 사라진다. 잘못 넓히는 쪽이 잘못 좁히는 쪽보다 낫다.</li>
 *   <li>선이 끊긴 자리(섬이 여러 way 로 잘린 곳)에서는 가장 가까운 조각이 엉뚱할 수 있다.</li>
 *   <li>간조에 드러나는 갯벌은 해안선에 없다.</li>
 * </ul>
 */

/** 해안선이 덮는 범위. 밖은 판정하지 않는다 */
export const COAST_BBOX = { west: 128.87, east: 129.32, south: 34.97, north: 35.34 };

export const inCoastRange = (lng: number, lat: number): boolean =>
  lng >= COAST_BBOX.west && lng <= COAST_BBOX.east
  && lat >= COAST_BBOX.south && lat <= COAST_BBOX.north;

/** 한 조각 — [시작, 끝]. 방향이 뜻을 가지므로 순서를 뒤집으면 안 된다 */
type Seg = [number, number, number, number];

/** 칸 크기(°). 약 1.1km — 조각 하나보다 크고 한 번에 훑기에 작다 */
const CELL = 0.01;
const key = (i: number, j: number) => `${i},${j}`;
const cellOf = (v: number) => Math.floor(v / CELL);

/** 조각을 칸에 나눠 담아 둔다. 1475개를 매번 다 재면 격자 한 판에 수십만 번이 된다 */
let index: Map<string, Seg[]> | null = null;

function build(): Map<string, Seg[]> {
  const m = new Map<string, Seg[]>();
  for (const way of COASTLINES as LngLat[][]) {
    for (let i = 0; i + 1 < way.length; i += 1) {
      const a = way[i]!;
      const b = way[i + 1]!;
      const seg: Seg = [a[0], a[1], b[0], b[1]];
      // 조각이 걸치는 칸 전부에 넣는다. 사선이면 두세 칸이다
      const i0 = Math.min(cellOf(a[0]), cellOf(b[0]));
      const i1 = Math.max(cellOf(a[0]), cellOf(b[0]));
      const j0 = Math.min(cellOf(a[1]), cellOf(b[1]));
      const j1 = Math.max(cellOf(a[1]), cellOf(b[1]));
      for (let x = i0; x <= i1; x += 1) {
        for (let y = j0; y <= j1; y += 1) {
          const k = key(x, y);
          const list = m.get(k);
          if (list) list.push(seg); else m.set(k, [seg]);
        }
      }
    }
  }
  return m;
}

/** 점에서 조각까지 거리의 제곱(경위도 단위). 순서 비교에만 쓰므로 미터로 안 고친다 */
function dist2(px: number, py: number, s: Seg): number {
  const [ax, ay, bx, by] = s;
  const dx = bx - ax;
  const dy = by - ay;
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len));
  const qx = ax + t * dx;
  const qy = ay + t * dy;
  return (px - qx) * (px - qx) + (py - qy) * (py - qy);
}

/**
 * 가장 가까운 해안선 조각. 자기 칸부터 보고, 없으면 한 겹씩 넓힌다.
 * 세 겹(약 3km)까지 아무것도 없으면 먼바다다.
 */
function nearest(lng: number, lat: number): Seg | null {
  if (!index) index = build();
  const ci = cellOf(lng);
  const cj = cellOf(lat);
  let best: Seg | null = null;
  let bestD = Infinity;

  // 겹 하나가 약 1.1km. 열두 겹이면 13km 까지 본다 — 추정 타원이 닿는 범위는 다 덮는다
  for (let ring = 0; ring <= 12; ring += 1) {
    for (let i = ci - ring; i <= ci + ring; i += 1) {
      for (let j = cj - ring; j <= cj + ring; j += 1) {
        // 이미 본 안쪽 겹은 건너뛴다
        if (ring > 0 && Math.abs(i - ci) < ring && Math.abs(j - cj) < ring) continue;
        const list = index.get(key(i, j));
        if (!list) continue;
        for (const s of list) {
          const d = dist2(lng, lat, s);
          if (d < bestD) { bestD = d; best = s; }
        }
      }
    }
    // 한 겹에서 찾았으면 그 바깥은 더 가까울 수 없다 — 한 겹 더 보고 끝낸다
    if (best && ring > 0) break;
  }
  return best;
}

/**
 * 육지인가. 해안선 범위 밖이면 <b>false</b>(바다로 본다).
 *
 * <p>OSM `natural=coastline` 은 진행 방향 왼쪽이 육지다. x(동)·y(북) 좌표에서
 * 외적의 부호가 양수면 왼쪽이다.</p>
 */
export function isLand(lng: number, lat: number): boolean {
  if (!inCoastRange(lng, lat)) return false;
  const s = nearest(lng, lat);
  if (!s) return false;
  const [ax, ay, bx, by] = s;
  // 위도에 따라 경도 1° 의 실제 길이가 달라진다. 그대로 두면 각도가 눌려 좌우 판정이 뒤집힐 수 있다
  const k = Math.cos(lat * Math.PI / 180);
  const cross = (bx - ax) * k * (lat - ay) - (by - ay) * (lng - ax) * k;
  return cross > 0;
}

/**
 * 중심에서 한 점까지 <b>바다인 데까지만</b> 간 자리.
 *
 * <p>추정 타원을 그릴 때 꼭짓점마다 이걸 거친다. 중심에서 밖으로 나가다 해안을 만나면
 * 거기서 멈춘다 — 타원이 해안선을 넘지 않는다. 중심 자체가 육지면(이미 해안에 닿은 추정)
 * 자를 곳이 없으므로 그대로 둔다.</p>
 */
export function clipToSea(center: LngLat, point: LngLat): LngLat {
  if (isLand(center[0], center[1])) return point;
  if (!isLand(point[0], point[1])) return point;
  // 바다인 안쪽과 육지인 바깥 사이를 반씩 좁힌다. 여덟 번이면 거리의 1/256 까지 좁혀진다
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 8; i += 1) {
    const mid = (lo + hi) / 2;
    const x = center[0] + (point[0] - center[0]) * mid;
    const y = center[1] + (point[1] - center[1]) * mid;
    if (isLand(x, y)) hi = mid; else lo = mid;
  }
  return [center[0] + (point[0] - center[0]) * lo, center[1] + (point[1] - center[1]) * lo];
}

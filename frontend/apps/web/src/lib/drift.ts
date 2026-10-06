import { FloaqMap } from '@floaq/shared';
import type { LngLat } from '@floaq/shared';
import type { Uncertainty } from '../types';

/**
 * 표류 추정(계획.md 8.1). 통신 두절 시 부표·사람 위치를 이어서 그리기 위한 계산이다.
 *
 *   표류 = **해류 + 풍압(leeway)**
 *   풍압 = 풍속 × 계수. 물 밖으로 나온 면적이 클수록 계수가 크다
 *
 * 이 구조는 국제 항공·해상 수색구조 편람(IAMSAR)의 표준이다 —
 * "Drift has two components: leeway and total water current."
 * 계수를 풍속의 백분율로 잡는 방식은 Allen & Plourde(1999, 美 해안경비대 연구소)가 세웠고
 * 지금 USCG·노르웨이 구조조정본부 모델의 바탕이다.
 *
 * 🔴 **풍압은 바람 방향으로만 가지 않는다.** 다운윈드 성분과 함께 **좌·우 가로 성분**이 있고,
 *    <b>그 좌우 부호는 예측할 수 없다</b> — 시간당 3~7% 확률로 뒤집힌다(jibing, Allen & Plourde).
 *    그래서 실제 SAR 모델은 화살표 하나가 아니라 입자 수천 개(몬테카를로)로 확률 구역을 만든다.
 *    여기서는 그것을 <b>좌우 양쪽으로 벌어지는 부채꼴</b>로 거칠게 근사한다.
 *
 * ⚠ 앙상블이 아니라 단일 벡터 + 부채꼴이다. 오프셋 항(cm/s)과 지빙 확률도 넣지 않았다.
 *   정확도를 주장하지 않는다. 화면에는 항상 "추정"이라고 쓴다.
 */

/**
 * 풍압 계수 — 다운윈드(바람 방향)와 가로(좌우) 두 성분.
 *
 * 출처: OpenDrift(노르웨이 기상청) `OBJECTPROP.DAT`. USCG leeway 현장 실험 회귀값이다.
 */
export interface Leeway {
  /** 바람이 흘러가는 방향으로 미는 몫 (풍속 대비 비율) */
  down: number;
  /** 바람 기준 좌우로 벌어지는 몫. <b>부호를 모른다</b> — 양쪽으로 같이 벌어진다 */
  cross: number;
  /**
   * 다운윈드 계수의 하한·상한. <b>값 하나가 아니라 폭인 이유는 대상의 상태를 모르기 때문이다</b> —
   * 사람은 자세와 구명조끼 착용에 따라, 부표는 밸러스트가 잠긴 정도에 따라 갈린다.
   * {@link cloud} 가 이 폭에서 입자마다 하나씩 뽑는다. {@link down} 은 그 중앙값이다.
   */
  downMin: number;
  downMax: number;
}

/**
 * 부표. 구명부표에 딱 맞는 실측 항목이 표에 없어 가장 가까운 것을 쓴다 —
 * 구명 뗏목(얕은 밸러스트) 다운윈드 2.68% · 가로 1.10%, 구조 키트 2.48% · 0.32%.
 * 뗏목류 범위(2.7~3.7%)의 낮은 쪽으로 잡았다. 폭은 그 두 항목과 뗏목류 상한을 양 끝으로 둔다.
 */
export const LEEWAY_BUOY: Leeway = { down: 0.03, cross: 0.011, downMin: 0.0248, downMax: 0.037 };

/**
 * 사람. 표의 <b>PIW 상태 불명</b> 항목이 다운윈드 0.96% · 가로 0.54% 다 —
 * 자세를 알 수 없으므로 이 값을 쓴다.
 * 부표보다 수면 위로 나온 면적이 작아 바람에 덜 밀리고 해류에 더 지배된다.
 *
 * <p>폭 0.48~1.71% 는 <b>구명조끼 입고 수직</b>(0.48) 부터 <b>생존복</b>(1.71) 까지다.
 * 3.5배 차이라 풍속 10m/s·1시간이면 173m 와 616m 로 갈린다 — 우리는 어느 쪽인지 알 방법이 없다.
 * 값 하나를 고르는 대신 이 폭 전체를 입자에 뿌린다.</p>
 */
export const LEEWAY_PERSON: Leeway = { down: 0.0096, cross: 0.0054, downMin: 0.0048, downMax: 0.0171 };

/**
 * 출발점 오차 — 마지막으로 받은 위치가 얼마나 틀렸을 수 있나(m).
 *
 * 🔴 <b>남은 유일한 근거 없는 상수다.</b> IAMSAR 는 초기 위치 오차를 GPS 정밀도·보고 지연·
 * 항법 오차로 나눠 세는 절차를 따로 두고 있다 — 거기서 가져와야 한다.
 */
/**
 * 🔴 <b>잡고 있는지 놓았는지 모를 때</b> 쓰는 계수 — 두 경우의 중간이다.
 *
 * <p>LoRa 가 끊기면 위치도 눌림도 함께 끊긴다. 마지막 패킷에서 눌려 있었다는 사실만 남는데,
 * 그건 "놓았다"가 아니라 <b>더는 모른다</b>는 뜻이다. 계속 잡고 있었다면 사람은 부표를 따라
 * 3% 로 흘렀고, 끊긴 직후 놓았다면 1% 로 흘렀다 — 같은 시간에 풍속 12m/s 면 862m 가 갈린다.</p>
 *
 * <p>분포가 실제로 두 덩이다. 어느 쪽인지 고를 근거가 없으니 <b>중간에 중심을 두고</b>,
 * 두 덩이 사이 거리({@link splitOf})를 분산 항으로 실어 하나의 넓은 타원으로 덮는다.
 * 재어 보니 두 봉우리 간격이 2.4σ 이고 가운데 밀도가 봉우리의 91% 라, 합쳐 그려도
 * "여기는 비어 있는데 있다고 말하는" 구간이 생기지 않는다.</p>
 *
 * <p>폭은 두 경우의 폭을 모두 덮는다 — 구명조끼 입고 수직(0.48%) 부터 부표 상한(3.7%) 까지.
 * ⚠ 이 폭과 {@link splitOf} 의 분산이 일부 겹친다. 겹치는 쪽이 넓게 잡는 쪽이라
 *   수색 구역이 좁아지는 실수는 나지 않지만, 정밀하게 하려면 둘 중 하나로 정리해야 한다.</p>
 */
export const LEEWAY_HELD_UNKNOWN: Leeway = {
  down: (LEEWAY_BUOY.down + LEEWAY_PERSON.down) / 2,
  cross: Math.max(LEEWAY_BUOY.cross, LEEWAY_PERSON.cross),
  downMin: LEEWAY_PERSON.downMin,
  downMax: LEEWAY_BUOY.downMax,
};

/**
 * 🔴 <b>이보다 오래 끊기면 추정하지 않는다</b>(초).
 *
 * <p>우리 식은 조류와 바람이 <b>그동안 내내 같다</b>고 본다(한 걸음 등속 표류). 그 가정은
 * 몇 시간까지만 참이다 — 한국 연안은 반일주조라 조류가 약 6.2시간마다 방향을 뒤집는다.
 * 한 주기를 넘기면 중심이 "불확실"한 게 아니라 <b>체계적으로 틀린다</b>. 밀어 둔 방향으로
 * 계속 가지만 실제 부표는 그 사이 되돌아오기를 반복한다.</p>
 *
 * <p>2026-09-18 에 실제로 겪었다: 마지막 수신이 53시간 전인 사고에서 타원이 진주 · 창원 · 여수를
 * 덮었다. 폭 수십 km 에 육지가 절반이었다 — 그건 "여기 있을 수도"가 아니라 <b>모른다</b>는 뜻인데
 * 화면은 아는 척을 했다. 모르면 <b>모른다고 해야</b> 한다.</p>
 *
 * <p>6시간으로 잡은 것은 반일주조 반주기다. 조류 예보를 시간별로 받아 구간마다 다시 흘리면
 * 이 한계는 사라진다 — 그때까지의 정직한 선이다.</p>
 */
export const MAX_DRIFT_SEC = 6 * 3600;

export const BASE_RADIUS_M = 50;

export interface Sea {
  /** 유속 (m/s) */
  currentSpeed: number;
  /** 유향 (°) */
  currentDir: number;
  /** 풍속 (m/s) */
  windSpeed: number;
  /** 풍향 (°) */
  windDir: number;
  /**
   * 유속을 얼마나 모르는가 (m/s). 서버 `/api/ocean/current` 의 `neighborSpreadMs` —
   * 한 칸(약 3km) 이내 이웃 격자와의 유속 <b>최대 차이</b>다.
   *
   * <p>연안 경계에서는 이웃끼리 유속이 10배까지 갈린다(2026-09-13 실측: 외해 0.289 vs 내만 0.035 m/s).
   * 그 자리에서는 "유속 0.22"라는 값 자체를 믿을 수 없다는 뜻이라, 시간이 갈수록 위치 오차가 커진다.</p>
   *
   * <p>없으면 0 — 격자가 하나뿐이거나 이웃이 없는 경우다. ⚠ 0 은 "확실하다"가 아니라 "모른다"에 가깝다.</p>
   */
  currentSpreadMs?: number;
}

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export interface Drift {
  /** 합성 표류 속도 (m/s) */
  speed: number;
  /** 합성 표류 방위 (°) */
  bearing: number;
  /**
   * 바람 기준 좌우로 벌어지는 속도 (m/s). <b>부호를 모른다</b> —
   * 좌우 어느 쪽인지 예측할 수 없고 도중에 뒤집히기도 한다. 양쪽으로 같이 벌어지는 폭으로 쓴다.
   */
  crossSpeed: number;
  /** 바람이 흘러가는 방위 (°). 가로 성분은 여기서 ±90° 다 */
  windBearing: number;
}

/**
 * 해류와 풍압의 벡터 합. 방위는 북 기준 시계방향이다.
 *
 * <p>가로 성분은 합치지 않고 따로 돌려준다 — 부호를 모르기 때문이다.
 * 더해 버리면 <b>모르는 것을 한쪽으로 정한 셈</b>이 된다.</p>
 */
export function drift(sea: Sea, leeway: Leeway): Drift {
  const cx = sea.currentSpeed * Math.sin(rad(sea.currentDir));
  const cy = sea.currentSpeed * Math.cos(rad(sea.currentDir));
  const wx = sea.windSpeed * leeway.down * Math.sin(rad(sea.windDir));
  const wy = sea.windSpeed * leeway.down * Math.cos(rad(sea.windDir));
  const x = cx + wx;
  const y = cy + wy;
  return {
    speed: Math.hypot(x, y),
    bearing: (deg(Math.atan2(x, y)) + 360) % 360,
    crossSpeed: sea.windSpeed * leeway.cross,
    windBearing: sea.windDir,
  };
}

/* ───────────────────────── 불확실 범위 ─────────────────────────
   🔴 **모르는 것마다 얼마나 퍼뜨리는지는 미리 셀 수 있다.** 뽑아 볼 필요가 없다.

   전에는 임의의 상수로 때웠다 — 흘러간 거리의 50%(`SPREAD`), 고리 배율 0.68·0.48.
   어디서 온 숫자인지 아무도 몰랐다. 지금은 모르는 것마다 분산을 세워 방향별로 더한다.

   이 방식이 맞는지는 입자 4만 개(`cloud`)로 대조해 확인했다(2026-09-17) —
   장반경·단반경·방위가 네 가지 바다 조건에서 소수점까지 같았다.
   분포가 종 모양이라 평균과 퍼짐만으로 완전히 결정되기 때문이다.

   <b>난수를 쓰지 않는다.</b> 그래서 Pi 와 관제가 씨앗을 맞출 필요 없이 같은 답을 낸다.
   ─────────────────────────────────────────────────────────────── */

/**
 * 고리를 장반경(σ)의 몇 배로 그릴지. 키오스크도 같은 값을 써야 해서
 * <b>`@floaq/shared` 로 옮겼다.</b> 여기서는 다시 내보내기만 한다 —
 * 두 벌을 두면 한쪽만 고쳐지고 두 화면이 다른 크기의 타원을 그린다.
 *
 * <p>2차원 정규분포라면 √(−2 ln(1−p)) 로 1.177 · 1.665 · 2.448 인데,
 * 입자 4만 개로 재 보니 <b>1.22 · 1.69 · 2.36</b> 이었다(네 조건에서 ±2% 안).
 * 바깥이 이론값보다 좁은 것은 풍압 계수에 상한이 있어 꼬리가 짧기 때문이다.</p>
 */
// ⚠ `export ... from` 만 쓰면 이 파일 안에서는 못 쓴다. 아래 uncertainty() 가 쓴다
import { RING_K, BAND_RAMP } from '@floaq/shared';

export { RING_K };

/**
 * {@link Uncertainty} 의 a·b 는 <b>95% 고리</b>다. 안쪽 두 고리는 여기에 이 비율을 곱한다 —
 * 지도의 `setBand` 에 넘긴다. 넓은 것부터다.
 */
export { BAND_RAMP };

/** 2×2 대칭 행렬 [xx, xy, yy]. x 는 동, y 는 북이다 */
type Cov = [number, number, number];

/** 방위 {@code dir} 을 향하는 분산 {@code v} 를 행렬에 싣는다 */
function push(S: Cov, v: number, dir: number): void {
  const s = Math.sin(rad(dir));
  const c = Math.cos(rad(dir));
  S[0] += v * s * s;
  S[1] += v * s * c;
  S[2] += v * c * c;
}

/**
 * 시간 t 뒤 위치의 <b>퍼짐</b>. 모르는 것 하나가 항 하나다.
 *
 * <p>각 항은 "그 값이 어느 범위에서 뽑힌다"고 보고 분산을 낸다 —
 * 균등분포는 폭²/12, 정규분포는 σ², 반지름 R 원 안 균등은 축마다 R²/4 다.</p>
 *
 * @param splitM 부표를 잡고 있나 놓았나 모를 때 두 경우의 중심 거리(m).
 *               혼합분포의 분산은 각 분산의 평균 + (거리/2)² 이라 항 하나로 끝난다.
 *               가운데가 비지 않는다 — 2.4σ 벌어져도 가운데 확률이 봉우리의 91% 다.
 */
function covOf(sea: Sea, leeway: Leeway, sec: number, splitM = 0): Cov {
  // 출발점 오차 — 반지름 BASE_RADIUS_M 원 안에 고르게. 방향이 없어 두 축에 같이 실린다
  const r2 = (BASE_RADIUS_M * BASE_RADIUS_M) / 4;
  const S: Cov = [r2, 0, r2];

  // 계수 폭 — 사람은 자세·구명조끼를, 부표는 얼마나 잠겼는지를 모른다. 바람 방향으로 늘어난다
  const width = (leeway.downMax - leeway.downMin) * sea.windSpeed * sec;
  push(S, (width * width) / 12, sea.windDir);

  // 유속 오차 — 이웃 격자와의 차이(neighborSpreadMs)의 절반을 표준편차로 본다. 해류 방향
  const sigma = ((sea.currentSpreadMs ?? 0) / 2) * sec;
  if (sigma > 0) push(S, sigma * sigma, sea.currentDir);

  // 좌우 성분 — 부호를 모르고(반반) 크기도 0~최대에서 고르다. 바람 기준 ±90°
  const cross = sea.windSpeed * leeway.cross * sec;
  push(S, (cross * cross) / 3, sea.windDir + 90);

  // 잡았나 놓았나 모름 — 갈리는 방향은 바람이다. 해류는 둘 다 같은 만큼 밀어 상쇄된다
  if (splitM > 0) push(S, (splitM * splitM) / 4, sea.windDir);

  return S;
}

/** 공분산 행렬 → 95% 타원. 고유값이 두 축의 분산이고 고유벡터가 그 방향이다 */
function ellipseOf(S: Cov): Uncertainty {
  const [xx, xy, yy] = S;
  const tr = xx + yy;
  const gap = Math.sqrt(Math.max(0, (tr * tr) / 4 - (xx * yy - xy * xy)));
  // 장축 각은 수학 관례(동에서 반시계)로 나온다. 방위는 북 기준 시계라 90 에서 뺀다
  const theta = deg(Math.atan2(2 * xy, xx - yy)) / 2;
  return {
    a: RING_K.p95 * Math.sqrt(Math.max(0, tr / 2 + gap)),
    b: RING_K.p95 * Math.sqrt(Math.max(0, tr / 2 - gap)),
    bearing: (90 - theta + 360) % 360,
  };
}

export interface Estimate {
  at: LngLat;
  band: Uncertainty;
  /** 출발점에서 흘러간 거리(m) */
  movedM: number;
}

/**
 * 출발점에서 {@code sec} 초 뒤의 추정 위치와 불확실 범위.
 *
 * <p>중심은 벡터 합 하나, 범위는 분산 합 하나다. <b>시간을 쪼개 굴리지 않는다</b> —
 * 등속 표류라 한 걸음으로 끝나고, 두 걸음으로 나누면 같은 불확실성을 두 번 세게 된다.
 * 그래서 슬라이더 Δt 도 "그려 둔 것을 더 민다"가 아니라 <b>경과에 더해 다시 계산</b>한다.</p>
 *
 * ⚠ 중심은 문헌의 대푯값({@link Leeway.down})을 쓴다. 폭의 한가운데와 조금 다르다 —
 *   사람은 0.96% 대 1.10% 라 풍속 12m/s·1시간이면 약 58m 차이인데, 50% 고리 안에 든다.
 */
export function estimate(
  from: LngLat, sea: Sea, sec: number, leeway: Leeway, splitM = 0,
): Estimate {
  const d = drift(sea, leeway);
  const moved = d.speed * sec;
  return {
    at: FloaqMap.offset(from, moved, d.bearing),
    band: ellipseOf(covOf(sea, leeway, sec, splitM)),
    movedM: moved,
  };
}

/**
 * 부표를 잡고 있는 경우와 놓은 경우의 <b>중심이 벌어지는 거리</b>(m).
 *
 * 해류는 둘 다 똑같이 밀어 상쇄되고 풍압 계수 차이만 남는다 — 부표 3.1% 대 사람 1.1%.
 * 이 값을 {@link estimate} 의 {@code splitM} 으로 넘기면 두 경우를 하나로 뭉쳐 그린다.
 */
export function splitOf(sea: Sea, sec: number): number {
  const mid = (l: Leeway) => (l.downMin + l.downMax) / 2;
  return (mid(LEEWAY_BUOY) - mid(LEEWAY_PERSON)) * sea.windSpeed * sec;
}

/* ───────────────────────── 입자(몬테카를로) ─────────────────────────
   타원 하나는 <b>모양이 거짓말을 한다</b>. 위에 쌓은 불확실성들은 서로 곱해지는데
   (계수 3.5배 × 좌우 부호 × 유속 오차), 그 결과는 타원이 아니라 두 덩어리이거나 부채꼴이다.
   타원으로 누르면 실제로는 비어 있는 사이 공간까지 "여기 있을 수도"라고 말하게 된다.

   실제 수색구조 모델(USCG SAROPS·노르웨이 OpenDrift)이 입자 수만 개를 뿌리는 이유가 이것이다.
   여기서는 수백 개만 뿌린다 — 등속 표류 한 걸음이라 시간을 잘게 쪼개 반복할 필요가 없다.
   ─────────────────────────────────────────────────────────────────── */

/**
 * 뿌릴 입자 수. 모양을 읽는 데는 이 정도면 충분하고, 지도에 SVG 원을 이만큼 얹어도 버틴다.
 * ⚠ 사고를 여럿 띄우면 이 수에 슬롯 수가 곱해진다. 늘릴 때 프레임을 같이 봐야 한다.
 */
export const CLOUD_N = 240;

/** 문자열 → 32비트 씨앗 (FNV-1a) */
function seedOf(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * 씨앗을 받는 난수(mulberry32).
 *
 * 🔴 <b>{@code Math.random()} 을 쓰면 안 된다.</b> 새로고침할 때마다 구름 모양이 달라져
 * 화면을 믿을 수 없게 되고, 키오스크와 관제가 서로 다른 구름을 그린다.
 * 씨앗을 사고 id 로 고정하면 언제 어디서 계산해도 <b>점 하나까지 같은 그림</b>이 나온다.
 */
function rngOf(seed: number): () => number {
  let a = seed || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 표준정규 한 개 (Box-Muller). 유속 오차를 뽑는 데 쓴다 */
function gauss(rnd: () => number): number {
  const u = Math.max(rnd(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rnd());
}

/**
 * 출발점에서 {@code sec} 초 뒤 있을 만한 자리들. 입자 하나하나가 "이럴 수도 있다" 한 가지다.
 *
 * <p>입자마다 다음을 뽑는다. <b>모르는 것을 정하지 않고 굴린다</b>는 것이 전부다.</p>
 * <ul>
 *   <li>출발점 오차 — 반지름 {@link BASE_RADIUS_M} 안에 고르게(면적 균등이라 √를 쓴다)</li>
 *   <li>다운윈드 계수 — {@code downMin ~ downMax}. 사람이면 구명조끼·자세를 모르는 몫이다</li>
 *   <li>가로 좌우 — 부호 반반. 도중에 뒤집히므로(jibing) 크기는 0~최대에서 고르게 뽑는다</li>
 *   <li>유속 오차 — 이웃 격자와의 차이의 절반을 표준편차로 본 정규분포</li>
 * </ul>
 *
 * @param seed 같은 사고는 늘 같은 구름이어야 한다. 사고 id 를 넣는다
 */
export function cloud(
  from: LngLat, sea: Sea, sec: number, leeway: Leeway, seed: string, n: number = CLOUD_N,
): LngLat[] {
  const rnd = rngOf(seedOf(seed));
  const sigma = (sea.currentSpreadMs ?? 0) / 2;
  const pts: LngLat[] = [];

  for (let i = 0; i < n; i += 1) {
    const start = FloaqMap.offset(from, BASE_RADIUS_M * Math.sqrt(rnd()), rnd() * 360);

    const down = leeway.downMin + rnd() * (leeway.downMax - leeway.downMin);
    // 유속이 뒤로 흐르는 일은 없다. 0 에서 자른다
    const cs = Math.max(0, sea.currentSpeed + gauss(rnd) * sigma);
    const side = rnd() < 0.5 ? -1 : 1;
    const cm = sea.windSpeed * leeway.cross * rnd();

    const x = cs * Math.sin(rad(sea.currentDir))
      + sea.windSpeed * down * Math.sin(rad(sea.windDir))
      + cm * Math.sin(rad(sea.windDir + side * 90));
    const y = cs * Math.cos(rad(sea.currentDir))
      + sea.windSpeed * down * Math.cos(rad(sea.windDir))
      + cm * Math.cos(rad(sea.windDir + side * 90));

    pts.push(FloaqMap.offset(start, Math.hypot(x, y) * sec, (deg(Math.atan2(x, y)) + 360) % 360));
  }
  return pts;
}

/** 슬라이더(신규 7) 눈금. 지금 시점 + Δ */
export const STEPS: [number, string][] = [
  [0, '지금'],
  [600, '+10분'],
  [1800, '+30분'],
  [3600, '+1시간'],
];

/*
 * `project(at, band, Δt)` 는 없앴다(2026-09-17).
 *
 * 이미 그려 둔 범위를 Δt 만큼 "더 미는" 함수였는데, 그러면 <b>같은 불확실성을 두 번 센다</b> —
 * 첫 걸음에서 이미 넣은 계수 폭·좌우 성분을 둘째 걸음에서 또 더하기 때문이다.
 * 등속 표류라 쪼갤 이유도 없다. 부르는 쪽은 출발점과 `경과 + Δt` 로 {@link estimate} 를 다시 부른다.
 */

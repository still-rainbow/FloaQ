/**
 * 저체온증 기반 생존 잔여시간(신규 1).
 *
 * ⚠ 의료적 확정치가 아니다. USCG·캐나다 해양 표준의 저체온증 생존곡선표를 구간으로 옮긴 값이고,
 *   화면에는 반드시 "참고용 추정치"를 병기한다. 체격·복장·구명조끼 착용 여부가 전부 빠져 있다.
 *
 * 쓰는 이유는 정확도가 아니라 **정렬 기준**이다. 사고가 여러 건일 때
 * "어느 쪽이 더 급한가"를 감이 아니라 수온과 경과 시간으로 줄 세우기 위한 값이다.
 */

export interface SurvivalBand {
  /** 의식 유지 예상 (분) */
  conscious: [number, number];
  /** 생존 예상 (분). Infinity = 무기한 */
  survive: [number, number];
}

/** 수온(℃) → 구간. 경계값은 표의 원문을 그대로 옮겼다. */
export function bandFor(tempC: number): SurvivalBand {
  if (tempC < 0.3) return { conscious: [0, 15], survive: [15, 45] };
  if (tempC < 4.4) return { conscious: [15, 30], survive: [30, 90] };
  if (tempC < 10) return { conscious: [30, 60], survive: [60, 180] };
  if (tempC < 15.6) return { conscious: [60, 120], survive: [60, 360] };
  if (tempC < 21.1) return { conscious: [120, 420], survive: [120, 2400] };
  if (tempC < 26.7) return { conscious: [180, 720], survive: [180, Infinity] };
  return { conscious: [Infinity, Infinity], survive: [Infinity, Infinity] };
}

export interface Survival {
  band: SurvivalBand;
  /** 의식 유지 상한까지 남은 분. 음수면 이미 넘겼다 */
  consciousLeftMin: number;
  /** 정렬용 키. 짧을수록 급하다. 무기한은 아주 큰 수 */
  sortKey: number;
  /** `의식 유지 예상 ~2시간` 같은 표시 문구 */
  text: string;
  /** 상한을 넘겼는지 — 넘겼으면 화면에서 색을 바꾼다 */
  past: boolean;
}

/** `1시간 42분` · `2시간` · `35분`. `1.7시간` 같은 소수 시간은 몇 분인지 바로 안 읽혀 쓰지 않는다. */
const hhmm = (min: number) => {
  if (!Number.isFinite(min)) return '무기한';
  const total = Math.round(min);
  if (total < 60) return `${total}분`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h}시간 ${m}분` : `${h}시간`;
};

export function survival(tempC: number, elapsedSec: number): Survival {
  const band = bandFor(tempC);
  const elapsedMin = elapsedSec / 60;
  const upper = band.conscious[1];
  const left = upper - elapsedMin;

  return {
    band,
    consciousLeftMin: left,
    sortKey: Number.isFinite(left) ? left : Number.MAX_SAFE_INTEGER,
    text: Number.isFinite(upper) ? `의식 유지 예상 약 ${hhmm(upper)}` : '의식 유지 예상 무기한',
    past: Number.isFinite(left) && left <= 0,
  };
}

/** W-02 목록 컬럼용 짧은 표기 */
export function shortLeft(s: Survival) {
  if (!Number.isFinite(s.consciousLeftMin)) return '—';
  if (s.past) return '상한 초과';
  return `약 ${hhmm(s.consciousLeftMin)}`;
}

export { hhmm };

/**
 * 지금 얼마나 급한가. **화면의 색을 정하는 하나의 기준**이다.
 *
 * <p>전에는 카드 색이 긴급도(조난·긴급)를 따랐는데, 관제에 오는 사고는 대부분 조난이라
 * 세 장이 전부 같은 빨강이었다 — <b>색이 아무것도 말하지 않았다</b>(2026-09-17).
 * 색은 "지금 뭘 먼저 봐야 하나"에만 쓴다.</p>
 *
 *   hot   30분 이내 · 상한의 80% 경과 · 이미 초과
 *   warm  1시간 이내 · 절반 경과
 *   calm  그 밖
 */
/**
 * 화면의 색 등급.
 *
 * <p>{@code stale} 은 긴급도가 아니라 <b>다른 축</b>이다 — "급하다"가 아니라
 * "이미 지났고 아직 안 닫혔다"는 뜻이라, 빨강·노랑과 섞이지 않는 짙은 남색을 쓴다.</p>
 */
export type Urgency3 = 'hot' | 'warm' | 'calm' | 'stale';

/**
 * 🔴 <b>장기 미종결</b> 기준 — 의식 유지 상한의 몇 배까지 목록 위에 둘 것인가.
 *
 * <p>상한을 넘겼다고 바로 내리면 안 된다. 그때부터가 수색이고, 화면이 제일 필요한 때다.
 * 하지만 <b>상한의 두 배</b>가 지나도 안 닫혀 있으면 그건 대응 중이 아니라 <b>닫는 걸 잊은 것</b>에
 * 가깝다 — 통신이 끊겼거나, 구조는 됐는데 선내 단말이 꺼졌거나, 종결을 깜빡했거나.</p>
 *
 * <p>2026-09-19 에 실제로 겪었다: 사흘 된 사고 여섯 건이 전부 빨강으로 목록 맨 위에 쌓여
 * <b>색이 아무것도 구분해 주지 못했다.</b> 진짜 급한 사고가 그 밑에 묻힌다.</p>
 */
export const STALE_RATIO = 2;

export function level(s: Survival, elapsedSec: number): Urgency3 {
  const hi = s.band.conscious[1];
  if (!Number.isFinite(hi)) return 'calm';
  const pct = (elapsedSec / 60 / hi) * 100;
  const left = s.consciousLeftMin;
  // 상한의 두 배를 넘기면 긴급도 축에서 내려온다. 급한 것이 아니라 닫히지 않은 것이다
  if (pct >= STALE_RATIO * 100) return 'stale';
  if (s.past || pct >= 80 || left <= 30) return 'hot';
  if (pct >= 50 || left <= 60) return 'warm';
  return 'calm';
}

/** 남은 시간을 상한 대비 비율(0~100)로. 막대 길이가 이 값이다 */
export function leftPct(s: Survival): number {
  const hi = s.band.conscious[1];
  if (!Number.isFinite(hi)) return 100;
  return Math.max(0, Math.min(100, (s.consciousLeftMin / hi) * 100));
}

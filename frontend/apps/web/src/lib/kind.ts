import { level, survival } from './survival';
import type { Urgency3 } from './survival';
import type { Incident } from '../types';

/**
 * 사고 유형이 화면을 가른다.
 *
 * 지금까지 관제 화면은 전부 MOB(인명 추락) 전제였다. 부표를 쏘고, 사람이 물에 있고,
 * 저체온증 시계가 급함을 말해 준다. 화재·좌초·기관 고장은 그 축이 통째로 없다 —
 * 조난 대상이 사람이 아니라 **배**다.
 *
 * 판정에 새 데이터를 쓰지 않는다. **DSC nature of distress 코드**가 이미 오고 있고,
 * 그게 곧 "무슨 사고인가"의 정본이다(§9.21 — 우리가 만든 분류가 아니다).
 */
export type Kind = 'mob' | 'vessel';

/** DSC 110 = MOB. 나머지는 배가 조난 대상이다. */
export const kindOf = (x: Incident): Kind => (x.type.dsc === '110' ? 'mob' : 'vessel');

export const isMob = (x: Incident) => kindOf(x) === 'mob';

/**
 * 배가 흘러가는가 — 유형으로 아는 경우.
 *
 * 조종 불능이면 배도 부표처럼 표류한다 — 같은 계산을 그대로 쓸 수 있다.
 * 좌초(103)는 박혀 있으므로 흐르지 않고, 화재(100)·충돌(102)은 동력이 남아 있다고 본다.
 *
 *   106 기관 고장 · 조종 불능
 *   101 침수 / 104 전복 위험
 */
const ADRIFT_DSC = new Set(['106', '101', '104']);

export const isAdrift = (x: Incident) => !isMob(x) && ADRIFT_DSC.has(x.type.dsc);

/*
 * 🔴 배가 **어디로 흘러갈지는 추정하지 않는다**(2026-09-17 결정).
 *
 * 잠시 있던 `shipDrifts`·`isShipLost`·`SHIP_LOST_SEC` 를 걷어냈다. 배의 풍압 계수를 모르는 채로
 * 부표 것(3%)을 빌려 쓰고 있었고, 근거 없는 범위를 수색 구역처럼 보여 주는 쪽이 안 그리는 것보다 나쁘다.
 *
 * {@link isAdrift} 는 남긴다 — 그건 추정이 아니라 DSC 코드가 말해 주는 사실이다.
 * 화면은 "표류 중 · 조종 불능"이라고 적기만 하고, 어디로 흘렀는지는 말하지 않는다.
 */

/* ══════════════════════════════════════════════════════════
   MOB 가 아닌 사고의 카드 색 (2026-09-17)

   MOB 은 저체온증 시계가 "지금 얼마나 급한가"를 답해 준다(survival.ts `level`).
   배가 조난 대상이면 그 시계가 없다. 그렇다고 긴급도(조난/긴급)로 칠하면
   대부분 조난이라 다시 전부 같은 빨강이 된다 — 색이 아무것도 말하지 않는다.

   그래서 같은 질문을 다시 묻는다: **지금 뭘 먼저 봐야 하나.**

     ③ 마지막 소식 이후 경과  — 색을 정하는 값. 시간이 가면 변한다
     ② DSC 코드가 말하는 위험 — 바닥값. 방금 소식이 왔어도 전복 위험을 calm 까지 내리지 않는다

   둘 중 <b>더 급한 쪽</b>을 쓴다. 그러면 세 유형이 같은 문장을 말한다 —
   빨강 = 이 배에 대해 아는 것이 제일 오래됐다.

   ⚠ 침몰까지 남은 시간이 제일 어울리지만 그걸 잴 데이터가 없다.
     배가 어디로 흘러갈지를 추정하지 않기로 한 것과 같은 이유로 지어내지 않는다.
   ══════════════════════════════════════════════════════════ */

/**
 * 소식이 끊긴 지 이만큼 지나면 등급이 오른다.
 *
 * 선박 위치는 사고 중에 주기적으로 올라온다. 한두 번 빠지는 것은 늘 있는 일이라
 * 5분까지는 색을 올리지 않는다. 15분이면 배에서 아무것도 못 보내고 있다는 뜻이다.
 */
export const SILENT_WARM_SEC = 5 * 60;
export const SILENT_HOT_SEC = 15 * 60;

/**
 * DSC nature of distress 가 말하는 바닥 등급(§9.21).
 *
 *   104 전복 위험 · 101 침수 · 100 화재 — 배가 사라지는 중이다
 *   102 충돌 · 103 좌초              — 멈춰 있고 가라앉지는 않는다
 *   106 기관 고장 · 조종 불능        — 배는 멀쩡하고 못 움직일 뿐이다
 */
const DSC_FLOOR: Record<string, Urgency3> = {
  '104': 'hot', '101': 'hot', '100': 'hot',
  '102': 'warm', '103': 'warm',
  '106': 'calm',
};

/**
 * 급한 정도. 큰 쪽이 급하다.
 *
 * ⚠ {@code stale}(장기 미종결)은 <b>calm 보다도 아래</b>다. 여유가 있어서가 아니라
 * 긴급도 축에서 내려온 것이라 — 목록 맨 아래로 가야 위쪽에 손쓸 수 있는 것만 남는다.
 */
const RANK: Record<Urgency3, number> = { stale: -1, calm: 0, warm: 1, hot: 2 };

/** 마지막 소식 이후 경과(초)만으로 본 등급 */
export function silentLevel(ageSec: number): Urgency3 {
  if (ageSec >= SILENT_HOT_SEC) return 'hot';
  if (ageSec >= SILENT_WARM_SEC) return 'warm';
  return 'calm';
}

/**
 * MOB 가 아닌 진행 중 사고의 카드 색. 소식 끊김과 DSC 바닥값 중 <b>급한 쪽</b>.
 *
 * ⚠ MOB 에는 쓰지 않는다 — 거기는 {@link import('./survival').level} 이 답한다.
 */
export function vesselLevel(x: Incident): Urgency3 {
  const silent = silentLevel(x.map.shipAgeSec ?? 0);
  const floor = DSC_FLOOR[x.type.dsc] ?? 'calm';
  return RANK[silent] >= RANK[floor] ? silent : floor;
}

/** 막대 길이(0~100) — 소식이 끊길수록 줄어든다. MOB 의 남은 시간 막대와 같은 뜻이다 */
export function silentPct(ageSec: number): number {
  return Math.max(0, Math.min(100, 100 - (ageSec / SILENT_HOT_SEC) * 100));
}

/** 등급을 숫자로 — 작을수록 급하다(정렬용). stale 은 맨 뒤로 간다 */
export const urgencyRank = (u: Urgency3) => -RANK[u];

/**
 * 이 사고의 카드 색 = 급한 정도. <b>목록 색과 정렬이 같은 함수를 쓴다</b> —
 * 따로 두면 "빨간 카드가 초록 카드 밑에 있는" 목록이 된다.
 */
export function urgencyOf(x: Incident): Urgency3 {
  if (x.state !== 'live') return 'calm';
  return isMob(x) ? level(survival(x.waterTemp, x.elapsedSec), x.elapsedSec) : vesselLevel(x);
}

/**
 * 같은 등급 안에서의 순서. <b>남은 분</b>으로 통일한다 — 재는 시계는 달라도
 * 묻는 것은 하나다("이 숫자가 0이 되면 늦는다").
 */
export function leftMinOf(x: Incident): number {
  if (isMob(x)) return survival(x.waterTemp, x.elapsedSec).sortKey;
  return (SILENT_HOT_SEC - (x.map.shipAgeSec ?? 0)) / 60;
}

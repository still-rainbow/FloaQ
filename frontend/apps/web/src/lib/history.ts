import { leftMinOf, urgencyOf, urgencyRank } from './kind';
import type { Incident } from '../types';

/** 최신 순. 날짜가 같으면 head 앞의 HH:MM:SS 로 가른다. */
export const byRecent = (a: Incident, b: Incident) =>
  b.day.localeCompare(a.day) || b.head.localeCompare(a.head);

/**
 * 들어온 지 얼마 안 된 사고로 볼 시간(초).
 *
 * 3분. 처음 화면에 들어왔을 때는 이 필터를 무시하고 무조건 맨 위에 세운다.
 * 사고 발생 시각을 기준으로 한다 — 관제가 신고를 받는 것은 그 직후라 거의 같고,
 * 따로 들고 있을 필요가 없다. 서버 수신 시각이 오면 그걸로 바꾸면 된다.
 */
export const FRESH_SEC = 180;

/**
 * 방금 들어온 사고인가. <b>{@link byUrgent} 가 이것만은 정렬보다 앞에 둔다.</b>
 *
 * <p>급한 순은 남은 생존 시간이 기준인데, <b>방금 빠진 사람은 시간이 제일 많이 남아</b>
 * 그대로 두면 목록 맨 아래로 간다. 새 신고가 제일 보이지 않는 자리에 높이는 셈이라
 * {@link FRESH_SEC} 동안만 위로 올리고, 지나면 제 순서로 돌려보낸다(2026-09-17).</p>
 */
export const isFresh = (x: Incident) => x.state === 'live' && x.elapsedSec <= FRESH_SEC;

/**
 * 급한 순. **진행 중이 늘 위**고, 그 안에서 남은 시간이 짧은 쪽이 앞이다.
 *
 * <p>생존 잔여시간은 물에 빠진 사람에게만 있는 시계다. MOB 이 아니면 그 값이 없으므로
 * 경과가 긴 쪽을 급하다고 본다.</p>
 *
 * <p>여기 있는 이유는 <b>목록과 첫 화면이 같은 기준을 써야 하기 때문</b>이다 —
 * 화면을 열면 이 순서의 첫 건이 자동으로 열리는데(App.tsx), 목록이 따로 정렬하면
 * "맨 위 카드"와 "열려 있는 사고"가 어긋난다.</p>
 */
export const byUrgent = (a: Incident, b: Incident) => {
  const live = Number(b.state === 'live') - Number(a.state === 'live');
  if (live) return live;

  // 방금 들어온 것이 먼저. 그 안에서는 더 방금 온 순서다
  const fresh = Number(isFresh(b)) - Number(isFresh(a));
  if (fresh) return fresh;
  if (isFresh(a) && isFresh(b)) return a.elapsedSec - b.elapsedSec;

  /*
   * 카드 색과 <b>같은 함수</b>로 먼저 가른다. 색은 급한 정도를 말하는데 정렬이 그걸
   * 안 따르면 빨간 카드가 초록 카드 밑에 놓인다 — 색이 거짓말을 하는 셈이다(2026-09-17).
   * 등급이 같으면 남은 분이 짧은 쪽이 앞이다.
   */
  const rank = urgencyRank(urgencyOf(a)) - urgencyRank(urgencyOf(b));
  if (rank) return rank;
  return leftMinOf(a) - leftMinOf(b);
};

/**
 * 한 선박의 사고 이력. 배 한 척에 사고는 0건일 수도, 여러 건일 수도 있다 —
 * 선박이 사고 id 를 들고 있지 않고 사고가 선박 id 를 든다(ERD 의 incidents.ship_id).
 * 진행 중이 맨 위, 나머지는 최신 순.
 */
export function incidentsOf(incidents: Incident[], shipId: string): Incident[] {
  return incidents
    .filter((x) => x.ship === shipId)
    .sort((a, b) => Number(b.state === 'live') - Number(a.state === 'live') || byRecent(a, b));
}

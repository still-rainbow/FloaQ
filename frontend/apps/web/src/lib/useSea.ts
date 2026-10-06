import { useEffect, useMemo, useState } from 'react';
import { seaAt } from './ocean';
import type { SeaReading } from './ocean';
import type { Incident } from '../types';

/**
 * 사고 지점의 바다 값을 받아 둔다. 표류 추정의 입력이다.
 *
 * <b>지도에 함께 띄운 사고도 다 받는다.</b> 보고 있는 사고만 받으면 나머지는 추정을 못 해
 * 사람 마커가 사라진다 — 토글은 있는데 켤 것이 없는 상태가 된다.
 *
 * <b>사고가 바뀔 때만 다시 받는다.</b> 슬라이더를 움직일 때마다 받으면 안 된다 —
 * Δt 는 "앞으로 얼마 뒤"라서 바다 값이 달라지지 않고, 격자는 한 시간에 한 번 갱신된다.
 *
 * 값이 없으면 null 이다. 그때 화면은 추정을 그리지 않고 마지막 실측 위치만 남긴다 —
 * 임의의 기본값으로 메우면 그 원이 근거 있는 것처럼 보인다.
 */

/** 사고의 바다 값을 물어볼 지점. 감지 지점이 먼저고, 없으면 부표를 마지막으로 받은 곳 */
const pointOf = (x: Incident) => x.map.mob ?? x.map.buoy?.lastFixAt ?? x.map.ship ?? null;

/**
 * <b>언제의 바다</b>를 물을까.
 *
 * <p>진행 중이면 지금이 곧 그때라 비워 둔다. <b>끝난 사고는 감지 시각을 넘긴다</b> —
 * 안 넘기면 9월 16일 사고를 여는 사람이 <b>오늘 바람을 그날 바람으로</b> 읽는다.
 * 표류 추정 타원도 같은 값으로 그려지므로 표만 고쳐서는 절반만 고치는 것이다(2026-09-21).</p>
 *
 * <p>⚠ 서버는 <b>24시간만 보관한다</b>({@code OceanRetention.WINDOW}). 그보다 오래된 사고는
 * 거절당해 값이 null 로 온다 — 화면은 그때 "기록이 남아 있지 않다"를 그린다.
 * 사고 행에 그때 값을 박아 두는 것이 제대로 된 답이지만 그건 표 변경이 필요하다.</p>
 */
const whenOf = (x: Incident) => (x.state === 'live' ? undefined : x.detectedAt);

/**
 * 박아 둔 값을 쓸 사고인가. <b>끝난 사고만</b>이다.
 *
 * <p>진행 중 사고는 지금 바다를 봐야 한다 — 사람은 <b>지금</b> 떠내려가고 있고, 표류 추정도
 * 지금 조류로 해야 맞는다. 사고가 난 지 세 시간이면 그때 조류는 이미 지난 물살이다.</p>
 *
 * <p>박힌 값은 그 사고가 <b>어떤 바다에서 시작했나</b>를 말한다 — 끝난 뒤 되짚을 때 쓰는 값이다.</p>
 */
const snapOf = (x: Incident) => (x.state === 'live' ? null : x.oceanSnap);

/**
 * 좌표를 소수 셋째 자리로 묶는다(약 100m). 격자가 3km 간격이라 그보다 촘촘히 물어봐야
 * 같은 칸이 나온다 — <b>같은 바다를 여러 번 부르지 않게</b> 묶는 열쇠로 쓴다.
 */
const keyOf = (at: [number, number], when?: string) =>
  `${at[1].toFixed(3)},${at[0].toFixed(3)}@${when ?? 'now'}`;

/** 사고 여럿의 바다 값. 사고 id 로 찾는다 */
export function useSeaOf(incidents: (Incident | null | undefined)[]): Record<string, SeaReading | null> {
  const targets = useMemo(() => {
    const rows: { id: string; at: [number, number]; when?: string }[] = [];
    for (const x of incidents) {
      if (!x) continue;
      const at = pointOf(x);
      // 박혀 있는 값이 있으면 물어보지 않는다 (끝난 사고만 해당)
      if (snapOf(x)) continue;
      if (at && !rows.some((r) => r.id === x.id)) rows.push({ id: x.id, at, when: whenOf(x) });
    }
    return rows;
    // 좌표·시각 문자열로 비교한다 — 배열을 그대로 두면 매 렌더마다 새 참조라 계속 다시 받는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents.map((x) => (x ? `${x.id}:${(pointOf(x) ?? []).join()}:${whenOf(x) ?? ''}:${x && snapOf(x) ? 1 : 0}` : '')).join('|')]);

  const [sea, setSea] = useState<Record<string, SeaReading | null>>({});

  /**
   * 🔴 <b>사고가 들고 있는 값이 먼저다.</b> 사고 행에 그때의 바다가 박혀 있으면 물어볼 것이 없다 —
   * 몇 년이 지나도 같은 값이고, 조회는 24시간만 답한다(서버 V20260921_1210).
   *
   * <p>조회는 <b>그 값이 없는 사고에만</b> 나간다. 이 칸이 생기기 전 사고, 격자가 없던 사고다.</p>
   */
  const stored = useMemo(() => {
    const m: Record<string, SeaReading> = {};
    for (const x of incidents) if (x && snapOf(x)) m[x.id] = x.oceanSnap!;
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents.map((x) => (x ? `${x.id}:${x && snapOf(x) ? 1 : 0}` : '')).join('|')]);

  useEffect(() => {
    // 사고를 빠르게 옮겨 다니면 먼저 보낸 응답이 나중에 올 수 있다. 떠난 화면의 값을 그리지 않게 끊는다
    const ctrl = new AbortController();
    const cache = new Map<string, Promise<SeaReading | null>>();

    void Promise.all(targets.map(async ({ id, at, when }) => {
      const k = keyOf(at, when);
      // 같은 바다·같은 시각에 모인 사고들은 한 번만 물어본다
      if (!cache.has(k)) cache.set(k, seaAt(at[1], at[0], when, ctrl.signal));
      return [id, await cache.get(k)!] as const;
    })).then((rows) => {
      if (!ctrl.signal.aborted) setSea(Object.fromEntries(rows));
    });

    return () => ctrl.abort();
  }, [targets]);

  // 박혀 있는 값이 조회 결과를 덮는다 — 둘 다 있으면 사고가 들고 있는 쪽이 사실이다
  return { ...sea, ...stored };
}

/** 사고 하나의 바다 값. 상세·수색 화면이 쓴다 */
export function useSea(incident: Incident | null): SeaReading | null {
  const map = useSeaOf([incident]);
  return incident ? map[incident.id] ?? null : null;
}

import type { Vessel } from '../types';

/**
 * 등록 선박. <b>서버에서 받아 채운다</b> — 하드코딩 배열(mock/data.ts `FLEET`)을 걷어낸 자리다(2026-09-18).
 *
 * <p>화면 여러 곳(지도 라벨 · 카드 · 리포트 · 수색 모드)이 배 이름을 `byVessel[id]` 로 꺼내 쓴다.
 * 그 자리마다 props 를 내려보내면 손댈 곳이 열 군데가 넘는다. 대신 <b>모듈 하나가 값을 들고 있고</b>
 * {@link setFleet} 이 채운다 — React 상태가 아니므로 갱신은 사고 목록 상태가 바뀔 때 함께 일어난다.</p>
 *
 * <p>출처는 둘이다. 사고 목록 응답에 딸려 오는 배(이름만)와, 관리자만 볼 수 있는
 * 선박 목록 API(`/api/admin/ships`)다. 둘 다 없으면 <b>비어 있다</b> — 지어내지 않는다.
 * 이름이 없으면 화면에는 그 자리에 선박 id 가 그대로 뜬다.</p>
 */
export const byVessel: Record<string, Vessel> = {};

/** 등록 선박 목록 화면(기록 → 등록 선박)이 이 배열을 그린다 */
export const FLEET: Vessel[] = [];

/** 서버에서 받은 배로 갈아 끼운다. 같은 id 는 뒤에 온 쪽(정보가 더 많은 쪽)이 이긴다 */
export function setFleet(rows: Vessel[]): void {
  for (const k of Object.keys(byVessel)) delete byVessel[k];
  FLEET.length = 0;
  for (const v of rows) {
    byVessel[v.id] = v;
    FLEET.push(v);
  }
}

/**
 * 사고 목록에 딸려 온 배를 이미 있는 목록에 덧댄다.
 * 선박 API 를 못 부르는 계정(해경)도 사고에 나온 배 이름은 볼 수 있어야 한다.
 */
export function mergeFleet(rows: Vessel[]): void {
  for (const v of rows) {
    if (byVessel[v.id]) continue;
    byVessel[v.id] = v;
    FLEET.push(v);
  }
}

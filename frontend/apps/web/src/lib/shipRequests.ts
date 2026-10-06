/**
 * 선박 등록 승인 (WEB-08 · W-05 · docs/api.md §3.3).
 *
 * 등록 요청은 선내 kiosk 의 최초 등록 화면(apps/kiosk/src/pages/Register.tsx)에서 나온다.
 * ⚠ **신청 경로는 아직 없다** — Pi 가 ship_id(UUID v7)를 만들어 서명해 보내는 것으로 정했고
 * 서명 계약(알고리즘·헤더·시각 창)이 IoT 팀에서 오지 않았다(api.md §9 3-1).
 * 그래서 지금 목록은 비어 있는 것이 정상이다. **가짜 데이터를 넣어 두지 않는다** —
 * 있지도 않은 신청이 보이면 승인 버튼이 도는지 아닌지를 아무도 확인할 수 없다.
 *
 * 승인·반려는 실제로 DB 를 바꾼다. 계정 승인(auth.ts applications·decide)과 같은 모양이라
 * 헬퍼를 그대로 가져다 쓴다 — 두 승인이 화면에서 같은 컴포넌트를 쓰므로 오류 모양이 어긋나면 안 된다.
 *
 * 보여 주는 칸은 kiosk 등록 화면에서 받는 것 중 승인 판단에 쓰는 것만이다 —
 * 선박명 · 등록번호 · 총톤수 · 승선 인원. 카메라 높이 같은 설치 값은 장비 설정이라 뺐다(AdminShipView).
 */

import type { AdminError } from './auth';
import { ADMIN_MAX_PAGES, ADMIN_PAGE_SIZE, adminErrorOf, authFetch, minuteText } from './auth';

export type ShipRequestStatus = 'wait' | 'approved' | 'rejected';

export interface ShipRequest {
  id: string;
  /** 선박명 */
  name: string;
  /** 선박 등록번호 */
  regNo: string;
  /** 승선 인원 */
  crew: number;
  /** 요청 시각 'YYYY-MM-DD HH:MM' */
  requestedAt: string;
  status: ShipRequestStatus;
  /** 승인·반려 시각 */
  decidedAt: string | null;
}

/** 서버 응답 한 줄 (AdminShipView) */
interface ApiAdminShip {
  shipId: string;
  name: string;
  registrationNo: string | null;
  tonnage: number | null;
  crew: number | null;
  status: 'WAIT' | 'ACTIVE' | 'REJECTED';
  createdAt: string;
  decidedAt: string | null;
}

const STATUS_OF: Record<ApiAdminShip['status'], ShipRequestStatus> = {
  WAIT: 'wait', ACTIVE: 'approved', REJECTED: 'rejected',
};

/**
 * 선박 등록 요청 목록. 승인 대기가 위(먼저 요청한 순), 처리한 건은 최근 처리 순.
 *
 * ⚠ V8 이전에 SA 가 직접 등록한 배는 `decidedAt` 이 null 인 채로 `approved` 다.
 *    승인 절차를 거친 적이 없어서다(V8 마이그레이션 주석). 목록 맨 아래로 간다.
 */
export async function shipRequests(): Promise<{ ok: true; list: ShipRequest[] } | { ok: false; error: AdminError }> {
  const rows: ApiAdminShip[] = [];
  try {
    for (let page = 0; page < ADMIN_MAX_PAGES; page += 1) {
      const res = await authFetch(`/api/admin/ships?page=${page}&size=${ADMIN_PAGE_SIZE}`);
      if (!res.ok) return { ok: false, error: adminErrorOf(res.status) };
      const body = await res.json();
      rows.push(...(body.data.content as ApiAdminShip[]));
      if (!body.data.hasNext) break;
    }
  } catch {
    return { ok: false, error: 'server' };
  }

  const list: ShipRequest[] = rows.map((s) => ({
    id: s.shipId,
    name: s.name,
    // 등록번호·제원이 없는 행은 V8 이전에 들어온 배다. 빈칸으로 두지 않고 모른다고 적는다
    regNo: s.registrationNo ?? '등록번호 없음',
    tonnage: s.tonnage ?? 0,
    crew: s.crew ?? 0,
    requestedAt: minuteText(s.createdAt),
    status: STATUS_OF[s.status],
    decidedAt: s.decidedAt ? minuteText(s.decidedAt) : null,
  }));

  const waiting = list.filter((r) => r.status === 'wait').sort((a, b) => a.requestedAt.localeCompare(b.requestedAt));
  const decided = list.filter((r) => r.status !== 'wait')
    .sort((a, b) => (b.decidedAt ?? '').localeCompare(a.decidedAt ?? ''));
  return { ok: true, list: [...waiting, ...decided] };
}

/** 승인(true) · 반려(false). 대기 중인 요청에만 적용된다 — 이미 처리됐으면 conflict */
/**
 * 선박 삭제(api.md §3.3 `DELETE /api/ships/{shipId}`).
 *
 * <p>논리 삭제다 — `is_deleted = true` 만 찍고 행은 남긴다. 과거 사고가 그 배를 참조하고
 * 있어서, 지우면 지난 사고의 배 이름이 사라진다.</p>
 *
 * <p>⚠ 진행 중인 사고가 있는 배는 서버가 409 로 막는다. 그 배를 목록에서 지우면
 * 관제가 그 사고를 못 찾기 때문이다 — 화면은 그 이유를 그대로 적어 준다(in-use).</p>
 */
export async function removeShip(id: string): Promise<{ ok: true } | { ok: false; error: AdminError }> {
  let res: Response;
  try {
    res = await authFetch(`/api/ships/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } catch {
    return { ok: false, error: 'server' };
  }
  if (res.ok) return { ok: true };
  // 409 는 여기서만 "사고 중인 배" 라는 뜻이다. 승인 쪽 409(이미 처리됨)와 같은 말을 쓰면 안 된다
  return { ok: false, error: res.status === 409 ? 'in-use' : adminErrorOf(res.status) };
}

export async function decideShip(id: string, approve: boolean): Promise<{ ok: true } | { ok: false; error: AdminError }> {
  let res: Response;
  try {
    res = await authFetch(`/api/admin/ships/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`, { method: 'POST' });
  } catch {
    return { ok: false, error: 'server' };
  }
  return res.ok ? { ok: true } : { ok: false, error: adminErrorOf(res.status) };
}

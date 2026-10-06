import type { Role } from '../types';

/**
 * 관제 웹 계정 — 로그인(WEB-01 · floaq-164) · 가입 신청(WEB-02 · floaq-165) · 계정 승인(WEB-07).
 *
 * 전부 서버에 붙었다(docs/api.md §3.1 · §3.2). JWT 를 받아 localStorage 에 두고 요청마다 붙인다.
 *     login          POST  /api/auth/login    → { accessToken, expiresAt, user }
 *     refreshSession GET   /api/auth/me
 *     apply          POST  /api/auth/signup   → 201 (A · WAIT)
 *     applications   GET   /api/admin/users   (SA)
 *     decide         POST  /api/admin/users/{id}/approve | /reject   (WAIT → ACTIVE | REJECTED)
 *     로그아웃 API 는 없다 — 무상태 JWT 라 토큰을 버리면 끝이다.
 *
 * 계정에는 users 테이블에 있는 것만 둔다 — 기관 이메일 · 이름 · 역할 · 상태.
 * 소속 · 부서 · 계급 · 연락처 · 재직증명서는 받지도 보여주지도 않는다(2026-09-15 결정) —
 * 해경 쪽에서는 신고를 받았는지만 알 수 있고, 누가 담당하는지·어느 곳에서 처리하는지는 알 수 없다.
 * 셀프 가입은 없다 — 신청은 승인 대기(WAIT)로 들어가고 SA 이 승인해야 로그인된다(계획.md §9.13).
 * 비밀번호 원문은 어디에도 두지 않는다. 서버가 bcrypt 로 해시한다.
 */

export type AccountStatus = 'wait' | 'active' | 'rejected';

/** 계정 관리 화면의 신청 한 줄 */
export interface Account {
  id: string;
  /** 로그인 ID. 기관 이메일 */
  email: string;
  name: string;
  role: Role;
  status: AccountStatus;
  /** 신청 시각 'YYYY-MM-DD HH:MM' — users.created_at */
  appliedAt: string;
  /** 승인·반려 시각. 따로 저장하지 않아 users.updated_at 을 쓴다 */
  decidedAt: string | null;
}

/** 로그인 상태로 들고 있는 값. 비밀번호·토큰은 넣지 않는다 */
export interface Session {
  id: string;
  email: string;
  name: string;
  role: Role;
}

export interface ApplyForm {
  name: string;
  email: string;
  password: string;
}

/**
 * 이메일·비밀번호 중 무엇이 틀렸는지는 알려 주지 않는다 — 계정이 있는지 없는지가 새지 않게.
 * rejected — 가입 신청이 반려됨. deleted — 쓰던 계정이 비활성화됨. 둘은 서버 상태가 다르다(V5).
 * server — 서버에 닿지 않았거나 서버가 실패했다. 비밀번호가 틀렸다고 말하면 사용자가 엉뚱한 걸 고친다.
 */
export type LoginError = 'invalid' | 'pending' | 'rejected' | 'deleted' | 'server';

/**
 * 가입 신청 실패.
 * invalid — 화면 검사를 통과했는데 서버가 형식을 거절했다. 두 검사가 어긋났다는 뜻이라 칸을 짚지 못한다.
 */
export type ApplyError = 'duplicate' | 'invalid' | 'server';

/**
 * 계정 관리 실패.
 * expired — 로그인이 풀렸다. conflict — 다른 관리자가 이미 처리했거나 없는 신청이다(409 · 404).
 */
export type AdminError = 'expired' | 'forbidden' | 'conflict' | 'server'
  /** 지금 지울 수 없는 상태다. 사고 중인 배를 지우려 했을 때(api.md §3.3 INVALID_STATE 409) */
  | 'in-use';

export const ROLE_LABEL: Record<Role, string> = { admin: '해경', superadmin: '관리자' };

/**
 * 시연용 계정. 로그인 화면의 "채우기" 버튼이 쓴다.
 * 서버 local 프로파일의 DemoAccountSeeder 가 같은 계정을 만든다 — 바꾸면 둘 다 바꾼다.
 */
export const DEMO = {
  superadmin: { email: 'admin@floaq.example', password: 'floaq1234!' },
  admin: { email: 'kim@kcg.example', password: 'floaq1234!' },
} as const;

/**
 * 로그인이 풀렸음을 App 에 알리는 이벤트. 토큰이 만료·무효가 되면 어느 화면에서든 로그인 화면으로 돌아가야 한다.
 * 화면 상태를 들고 있는 것은 App 이라 여기서는 알리기만 한다.
 */
export const AUTH_EXPIRED_EVENT = 'floaq:auth-expired';

const LS_SESSION = 'floaq.web.session';
const LS_TOKEN = 'floaq.web.token';

// ── 서버 로그인 ─────────────────────────────────────────────

/** 서버가 주는 역할 값. A = 해경 · SA = 운영 관리자 (2026-09-16 짧은 이름으로 바뀜) */
type ApiRole = 'A' | 'SA';
type ApiStatus = 'WAIT' | 'ACTIVE' | 'REJECTED' | 'DELETED';

/** 서버의 계정 모양 (UserView) */
interface ApiUser {
  userId: number;
  loginId: string;
  name: string;
  role: ApiRole;
  status: ApiStatus;
}

interface StoredToken {
  accessToken: string;
  /** ISO-8601. refresh token 이 없어 이 시각이 지나면 다시 로그인한다 */
  expiresAt: string;
}

/** 서버 오류 코드 → 화면 문구. 문구가 아니라 code 로 가른다(docs/api.md §7) */
const LOGIN_ERROR_OF: Record<string, LoginError> = {
  AUTH_INVALID_CREDENTIALS: 'invalid',
  AUTH_ACCOUNT_PENDING: 'pending',
  AUTH_ACCOUNT_REJECTED: 'rejected',
  AUTH_ACCOUNT_DELETED: 'deleted',
};

const roleOf = (r: ApiRole): Role => (r === 'SA' ? 'superadmin' : 'admin');

const fromApi = (u: ApiUser): Session => ({
  id: String(u.userId),
  email: u.loginId,
  name: u.name,
  role: roleOf(u.role),
});

function storeSession(session: Session) {
  try { localStorage.setItem(LS_SESSION, JSON.stringify(session)); } catch { /* 새로고침하면 다시 로그인 */ }
}

/** 만료된 토큰은 없는 것과 같다. 보내 봐야 401 이다 */
function liveToken(): string | null {
  try {
    const s = localStorage.getItem(LS_TOKEN);
    if (!s) return null;
    const t = JSON.parse(s) as StoredToken;
    return Date.parse(t.expiresAt) > Date.now() ? t.accessToken : null;
  } catch {
    return null;
  }
}

/**
 * 토큰을 붙여 부른다. 401 이면 저장된 로그인을 지우고 App 에 알린다.
 * 망 오류는 그대로 던진다 — 부르는 쪽이 "서버에 연결할 수 없음"으로 바꾼다.
 */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = liveToken();
  const res = await fetch(path, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (res.status === 401) {
    logout();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }
  return res;
}

export async function login(
  email: string, password: string,
): Promise<{ ok: true; session: Session } | { ok: false; error: LoginError }> {
  let res: Response;
  try {
    res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ loginId: email.trim(), password }),
    });
  } catch {
    return { ok: false, error: 'server' };
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    // 400 은 형식이 틀린 입력(너무 긴 이메일 등)이다. 사용자에게는 틀린 것과 같다
    const error = LOGIN_ERROR_OF[body?.code] ?? (res.status === 400 ? 'invalid' : 'server');
    return { ok: false, error };
  }
  const data = body.data as { accessToken: string; expiresAt: string; user: ApiUser };
  const session = fromApi(data.user);
  try {
    localStorage.setItem(LS_TOKEN, JSON.stringify({ accessToken: data.accessToken, expiresAt: data.expiresAt }));
  } catch { /* 저장소가 막혀 있으면 새로고침할 때 다시 로그인한다 */ }
  storeSession(session);
  return { ok: true, session };
}

/** 첫 화면을 바로 그리기 위한 값. 토큰이 만료됐으면 로그인 전으로 본다. 서버 확인은 refreshSession 이 한다 */
export function currentSession(): Session | null {
  if (!liveToken()) {
    logout();
    return null;
  }
  try {
    const s = localStorage.getItem(LS_SESSION);
    return s ? (JSON.parse(s) as Session) : null;
  } catch {
    return null;
  }
}

/**
 * 저장해 둔 로그인이 아직 유효한지 서버에 묻는다. 새로고침 직후 한 번 부른다.
 * 토큰이 살아 있어도 그사이 계정이 비활성화됐으면 서버가 403 을 준다 — 그때 로그아웃된다.
 * 서버에 닿지 않으면 저장해 둔 값을 그대로 쓴다. 망이 잠깐 끊겼다고 관제 화면을 닫지 않는다.
 */
export async function refreshSession(): Promise<Session | null> {
  const token = liveToken();
  if (!token) {
    logout();
    return null;
  }
  let res: Response;
  try {
    res = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    return currentSession();
  }
  if (res.status === 401 || res.status === 403) {
    logout();
    return null;
  }
  if (!res.ok) return currentSession();
  const body = await res.json();
  const session = fromApi(body.data as ApiUser);
  storeSession(session);
  return session;
}

export function logout() {
  try {
    localStorage.removeItem(LS_TOKEN);
    localStorage.removeItem(LS_SESSION);
  } catch { /* 저장된 게 없으면 할 일도 없다 */ }
}

// ── 가입 신청 ───────────────────────────────────────────────

/**
 * 가입 신청. 서버가 A + WAIT 로 만든다.
 * 반려된 이메일은 다시 신청할 수 있다 — 서버가 옛 신청을 지우고 새로 받는다.
 * 대기 · 승인 · 비활성화된 이메일은 중복(duplicate)이다.
 */
export async function apply(f: ApplyForm): Promise<{ ok: true } | { ok: false; error: ApplyError }> {
  let res: Response;
  try {
    res = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ loginId: f.email.trim(), password: f.password, name: f.name.trim() }),
    });
  } catch {
    return { ok: false, error: 'server' };
  }
  if (res.ok) return { ok: true };
  const body = await res.json().catch(() => null);
  if (body?.code === 'AUTH_ALREADY_REGISTERED') return { ok: false, error: 'duplicate' };
  return { ok: false, error: res.status === 400 ? 'invalid' : 'server' };
}

// ── 계정 관리 (SA) ─────────────────────────────────

/** 서버의 계정 관리 한 줄 (AdminUserView) */
interface ApiAdminUser extends ApiUser {
  createdAt: string;
  updatedAt: string | null;
}

/** 한 번에 받는 신청 수. 서버 상한(100)과 같다 — 넘치면 다음 페이지를 이어 받는다 */
export const ADMIN_PAGE_SIZE = 100;
/** 페이지를 끝없이 넘기지 않게 막는 상한. 신청이 이만큼 쌓이면 화면을 다시 설계해야 한다 */
export const ADMIN_MAX_PAGES = 20;

const pad = (n: number) => String(n).padStart(2, '0');
/** ISO-8601 → 'YYYY-MM-DD HH:MM' (브라우저 시간대) */
export const minuteText = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const STATUS_OF: Partial<Record<ApiStatus, AccountStatus>> = { WAIT: 'wait', ACTIVE: 'active', REJECTED: 'rejected' };

export const adminErrorOf = (status: number): AdminError =>
  status === 401 ? 'expired'
    : status === 403 ? 'forbidden'
      : status === 404 || status === 409 ? 'conflict'
        : 'server';

/** 해경 계정 신청 목록. 승인 대기가 위(먼저 신청한 순), 처리한 건은 최근 처리 순 */
export async function applications(): Promise<{ ok: true; list: Account[] } | { ok: false; error: AdminError }> {
  const rows: ApiAdminUser[] = [];
  try {
    for (let page = 0; page < ADMIN_MAX_PAGES; page += 1) {
      const res = await authFetch(`/api/admin/users?page=${page}&size=${ADMIN_PAGE_SIZE}`);
      if (!res.ok) return { ok: false, error: adminErrorOf(res.status) };
      const body = await res.json();
      rows.push(...(body.data.content as ApiAdminUser[]));
      if (!body.data.hasNext) break;
    }
  } catch {
    return { ok: false, error: 'server' };
  }

  // 관리자 계정은 승인·반려 대상이 아니다(서버도 막는다). 비활성화 계정은 서버가 이미 뺐다
  const list: Account[] = rows
    .filter((u) => u.role === 'A' && STATUS_OF[u.status])
    .map((u) => ({
      id: String(u.userId),
      email: u.loginId,
      name: u.name,
      role: roleOf(u.role),
      status: STATUS_OF[u.status]!,
      appliedAt: minuteText(u.createdAt),
      decidedAt: u.status !== 'WAIT' && u.updatedAt ? minuteText(u.updatedAt) : null,
    }));
  const waiting = list.filter((x) => x.status === 'wait').sort((a, b) => a.appliedAt.localeCompare(b.appliedAt));
  const decided = list.filter((x) => x.status !== 'wait')
    .sort((a, b) => (b.decidedAt ?? '').localeCompare(a.decidedAt ?? ''));
  return { ok: true, list: [...waiting, ...decided] };
}

/**
 * 계정 삭제(api.md §3.2 `POST /api/admin/users/{userId}/deactivate`).
 *
 * <p>행을 지우지 않고 상태를 `DELETED` 로 바꾼다 — 그 계정이 처리한 사고 기록이
 * 남아 있어서다. 로그인은 막히고(AUTH_ACCOUNT_DELETED 403) 목록에서도 빠진다.</p>
 */
export async function deactivate(id: string): Promise<{ ok: true } | { ok: false; error: AdminError }> {
  let res: Response;
  try {
    res = await authFetch(`/api/admin/users/${encodeURIComponent(id)}/deactivate`, { method: 'POST' });
  } catch {
    return { ok: false, error: 'server' };
  }
  return res.ok ? { ok: true } : { ok: false, error: adminErrorOf(res.status) };
}

/** 승인(true) · 반려(false). 대기 중인 신청에만 적용된다 — 이미 처리됐으면 conflict */
export async function decide(id: string, approve: boolean): Promise<{ ok: true } | { ok: false; error: AdminError }> {
  let res: Response;
  try {
    res = await authFetch(`/api/admin/users/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`, { method: 'POST' });
  } catch {
    return { ok: false, error: 'server' };
  }
  return res.ok ? { ok: true } : { ok: false, error: adminErrorOf(res.status) };
}

import { useEffect, useState } from 'react';

/**
 * 새로고침 너머로 <b>보던 자리</b>를 기억한다.
 *
 * <p>F5 를 누르면 탭이 전부 처음으로 튕겼다 — 기록의 등록 선박을 보던 중이었어도 종결된 사고로,
 * 계정 관리의 선박 등록을 보던 중이었어도 해경 계정으로 돌아갔다. 새로고침은 <b>화면을 다시
 * 그리라는 뜻</b>이지 처음으로 가라는 뜻이 아니다(2026-09-20).</p>
 *
 * <p>{@code sessionStorage} 를 쓴다 — <b>브라우저 탭을 닫으면 잊는다.</b> 다음에 새로 열면
 * 다시 처음 자리에서 시작한다. {@code localStorage} 였다면 어제 선박 목록에서 끝낸 사람이
 * 오늘도 거기서 시작하는데, 들어올 때의 첫 질문은 늘 "지금 무슨 일이 벌어지나"다.</p>
 *
 * <p>읽고 쓰는 것이 <b>둘 다 실패할 수 있다</b>(사생활 보호 모드·저장 공간 꽉 참).
 * 그때는 기억을 못 할 뿐 화면은 그대로 돈다.</p>
 */
const KEYS = new Set<string>();

/** 저장된 값을 읽는다. 아는 값이 아니면 {@code null} — 예전 판에서 쓰던 값이 남아 있을 수 있다 */
export function readSticky<T extends string>(key: string, allowed: readonly T[]): T | null {
  try {
    const v = sessionStorage.getItem(key);
    return allowed.includes(v as T) ? (v as T) : null;
  } catch {
    return null;
  }
}

/**
 * {@code useState} 와 같은데 <b>새로고침을 견딘다</b>.
 *
 * @param allowed 허용값 목록. 저장된 값이 여기 없으면 무시한다
 */
export function useSticky<T extends string>(key: string, allowed: readonly T[], fallback: T) {
  KEYS.add(key);
  const [v, set] = useState<T>(() => readSticky(key, allowed) ?? fallback);
  useEffect(() => {
    try { sessionStorage.setItem(key, v); } catch { /* 저장만 실패한다 */ }
  }, [key, v]);
  return [v, set] as const;
}

/**
 * 기억을 지운다. <b>로그아웃할 때 부른다</b> — 관제실은 한 대를 여럿이 쓰는 자리라,
 * 다음 사람이 앞사람 보던 화면에서 시작하면 안 된다.
 */
export function forgetSticky() {
  try { KEYS.forEach((k) => sessionStorage.removeItem(k)); } catch { /* 지우기만 실패한다 */ }
}

/** 최상위 탭 — 사고 · 기록 · 계정 관리 */
export const VIEW_KEY = 'floaq.view';
/** 기록 탭 안 — 종결된 사고 · 등록 선박 */
export const LOG_TAB_KEY = 'floaq.logTab';
/** 계정 관리 안 — 해경 계정 · 선박 등록 */
export const ADMIN_TAB_KEY = 'floaq.adminTab';

package com.floaq.auth.entity;

/**
 * 계정 상태 (ERD {@code users.status}).
 *
 * <p>셀프 가입을 열지 않는다 — {@code WAIT} 로 신청되고 SA 이 {@code ACTIVE} 로
 * 승인하거나 {@code REJECTED} 로 반려한다(계획.md §9.13 · WEB-02·07).</p>
 */
public enum UserStatus {
    /** 가입 신청됨. 승인 대기 */
    WAIT,
    ACTIVE,
    /**
     * 가입 신청이 반려됨(V5). ⚠ ERD 에 없다.
     * 비활성화({@code DELETED})와 가른다 — 반려는 계정이 된 적이 없는 신청이라 로그인 문구도 관리 화면도 다르다.
     */
    REJECTED,
    DELETED
}

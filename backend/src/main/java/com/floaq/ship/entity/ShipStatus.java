package com.floaq.ship.entity;

/**
 * 선박 등록 상태 (V8 {@code ship.status}).
 *
 * <p>선내 kiosk 에서 신청하면 {@code WAIT} 로 들어오고 SUPER_ADMIN 이 {@code ACTIVE} 로 승인하거나
 * {@code REJECTED} 로 반려한다 (WEB-08 · W-05 · docs/api.md §3.3).</p>
 *
 * <p>값 이름을 {@link com.floaq.auth.entity.UserStatus} 와 맞췄다 — 관제 웹이 계정 승인과
 * 같은 컴포넌트로 그린다(apps/web SuperAdmin.tsx).</p>
 *
 * <p><b>{@code DELETED} 가 없다.</b> 선박의 논리 삭제는 {@code is_deleted} 컬럼이 따로 본다 —
 * 상태에도 넣으면 둘 중 어느 쪽이 진실인지 알 수 없는 행이 생긴다.</p>
 */
public enum ShipStatus {
    /** 선내 단말에서 등록 신청됨. 승인 대기 */
    WAIT,
    /** 승인됨. V8 이전에 SA 가 직접 등록한 행도 여기로 넣었다(V8 마이그레이션 주석) */
    ACTIVE,
    /** 반려됨. 행은 지우지 않는다 — 같은 배가 고쳐서 다시 신청할 수 있어야 한다(uq_ship_registration_no) */
    REJECTED
}

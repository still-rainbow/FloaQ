package com.floaq.auth.entity;

/**
 * 관제 웹 역할 2종 (ERD {@code users.role}).
 *
 * <p><b>A 가 해경이다.</b> 상세기획이 쓰는 이름을 그대로 값으로 삼는다(2026-09-16) —
 * 문서는 A, DB 는 {@code ADMIN} 이면 읽는 쪽이 매번 옮겨 적어야 한다.
 * {@code SA} 는 운영 관리자다.</p>
 *
 * <p>조회 범위가 다르다 — A 는 <b>신고받은 사고만</b> 보고, SA 는 사고 화면 자체가 없다
 * (계획.md §9.13 · docs/api.md §3.4). 대신 계정·선박 등록 승인을 한다.</p>
 *
 * <p>이 이름이 그대로 <b>DB 값이자 JWT {@code role} 클레임</b>이고,
 * Spring Security 에서는 {@code ROLE_A} · {@code ROLE_SA} 가 된다(SecurityConfig).
 * 셋이 한 값에 묶여 있어 여기를 고치면 마이그레이션도 같이 필요하다(V10).</p>
 */
public enum UserRole {
    A, SA
}

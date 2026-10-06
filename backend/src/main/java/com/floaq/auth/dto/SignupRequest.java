package com.floaq.auth.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 가입 신청 요청 (docs/api.md §3.1) — 기관 이메일 · 비밀번호 · 이름.
 *
 * <p>소속 · 부서 · 계급 · 연락처 · 재직증명서는 받지 않는다(2026-09-15 결정).
 * 해경 쪽에서는 신고를 받았는지만 알 수 있고 누가·어디서 담당하는지는 알 수 없어, 계정에 소속을 둘 이유가 없다.</p>
 *
 * <p>역할·상태는 요청에 없다 — 가입 신청은 항상 A + WAIT 다.</p>
 */
public record SignupRequest(
        /** 기관 이메일. {@code users.login_id} varchar(64) */
        @NotBlank @Email @Size(max = 64) String loginId,
        /** 8자 이상. 72바이트 상한은 서비스가 본다 — 글자 수가 아니라 바이트라서 여기서 못 막는다 */
        @NotBlank @Size(min = 8) String password,
        /** {@code users.name} varchar(20) */
        @NotBlank @Size(max = 20) String name
) {

    /**
     * 앞뒤 공백을 검증 전에 지운다. 검증은 이 생성자가 만든 값을 본다 —
     * 여기서 안 지우면 {@code " kim@kcg.example"} 이 {@code @Email} 에서 먼저 떨어져,
     * 로그인은 받는 모양을 가입만 형식 오류로 거절한다. 비밀번호는 공백도 비밀번호라 건드리지 않는다.
     */
    public SignupRequest {
        loginId = loginId == null ? null : loginId.trim();
        name = name == null ? null : name.trim();
    }
}

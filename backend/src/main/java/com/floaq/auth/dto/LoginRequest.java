package com.floaq.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 로그인 요청 (docs/api.md §3.1). {@code loginId} 는 기관 이메일이다.
 *
 * <p>비밀번호 길이를 여기서 막지 않는다 — 길이 규칙이 어긋나면 400 으로 "틀린 형식"을 알려 주게 되고,
 * 그건 가입 규칙을 흘린다. 72바이트를 넘으면 서비스가 틀린 비밀번호와 같게 처리한다.</p>
 */
public record LoginRequest(
        @NotBlank @Size(max = 64) String loginId,
        @NotBlank String password
) {
}

package com.floaq.auth.dto;

import java.time.Instant;

/**
 * 로그인 응답 (docs/api.md §3.1).
 *
 * <p>{@code expiresAt} 을 함께 준다 — refresh token 이 없어서, 화면이 만료 전에
 * "곧 다시 로그인해야 한다"를 알릴 방법이 이것뿐이다.</p>
 */
public record LoginResponse(String accessToken, String tokenType, Instant expiresAt, UserView user) {
}

package com.floaq.auth;

import com.floaq.auth.dto.LoginRequest;
import com.floaq.auth.dto.LoginResponse;
import com.floaq.auth.dto.SignupRequest;
import com.floaq.auth.dto.SignupResponse;
import com.floaq.auth.dto.UserView;
import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.response.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관제 웹 로그인 (docs/api.md §3.1).
 *
 * <p>로그아웃 API 는 없다 — 무상태 JWT 라 클라이언트가 토큰을 버린다.</p>
 */
@Tag(name = "auth", description = "관제 웹 로그인")
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService auth;

    @PostMapping("/login")
    @Operation(summary = "로그인 → JWT (loginId 는 기관 이메일)")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.ok(auth.login(request));
    }

    @PostMapping("/signup")
    @ResponseStatus(HttpStatus.CREATED)
    @Operation(summary = "가입 신청 → 승인 대기 (항상 A · WAIT)")
    public ApiResponse<SignupResponse> signup(@Valid @RequestBody SignupRequest request) {
        return ApiResponse.ok("가입 신청이 접수됐습니다.", auth.signup(request));
    }

    @GetMapping("/me")
    @Operation(summary = "내 계정")
    @SecurityRequirement(name = OpenApiConfig.JWT_SCHEME)
    public ApiResponse<UserView> me(@AuthenticationPrincipal Jwt jwt) {
        return ApiResponse.ok(auth.me(Long.parseLong(jwt.getSubject())));
    }
}

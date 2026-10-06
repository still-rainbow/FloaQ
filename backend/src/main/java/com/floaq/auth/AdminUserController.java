package com.floaq.auth;

import com.floaq.auth.dto.AdminUserView;
import com.floaq.auth.entity.UserStatus;
import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.response.ApiResponse;
import com.floaq.global.response.PageView;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 계정 관리 (SA · docs/api.md §3.2). 권한은 SecurityConfig 의 {@code /api/admin/**} 가 막는다.
 */
@Tag(name = "admin-users", description = "계정 관리 (SA)")
@RestController
@RequestMapping("/api/admin/users")
@RequiredArgsConstructor
@SecurityRequirement(name = OpenApiConfig.JWT_SCHEME)
public class AdminUserController {

    private final AdminUserService admin;

    @GetMapping
    @Operation(summary = "계정 목록 (status 생략 시 비활성화 계정만 뺀 전체, 최근 신청 순)")
    public ApiResponse<PageView<AdminUserView>> list(
            @RequestParam(required = false) UserStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(admin.list(status, page, size));
    }

    @PostMapping("/{userId}/approve")
    @Operation(summary = "승인 WAIT → ACTIVE")
    public ApiResponse<AdminUserView> approve(@PathVariable long userId) {
        return ApiResponse.ok(admin.approve(userId));
    }

    @PostMapping("/{userId}/reject")
    @Operation(summary = "반려 WAIT → REJECTED")
    public ApiResponse<AdminUserView> reject(@PathVariable long userId) {
        return ApiResponse.ok(admin.reject(userId));
    }

    /** 승인·반려가 <b>신청</b>을 처리하는 것과 달리, 이것은 <b>쓰던 계정</b>을 끊는다 */
    @PostMapping("/{userId}/deactivate")
    @Operation(summary = "비활성화 ACTIVE → DELETED. 행은 남긴다 — 지난 사고의 접수자가 참조한다")
    public ApiResponse<AdminUserView> deactivate(@PathVariable long userId) {
        return ApiResponse.ok(admin.deactivate(userId));
    }
}

package com.floaq.ship;

import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.response.ApiResponse;
import com.floaq.global.response.PageView;
import com.floaq.ship.dto.AdminShipView;
import com.floaq.ship.entity.ShipStatus;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 선박 등록 관리 (SUPER_ADMIN · docs/api.md §3.3). 권한은 SecurityConfig 의 {@code /api/admin/**} 가 막는다.
 */
@Tag(name = "admin-ships", description = "선박 등록 관리 (SUPER_ADMIN)")
@RestController
@RequestMapping("/api/admin/ships")
@RequiredArgsConstructor
@SecurityRequirement(name = OpenApiConfig.JWT_SCHEME)
public class AdminShipController {

    private final AdminShipService admin;

    @GetMapping
    @Operation(summary = "선박 등록 목록 (status 생략 시 논리 삭제만 뺀 전체, 최근 신청 순)")
    public ApiResponse<PageView<AdminShipView>> list(
            @RequestParam(required = false) ShipStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(admin.list(status, page, size));
    }

    @PostMapping("/{shipId}/approve")
    @Operation(summary = "승인 WAIT → ACTIVE")
    public ApiResponse<AdminShipView> approve(@PathVariable UUID shipId, @AuthenticationPrincipal Jwt jwt) {
        return ApiResponse.ok(admin.approve(shipId, Long.parseLong(jwt.getSubject())));
    }

    @PostMapping("/{shipId}/reject")
    @Operation(summary = "반려 WAIT → REJECTED")
    public ApiResponse<AdminShipView> reject(@PathVariable UUID shipId, @AuthenticationPrincipal Jwt jwt) {
        return ApiResponse.ok(admin.reject(shipId, Long.parseLong(jwt.getSubject())));
    }
}

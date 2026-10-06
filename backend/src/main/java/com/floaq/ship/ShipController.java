package com.floaq.ship;

import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.response.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 선박 자체에 대한 조작 (SUPER_ADMIN · docs/api.md §3.3).
 *
 * <p>승인·반려는 {@link AdminShipController}(`/api/admin/ships`)가 받는다. 여기는 <b>배 한 척</b>을
 * 가리키는 경로다 — 규격이 {@code /api/ships/{shipId}} 로 정해져 있고 관제 화면도 그리로 부른다.</p>
 *
 * <p>⚠ 이 경로는 {@code /api/admin/**} 이 아니라서 {@code SecurityConfig} 의 SA 규칙에 안 걸린다.
 * 거기에 <b>DELETE 전용 규칙을 따로 걸어 뒀다</b> — 안 걸면 해경 계정도 배를 지울 수 있다.</p>
 */
@Tag(name = "ships", description = "선박 (SUPER_ADMIN)")
@RestController
@RequestMapping("/api/ships")
@RequiredArgsConstructor
@SecurityRequirement(name = OpenApiConfig.JWT_SCHEME)
public class ShipController {

    private final AdminShipService admin;

    /**
     * 논리 삭제. 성공하면 본문 없이 204 다 — 지운 배를 되돌려 줄 이유가 없다.
     *
     * <p>오류: 없는 배 404 {@code SHIP_NOT_FOUND} · 진행 중 사고가 있으면 409 {@code INVALID_STATE}.</p>
     */
    @DeleteMapping("/{shipId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Operation(summary = "선박 삭제 — 논리 삭제. 진행 중 사고가 있으면 409")
    public void remove(@PathVariable UUID shipId) {
        admin.remove(shipId);
    }
}

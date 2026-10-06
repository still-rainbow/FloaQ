package com.floaq.auth.dto;

import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;

import java.time.Instant;

/**
 * 계정 관리 목록의 한 줄 (docs/api.md §3.2).
 *
 * <p>{@code updatedAt} 을 함께 준다 — 승인·반려 시각 컬럼이 따로 없어, 처리된 신청에서는 이 값이
 * "언제 처리했나"다. 계정을 나중에 또 바꾸면 그 시각으로 밀린다는 한계가 있다.</p>
 */
public record AdminUserView(Long userId, String loginId, String name, UserRole role, UserStatus status,
                            Instant createdAt, Instant updatedAt) {

    public static AdminUserView of(User user) {
        return new AdminUserView(user.getUserId(), user.getLoginId(), user.getName(), user.getRole(),
                user.getStatus(), user.getCreatedAt(), user.getUpdatedAt());
    }
}

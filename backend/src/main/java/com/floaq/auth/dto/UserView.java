package com.floaq.auth.dto;

import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;

/** 로그인 응답의 {@code user} 이자 {@code /api/auth/me} 의 {@code data}. 비밀번호 해시는 싣지 않는다 */
public record UserView(Long userId, String loginId, String name, UserRole role, UserStatus status) {

    public static UserView of(User user) {
        return new UserView(user.getUserId(), user.getLoginId(), user.getName(), user.getRole(), user.getStatus());
    }
}

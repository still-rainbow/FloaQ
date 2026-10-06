package com.floaq.auth.dto;

import com.floaq.auth.entity.UserStatus;

/** 가입 신청 응답 (docs/api.md §3.1). 상태는 항상 WAIT 다 — 화면이 "승인 대기"를 안내하는 근거다 */
public record SignupResponse(Long userId, UserStatus status) {
}

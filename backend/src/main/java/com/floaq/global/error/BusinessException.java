package com.floaq.global.error;

import lombok.Getter;

/**
 * 업무 규칙 위반. {@link GlobalExceptionHandler} 가 받아 {@link ErrorCode} 의
 * HTTP 상태와 코드로 응답한다.
 *
 * <p>기술적 실패(DB 두절·타임아웃)에는 쓰지 않는다 — 그쪽은 500 으로 올라가야
 * 로그와 알림에 잡힌다. 여기로 감싸면 장애가 정상 응답으로 둔갑한다.</p>
 */
@Getter
public class BusinessException extends RuntimeException {

    private final transient ErrorCode errorCode;

    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    /** 기본 문구로 설명이 부족할 때만. 사용자에게 보이는 문장이므로 내부 정보를 넣지 않는다. */
    public BusinessException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }
}

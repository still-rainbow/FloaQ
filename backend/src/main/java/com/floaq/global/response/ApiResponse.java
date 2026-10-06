package com.floaq.global.response;

/**
 * 성공 응답 포맷 — {@code {success, message, data}}.
 *
 * <p>오류는 이 타입을 쓰지 않는다. {@link ErrorResponse} 가 따로 있다 —
 * 성공과 실패를 같은 껍데기에 담으면 클라이언트가 {@code success} 를 매번 확인해야 하고,
 * 빠뜨리면 실패 응답을 성공으로 읽는다. HTTP 상태 코드와 본문 형태를 함께 갈라 둔다.</p>
 */
public record ApiResponse<T>(boolean success, String message, T data) {

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(true, "OK", data);
    }

    public static <T> ApiResponse<T> ok(String message, T data) {
        return new ApiResponse<>(true, message, data);
    }

    public static ApiResponse<Void> ok(String message) {
        return new ApiResponse<>(true, message, null);
    }
}

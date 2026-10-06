package com.floaq.global.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.floaq.pi.PiFailure;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 오류 응답 포맷 — 모든 실패 본문이 이 형태다.
 *
 * <p>{@code code} 는 {@link com.floaq.global.error.ErrorCode} 의 값이 그대로 나간다.
 * 프론트가 문구가 아니라 코드로 분기하므로 **코드 문자열을 바꾸면 화면이 깨진다** —
 * 예: {@code apps/kiosk/src/pages/Kiosk.tsx} 의 REJECT_TEXT 가 이 값을 키로 쓴다.</p>
 *
 * <p>{@code path} 와 {@code timestamp} 는 사고 경위를 나중에 재구성하기 위한 것이다.
 * nginx 액세스 로그의 {@code $request_id} 와 함께 보면 한 요청의 전체 경로가 이어진다(계획.md §5③).</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ErrorResponse(String code, String message, String path, OffsetDateTime timestamp,
                            List<PiFailure> failed) {

    public static ErrorResponse of(String code, String message, String path) {
        return new ErrorResponse(code, message, path, OffsetDateTime.now(), null);
    }

    /**
     * Pi 배치 거절 — <b>어느 원소가 왜 거절됐는지 반드시 싣는다</b> (docs/api.md §4.1).
     *
     * <p>{@code failed} 가 없으면 Pi 는 배치의 나머지를 버릴지 다시 보낼지 알 수 없다.
     * 두절 복귀 때 밀린 부표 위치 300건 중 1건이 아직 안 올라간 사고를 가리키는 일은 흔하고,
     * 그 1건 때문에 300건이 실패로 찍히면 조용한 손실이다.</p>
     */
    public static ErrorResponse of(String code, String message, String path, List<PiFailure> failed) {
        return new ErrorResponse(code, message, path, OffsetDateTime.now(), failed);
    }
}

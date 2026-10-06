package com.floaq.global.error;

import com.floaq.global.response.ErrorResponse;
import com.floaq.pi.PiBatchException;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

/**
 * 모든 오류 응답을 {@link ErrorResponse} 한 형태로 강제한다.
 *
 * <p>이게 없으면 Spring 기본 오류 본문({@code {timestamp, status, error, path}})이 섞여 나가고,
 * 프론트가 두 형태를 다 파싱해야 한다.</p>
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusiness(BusinessException e, HttpServletRequest req) {
        ErrorCode ec = e.getErrorCode();
        // 업무 규칙 위반은 정상 흐름이라 stack trace 를 남기지 않는다 — 남기면 진짜 장애가 묻힌다
        return ResponseEntity.status(ec.getStatus())
                .body(ErrorResponse.of(ec.getCode(), e.getMessage(), req.getRequestURI()));
    }

    /** Bean Validation 실패 — 어느 필드가 왜 틀렸는지 첫 건을 그대로 보여준다. */
    /**
     * Pi 배치 거절 — <b>어느 원소가 왜 거절됐는지를 {@code failed} 로 돌려준다</b>(docs/api.md §4.1).
     *
     * <p>이게 없으면 Pi 는 배치의 나머지를 버릴지 다시 보낼지 알 수 없다. 두절 복귀 때 밀린
     * 부표 위치 300건 중 1건이 아직 안 올라간 사고를 가리키는 일은 흔하고, 그 1건 때문에
     * 300건이 실패로 찍히면 조용한 손실이다.</p>
     */
    @ExceptionHandler(PiBatchException.class)
    public ResponseEntity<ErrorResponse> handlePiBatch(PiBatchException e, HttpServletRequest req) {
        ErrorCode code = e.getErrorCode();
        log.warn("pi 배치 거절 {} — {}건 (path={})", code.getCode(), e.getFailures().size(), req.getRequestURI());
        return ResponseEntity.status(code.getStatus())
                .body(ErrorResponse.of(code.getCode(), code.getMessage(), req.getRequestURI(), e.getFailures()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException e,
                                                          HttpServletRequest req) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
                .orElse(ErrorCode.INVALID_INPUT.getMessage());
        return badRequest(msg, req);
    }

    /**
     * 🔴 {@code MissingServletRequestPartException} 이 여기 있어야 한다 (2026-09-18).
     *
     * <p>빠뜨리면 multipart 필드를 안 보낸 요청이 <b>500</b> 으로 나간다. dev-iot
     * {@code tools/probe_archive.py} 의 판별 세트가 <i>"일부러 틀린 것에도 500 이면
     * 서버 핸들러 문제다"</i> 로 읽으므로, 400 이어야 할 자리에서 500 을 주면
     * <b>IoT 쪽이 우리 핸들러가 터진 줄로 오판한다.</b> 실제로 그 도구가 만들어진 이유다.</p>
     */
    @ExceptionHandler({
            HttpMessageNotReadableException.class,
            HandlerMethodValidationException.class,
            MissingServletRequestParameterException.class,
            MissingServletRequestPartException.class,
            MethodArgumentTypeMismatchException.class,
    })
    public ResponseEntity<ErrorResponse> handleBadRequest(Exception e, HttpServletRequest req) {
        return badRequest(ErrorCode.INVALID_INPUT.getMessage(), req);
    }

    /**
     * 업로드 상한 초과 — 사고 프레임 tar (api.md §4 {@code POST /api/pi/frames}).
     *
     * <p>업무 규칙 위반과 같이 <b>정상 흐름</b>이라 stack trace 를 남기지 않는다.
     * Pi 는 이 응답을 받고 청크를 쪼개 다시 보낸다({@code chunk_seq} 를 새로 매기고 {@code frame_count} 를 줄인다) —
     * 재시도가 아니라 분할이므로 같은 크기로 다시 오지 않는다.</p>
     *
     * <p>⚠ 이게 자주 찍히면 상한이 낮은 것이다. {@code spring.servlet.multipart} 와
     * nginx {@code client_max_body_size} 를 <b>같이</b> 올린다 — 한쪽만 올리면 증상이 엉뚱한 데서 난다
     * (nginx 가 먼저 끊으면 이 JSON 대신 nginx HTML 이 나가 Pi 가 분할 신호를 못 받는다).</p>
     */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ErrorResponse> handleTooLarge(MaxUploadSizeExceededException e, HttpServletRequest req) {
        ErrorCode ec = ErrorCode.MEDIA_TOO_LARGE;
        log.warn("업로드 상한 초과 - {} {} (상한 {}바이트)", req.getMethod(), req.getRequestURI(), e.getMaxUploadSize());
        return ResponseEntity.status(ec.getStatus())
                .body(ErrorResponse.of(ec.getCode(), ec.getMessage(), req.getRequestURI()));
    }

    /**
     * 마지막 그물. <b>여기서는 반드시 stack trace 를 남긴다</b> —
     * 예상 못 한 실패라 로그가 유일한 단서다. 클라이언트에는 내부 메시지를 노출하지 않는다
     * (예외 문구에 쿼리·경로·키가 섞여 나올 수 있다).
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpected(Exception e, HttpServletRequest req) {
        ErrorCode ec = ErrorCode.INTERNAL_ERROR;
        log.error("처리되지 않은 예외 - {} {}", req.getMethod(), req.getRequestURI(), e);
        return ResponseEntity.status(ec.getStatus())
                .body(ErrorResponse.of(ec.getCode(), ec.getMessage(), req.getRequestURI()));
    }

    private ResponseEntity<ErrorResponse> badRequest(String message, HttpServletRequest req) {
        ErrorCode ec = ErrorCode.INVALID_INPUT;
        return ResponseEntity.status(ec.getStatus())
                .body(ErrorResponse.of(ec.getCode(), message, req.getRequestURI()));
    }
}

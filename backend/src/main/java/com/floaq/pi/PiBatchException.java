package com.floaq.pi;

import com.floaq.global.error.ErrorCode;
import lombok.Getter;

import java.util.List;

/**
 * 배치 전체 거절. <b>원소 하나가 거절되면 전부 반영하지 않는다</b>(docs/api.md §4.1) —
 * 일부만 들어가면 Pi 가 어디까지 성공했는지 알 수 없다.
 *
 * <p>거절된 원소 목록을 들고 나가서 {@code ErrorResponse.failed} 로 실린다.</p>
 */
@Getter
public class PiBatchException extends RuntimeException {

    private final ErrorCode errorCode;
    private final transient List<PiFailure> failures;

    public PiBatchException(ErrorCode errorCode, List<PiFailure> failures) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
        this.failures = failures;
    }
}

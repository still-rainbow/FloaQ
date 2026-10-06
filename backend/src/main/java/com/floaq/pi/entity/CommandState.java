package com.floaq.pi.entity;

/**
 * 명령 처리 상태 (docs/api.md §3.5).
 *
 * <p><b>배달된 것과 처리된 것은 다르다.</b> 관제 화면은 "종료 요청함"과 "종료됨"을 구분해야 한다 —
 * ack 없이 상태를 바꾸면 화면이 거짓말을 한다(계획.md §9.9).</p>
 */
public enum CommandState {
    ISSUED, DELIVERED, DONE, REJECTED, EXPIRED;

    /** Pi 가 아직 가져가지 않았거나 처리 중. 같은 사고·유형에 하나만 있을 수 있다 */
    public boolean isPending() {
        return this == ISSUED || this == DELIVERED;
    }
}

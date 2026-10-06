package com.floaq.accident.entity;

/**
 * 사고 상태 (상세기획 §3.1 · ERD {@code accident.status}).
 *
 * <pre>
 * DETECT ─▶ WAIT ─┬─[취소]─▶ CANCEL
 *                 ├─[즉시신고]──┐
 *                 └─30초 경과 ──┴▶ REPORT ─[구조확정|사고종료]─▶ CLOSE
 * </pre>
 *
 * <p>⚠ 프론트의 {@code IncidentStatus}(DETECTED/PENDING/REPORTED/CANCELLED/RESOLVED)와
 * 이름이 다르다. 변환은 {@code apps/kiosk/src/pi/decode.ts} 한 곳에서만 한다 —
 * DB·MQTT 페이로드가 이 이름이므로 서버는 이쪽을 쓴다.</p>
 */
public enum AccidentStatus {
    DETECT(1), WAIT(2), REPORT(3), CANCEL(4), CLOSE(5);

    private final int rank;

    AccidentStatus(int rank) {
        this.rank = rank;
    }

    /**
     * 상태 단조 판정용 순위 (docs/api.md §4.2).
     *
     * <p>Pi 수신은 <b>순위가 올라갈 때만</b> 현재 상태를 바꾼다. 낮은 순위가 오면 {@code stale} 이다 —
     * 두절 복귀 때 밀린 행이 순서가 뒤바뀌어 도착할 수 있고, 그때 <b>시각을 비교하지 않는다</b>
     * (Pi 와 서버의 시계 차이에 기대지 않기 위해서다).</p>
     *
     * <p>⚠ <b>{@code CANCEL} 과 {@code CLOSE} 는 둘 다 종료 상태인데 순위가 다르다.</b>
     * 선언 순서를 그대로 쓴 것이고, 둘 사이 전이가 없다는 전제 위에서만 맞다 —
     * Pi 상태머신의 {@code TERMINAL} 집합은 어떤 명령도 받지 않는다({@code database/pi.sql} · {@code core/state.py}).
     * 그 전제가 깨지면(오종결 후 재개 등) 여기부터 다시 봐야 한다.</p>
     */
    public int rank() {
        return rank;
    }

    /** 종료 상태. 어떤 명령도 받지 않는다 (docs/edge/mqtt.md §5.9). */
    public boolean isTerminal() {
        return this == CANCEL || this == CLOSE;
    }
}

package com.floaq.report.entity;

/**
 * 채널별 발신 상태 (database/pi.sql {@code pi_report}).
 *
 * <p>⚠ <b>{@code SENDING} 이 오래 지속되는 것이 정상이다.</b> DSC 확인응답은 해안국 운용자가
 * 수동으로 보내고(ITU-R M.541 §3.3) 무선전화로 대신 답하면 영영 오지 않는다 —
 * 화면에서 오류로 표시하면 안 된다(docs/edge/mqtt.md).</p>
 *
 * <p>전이는 {@code SENDING → ACKED|STOPPED|FAILED} 한 방향뿐이다. 역행은 옛 행({@code stale})이다.</p>
 */
public enum ReportStatus {
    SENDING, ACKED, STOPPED, FAILED
}

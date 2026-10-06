package com.floaq.report.entity;

/**
 * 신고 채널 (계획.md §9.4).
 *
 * <p><b>ACK 은 {@code DSC} 에만 온다.</b> AIS 는 단방향 브로드캐스트라 확인응답이 규격에 없다 —
 * AIS 채널에 {@code ackedAt} 이 채워지면 그건 버그다(DB CHECK 가 막는다).</p>
 */
public enum ReportChannel {
    AIS_MOB, AIS_SART, DSC
}

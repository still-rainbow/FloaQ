package com.floaq.accident.dto;

import com.floaq.report.entity.Report;
import com.floaq.report.entity.ReportChannel;
import com.floaq.report.entity.ReportFailReason;
import com.floaq.report.entity.ReportStatus;

import java.time.Instant;
import java.util.UUID;

/**
 * 채널별 신고 발신 기록 (docs/api.md §3.4).
 *
 * <p>{@code ackedAt}·{@code ackedBy} 는 <b>DSC 만</b> 값이 있다. AIS 는 단방향 브로드캐스트라
 * 규격상 확인응답이 없다.</p>
 *
 * <p>⚠ <b>{@code SENDING} 이 오래 가는 것은 정상이다.</b> 해안국 운용자가 수동으로 응답하고
 * 무선전화로 대신 답하면 영영 오지 않는다 — 화면이 오류로 표시하면 안 된다.</p>
 */
public record ReportView(
        UUID reportId,
        ReportChannel channel,
        ReportStatus status,
        Integer sentCount,
        Instant firstSentAt,
        Instant lastSentAt,
        Instant ackedAt,
        String ackedBy,
        ReportFailReason failReason,
        Double lat,
        Double lon) {

    public static ReportView of(Report r) {
        return new ReportView(r.getReportId(), r.getChannel(), r.getStatus(), r.getSentCount(),
                r.getFirstSentAt(), r.getLastSentAt(), r.getAckedAt(), r.getAckedBy(),
                r.getFailReason(), r.getReportLat(), r.getReportLon());
    }
}

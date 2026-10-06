package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.report.entity.ReportChannel;
import com.floaq.report.entity.ReportFailReason;
import com.floaq.report.entity.ReportStatus;
import com.floaq.report.entity.ReportTriggerKind;

import java.util.UUID;

/**
 * {@code POST /api/pi/reports} 원소 (dev-iot {@code sync.py} pi_report).
 *
 * <p><b>사고당 채널 1행</b>(V9 {@code uq_report_accident_channel}). 같은 채널이 두 행이면
 * "몇 번 보냈나"가 둘로 쪼개진다. 그래서 append 가 아니라 <b>채널별 upsert</b> 다.</p>
 *
 * <p>🔴 <b>{@code createdAt} 과 {@code firstSentAt} 은 다른 값이다.</b>
 * Pi 의 {@code first_sent_at} 은 NULL 일 수 있다 — 아직 한 번도 못 쏜 채널의 행이 먼저 생긴다
 * (예: 인터넷 두절로 {@code SENDING} 도 못 간 DSC). 서버 PK 가 {@code (report_id, created_at)} 라
 * {@code created_at} 에 {@code first_sent_at} 을 그대로 쓰면 그 행이 아예 못 들어간다.
 * <b>못 쏜 채널이야말로 관제가 봐야 하는 정보다</b> — 그래서 Pi 의 행 생성 시각을
 * {@code created_at} 으로 쓰고 {@code first_sent_at} 은 별도 컬럼에 둔다(V9 ④ 후보 ①).</p>
 *
 * <p>⚠ Pi 의 {@code report_type}(AUTO/MANUAL/RESCUE)은 받지 않는다 —
 * {@code accident.report_type}(DISTRESS/URGENCY/SAFETY)과 이름만 같고 뜻이 다르다.
 * Pi 가 {@code trigger_kind} 로 개명해 보낸다(ref/mqtt.md §8).</p>
 *
 * @param sentCount 누적. <b>줄어들면 옛 행(stale)</b>이라 반영하지 않는다(api.md §4.3)
 * @param ackedBy   9자리 MMSI. AIS 는 단방향이라 ACK 이 올 수 없다 — DSC 만 가능하다
 */
public record PiReport(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("channel") ReportChannel channel,
        @JsonProperty("trigger_kind") ReportTriggerKind triggerKind,
        @JsonProperty("status") ReportStatus status,
        @JsonProperty("sent_count") Integer sentCount,
        @JsonProperty("report_lat") Double reportLat,
        @JsonProperty("report_lon") Double reportLon,
        @JsonProperty("first_sent_at") Long firstSentAt,
        @JsonProperty("last_sent_at") Long lastSentAt,
        @JsonProperty("acked_at") Long ackedAt,
        @JsonProperty("acked_by") String ackedBy,
        @JsonProperty("fail_reason") ReportFailReason failReason,
        @JsonProperty("created_at") Long createdAt) {
}

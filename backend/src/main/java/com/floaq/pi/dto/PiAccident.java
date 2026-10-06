package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.TriggerSource;

import java.util.UUID;

/**
 * {@code POST /api/pi/accidents} 원소 — Pi {@code pi_accident} 16컬럼 중 {@code updated_at} 만 뺐다.
 *
 * <p><b>이 엔드포인트만 Pi 의 PK 를 그대로 쓴다</b>(docs/api.md §4.2). Pi 가 인터넷 없이
 * 사고 ID 를 발급해야 하기 때문이고, 그래서 {@code accident_id} 는 uuid v7 이다.</p>
 *
 * <p>시각은 전부 Unix <b>초</b>다. 밀리초를 넣으면 1970년이 아니라 수만 년 뒤가 된다 —
 * 조용히 통과하므로 Pi 쪽 테스트에서 걸러야 한다(docs/edge/mqtt.md §9).</p>
 */
public record PiAccident(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("ship_id") UUID shipId,
        @JsonProperty("accident_type") AccidentType accidentType,
        @JsonProperty("trigger_source") TriggerSource triggerSource,
        @JsonProperty("report_type") ReportType reportType,
        @JsonProperty("report_dsc") Integer reportDsc,
        @JsonProperty("status") AccidentStatus status,
        @JsonProperty("accident_lat") Double lat,
        @JsonProperty("accident_lon") Double lon,
        @JsonProperty("report_due_at") Long reportDueAt,
        @JsonProperty("wait_sec") Integer waitSec,
        @JsonProperty("rescued_at") Long rescuedAt,
        @JsonProperty("closed_at") Long closedAt,
        @JsonProperty("model_version") String modelVersion,
        @JsonProperty("created_at") Long createdAt) {
}

package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.StateReason;

import java.util.UUID;

/**
 * {@code POST /api/pi/accident-states} 원소 (docs/api.md §4.3).
 *
 * <p><b>Pi 의 PK({@code accident_state_id}, INTEGER)는 받지 않는다.</b> 서버가 uuid v7 을 채번하고
 * 멱등은 자연키 {@code (accident_id, status, created_at)} 가 보장한다.</p>
 *
 * <p>이력은 {@code stale} 이어도 저장한다 — 타임라인에서 "무엇이 늦게 왔나"가 보여야 한다.</p>
 */
public record PiAccidentState(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("status") AccidentStatus status,
        @JsonProperty("prev_status") AccidentStatus prevStatus,
        @JsonProperty("reason") StateReason reason,
        @JsonProperty("caused_by") String causedBy,
        @JsonProperty("created_at") Long createdAt) {
}

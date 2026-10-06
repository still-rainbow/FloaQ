package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * {@code POST /api/pi/ship-positions} 원소 (dev-iot {@code sync.py} pi_ship_position).
 *
 * <p>사고와 무관한 평시 항적도 올라온다 — {@code ship_position.accident_id} 는 nullable 이다.
 * <b>Pi 에는 그 컬럼이 없다</b>(api.md §0.1 #5): 서버가 수신 시각 기준으로 붙이는 쪽으로 간다.
 * 지금은 붙이지 않고 null 로 둔다 — 붙이는 규칙이 정해지기 전에 값을 넣으면 나중에 못 고친다.</p>
 *
 * <p><b>Pi 의 PK({@code position_id}, INTEGER)는 받지 않는다.</b> 멱등은 자연키
 * {@code (ship_id, created_at)} 가 보장한다(V9 {@code uq_ship_position_measured}).</p>
 *
 * @param createdAt GPS 가 위치를 측정한 시각. 서버 수신 시각이 아니다
 */
public record PiShipPosition(
        @JsonProperty("ship_id") UUID shipId,
        @JsonProperty("lat") Double lat,
        @JsonProperty("lon") Double lon,
        @JsonProperty("speed_kn") Float speedKn,
        @JsonProperty("heading_deg") Float headingDeg,
        @JsonProperty("accuracy_m") Float accuracyM,
        @JsonProperty("created_at") Long createdAt) {
}

package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.ship.entity.ShipStatus;

import java.util.UUID;

/**
 * {@code GET /api/pi/ships/{ship_id}} 응답 — 승인 상태 확인 (docs/api.md §4.3).
 *
 * <p>{@code WAIT} 동안 Pi 는 화면에 "승인 대기"를 띄운다. 주기는 Pi 가 정한다 — 초 단위 긴급도가 아니다.
 * {@code REJECTED} 는 자동 재시도로 풀리지 않는다. 사람이 고쳐서 다시 신청해야 한다.</p>
 */
public record PiShipStatusResponse(
        @JsonProperty("ship_id") UUID shipId,
        @JsonProperty("name") String name,
        @JsonProperty("status") ShipStatus status) {
}

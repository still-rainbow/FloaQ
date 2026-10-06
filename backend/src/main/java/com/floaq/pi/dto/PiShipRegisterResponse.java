package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.ship.entity.ShipStatus;

import java.util.UUID;

/**
 * {@code POST /api/pi/ships} 응답 (docs/api.md §4.3).
 *
 * <p>🔴 <b>{@code shipKey} 는 이때 한 번만 내려간다.</b> 서버는 해시로만 보관하므로 다시 보여줄 수 없다 —
 * Pi 는 받는 즉시 <b>영속 저장</b>해야 한다(메모리에만 두면 재부팅에 잃는다).</p>
 *
 * <p>재전송(200)일 때는 {@code shipKey} 가 <b>{@code null} 로 실린다.</b> 이미 발급된 키를
 * 다시 만들 수 없기 때문이다(해시만 있다).</p>
 *
 * <p>⚠ 필드를 <b>빼지 않고 null 로 싣는다</b>(2026-09-17). IoT 계약(docs/api.json)이
 * {@code ship_key} 를 required 로 두고 있어서다 — 키가 없을 때 필드까지 사라지면
 * <b>파서가 "응답 형식이 틀렸다"로 읽는다.</b> 있으나 비었음과 아예 없음은 다르다.</p>
 */
public record PiShipRegisterResponse(
        @JsonProperty("ship_id") UUID shipId,
        @JsonProperty("ship_key") String shipKey,
        @JsonProperty("status") ShipStatus status) {
}

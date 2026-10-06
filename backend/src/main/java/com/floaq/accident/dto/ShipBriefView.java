package com.floaq.accident.dto;

import java.util.UUID;

/** 사고에 딸려 나가는 선박 요약. 목록에서는 {@code shipId}·{@code name} 만 채운다. */
public record ShipBriefView(UUID shipId, String name, String registrationNo, String mmsi) {

    public static ShipBriefView brief(UUID shipId, String name) {
        return new ShipBriefView(shipId, name, null, null);
    }
}

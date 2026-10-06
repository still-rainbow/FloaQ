package com.floaq.ocean.zone;

import com.floaq.ocean.client.OceanApiClient;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 전국 대해구(0.5°, 1,330개). 해양포털 방식 전국 층의 입력.
 *
 * 해역과 무관하다 — 본선이 움직여도 다시 받지 않는다.
 * 소해구보다 먼저 돈다(@Order) — 소해구가 이 발표본에서 가까운 해구를 고른다.
 */
@Component
@Order(1)
public class LargeZoneCollector extends ZoneCollector {

    public static final String SOURCE = "marine-zone";

    public LargeZoneCollector(OceanApiClient client, OceanZoneStore store) {
        super(client, store, ZoneLevel.LARGE);
    }

    @Override
    public String source() {
        return SOURCE;
    }

    /** 전체 — Lzone=0 한 번에 1,330칸이 온다(214KB, 2026-09-14 실측) */
    @Override
    protected List<Integer> targetZones() {
        return null;
    }
}

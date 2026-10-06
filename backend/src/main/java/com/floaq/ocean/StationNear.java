package com.floaq.ocean;

import com.floaq.ocean.khoa.CurrentForecastCollector;
import com.floaq.ocean.khoa.TideForecastCollector;
import com.floaq.ocean.nifs.FishingGroundCollector;
import com.floaq.ocean.seaobs.SeaObsCollector;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 지점 소스 payload(sea-obs · fishing-ground)를 조회 좌표 기준으로 자른다. 순수 함수 — StationNearTest.
 *
 * 수집은 전국 지점을 넣는다(2026-09-15) — 선박이 여러 척이라 수집 시점에 기준 좌표가 하나가 아니다.
 * 반경·거리는 조회 때 요청 좌표로 잰다. 수집 때 해역 중심으로 재면 다른 배에게는 틀린 거리다.
 */
public final class StationNear {

    /** 지점 목록을 payload.stations 로 싣는 소스. 조류·조석예보도 전국이라 같은 규칙이다 (2026-09-16) */
    public static final Set<String> SOURCES = Set.of(
            SeaObsCollector.SOURCE, FishingGroundCollector.SOURCE,
            CurrentForecastCollector.SOURCE, TideForecastCollector.SOURCE);

    private StationNear() {
    }

    /**
     * @return 반경 안 지점만, 가까운 순, 각 행에 distanceKm. payload 에 stations 가 없으면 그대로
     */
    public static Map<String, Object> filter(Map<String, Object> payload, double lat, double lon, double radiusKm) {
        if (payload == null || !(payload.get("stations") instanceof List<?> stations)) {
            return payload;
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object item : stations) {
            // 좌표 없는 행은 거리를 잴 수 없다 — "0km" 로 두면 가장 가까운 지점으로 읽힌다
            if (!(item instanceof Map<?, ?> station)
                    || !(station.get("lat") instanceof Number sLat)
                    || !(station.get("lon") instanceof Number sLon)) {
                continue;
            }
            double km = GeoDistance.round1(GeoDistance.km(lat, lon, sLat.doubleValue(), sLon.doubleValue()));
            if (km > radiusKm) {
                continue;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            station.forEach((k, v) -> row.put(String.valueOf(k), v));
            row.put("distanceKm", km);
            rows.add(row);
        }
        rows.sort(Comparator.comparingDouble(r -> (Double) r.get("distanceKm")));
        Map<String, Object> out = new LinkedHashMap<>(payload);
        out.put("stations", rows);
        out.put("stationCount", rows.size());
        return out;
    }
}

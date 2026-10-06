package com.floaq.ocean.seaobs;

import com.floaq.ocean.GeoDistance;

import java.time.Duration;
import java.util.Comparator;
import java.util.List;

/**
 * 관측 이력에서 "시각 T 에 이 좌표 근처" 지점 고르기. 순수 함수 — SeaObsHistoryTest 가 검증한다.
 */
public final class SeaObsHistory {

    /**
     * 이만큼 오래된 관측까지 "그 시각 값"으로 쓴다.
     * 90분 근거: sea_obs 는 정시 생산(1시간 간격)이고 수집이 30분 주기라, 관측이 도착해 쌓이기까지 최대 1시간 30분이 벌어진다.
     */
    public static final Duration WINDOW = Duration.ofMinutes(90);

    /**
     * 반경 상한.
     * 100km 근거: 부산 앞 30km 반경에 지점 7곳(2026-09-14 실측) — 100km 면 광역 해역을 덮고,
     * 그보다 넓으면 전국 약 200지점이 한 응답에 실려 "근처 관측"이라는 뜻이 사라진다.
     */
    public static final double MAX_RADIUS_KM = 100;

    private SeaObsHistory() {
    }

    /** 지점 하나와 조회 좌표까지의 거리 */
    public record Near(SeaObsStation station, double distanceKm) {
    }

    /** 반경 안 지점을 가까운 순으로. 반경은 상한으로 물린다 */
    public static List<Near> near(List<SeaObsStation> stations, double lat, double lon, double radiusKm) {
        double radius = Math.max(0, Math.min(MAX_RADIUS_KM, radiusKm));
        return stations.stream()
                .map(s -> new Near(s, GeoDistance.round1(GeoDistance.km(lat, lon, s.lat(), s.lon()))))
                .filter(n -> n.distanceKm() <= radius)
                .sorted(Comparator.comparingDouble(Near::distanceKm))
                .toList();
    }
}

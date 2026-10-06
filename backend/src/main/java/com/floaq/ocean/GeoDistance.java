package com.floaq.ocean;

/**
 * 두 좌표 사이 거리.
 *
 * 위·경도 차이를 그대로 제곱합하지 않는다. 35°N 에서 경도 1도는 위도 1도의 0.82배라
 * 보정 없이 고르면 동서로 치우친 격자·지점이 뽑힌다.
 */
public final class GeoDistance {

    private static final double EARTH_RADIUS_KM = 6371.0;

    private GeoDistance() {
    }

    public static double km(double lat1, double lon1, double lat2, double lon2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLon = Math.toRadians(lon2 - lon1);
        double a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.sin(dLon / 2) * Math.sin(dLon / 2);
        return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1.0, Math.sqrt(a)));
    }

    /** 화면·payload 용. 100m 미만은 의미가 없다 */
    public static double round1(double km) {
        return Math.round(km * 10) / 10.0;
    }
}

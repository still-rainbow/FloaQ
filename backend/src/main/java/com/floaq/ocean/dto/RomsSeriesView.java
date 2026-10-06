package com.floaq.ocean.dto;

import java.time.Instant;
import java.util.List;

/**
 * 한 격자점의 시각별 예측. 조석 반일주기가 여기서 보인다 —
 * 약 6시간마다 유향이 뒤집히고 그때 유속이 0 근처로 떨어진다(2026-09-13 실측).
 *
 * @param distanceKm 요청 좌표에서 이 격자까지. 값이 어디 것인지 숨기지 않는다
 * @param points     시각 오름차순
 */
public record RomsSeriesView(
        double lat,
        double lon,
        double distanceKm,
        List<Point> points) {

    public record Point(
            Instant at,
            Double currentDirDeg,
            Double currentSpeedMs,
            Double waterTempC) {
    }
}

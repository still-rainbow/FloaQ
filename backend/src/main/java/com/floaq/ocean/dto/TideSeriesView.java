package com.floaq.ocean.dto;

import com.floaq.ocean.khoa.TideExtremes;
import com.floaq.ocean.seaobs.SeaObsHistory;
import com.floaq.ocean.seaobs.SeaObsStation;

import java.time.Instant;
import java.util.List;

/**
 * 가장 가까운 조석예보 지점의 조위 곡선.
 *
 * 지점을 숨기지 않는다 — 조위는 만(灣)마다 다르다. 어느 지점 값인지, 몇 km 인지 화면이 밝혀야
 * "우리 항구 만조"와 헷갈리지 않는다.
 *
 * @param distanceKm 요청 좌표에서 이 지점까지
 * @param points     1시간 간격 예보. 결측은 null 로 둔다 — 0 으로 두면 간조로 읽힌다
 * @param extremes   만조·간조. 1시간 간격이라 시각은 최대 ±30분 어긋난다(TideExtremes)
 */
public record TideSeriesView(
        String stn,
        String name,
        double lat,
        double lon,
        double distanceKm,
        List<Point> points,
        List<TideExtremes.Extreme> extremes) {

    public record Point(Instant at, Double tideLevelM) {
    }

    public static TideSeriesView of(SeaObsHistory.Near near, List<SeaObsStation> series) {
        var s = near.station();
        return new TideSeriesView(s.stn(), s.name(), s.lat(), s.lon(), near.distanceKm(),
                series.stream().map(r -> new Point(r.observedAt(), r.tideLevelM())).toList(),
                TideExtremes.of(series));
    }
}

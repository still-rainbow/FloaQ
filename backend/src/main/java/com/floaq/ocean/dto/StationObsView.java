package com.floaq.ocean.dto;

import com.floaq.ocean.seaobs.SeaObsHistory;

import java.time.Instant;

/**
 * 관측 지점 한 곳의 시각 at 기준 최근 관측.
 *
 * @param observedAt  관측 시각. 요청 at 보다 최대 90분 이르다 — 화면·표류 계산이 이 차이를 알아야 한다
 * @param distanceKm  요청 좌표에서 이 지점까지
 * @param windDirDeg  불어오는 쪽(기상 관례)
 */
public record StationObsView(
        String network,
        String stn,
        String name,
        double lat,
        double lon,
        double distanceKm,
        Instant observedAt,
        Double waveHeightM,
        Double windDirDeg,
        Double windSpeedMs,
        Double windGustMs,
        Double waterTempC,
        Double airTempC,
        Double pressureHpa,
        Double humidityPct,
        /** 조류예보(예보 소스)에서만 온다. 원본 16방위 한글을 deg 로 바꾼 값 */
        Double currentDirDeg,
        Double currentSpeedMs,
        /** 조석예보에서만 온다 */
        Double tideLevelM) {

    public static StationObsView of(SeaObsHistory.Near near) {
        var s = near.station();
        return new StationObsView(s.network(), s.stn(), s.name(), s.lat(), s.lon(), near.distanceKm(),
                s.observedAt(), s.waveHeightM(), s.windDirDeg(), s.windSpeedMs(), s.windGustMs(),
                s.waterTempC(), s.airTempC(), s.pressureHpa(), s.humidityPct(),
                s.currentDirDeg(), s.currentSpeedMs(), s.tideLevelM());
    }
}

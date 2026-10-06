package com.floaq.ocean.seaobs;

import java.time.Instant;

/**
 * 지점 한 곳의 한 시각 값 — `ocean_station_obs` 한 행.
 *
 * 이름은 sea_obs 에서 왔지만 **KHOA 조류예보·조석예보도 같은 모양을 쓴다** (2026-09-16).
 * 소스는 행의 source 컬럼이 가른다 — 조회가 "좌표 근처 지점"으로 같아서 테이블을 나누지 않았다.
 *
 * 요소가 소스·관측망마다 갈린다. 파고부이는 파고·수온만, 등표는 바람·기압만, 조석예보는 조위만 준다
 * (2026-09-13~14 실측). 그래서 대부분이 null 가능이다 —
 * "가장 가까운 지점"이 아니라 "필요한 요소가 나오는 지점"을 골라야 하는 이유다.
 *
 * @param network     관측망 구분. B 해양기상부이 · C 파고부이 · L 등표 · N 방재기상. 예보 소스는 null
 * @param observedAt  관측 시각. **예보 소스(조류·조석)는 예측 시각이라 미래다**
 */
public record SeaObsStation(
        String network,
        String stn,
        String name,
        double lat,
        double lon,
        Instant observedAt,
        Double waveHeightM,
        Double windDirDeg,
        Double windSpeedMs,
        Double windGustMs,
        Double waterTempC,
        Double airTempC,
        Double pressureHpa,
        Double humidityPct,
        Double currentDirDeg,
        Double currentSpeedMs,
        Double tideLevelM) {

    /** sea_obs 처럼 유향·유속·조위가 없는 소스용 */
    public SeaObsStation(String network, String stn, String name, double lat, double lon, Instant observedAt,
                         Double waveHeightM, Double windDirDeg, Double windSpeedMs, Double windGustMs,
                         Double waterTempC, Double airTempC, Double pressureHpa, Double humidityPct) {
        this(network, stn, name, lat, lon, observedAt, waveHeightM, windDirDeg, windSpeedMs, windGustMs,
                waterTempC, airTempC, pressureHpa, humidityPct, null, null, null);
    }
}

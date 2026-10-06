package com.floaq.ocean.dto;

import com.floaq.ocean.roms.RomsSample;

import java.time.Instant;

/**
 * 표류 추정 입력 — 좌표 최근접 격자의 예측값과 그 불확실성.
 *
 * 값만 내보내면 화면이 점 하나를 그린다. 격자는 약 3km 간격이고, 연안 경계에서는
 * 이웃끼리 유속이 10배 갈린다(2026-09-13 실측: 외해 0.289 vs 내만 0.035 m/s).
 * 표류 범위의 반경이 neighborSpreadMs 에서 나온다.
 *
 * @param predcDt          예측 시각. 요청 시각이 아님 — 항상 미래
 * @param currentDirDeg    유향 deg. null 은 '방위 없음' (0.0 아님)
 * @param distanceKm       요청 좌표에서 이 격자까지. 한 칸(약 3km)을 넘으면 육지를 건너뛴 것이다
 * @param neighborSpreadMs 한 칸 이내 이웃 격자와의 유속 최대 차이. 경계에 걸리면 커진다.
 *                         이웃이 없으면 null — 산포를 0 으로 두면 "확실하다"로 읽힌다
 * @param neighborCount    산포를 계산한 격자 수(자기 자신 포함)
 */
public record RomsPointView(
        Instant predcDt,
        double lat,
        double lon,
        Double currentDirDeg,
        Double currentSpeedMs,
        Double waterTempC,
        double distanceKm,
        Double neighborSpreadMs,
        int neighborCount) {

    public static RomsPointView of(RomsSample sample) {
        var grid = sample.grid();
        return new RomsPointView(grid.predcDt(), grid.lat(), grid.lon(),
                grid.crdirDeg(), grid.crspMs(), grid.wtemC(),
                sample.distanceKm(), sample.neighborSpreadMs(), sample.neighborCount());
    }
}

package com.floaq.ocean.roms;

import java.time.Instant;

/**
 * ROMS 격자점 한 칸의 예측값. 단위는 전부 SI (com.floaq.ocean.OceanUnits).
 *
 * @param predcDt  예측 시각. ⚠ 원본에 타임존 표기 없음
 * @param lon      경도. ⚠ 응답 필드명은 lot
 * @param crdirDeg 유향 deg. null 유지 — 0.0 은 '북'
 */
public record RomsGrid(
        Instant predcDt,
        double lat,
        double lon,
        Double crdirDeg,
        Double crspMs,
        Double wtemC) {
}

package com.floaq.ocean.dto;

import com.floaq.ocean.roms.RomsGrid;

/** 격자 한 칸. 지도에 구역으로 그린다 */
public record RomsCellView(
        double lat,
        double lon,
        Double currentDirDeg,
        Double currentSpeedMs,
        Double waterTempC) {

    public static RomsCellView of(RomsGrid g) {
        return new RomsCellView(g.lat(), g.lon(), g.crdirDeg(), g.crspMs(), g.wtemC());
    }
}

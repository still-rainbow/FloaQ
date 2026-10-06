package com.floaq.ocean.dto;

import com.floaq.ocean.roms.RomsRange;

import java.time.Instant;
import java.util.List;

/**
 * 본선 주변 격자. 지도에 실제 구역을 그리는 데 쓴다.
 *
 * 합성 필드를 그리지 않는다 — 예쁘게 보이려고 지어낸 등치선은 화면에서 실데이터와 구분되지 않는다.
 * 격자가 3km 라 칸이 굵게 보이지만, 그게 우리가 가진 해상도의 정직한 모습이다.
 *
 * @param predcDt 이 값들이 유효한 예측 시각. 요청 at(없으면 지금) 이후 가장 이른 것
 * @param latStep 칸 크기. 화면이 사각형을 그릴 때 쓴다
 * @param cells   본선 칸 + 이웃. 육지는 빠져 있어 9개가 안 될 수 있다
 * @param times   지금 이후 받을 수 있는 예측 시각 전체, 오름차순. 시간 슬라이더 눈금
 * @param range   같은 칸들의 지금 이후 전 시각 min·max. 화면이 이 범위로 칠해야
 *                시각을 넘겨도 같은 색이 같은 값이다
 */
public record RomsGridView(
        Instant predcDt,
        double latStep,
        double lonStep,
        List<RomsCellView> cells,
        List<Instant> times,
        RomsRange range) {
}

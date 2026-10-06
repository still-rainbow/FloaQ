package com.floaq.ocean.roms;

/**
 * 본선 주변 칸들의 지금 이후 전 시각 min·max. 화면의 색 기준.
 *
 * 프레임마다 min·max 를 다시 잡으면 시간 슬라이더를 넘길 때 같은 색이 다른 값이 된다.
 *
 * 항목마다 값이 하나도 없으면 null — 0 으로 두면 "0 부터"로 읽힌다.
 */
public record RomsRange(Double speedMin, Double speedMax, Double tempMin, Double tempMax) {

    public static final RomsRange EMPTY = new RomsRange(null, null, null, null);
}

package com.floaq.ocean.zone;

/**
 * 한 층의 발표본 전 발효시각 min·max. 화면 색 기준.
 *
 * 프레임마다 다시 잡으면 시간 슬라이더를 넘길 때 같은 색이 다른 값이 된다 — ROMS 의 RomsRange 와 같은 이유.
 * 항목마다 값이 하나도 없으면 null.
 */
public record ZoneRange(
        Double waveMin, Double waveMax,
        Double windMin, Double windMax,
        Double tempMin, Double tempMax) {

    public static final ZoneRange EMPTY = new ZoneRange(null, null, null, null, null, null);
}

package com.floaq.ocean.roms;

import java.util.ArrayList;
import java.util.List;

/**
 * ROMS 수집 단위 — 0.25° 고정 타일 (2026-09-15).
 *
 * 좌표만 보고 타일이 정해진다. 선박마다 해역을 들고 다니지 않으니 배가 여러 척이어도 서로의 수집 범위를 빼앗지 않고,
 * 같은 바다에 모인 배는 같은 타일을 나눠 쓴다.
 *
 * 크기 0.25° 근거: 0.3° 가 10,324건 35페이지(2026-09-13 실측) → 면적 비로 약 24페이지(추정).
 *   1° 를 4등분해 경계가 부동소수 오차 없이 떨어진다(0.25 는 이진수로 정확).
 *   기각 0.1°(5p) — 본선 ±0.15° 를 덮으려면 타일 9~16개라 페이지 합이 더 크다
 *   기각 0.5°(100p) — 한 척이 한 번에 하루 쿼터 1%
 *
 * 경계 격자점은 반열린 구간 [south, north) · [west, east) 로 한 타일만 갖는다 —
 * API bbox 는 양끝을 포함해 이웃 타일 응답에 같은 점이 오는데, 그걸 둘 다 저장하면 한쪽을 다시 받을 때 남의 칸을 지운다.
 */
public record RomsTile(int row, int col) {

    public static final double DEG = 0.25;

    public static RomsTile of(double lat, double lon) {
        return new RomsTile((int) Math.floor(lat / DEG), (int) Math.floor(lon / DEG));
    }

    public double south() {
        return row * DEG;
    }

    public double north() {
        return (row + 1) * DEG;
    }

    public double west() {
        return col * DEG;
    }

    public double east() {
        return (col + 1) * DEG;
    }

    public double centerLat() {
        return (row + 0.5) * DEG;
    }

    public double centerLon() {
        return (col + 0.5) * DEG;
    }

    /** 이 격자점을 이 타일이 갖나 — 반열린 구간 */
    public boolean owns(double lat, double lon) {
        return lat >= south() && lat < north() && lon >= west() && lon < east();
    }

    /** 좌표 ± 반폭 상자에 걸치는 타일 전부. 행·열 오름차순 */
    public static List<RomsTile> covering(double lat, double lon, double halfLat, double halfLon) {
        RomsTile lo = of(lat - halfLat, lon - halfLon);
        RomsTile hi = of(lat + halfLat, lon + halfLon);
        List<RomsTile> tiles = new ArrayList<>();
        for (int r = lo.row; r <= hi.row; r++) {
            for (int c = lo.col; c <= hi.col; c++) {
                tiles.add(new RomsTile(r, c));
            }
        }
        return tiles;
    }

    @Override
    public String toString() {
        return "타일(%.2f~%.2f, %.2f~%.2f)".formatted(south(), north(), west(), east());
    }
}

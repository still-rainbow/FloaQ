package com.floaq.ocean;

import java.util.Map;

/**
 * 해양 공공데이터의 단위·타입 정규화. 저장·계산은 전부 SI(m/s, deg)로 한다.
 *
 * 왜 이 클래스가 있나. 같은 필드 이름이 API 마다 다른 단위로 온다.
 * 파서마다 변환을 흩뿌리면 한 곳에서 빠뜨렸을 때 값이 조용히 100배 틀린다 —
 * 표류 추정 공식(상세기획 §8.1)이 m/s 기반이라 반경이 100배가 되고,
 * 숫자가 나오긴 하므로 아무도 실패로 알아채지 못한다.
 *
 * crsp  (유속)  ROMS m/s │ HF-RADAR cm/s │ 해양관측부이 cm/s │ 조류예보 cm/s │ 선박운항지수 kn
 * crdir (유향)  ROMS deg │ HF-RADAR deg  │ 해양관측부이 deg  │ 조류예보 **16방위 한글 문자열**
 *
 * 출처: KHOA 오픈API 활용가이드 PDF 6종 (2026-09-11 확인, p-shim/ref/openapi/).
 */
public final class OceanUnits {

    private OceanUnits() {
    }

    /** 1노트. 국제해리 1852m ÷ 3600s */
    public static final double KNOT_MS = 0.5144444444444445;

    public static double fromCmPerSec(double cmPerSec) {
        return cmPerSec / 100.0;
    }

    public static double fromKnots(double knots) {
        return knots * KNOT_MS;
    }

    /**
     * 16방위 한글 → 도(0~360, 북=0, 시계방향).
     *
     * 조류예보(crntFcstTime)의 crdir 이 varchar 로 온다. 벡터 합을 하려면 각도여야 한다.
     *
     * ⚠ 실제 응답의 표기 변형을 아직 못 봤다. 가이드 예시는 "동남동" 형태지만
     * 무풍·전류(轉流) 시각에 빈 문자열이나 "-" 가 올 수 있다. 그래서 예외 대신 null 이다 —
     * 한 시각의 방위를 못 읽었다고 수집 전체를 중단시키면 나머지 지점까지 통째로 빈다.
     *
     * @return 못 읽으면 null. 호출부가 "방위 없음"으로 남기고 0도로 대체하지 않는다
     */
    public static Double degreesOfKorean16(String point) {
        if (point == null) {
            return null;
        }
        return COMPASS_16.get(point.trim());
    }

    /** 북 0도에서 시계방향 22.5도 간격 */
    private static final Map<String, Double> COMPASS_16 = Map.ofEntries(
            Map.entry("북", 0.0),
            Map.entry("북북동", 22.5),
            Map.entry("북동", 45.0),
            Map.entry("동북동", 67.5),
            Map.entry("동", 90.0),
            Map.entry("동남동", 112.5),
            Map.entry("남동", 135.0),
            Map.entry("남남동", 157.5),
            Map.entry("남", 180.0),
            Map.entry("남남서", 202.5),
            Map.entry("남서", 225.0),
            Map.entry("서남서", 247.5),
            Map.entry("서", 270.0),
            Map.entry("서북서", 292.5),
            Map.entry("북서", 315.0),
            Map.entry("북북서", 337.5));
}

package com.floaq.ocean.zone;

import java.time.Instant;

/**
 * 해구 한 칸 · 한 발효시각의 예측.
 *
 * 꼭짓점 넷 대신 경계(min·max)로 둔다 — 해구는 위·경도에 정렬된 사각형이다(2026-09-14 실응답 확인).
 *
 * 값이 null 이면 결측(-999.0)이다. 대해구 행(szone = 0)은 시정·강수·수온·너울이 항상 null.
 *
 * @param szone         0 = 대해구 · 1~9 = 소해구
 * @param waveDirDeg    파향. ⚠ 오는 쪽/가는 쪽 관례가 명세에 없다
 * @param windDirDeg    풍향. 기상 관례상 불어오는 쪽
 * @param swellLevel    너울 위험 1 관심 · 2 주의 · 3 경계 · 4 위험
 */
public record ZoneCell(
        Instant tmaFc,
        Instant tmaEf,
        int lzone,
        int szone,
        double latMin,
        double latMax,
        double lonMin,
        double lonMax,
        Double waveHeightM,
        Double wavePeriodMaxS,
        Double waveDirDeg,
        Double windSpeedMs,
        Double windDirDeg,
        Double visibilityM,
        Double rainMm,
        Double waterTempC,
        Integer swellLevel) {
}

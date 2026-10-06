package com.floaq.ocean.dto;

import com.floaq.ocean.zone.ZoneCell;
import com.floaq.ocean.zone.ZoneLevel;
import com.floaq.ocean.zone.ZoneRange;

import java.time.Instant;
import java.util.List;

/**
 * 기상청 해구별 예측 한 프레임 — 해양포털 방식 전국 층.
 *
 * @param level    large · small
 * @param issuedAt 발표시각
 * @param validAt  이 칸들의 발효시각. 3시간 구간의 시작
 * @param stepDeg  칸 크기 (대해구 0.5 · 소해구 1/6)
 * @param times    발표본의 발효시각 전체, 오름차순. 시간 슬라이더 눈금
 * @param range    발표본 전 발효시각 min·max. 화면이 이 범위로 칠해야 시각을 넘겨도 같은 색이 같은 값이다
 * @param nextIssuanceAt 받는 중인 <b>다음</b> 발표본. null 이면 받는 중이 아니다.
 *                       <p>여기 실린 {@code cells} 는 <b>완결된 직전 발표본</b>이다 — 반쪽이 아니다.
 *                       전국 소해구는 34분에 걸쳐 받으므로(V11) 그동안 화면이 "옛 발표본을 보고 있다"를
 *                       알 수 있어야 한다. 모르면 사람이 갱신 안 된 화면을 최신으로 읽는다.</p>
 */
public record ZoneGridView(
        String level,
        Instant issuedAt,
        Instant validAt,
        double stepDeg,
        List<Cell> cells,
        List<Instant> times,
        ZoneRange range,
        Instant nextIssuanceAt) {

    /** 발표·발효시각은 프레임 공통이라 칸에서 뺀다 — 1,330칸마다 같은 문자열을 두 번씩 싣지 않게 */
    public record Cell(
            int lzone, int szone,
            double latMin, double latMax, double lonMin, double lonMax,
            Double waveHeightM, Double wavePeriodMaxS, Double waveDirDeg,
            Double windSpeedMs, Double windDirDeg,
            Double visibilityM, Double rainMm, Double waterTempC, Integer swellLevel) {

        static Cell of(ZoneCell c) {
            return new Cell(c.lzone(), c.szone(), c.latMin(), c.latMax(), c.lonMin(), c.lonMax(),
                    c.waveHeightM(), c.wavePeriodMaxS(), c.waveDirDeg(), c.windSpeedMs(), c.windDirDeg(),
                    c.visibilityM(), c.rainMm(), c.waterTempC(), c.swellLevel());
        }
    }

    public static ZoneGridView of(ZoneLevel level, Instant validAt, List<ZoneCell> cells,
                                  List<Instant> times, ZoneRange range, Instant nextIssuanceAt) {
        Instant issuedAt = cells.isEmpty() ? null : cells.getFirst().tmaFc();
        return new ZoneGridView(level.code(), issuedAt, validAt, level.stepDeg(),
                cells.stream().map(Cell::of).toList(), times, range, nextIssuanceAt);
    }
}

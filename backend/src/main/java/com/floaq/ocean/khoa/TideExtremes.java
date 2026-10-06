package com.floaq.ocean.khoa;

import com.floaq.ocean.seaobs.SeaObsStation;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * 조위 시계열에서 만조·간조를 뽑는다. 순수 함수 — TideExtremesTest.
 *
 * "다음 만조 언제냐"가 출입항 판단이다. 곡선만 주면 화면이 눈으로 읽어야 한다.
 *
 * ⚠ **보간하지 않는다.** 수집이 1시간 간격(min=60)이라 실제 극값 시각은 최대 ±30분 어긋난다.
 *    2차 보간으로 분 단위를 만들면 원본에 없는 정밀도가 화면에 "16:12" 처럼 찍힌다 —
 *    KHOA 는 고조·저조 예보표를 따로 주므로, 분 단위가 필요해지면 그 API 를 붙인다(미결).
 *
 * 양 끝 점은 극값으로 보지 않는다. 창이 거기서 잘린 것이지 거기가 꼭대기라는 뜻이 아니다.
 */
public final class TideExtremes {

    /** 만조 · 간조 */
    public enum Kind { HIGH, LOW }

    /**
     * @param levelM 조위(m). 관측 기준면 위 높이다
     */
    public record Extreme(Instant at, double levelM, Kind kind) {
    }

    private TideExtremes() {
    }

    /**
     * @param series 한 지점의 조위 시계열. 시각 오름차순 전제(SeaObsStore.forecastSeries)
     * @return 시각 순 만조·간조. 값이 없는 구간은 건너뛴다
     */
    public static List<Extreme> of(List<SeaObsStation> series) {
        List<Extreme> out = new ArrayList<>();
        for (int i = 1; i < series.size() - 1; i++) {
            Double prev = series.get(i - 1).tideLevelM();
            Double cur = series.get(i).tideLevelM();
            Double next = series.get(i + 1).tideLevelM();
            if (prev == null || cur == null || next == null) {
                // 결측 옆은 판정하지 않는다. 건너뛴 값이 진짜 꼭대기일 수 있다
                continue;
            }
            // 평탄 구간(같은 값 연속)에서 한 번만 잡는다 — 한쪽만 등호
            if (cur > prev && cur >= next) {
                out.add(new Extreme(series.get(i).observedAt(), cur, Kind.HIGH));
            } else if (cur < prev && cur <= next) {
                out.add(new Extreme(series.get(i).observedAt(), cur, Kind.LOW));
            }
        }
        return out;
    }
}

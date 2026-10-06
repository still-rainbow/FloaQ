package com.floaq.ocean;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/** 사고 기록이 늦게 동기화돼도 사고 시각의 해양 값을 답할 수 있는 창 */
class OceanRetentionTest {

    private static final Instant NOW = Instant.parse("2026-09-14T12:00:00Z");

    @Test
    void 보관_기간은_24시간() {
        assertThat(OceanRetention.cutoff(NOW)).isEqualTo(Instant.parse("2026-09-13T12:00:00Z"));
    }

    @Test
    void 경계는_포함한다() {
        assertThat(OceanRetention.covers(Instant.parse("2026-09-13T12:00:00Z"), NOW)).isTrue();
        assertThat(OceanRetention.covers(Instant.parse("2026-09-13T11:59:59Z"), NOW)).isFalse();
    }

    @Test
    void 미래는_보관_기간_문제가_아니다() {
        // 예측 시각 조회는 보관 기간과 무관하다 — 막으면 슬라이더가 못 넘긴다
        assertThat(OceanRetention.covers(Instant.parse("2026-09-17T00:00:00Z"), NOW)).isTrue();
    }
}

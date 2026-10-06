package com.floaq.ocean;

import com.floaq.global.error.BusinessException;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** 시간 슬라이더가 고른 시각을 받을 수 있는 범위로 물린다 */
class OceanControllerTest {

    private static final Instant NOW = Instant.parse("2026-09-14T11:20:00Z");
    private static final List<Instant> TIMES = List.of(
            Instant.parse("2026-09-14T12:00:00Z"),
            Instant.parse("2026-09-14T13:00:00Z"),
            Instant.parse("2026-09-21T23:00:00Z"));

    @Test
    void 시각이_없으면_지금() {
        assertThat(OceanController.frameAt(null, NOW, TIMES)).isEqualTo(NOW);
    }

    @Test
    void 과거는_지금으로_올린다() {
        // 지난 예측을 "그 시각 값"으로 보여주지 않는다 — /current 와 같은 규칙
        assertThat(OceanController.frameAt(NOW.minusSeconds(7200), NOW, TIMES)).isEqualTo(NOW);
    }

    @Test
    void 범위_안이면_그대로() {
        var at = Instant.parse("2026-09-14T13:00:00Z");
        assertThat(OceanController.frameAt(at, NOW, TIMES)).isEqualTo(at);
    }

    @Test
    void 마지막_예측보다_뒤면_마지막으로_물린다() {
        // 그대로 두면 격자가 비어 "해역 밖(OUTSIDE_AREA)"으로 잘못 답한다
        assertThat(OceanController.frameAt(Instant.parse("2026-09-30T00:00:00Z"), NOW, TIMES))
                .isEqualTo(TIMES.getLast());
    }

    private static final List<Instant> ZONE_TIMES = List.of(
            Instant.parse("2026-09-14T00:00:00Z"),
            Instant.parse("2026-09-14T03:00:00Z"),
            Instant.parse("2026-09-14T06:00:00Z"));

    @Test
    void 해구는_그_시각을_덮는_구간의_시작을_고른다() {
        // 3시간 간격에서 "이후 가장 이른"을 고르면 04시에 06시 예측을 "지금"으로 보여준다
        assertThat(OceanController.zoneFrame(null, Instant.parse("2026-09-14T04:10:00Z"), ZONE_TIMES))
                .isEqualTo(Instant.parse("2026-09-14T03:00:00Z"));
    }

    @Test
    void 해구_시각이_발표본보다_앞이면_첫_시각() {
        assertThat(OceanController.zoneFrame(Instant.parse("2026-09-13T20:00:00Z"), NOW, ZONE_TIMES))
                .isEqualTo(ZONE_TIMES.getFirst());
    }

    @Test
    void 해구_시각이_발표본보다_뒤면_마지막_시각() {
        assertThat(OceanController.zoneFrame(Instant.parse("2026-09-20T00:00:00Z"), NOW, ZONE_TIMES))
                .isEqualTo(ZONE_TIMES.getLast());
    }

    @Test
    void 과거_조회는_1시간_안의_예측만_그_시각_값으로_본다() {
        // "at 이후 가장 이른 예측"이라, 그 시각에 해역이 거기 없었으면 몇 시간 뒤 격자가 잡힌다
        Instant accident = Instant.parse("2026-09-14T03:20:00Z");
        assertThat(OceanController.withinHistoryGap(Instant.parse("2026-09-14T04:00:00Z"), accident)).isTrue();
        assertThat(OceanController.withinHistoryGap(Instant.parse("2026-09-14T04:20:00Z"), accident)).isTrue();
        assertThat(OceanController.withinHistoryGap(Instant.parse("2026-09-14T06:00:00Z"), accident)).isFalse();
    }

    @Test
    void 예측본이_없으면_물릴_기준이_없어_그대로() {
        var at = Instant.parse("2026-09-15T00:00:00Z");
        assertThat(OceanController.frameAt(at, NOW, List.of())).isEqualTo(at);
    }

    @Test
    void 수집을_넘겼으면_받는_중이라고_답한다() {
        assertThat(OceanController.notCovered(OceanController.Interest.COLLECTING).message())
                .isEqualTo(OceanController.OUTSIDE_AREA);
    }

    @Test
    void 키가_없어_수집을_안_불렀으면_받는_중이라고_답하지_않는다() {
        // OUTSIDE_AREA 로 주면 kiosk 가 "받는 중"을 띄우고 10초마다 영원히 다시 묻는다
        assertThat(OceanController.notCovered(OceanController.Interest.NO_KEY).message())
                .isEqualTo(OceanController.OUTSIDE_AREA_NOT_MOVED);
    }

    @Test
    void 키는_맞는데_ROMS_수집이_꺼져_있으면_503() {
        // 기다려도 안 들어온다 — 사람이 봐야 한다.
        // 이전의 "예측이 하나도 없으면 503" 은 기동 직후 타일 0개(정상)와 키 누락까지 장애로 덮었다(2026-09-15 실측)
        assertThatThrownBy(() -> OceanController.notCovered(OceanController.Interest.COLLECTION_OFF))
                .isInstanceOf(BusinessException.class);
    }
}

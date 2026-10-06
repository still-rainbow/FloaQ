package com.floaq.ocean.roms;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** 중복 격자. 한 건의 PK 위반이 배치 전체를 롤백시키면 예측본이 통째로 안 갱신된다 */
class OceanRomsStoreTest {

    private static final Instant T = Instant.parse("2026-09-13T08:00:00Z");

    @Test
    void 같은_시각_같은_좌표는_먼저_온_행만_남는다() {
        List<RomsGrid> rows = List.of(
                new RomsGrid(T, 35.00898, 129.02008, 73.1, 0.91, 25.1),
                new RomsGrid(T, 35.00898, 129.05204, 78.0, 0.87, 25.2),
                // 페이지 경계에서 다시 온 행. 값이 달라도 키가 같으면 중복이다
                new RomsGrid(T, 35.00898, 129.02008, 74.0, 0.92, 25.1));

        List<RomsGrid> unique = OceanRomsStore.dedupe(rows);

        assertThat(unique).hasSize(2);
        assertThat(unique.getFirst().crspMs()).isEqualTo(0.91);
    }

    @Test
    void 시각이_다르면_같은_좌표라도_별개다() {
        List<RomsGrid> rows = List.of(
                new RomsGrid(T, 35.0, 129.0, 0.0, 0.1, 25.0),
                new RomsGrid(T.plusSeconds(3600), 35.0, 129.0, 0.0, 0.2, 25.0));

        assertThat(OceanRomsStore.dedupe(rows)).hasSize(2);
    }

    // ── 새 예측본 판정. 틀리면 매시 전량(쿼터 24배)이거나 새 예측본을 하루 동안 놓친다 ──

    private static final Instant CUTOFF = T.minusSeconds(24 * 3600);

    /** real 컬럼을 거쳐 돌아온 값 흉내 — double → float4 → double */
    private static Double real(double v) {
        return (double) (float) v;
    }

    @Test
    void real_컬럼을_거친_값도_같은_예측본이다() {
        // 0.44 는 real 로 저장하면 0.4399999976 으로 돌아온다. double 비교면 매번 "바뀜"
        List<RomsGrid> probe = List.of(new RomsGrid(T, 35.0, 129.0, 212.3, 0.44, 24.1));
        List<RomsGrid> stored = List.of(new RomsGrid(T, 35.0, 129.0, real(212.3), real(0.44), real(24.1)));

        assertThat(stored.getFirst().crspMs()).isNotEqualTo(0.44);
        assertThat(OceanRomsStore.matches(probe, stored, CUTOFF)).isTrue();
    }

    @Test
    void 값이_하나라도_다르면_새_예측본이다() {
        List<RomsGrid> probe = List.of(
                new RomsGrid(T, 35.0, 129.0, 212.3, 0.44, 24.1),
                new RomsGrid(T, 35.0, 129.03, 200.0, 0.30, 24.0));
        List<RomsGrid> stored = List.of(
                new RomsGrid(T, 35.0, 129.0, real(212.3), real(0.44), real(24.1)),
                new RomsGrid(T, 35.0, 129.03, real(200.0), real(0.31), real(24.0)));

        assertThat(OceanRomsStore.matches(probe, stored, CUTOFF)).isFalse();
    }

    @Test
    void 저장에_없는_키가_있으면_새_예측본이다() {
        // 새 예측본은 마지막 날 다음 시각을 들고 온다 — 모르는 키는 받는 쪽
        List<RomsGrid> probe = List.of(new RomsGrid(T.plusSeconds(3600), 35.0, 129.0, 1.0, 0.1, 25.0));
        List<RomsGrid> stored = List.of(new RomsGrid(T, 35.0, 129.0, real(1.0), real(0.1), real(25.0)));

        assertThat(OceanRomsStore.matches(probe, stored, CUTOFF)).isFalse();
    }

    @Test
    void 결측이_값으로_바뀌면_새_예측본이다() {
        List<RomsGrid> probe = List.of(new RomsGrid(T, 35.0, 129.0, null, 0.1, 25.0));
        List<RomsGrid> stored = List.of(new RomsGrid(T, 35.0, 129.0, real(90.0), real(0.1), real(25.0)));
        List<RomsGrid> bothNull = List.of(new RomsGrid(T, 35.0, 129.0, null, real(0.1), real(25.0)));

        assertThat(OceanRomsStore.matches(probe, stored, CUTOFF)).isFalse();
        assertThat(OceanRomsStore.matches(probe, bothNull, CUTOFF)).isTrue();
    }

    @Test
    void 보관_기간_전_행은_비교하지_않는다() {
        // 저장하지 않는 행이라 DB 에 없다. 비교에 넣으면 매번 "없는 키" → 매시 전량
        Instant old = CUTOFF.minusSeconds(3600);
        List<RomsGrid> probe = List.of(
                new RomsGrid(old, 35.0, 129.0, 1.0, 0.1, 25.0),
                new RomsGrid(T, 35.0, 129.0, 1.0, 0.1, 25.0));
        List<RomsGrid> stored = List.of(new RomsGrid(T, 35.0, 129.0, real(1.0), real(0.1), real(25.0)));

        assertThat(OceanRomsStore.matches(probe, stored, CUTOFF)).isTrue();
    }

    @Test
    void 비교할_행이_없으면_받는_쪽이다() {
        List<RomsGrid> onlyOld = List.of(new RomsGrid(CUTOFF.minusSeconds(60), 35.0, 129.0, 1.0, 0.1, 25.0));

        assertThat(OceanRomsStore.matches(List.of(), List.of(), CUTOFF)).isFalse();
        assertThat(OceanRomsStore.matches(onlyOld, List.of(), CUTOFF)).isFalse();
    }
}

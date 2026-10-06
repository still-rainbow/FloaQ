package com.floaq.ocean.roms;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** bbox 가 어떤 격자점을 고를지 미리 계산한다. 모델 격자가 공간에 고정돼 있어 가능하다 */
class RomsLatticeTest {

    /** 2026-09-13 부산 앞 실측 */
    private static final RomsLattice LATTICE =
            new RomsLattice(35.00898, 129.02008, 0.02864, 0.03197);

    /** 부산 앞 0.1° bbox. 중심 35.05, 129.05 */
    private static RomsLattice.Selection busan() {
        return LATTICE.selectionOf(35.0, 35.1, 129.0, 129.1);
    }

    @Test
    void 실측_bbox_가_4행_3열을_고른다() {
        // 실호출 격자점은 8개였다 — 4x3=12 중 4칸이 육지라 빠졌다. 격자 선택 자체는 12칸이다
        var sel = busan();

        assertThat(sel.latHi() - sel.latLo() + 1).isEqualTo(4);
        assertThat(sel.lonHi() - sel.lonLo() + 1).isEqualTo(3);
        assertThat(sel.isEmpty()).isFalse();
    }

    @Test
    void 격자_사이에_낀_bbox_는_비어_있다() {
        // 격자점 두 개 사이의 좁은 창. 받아도 0건이다
        assertThat(LATTICE.selectionOf(35.020, 35.030, 129.030, 129.040).isEmpty()).isTrue();
    }

    @Test
    void 중심_근처는_이웃까지_덮인다() {
        var sel = busan();

        assertThat(LATTICE.coversNeighborhood(sel, 35.05, 129.05)).isTrue();
        // 1km(0.009°) 움직여도 그대로다 — 배가 같은 칸 안에 있다
        assertThat(LATTICE.coversNeighborhood(sel, 35.059, 129.05)).isTrue();
    }

    @Test
    void 가장자리에_서면_이웃이_모자란다() {
        // 한쪽에만 이웃이 있으면 유속 산포가 실제보다 작게 나온다 — 표류 반경 과소평가다
        var sel = busan();

        assertThat(LATTICE.coversNeighborhood(sel, 35.098, 129.05)).isFalse();
        assertThat(LATTICE.coversNeighborhood(sel, 35.05, 129.098)).isFalse();
    }

    @Test
    void 범위_밖은_당연히_안_덮인다() {
        assertThat(LATTICE.coversNeighborhood(busan(), 34.80, 128.40)).isFalse();
    }
}

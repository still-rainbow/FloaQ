package com.floaq.ocean;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** 위도에 따른 경도 수축. 보정 없이 고르면 동서로 치우친 격자가 뽑힌다 */
class GeoDistanceTest {

    @Test
    void 같은_0_1도라도_경도가_더_짧다() {
        // 35°N 에서 경도 1도는 위도 1도의 약 0.82배
        assertThat(GeoDistance.km(35.0, 129.0, 35.1, 129.0)).isBetween(11.0, 11.2);
        assertThat(GeoDistance.km(35.0, 129.0, 35.0, 129.1)).isBetween(9.0, 9.2);
    }

    @Test
    void ROMS_격자_간격이_실측과_맞는다() {
        // 2026-09-13 부산 앞 응답의 실제 격자점. 위도 0.02864° · 경도 0.03197°
        assertThat(GeoDistance.km(35.00898, 129.02008, 35.03764, 129.02008)).isBetween(3.1, 3.3);
        assertThat(GeoDistance.km(35.00898, 129.02008, 35.00898, 129.05204)).isBetween(2.8, 3.0);
        // 대각 이웃. 두 칸(5.8km 이상)과 가르는 기준이 이 값이다
        assertThat(GeoDistance.km(35.00898, 129.02008, 35.03764, 129.05204)).isBetween(4.2, 4.4);
    }

    @Test
    void 같은_좌표는_0_이다() {
        assertThat(GeoDistance.km(35.0, 129.0, 35.0, 129.0)).isZero();
    }
}

package com.floaq.ocean;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** 해역 이동 키. 틀리면 공개 조회가 ROMS 예산을 태우거나, kiosk 가 해역을 못 옮긴다 */
class KioskKeyTest {

    @Test
    void 맞는_키만_통과한다() {
        KioskKey key = new KioskKey("k-1234");

        assertThat(key.matches("k-1234")).isTrue();
        assertThat(key.matches("k-1235")).isFalse();
        assertThat(key.matches("k-12345")).isFalse();
        assertThat(key.matches(null)).isFalse();
    }

    @Test
    void 키가_설정되지_않으면_아무것도_통과하지_않는다() {
        // 빈 값끼리 같다고 열리면 설정을 빠뜨린 서버가 누구에게나 이동을 허락한다
        assertThat(new KioskKey("").matches("")).isFalse();
        assertThat(new KioskKey("  ").matches("  ")).isFalse();
        assertThat(new KioskKey(null).matches(null)).isFalse();
    }
}

package com.floaq.ocean;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 단위 환산은 틀려도 예외가 안 난다. 그래서 테스트로 고정한다.
 * 표류 추정 반경이 100배 틀리는 것을 잡아내는 유일한 장치다.
 */
class OceanUnitsTest {

    @Test
    @DisplayName("cm/s → m/s — HF-RADAR·부이·조류예보 세 API 가 cm/s 다")
    void cmPerSec() {
        assertThat(OceanUnits.fromCmPerSec(50)).isEqualTo(0.5);
    }

    @Test
    @DisplayName("kn → m/s — 선박운항지수 avgCrsp")
    void knots() {
        // 1 kn = 1852m/3600s. 반올림 아닌 정의값
        assertThat(OceanUnits.fromKnots(1)).isCloseTo(0.5144, org.assertj.core.data.Offset.offset(1e-4));
    }

    @Test
    @DisplayName("16방위 한글 → deg. 북 0, 시계방향 22.5도")
    void compass() {
        assertThat(OceanUnits.degreesOfKorean16("북")).isEqualTo(0.0);
        assertThat(OceanUnits.degreesOfKorean16("동")).isEqualTo(90.0);
        assertThat(OceanUnits.degreesOfKorean16("동남동")).isEqualTo(112.5);   // 가이드 예시값
        assertThat(OceanUnits.degreesOfKorean16("북북서")).isEqualTo(337.5);
    }

    @Test
    @DisplayName("16방위 모두 매핑되고 22.5도 간격을 지킨다 — 표를 손으로 옮기다 한 칸 밀리는 것을 막는다")
    void compassComplete() {
        String[] order = {"북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동",
                "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"};
        for (int i = 0; i < order.length; i++) {
            assertThat(OceanUnits.degreesOfKorean16(order[i]))
                    .as("%s", order[i])
                    .isEqualTo(i * 22.5);
        }
    }

    @Test
    @DisplayName("못 읽는 방위는 null — 0도(북)로 대체하면 표류 방향이 조용히 틀린다")
    void unknownDirection() {
        assertThat(OceanUnits.degreesOfKorean16(null)).isNull();
        assertThat(OceanUnits.degreesOfKorean16("")).isNull();
        assertThat(OceanUnits.degreesOfKorean16("-")).isNull();
        assertThat(OceanUnits.degreesOfKorean16("ESE")).isNull();   // 영문 표기는 안 받는다
    }

    @Test
    @DisplayName("공백이 섞여 와도 읽는다 — 고정폭 필드에서 자주 나온다")
    void trims() {
        assertThat(OceanUnits.degreesOfKorean16(" 남서 ")).isEqualTo(225.0);
    }
}

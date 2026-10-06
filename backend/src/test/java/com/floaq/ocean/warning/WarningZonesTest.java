package com.floaq.ocean.warning;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** 특보구역 계층. 구조는 2026-09-14 wrn_reg.php 실응답 */
class WarningZonesTest {

    private static final WarningZones ZONES = WarningZones.of(List.of(
            new WarningZones.Zone("S1000000", null, "전해상"),
            new WarningZones.Zone("S1300000", "S1000000", "남해전해상"),
            new WarningZones.Zone("S1310000", "S1300000", "남해동부전해상"),
            new WarningZones.Zone("S1311000", "S1310000", "남해동부앞바다"),
            new WarningZones.Zone("S1311100", "S1311000", "부산앞바다"),
            new WarningZones.Zone("S1311400", "S1311000", "거제시동부앞바다"),
            new WarningZones.Zone("S1312010", "S1310000", "남해동부안쪽먼바다"),
            new WarningZones.Zone("S2000000", "S2000000", "연안바다/평수구역"),
            new WarningZones.Zone("S2110200", "S2000000", "울산앞바다중")));

    @Test
    void 조업_해역의_상위_구역을_모두_포함한다() {
        assertThat(ZONES.related(List.of("S1311100")))
                .containsExactlyInAnyOrder("S1311100", "S1311000", "S1310000", "S1300000", "S1000000");
    }

    @Test
    void 이웃_구역은_포함하지_않는다() {
        // 거제시동부앞바다는 같은 상위 아래 형제다. 부산앞바다 특보가 아니다
        assertThat(ZONES.related(List.of("S1311100"))).doesNotContain("S1311400", "S1312010");
    }

    @Test
    void 넓은_구역을_설정하면_하위_구역도_포함한다() {
        assertThat(ZONES.related(List.of("S1311000"))).contains("S1311100", "S1311400");
    }

    @Test
    void 자기_자신이_상위인_구역에서_멈춘다() {
        // S2000000 의 상위가 S2000000. 방문 확인이 없으면 끝나지 않는다
        assertThat(ZONES.related(List.of("S2110200"))).containsExactlyInAnyOrder("S2110200", "S2000000");
    }

    @Test
    void 모르는_코드는_자기_자신만() {
        assertThat(ZONES.related(List.of("S9999999"))).containsExactly("S9999999");
        assertThat(WarningZones.empty().related(List.of("S1311100"))).containsExactly("S1311100");
    }

    @Test
    void 스냅샷_payload_에서_계층을_만든다() {
        var zones = WarningZones.fromPayload(Map.of("zones", List.of(
                Map.of("id", "S1311000", "up", "S1310000", "name", "남해동부앞바다"),
                Map.of("id", "S1311100", "up", "S1311000", "name", "부산앞바다"))));

        assertThat(zones.name("S1311100")).isEqualTo("부산앞바다");
        assertThat(zones.related(List.of("S1311100"))).contains("S1311000");
        assertThat(WarningZones.fromPayload(Map.of("other", 1)).isEmpty()).isTrue();
    }
}

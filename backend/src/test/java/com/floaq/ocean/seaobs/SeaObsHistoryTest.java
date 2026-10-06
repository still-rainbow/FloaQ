package com.floaq.ocean.seaobs;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** 관측 이력에서 사고 지점 근처 지점 고르기 */
class SeaObsHistoryTest {

    private static final Instant T = Instant.parse("2026-09-14T11:00:00Z");

    private static SeaObsStation station(String stn, double lat, double lon) {
        return new SeaObsStation("B", stn, stn, lat, lon, T, 0.4, 40.0, 6.6, 9.1, 25.4, 24.0, 1012.0, 80.0);
    }

    // 부산 앞 기준 좌표와 실제 지점 근사 위치 (2026-09-14 sea_obs)
    private static final double LAT = 35.055;
    private static final double LON = 129.1185;

    @Test
    void 반경_안_지점만_가까운_순으로() {
        var near = SeaObsHistory.near(List.of(
                station("far", 35.40, 129.60),      // 약 58km
                station("near", 35.08, 129.13),     // 약 3km
                station("mid", 35.20, 129.20)),     // 약 18km
                LAT, LON, 30);

        assertThat(near).extracting(n -> n.station().stn()).containsExactly("near", "mid");
        assertThat(near.getFirst().distanceKm()).isLessThan(near.get(1).distanceKm());
    }

    @Test
    void 거리는_소수_첫째_자리로() {
        var near = SeaObsHistory.near(List.of(station("near", 35.08, 129.13)), LAT, LON, 30);

        double km = near.getFirst().distanceKm();
        assertThat(km * 10).isEqualTo(Math.rint(km * 10));
    }

    @Test
    void 반경은_상한으로_물린다() {
        // 반경을 크게 줘도 전국 목록이 한 응답에 실리지 않게
        var near = SeaObsHistory.near(List.of(station("seoul-ish", 37.5, 126.9)), LAT, LON, 10_000);

        assertThat(near).isEmpty();
    }

    @Test
    void 음수_반경은_0() {
        assertThat(SeaObsHistory.near(List.of(station("near", 35.08, 129.13)), LAT, LON, -5)).isEmpty();
    }
}

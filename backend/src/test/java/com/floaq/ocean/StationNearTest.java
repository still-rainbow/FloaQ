package com.floaq.ocean;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 지점 소스를 조회 좌표로 자른다.
 *
 * 수집은 전국이다(선박 여러 척). 거리를 수집 때 한 기준 좌표로 재면 다른 배에게는 틀린 거리다.
 */
class StationNearTest {

    private static Map<String, Object> station(String name, double lat, double lon) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("name", name);
        row.put("lat", lat);
        row.put("lon", lon);
        row.put("waveHeightM", 0.5);
        return row;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> stations(Map<String, Object> payload) {
        return (List<Map<String, Object>>) payload.get("stations");
    }

    @Test
    void 반경_안_지점만_가까운_순으로_거리를_붙인다() {
        var payload = Map.<String, Object>of("stationCount", 3, "stations", List.of(
                station("덕적도", 37.2361, 126.0188),
                station("기장", 35.2208, 129.2635),
                station("오륙도", 35.0945, 129.1283)));

        var out = StationNear.filter(payload, 35.05, 129.05, 30);

        // 0.1° bbox 로 자르면 기장·오륙도 둘 다 빠진다 — 지점은 반경으로 고른다(2026-09-13 실측)
        assertThat(stations(out)).extracting(s -> s.get("name")).containsExactly("오륙도", "기장");
        assertThat(out).containsEntry("stationCount", 2);
        assertThat((Double) stations(out).getFirst().get("distanceKm")).isBetween(8.0, 9.5);
    }

    @Test
    void 같은_지점도_조회_좌표마다_거리가_다르다() {
        var payload = Map.<String, Object>of("stations", List.of(station("기장", 35.2208, 129.2635)));

        var near = StationNear.filter(payload, 35.20, 129.25, 30);
        var far = StationNear.filter(payload, 35.05, 129.05, 30);

        assertThat((Double) stations(near).getFirst().get("distanceKm"))
                .isLessThan((Double) stations(far).getFirst().get("distanceKm"));
    }

    @Test
    void 거리는_위도에_따른_경도_수축을_반영한다() {
        var payload = Map.<String, Object>of("stations", List.of(
                station("북", 35.15, 129.05), station("동", 35.05, 129.15)));

        var out = stations(StationNear.filter(payload, 35.05, 129.05, 100));

        // 위도 0.1° 약 11.1km · 같은 0.1° 라도 경도는 35°N 에서 약 9.1km. 단순 제곱합이면 같은 값이 나온다
        assertThat(out).extracting(s -> s.get("name")).containsExactly("동", "북");
        assertThat((Double) out.get(0).get("distanceKm")).isBetween(9.0, 9.2);
        assertThat((Double) out.get(1).get("distanceKm")).isBetween(11.0, 11.2);
    }

    @Test
    void 좌표가_없는_행은_뺀다() {
        // 거리를 잴 수 없다 — 0km 로 두면 가장 가까운 지점으로 읽힌다
        Map<String, Object> noCoord = new LinkedHashMap<>();
        noCoord.put("name", "좌표없음");
        var payload = Map.<String, Object>of("stations", List.of(noCoord, station("오륙도", 35.0945, 129.1283)));

        assertThat(stations(StationNear.filter(payload, 35.05, 129.05, 30)))
                .extracting(s -> s.get("name")).containsExactly("오륙도");
    }

    @Test
    void stations_가_없으면_그대로_돌려준다() {
        var payload = Map.<String, Object>of("activeMarineWarnings", List.of());

        assertThat(StationNear.filter(payload, 35.05, 129.05, 30)).isSameAs(payload);
        assertThat(StationNear.filter(null, 35.05, 129.05, 30)).isNull();
    }

    @Test
    void 저장된_payload_를_바꾸지_않는다() {
        // 스냅샷 엔티티의 payload 다 — 조회마다 덮어쓰면 다음 조회가 이미 잘린 목록을 받는다
        var original = station("오륙도", 35.0945, 129.1283);
        var payload = Map.<String, Object>of("stations", List.of(original));

        StationNear.filter(payload, 35.05, 129.05, 30);

        assertThat(original).doesNotContainKey("distanceKm");
    }
}

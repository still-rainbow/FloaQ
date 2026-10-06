package com.floaq.ocean.roms;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** ROMS 파싱. 틀려도 예외가 안 나는 종류라 테스트로 고정한다 */
class RomsParseTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    private static JsonNode json(String raw) {
        return MAPPER.readTree(raw);
    }

    private static RomsGrid grid(String predcDt, double crspMs) {
        return new RomsGrid(Instant.parse(predcDt), 35.0, 129.0, 0.0, crspMs, 25.0);
    }

    @Test
    void 경도는_lot_필드다() {
        // lon 으로 읽으면 전부 0 이 되고 지도가 서아프리카를 가리킨다
        List<RomsGrid> grids = RomsCollector.parseItems(json("""
                {"items":{"item":[
                  {"predcDt":"2025-08-25 00:00:00","lat":34.02873,"lot":123.20205,
                   "crdir":314.8,"crsp":0.44,"wtem":29.56}]},
                 "totalCount":1}
                """));

        assertThat(grids).hasSize(1);
        assertThat(grids.getFirst().lon()).isEqualTo(123.20205);
        assertThat(grids.getFirst().crspMs()).isEqualTo(0.44);
    }

    @Test
    void 결과가_1건이면_item_이_배열이_아니라_객체로_온다() {
        // 공공데이터포털 공통 함정. 배열만 보면 1건일 때 0건이 된다
        List<RomsGrid> grids = RomsCollector.parseItems(json("""
                {"items":{"item":{"predcDt":"2025-08-25 00:00:00","lat":34.0,"lot":123.2}},
                 "totalCount":1}
                """));

        assertThat(grids).hasSize(1);
    }

    @Test
    void 결과가_0건이면_items_가_빈_문자열로_온다() {
        List<RomsGrid> grids = RomsCollector.parseItems(json("""
                {"items":"","totalCount":0}
                """));

        assertThat(grids).isEmpty();
    }

    @Test
    void 유향이_없으면_null_이다() {
        // 0.0 으로 대체하면 '북'으로 읽혀 표류 방향이 조용히 틀린다
        List<RomsGrid> grids = RomsCollector.parseItems(json("""
                {"items":{"item":[{"predcDt":"2025-08-25 00:00:00","lat":34.0,"lot":123.2}]}}
                """));

        assertThat(grids.getFirst().crdirDeg()).isNull();
    }

    @Test
    void predcDt_는_타임존_표기가_없어_KST_로_읽는다() {
        // 2026-09-13 실호출로 확정. 근거는 표층 수온 일주기 위상 (최고 14~17시)
        assertThat(RomsCollector.parsePredcDt("2025-08-25 00:00:00"))
                .isEqualTo(Instant.parse("2025-08-24T15:00:00Z"));
    }

    @Test
    void 형식이_다른_행만_버린다() {
        // 한 행 때문에 수집 전체가 비면 그날 값이 통째로 없어진다
        List<RomsGrid> grids = RomsCollector.parseItems(json("""
                {"items":{"item":[
                  {"predcDt":"깨진값","lat":34.0,"lot":123.2},
                  {"predcDt":"2025-08-25 00:00:00","lat":34.1,"lot":123.3}]}}
                """));

        assertThat(grids).hasSize(1);
        assertThat(grids.getFirst().lat()).isEqualTo(34.1);
    }

    @Test
    void 지금_이후_가장_이른_예측_시각을_고른다() {
        // 예측본이 당일 00시부터라 min(predcDt) 를 쓰면 최대 하루 전 예측이 "현재 유속"이 된다.
        // 실측에서 0.82 m/s(00시) vs 0.14 m/s(17시)로 6배 차이였다
        Instant now = Instant.parse("2026-09-13T08:30:00Z");
        List<RomsGrid> grids = List.of(
                grid("2026-09-12T15:00:00Z", 0.82),
                grid("2026-09-13T08:00:00Z", 0.20),
                grid("2026-09-13T09:00:00Z", 0.14));

        assertThat(RomsCollector.firstForecastAt(grids, now))
                .isEqualTo(Instant.parse("2026-09-13T09:00:00Z"));
    }

    @Test
    void 미래_예측이_없으면_null_이다() {
        // 예측본이 낡았다는 신호다. 과거 값을 현재값으로 내보내지 않는다
        Instant now = Instant.parse("2026-09-21T00:00:00Z");
        List<RomsGrid> grids = List.of(grid("2026-09-13T08:00:00Z", 0.2));

        assertThat(RomsCollector.firstForecastAt(grids, now)).isNull();
    }

    @Test
    void bbox_좌표는_소수_4자리로_자른다() {
        // 부동소수 잔차가 실리면 KHOA 가 거부한다 (2026-09-13 실측)
        //   ymin=35.048000000000002 → resultCode 10 INVALID_REQUEST_PARAMETER_ERROR
        //   ymin=35.0480            → 00 NORMAL_SERVICE
        assertThat(RomsCollector.coordFor(35.048000000000002)).isEqualTo("35.0480");
        assertThat(RomsCollector.coordFor(129.10000000000002)).isEqualTo("129.1000");
    }

    @Test
    void 타일_경계는_잔차_없이_찍힌다() {
        // 0.25 는 이진수로 정확해 경계 계산에 잔차가 붙지 않는다 — 옛 해역 재중심화(중심 ± 반폭)에서 거부당하던 경로가 없다
        var tile = RomsTile.of(35.1992, 129.267);

        assertThat(RomsCollector.coordFor(tile.south())).isEqualTo("35.0000");
        assertThat(RomsCollector.coordFor(tile.north())).isEqualTo("35.2500");
        assertThat(RomsCollector.coordFor(tile.west())).isEqualTo("129.2500");
        assertThat(RomsCollector.coordFor(tile.east())).isEqualTo("129.5000");
    }
}

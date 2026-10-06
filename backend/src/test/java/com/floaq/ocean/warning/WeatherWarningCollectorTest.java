package com.floaq.ocean.warning;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** 특보구역 이벤트 발효 판정. 2026-09-08~11 부산 앞 실제 발표 순서로 재현 */
class WeatherWarningCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final DateTimeFormatter TM = DateTimeFormatter.ofPattern("yyyyMMddHHmm");

    /** wrn_reg.php 확인 (2026-09-14). S1323200 은 제주도동부앞바다다 — 헷갈렸던 적 있음 */
    private static final String BUSAN = "S1311100";
    private static final String SOUTH_EAST_INNER = "S1312010";

    private static Instant kst(String tmFc) {
        return LocalDateTime.parse(tmFc, TM).atZone(ZoneId.of("Asia/Seoul")).toInstant();
    }

    private static WarningAreaEvent ev(String tmFc, int seq, String code, String name,
                                       int kind, int level, int command) {
        return new WarningAreaEvent(kst(tmFc), seq, code, name, kind, level, command, false, null);
    }

    @Test
    void 발표_뒤_해제되면_발효_중이_아니다() {
        var events = List.of(
                ev("202609081800", 54, BUSAN, "부산앞바다", 6, 0, 1),
                ev("202609100400", 70, BUSAN, "부산앞바다", 6, 0, 2));

        assertThat(WarningAreaEvent.activeMarine(events)).isEmpty();
    }

    @Test
    void 경보가_주의보로_변경되면_주의보로_남는다() {
        // title 방식은 이 순서에서 "풍랑경보"를 영원히 발효로 남겼다 (2026-09-13)
        var events = List.of(
                ev("202609091200", 58, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 1, 7),
                ev("202609100400", 70, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 0, 7));

        assertThat(WarningAreaEvent.activeMarine(events))
                .extracting(WarningAreaEvent::name).containsExactly("풍랑주의보");
    }

    @Test
    void 변경_뒤_해제까지_오면_발효_중이_아니다() {
        var events = List.of(
                ev("202609091200", 58, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 1, 7),
                ev("202609100400", 70, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 0, 7),
                ev("202609101800", 73, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 0, 2));

        assertThat(WarningAreaEvent.activeMarine(events)).isEmpty();
    }

    @Test
    void 강풍은_빠지고_폭풍해일은_남는다() {
        // 강풍은 육상 구역만 온다. 폭풍해일은 L 구역이어도 해안 침수라 조업 판단에 넣는다
        var events = List.of(
                ev("202609091500", 60, "L1070100", "부산", 1, 0, 1),
                ev("202609092215", 65, "L1070200", "부산동부", 5, 0, 1));

        assertThat(WarningAreaEvent.activeMarine(events))
                .extracting(WarningAreaEvent::name).containsExactly("폭풍해일주의보");
    }

    @Test
    void 취소된_이벤트는_없던_일이다() {
        var released = new WarningAreaEvent(kst("202609100400"), 70, BUSAN, "부산앞바다", 6, 0, 2, true, null);
        var events = List.of(ev("202609081800", 54, BUSAN, "부산앞바다", 6, 0, 1), released);

        assertThat(WarningAreaEvent.activeMarine(events)).hasSize(1);
    }

    @Test
    void 같은_발표_안에서는_발효가_해제를_이긴다() {
        var events = List.of(
                ev("202609100400", 70, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 1, 8),
                ev("202609100400", 70, SOUTH_EAST_INNER, "남해동부안쪽먼바다", 6, 0, 7));

        assertThat(WarningAreaEvent.activeMarine(events))
                .extracting(WarningAreaEvent::name).containsExactly("풍랑주의보");
    }

    @Test
    void 모르는_발표구분은_발효로_본다() {
        var events = List.of(ev("202609100400", 70, BUSAN, "부산앞바다", 6, 0, 99));

        assertThat(WarningAreaEvent.activeMarine(events)).hasSize(1);
    }

    @Test
    void 실응답은_숫자와_문자열이_섞여_온다() {
        JsonNode body = MAPPER.readTree("""
                {"dataType":"JSON","items":{"item":[
                  {"allEndTime":202609110800,"areaCode":"S1324020","areaName":"제주도남쪽바깥먼바다","cancel":"0",
                   "command":"2","endTime":202609110800,"stnId":"108","tmFc":202609110600,"tmSeq":77,
                   "warnVar":6,"warnStress":0,"startTime":0}]},
                 "pageNo":1,"numOfRows":3,"totalCount":75}
                """);

        var e = WeatherWarningCollector.parseEvents(body).getFirst();

        assertThat(e.command()).isEqualTo(2);
        assertThat(e.kindCode()).isEqualTo(6);
        assertThat(e.cancelled()).isFalse();
        assertThat(e.announcedAt()).isEqualTo(Instant.parse("2026-09-10T21:00:00Z"));
        // startTime 0 은 해당 없음 — 해제 이벤트의 발효 시각은 endTime
        assertThat(e.effectiveAt()).isEqualTo(Instant.parse("2026-09-10T23:00:00Z"));
    }

    @Test
    void 결과가_1건이면_item_이_객체로_온다() {
        JsonNode body = MAPPER.readTree("""
                {"items":{"item":{"areaCode":"S1311100","areaName":"부산앞바다","tmFc":202609081800,
                  "tmSeq":54,"warnVar":6,"warnStress":0,"command":"1","cancel":"0","startTime":202609081800}}}
                """);

        assertThat(WeatherWarningCollector.parseEvents(body)).hasSize(1);
    }

    @Test
    void 현황_문장의_없_음은_없음이다() {
        assertThat(WeatherWarningCollector.isNone("o 없 음")).isTrue();
        assertThat(WeatherWarningCollector.clean("o 없음\r\n\r\n")).isEqualTo("없음");
        assertThat(WeatherWarningCollector.clean("o 강풍주의보 : 울릉도.독도\no 풍랑주의보 : 남해동부먼바다"))
                .isEqualTo("강풍주의보 : 울릉도.독도\n풍랑주의보 : 남해동부먼바다");
    }

    @Test
    @SuppressWarnings("unchecked")
    void payload_에_해역과_현황을_싣는다() {
        var events = List.of(
                ev("202609081800", 54, BUSAN, "부산앞바다", 6, 0, 1),
                ev("202609081800", 54, "L1070100", "부산", 1, 0, 1));
        JsonNode status = MAPPER.readTree("""
                {"other":"o 없음\\r\\n\\r\\n","t6":"o 풍랑주의보 : 부산앞바다","t7":"o 없음",
                 "tmEf":"202609081800","tmFc":202609081800,"tmSeq":54}
                """);

        var payload = WeatherWarningCollector.payload(events, status);

        assertThat((List<String>) payload.get("activeMarineWarnings")).containsExactly("풍랑주의보");
        assertThat((List<Map<String, Object>>) payload.get("activeAreas"))
                .extracting(a -> a.get("areaName")).containsExactly("부산앞바다");
        // 강풍은 해상 이벤트 목록에서도 빠진다
        assertThat(payload.get("eventCount")).isEqualTo(1);
        var s = (Map<String, Object>) payload.get("status");
        assertThat(s.get("current")).isEqualTo("풍랑주의보 : 부산앞바다");
        assertThat(s.get("preliminary")).isEqualTo("없음");
    }

    @Test
    @SuppressWarnings("unchecked")
    void 조업_해역은_상위_구역_특보까지_잡고_전국_목록은_그대로_둔다() {
        var zones = WarningZones.of(List.of(
                new WarningZones.Zone("S1000000", null, "전해상"),
                new WarningZones.Zone("S1300000", "S1000000", "남해전해상"),
                new WarningZones.Zone("S1310000", "S1300000", "남해동부전해상"),
                new WarningZones.Zone("S1311000", "S1310000", "남해동부앞바다"),
                new WarningZones.Zone(BUSAN, "S1311000", "부산앞바다"),
                new WarningZones.Zone("S1323200", "S1323000", "제주도동부앞바다")));
        var events = List.of(
                ev("202609081800", 54, "S1310000", "남해동부전해상", 6, 0, 1),
                ev("202609081800", 54, "S1323200", "제주도동부앞바다", 6, 0, 1));

        var payload = WeatherWarningCollector.payload(events, null, List.of(BUSAN), zones);

        var focus = (Map<String, Object>) payload.get("focus");
        assertThat((List<Map<String, Object>>) focus.get("activeAreas"))
                .extracting(a -> a.get("areaName")).containsExactly("남해동부전해상");
        assertThat(focus.get("names")).isEqualTo(List.of("부산앞바다"));
        assertThat(focus.get("hierarchy")).isEqualTo(true);
        // 전국 목록은 거르지 않는다
        assertThat((List<?>) payload.get("activeAreas")).hasSize(2);
    }

    @Test
    @SuppressWarnings("unchecked")
    void 계층이_없으면_설정한_코드만_본다() {
        var events = List.of(ev("202609081800", 54, "S1310000", "남해동부전해상", 6, 0, 1));

        var focus = (Map<String, Object>) WeatherWarningCollector
                .payload(events, null, List.of(BUSAN), WarningZones.empty()).get("focus");

        assertThat((List<?>) focus.get("activeAreas")).isEmpty();
        assertThat(focus.get("hierarchy")).isEqualTo(false);
        // 이름을 모르면 코드 그대로. 지어내지 않는다
        assertThat(focus.get("names")).isEqualTo(List.of(BUSAN));
    }

    @Test
    void 조업_해역_설정은_쉼표로_나누고_비면_판정하지_않는다() {
        assertThat(WeatherWarningCollector.focusCodes(" S1311100 , S1312010,,S1311100"))
                .containsExactly("S1311100", "S1312010");
        assertThat(WeatherWarningCollector.focusCodes(null)).isEmpty();
        assertThat(WeatherWarningCollector.payload(List.of(), null).get("focus")).isNull();
    }
}

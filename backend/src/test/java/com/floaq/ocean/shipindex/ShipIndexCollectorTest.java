package com.floaq.ocean.shipindex;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** 선박운항지수 파싱. 입력은 2026-09-14 실응답 행 */
class ShipIndexCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    /** 순서를 일부러 섞었다 — 응답 순서에 기대지 않는지 본다 */
    private static final JsonNode BODY = MAPPER.readTree("""
            {"items":{"item":[
              {"vslNvgtBrnchCdNm":"대한해협","vslNvgtBrnchType":"AREA","predcYmd":"2026-09-14","predcTm":"00:00",
               "predcNoonSeCd":"새벽","lastScrCn":"좋음","avgCrsp":0.80,"avgWspd":3.1,"avgWvhgt":0.4},
              {"vslNvgtBrnchCdNm":"대한해협","vslNvgtBrnchType":"AREA","predcYmd":"2026-09-14","predcTm":"12:00",
               "predcNoonSeCd":"오후","lastScrCn":"좋음","avgCrsp":0.80,"avgWspd":5.5,"avgWvhgt":0.5},
              {"vslNvgtBrnchCdNm":"대한해협","vslNvgtBrnchType":"AREA","predcYmd":"2026-09-14","predcTm":"06:00",
               "predcNoonSeCd":"오전","lastScrCn":"좋음","avgCrsp":0.40,"avgWspd":4.7,"avgWvhgt":0.5},
              {"vslNvgtBrnchCdNm":"황해중부","vslNvgtBrnchType":"AREA","predcYmd":"2026-09-14","predcTm":"00:00",
               "predcNoonSeCd":"새벽","lastScrCn":"좋음","avgCrsp":1.00,"avgWspd":4.6,"avgWvhgt":0.4},
              {"vslNvgtBrnchCdNm":"대한해협","vslNvgtBrnchType":"AREA","predcYmd":"2026-09-18","predcTm":"06:00",
               "predcNoonSeCd":"오전","lastScrCn":"매우나쁨","avgCrsp":0.80,"avgWspd":13.0,"avgWvhgt":0.7}]},
             "pageNo":1,"numOfRows":300,"totalCount":5}
            """);

    @Test
    void 예보_시각은_KST_다() {
        var first = ShipIndexCollector.parse(BODY).getFirst();

        assertThat(first.at()).isEqualTo(Instant.parse("2026-09-13T15:00:00Z"));
    }

    @Test
    void 유속은_노트라_ms_로_바꾼다() {
        // ROMS 는 m/s, HF 는 cm/s, 여기는 kn. 그대로 두면 2배 가까이 틀린다
        assertThat(ShipIndexCollector.parse(BODY).getFirst().currentSpeedMs()).isEqualTo(0.41);
    }

    @Test
    void 지수_문구를_등급으로_바꾸고_모르는_문구는_남긴다() {
        assertThat(ShipIndexCollector.parse(BODY).getLast().level()).isEqualTo(5);

        var odd = ShipIndexCollector.parse(MAPPER.readTree("""
                {"items":{"item":{"vslNvgtBrnchCdNm":"대한해협","predcYmd":"2026-09-14","predcTm":"00:00",
                  "predcNoonSeCd":"새벽","lastScrCn":"주의","avgCrsp":"","avgWspd":3.1,"avgWvhgt":0.4}}}
                """)).getFirst();
        assertThat(odd.level()).isNull();
        assertThat(odd.score()).isEqualTo("주의");
        // 빈 문자열은 0 이 아니라 값 없음
        assertThat(odd.currentSpeedMs()).isNull();
    }

    @Test
    @SuppressWarnings("unchecked")
    void 지금_구간은_시작_시각이_지난_마지막_구간이다() {
        // 13:00 KST — 12시 오후 구간 안
        var payload = ShipIndexCollector.payload(
                ShipIndexCollector.parse(BODY), "AA_0004", Instant.parse("2026-09-14T04:00:00Z"));

        var current = (Map<String, Object>) payload.get("current");
        assertThat(current.get("slot")).isEqualTo("오후");
        assertThat(payload.get("validAt")).isEqualTo("2026-09-14T03:00:00Z");
        assertThat(payload.get("focusName")).isEqualTo("대한해협");
    }

    @Test
    @SuppressWarnings("unchecked")
    void 권역별로_묶고_코드를_붙인다() {
        var payload = ShipIndexCollector.payload(
                ShipIndexCollector.parse(BODY), "AA_0004", Instant.parse("2026-09-14T04:00:00Z"));

        var areas = (List<Map<String, Object>>) payload.get("areas");
        assertThat(areas).extracting(a -> a.get("code")).containsExactly("AA_0004", "AA_0001");
        var slots = (List<Map<String, Object>>) areas.getFirst().get("slots");
        assertThat(slots).extracting(s -> s.get("slot")).containsExactly("새벽", "오전", "오후", "오전");
    }

    @Test
    void 모르는_권역_코드면_지금_구간이_없다() {
        var payload = ShipIndexCollector.payload(
                ShipIndexCollector.parse(BODY), "AA_9999", Instant.parse("2026-09-14T04:00:00Z"));

        assertThat(payload.get("current")).isNull();
        assertThat(payload.get("focusName")).isNull();
    }
}

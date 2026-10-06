package com.floaq.ocean.nifs;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

/** 수과원 응답 공통 함정 — 빈 문자열, 중첩 배열, HTML 혼입 */
class NifsResponsesTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    private static JsonNode json(String raw) {
        return MAPPER.readTree(raw);
    }

    @Test
    void 빈_값이_null_이_아니라_빈_문자열로_온다() {
        // 적조 min_density 가 그렇다. 0 으로 두면 "밀도 0" 과 "측정 안 함" 이 같아진다
        JsonNode node = json("""
                {"min_density":"","max_density":"0.1","nam_biology":"Cochlodinium polykrikoides"}
                """);

        assertThat(NifsResponses.number(node, "min_density")).isNull();
        assertThat(NifsResponses.number(node, "max_density")).isEqualTo(0.1);
        assertThat(NifsResponses.text(node, "min_density")).isNull();
        assertThat(NifsResponses.text(node, "nam_biology")).isEqualTo("Cochlodinium polykrikoides");
    }

    @Test
    void 숫자가_아니면_null_이다() {
        assertThat(NifsResponses.number(json("{\"x\":\"없음\"}"), "x")).isNull();
    }

    @Test
    void item_이_하나면_객체로_온다() {
        assertThat(NifsResponses.items(json("{\"item\":{\"a\":1}}"))).hasSize(1);
        assertThat(NifsResponses.items(json("{\"item\":[{\"a\":1},{\"a\":2}]}"))).hasSize(2);
        assertThat(NifsResponses.items(null)).isEmpty();
    }

    @Test
    void HTML_을_걷어낸다() {
        // 그대로 렌더하면 깨지거나 XSS 가 된다
        String raw = "<p>해파리 주간보고</p><br>전남 완도&nbsp;해역<script>alert(1)</script>";

        assertThat(NifsResponses.plainText(raw)).isEqualTo("해파리 주간보고\n전남 완도 해역alert(1)");
    }

    @Test
    void 태그만_있으면_null_이다() {
        assertThat(NifsResponses.plainText("<p></p>")).isNull();
        assertThat(NifsResponses.plainText(null)).isNull();
    }
}

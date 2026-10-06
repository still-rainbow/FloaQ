package com.floaq.ocean.nifs;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

/** 해파리 첨부 원문. 입력은 2026-09-14 jellyDetail 실응답 모양 */
class JellyfishCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    @Test
    void 첨부가_1건이면_객체로_온다() {
        var detail = MAPPER.readTree("""
                {"srcode":"20260910094524086TAM","board_context":"<p>해파리 모니터링 주간보고 19차 (2026.09.10)</p>",
                 "item2":{"board_file":"https://nifs.go.kr/cmmnFile/getCmmnFile.do?FILE_ID=DX5-1789001082082-1"}}
                """);

        assertThat(JellyfishCollector.attachments(detail))
                .containsExactly("https://nifs.go.kr/cmmnFile/getCmmnFile.do?FILE_ID=DX5-1789001082082-1");
    }

    @Test
    void 첨부가_여러_건이면_배열로_온다() {
        var detail = MAPPER.readTree("""
                {"item2":[{"board_file":"https://nifs.go.kr/a"},{"board_file":"https://nifs.go.kr/b"}]}
                """);

        assertThat(JellyfishCollector.attachments(detail)).hasSize(2);
    }

    @Test
    void https_가_아닌_주소와_빈_값은_버린다() {
        // 화면이 링크로 여는 값이다. javascript: 가 들어오면 클릭 한 번이 스크립트 실행이 된다
        var detail = MAPPER.readTree("""
                {"item2":[{"board_file":"javascript:alert(1)"},{"board_file":"http://nifs.go.kr/a"},{"board_file":""}]}
                """);

        assertThat(JellyfishCollector.attachments(detail)).isEmpty();
    }

    @Test
    void 첨부가_없으면_빈_목록이다() {
        assertThat(JellyfishCollector.attachments(MAPPER.readTree("{\"srcode\":\"x\"}"))).isEmpty();
    }
}

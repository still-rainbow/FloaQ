package com.floaq.ocean.warning;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/** wrn_reg.php 고정폭. 입력은 2026-09-14 실응답 줄 */
class WarningZoneParserTest {

    private static final String BODY = """
            #START7777
            #  1. REG_ID   : 특보구역코드
            # REG_ID TM_ST        TM_ED        REG_SP   REG_UP   REG_KO---------------------------------- REG_NAME
            L1000000 200507010000 210012310000 00000001 00000000 전국                                     전국\s
            S1311100 200507010000 210012310000 00000015 S1311000 부산앞바다                               부산앞바다\s
            S2000000 200507010000 210012310000 00001001 S2000000 연안바다/평수구역                        연안바다/평수구역\s
            S1312010 202107291100 210012310000 00000014 S1310000 남해동부안쪽먼바다                       남해동부안쪽먼바다
            이상한 줄
            #7777END
            """;

    @Test
    void 머리말은_건너뛰고_데이터_줄만_읽는다() {
        assertThat(WarningZoneParser.parse(BODY)).extracting(WarningZoneParser.Row::id)
                .containsExactly("L1000000", "S1311100", "S2000000", "S1312010");
    }

    @Test
    void 상위코드_00000000_은_루트다() {
        assertThat(WarningZoneParser.parse(BODY).getFirst().up()).isNull();
    }

    @Test
    void 이름과_상위와_유효기간을_읽는다() {
        var busan = WarningZoneParser.parse(BODY).get(1);
        assertThat(busan.name()).isEqualTo("부산앞바다");
        assertThat(busan.up()).isEqualTo("S1311000");

        // 2021-07-29 11:00 KST 먼바다 세분화
        var outer = WarningZoneParser.parse(BODY).getLast();
        assertThat(outer.validFrom()).isEqualTo(Instant.parse("2021-07-29T02:00:00Z"));
    }

    @Test
    void 거부_응답이면_빈_목록이다() {
        assertThat(WarningZoneParser.parse("""
                {"result":{"status":403,"message":"활용신청이 필요한 API 입니다."}}
                """)).isEmpty();
    }
}

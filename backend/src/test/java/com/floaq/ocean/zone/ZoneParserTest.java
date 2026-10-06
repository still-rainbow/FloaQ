package com.floaq.ocean.zone;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/** 2026-09-14 API허브 실응답(EUC-KR 변환 후) 발췌 */
class ZoneParserTest {

    private static final String LARGE = """
            #START7777
            #   TMA_FC     TMA_EF LZONE LAT_LB  LON_LB  LAT_LT  LON_LT  LAT_RT  LON_RT  LAT_RB  LON_RB       WH_SIG     WVPRD_MAX          WVDR            WS            WD\s
            #      UTC        UTC          deg     deg     deg     deg     deg     deg     deg     deg            m           sec        degree           m/s        degree\s
            2026091400 2026091412    92   35.0   129.0    35.5   129.0    35.5   129.5    35.0   129.5          0.6           4.1          53.8           6.6          39.6
            2026091400 2026091412    17   37.5   127.0    38.0   127.0    38.0   127.5    37.5   127.5       -999.0        -999.0        -999.0        -999.0        -999.0
            #7777END
            """;

    private static final String SMALL = """
            #START7777
            #   TMA_FC     TMA_EF LZONE SZONE   LAT_LB    LON_LB    LAT_LT    LON_LT    LAT_RT    LON_RT    LAT_RB    LON_RB       WH_SIG     WVPRD_MAX          WVDR            WS            WD            VS          RAIN            TW         SWELL
            2026091400 2026091412    92     1   35.333   129.000    35.500   129.000    35.500   129.167    35.333   129.167       -999.0        -999.0        -999.0        -999.0        -999.0       20000.0           0.0          26.3          -999
            2026091400 2026091412    92     9   35.000   129.333    35.167   129.333    35.167   129.500    35.000   129.500          0.7           4.7          41.8           7.9          41.8       12360.0           0.8          26.4             2
            #7777END
            """;

    /** 2026-07-01 이전 소해구 — 끝 네 칸이 없다 */
    private static final String SMALL_OLD = """
            #START7777
            2025012500 2025012609     1     1   42.833   131.500    43.000   131.500    43.000   131.667    42.833   131.667          0.1           5.5         200.6           3.6         315.9
            #7777END
            """;

    @Test
    void 대해구_한_줄을_읽는다() {
        var cells = ZoneParser.parse(LARGE, ZoneLevel.LARGE);

        assertThat(cells).hasSize(2);
        var c = cells.getFirst();
        assertThat(c.lzone()).isEqualTo(92);
        assertThat(c.szone()).isZero();
        assertThat(c.tmaFc()).isEqualTo(Instant.parse("2026-09-14T00:00:00Z"));
        assertThat(c.tmaEf()).isEqualTo(Instant.parse("2026-09-14T12:00:00Z"));
        assertThat(c.latMin()).isEqualTo(35.0);
        assertThat(c.latMax()).isEqualTo(35.5);
        assertThat(c.lonMin()).isEqualTo(129.0);
        assertThat(c.lonMax()).isEqualTo(129.5);
        assertThat(c.waveHeightM()).isEqualTo(0.6);
        assertThat(c.windDirDeg()).isEqualTo(39.6);
        // 대해구에는 없는 요소
        assertThat(c.waterTempC()).isNull();
        assertThat(c.swellLevel()).isNull();
    }

    @Test
    void 결측은_null_이다() {
        // -999 를 숫자로 두면 파고 -999m 가 화면에 오른다. 0 으로 두면 잔잔한 바다로 읽힌다
        var land = ZoneParser.parse(LARGE, ZoneLevel.LARGE).get(1);

        assertThat(land.waveHeightM()).isNull();
        assertThat(land.windSpeedMs()).isNull();
    }

    @Test
    void 소해구는_수온_시정_강수_너울까지_읽는다() {
        var cells = ZoneParser.parse(SMALL, ZoneLevel.SMALL);

        assertThat(cells).hasSize(2);
        var coast = cells.getFirst();
        assertThat(coast.szone()).isEqualTo(1);
        // 육지에 걸린 칸 — 파고·바람은 결측인데 수온은 있다(실응답 그대로)
        assertThat(coast.waveHeightM()).isNull();
        assertThat(coast.waterTempC()).isEqualTo(26.3);
        assertThat(coast.swellLevel()).isNull();

        var sea = cells.get(1);
        assertThat(sea.visibilityM()).isEqualTo(12360.0);
        assertThat(sea.rainMm()).isEqualTo(0.8);
        assertThat(sea.swellLevel()).isEqualTo(2);
        assertThat(sea.latMin()).isEqualTo(35.0);
        assertThat(sea.lonMax()).isEqualTo(129.5);
    }

    @Test
    void 이전_소해구_형식은_추가_요소를_null_로_둔다() {
        var cells = ZoneParser.parse(SMALL_OLD, ZoneLevel.SMALL);

        assertThat(cells).hasSize(1);
        assertThat(cells.getFirst().windSpeedMs()).isEqualTo(3.6);
        assertThat(cells.getFirst().waterTempC()).isNull();
    }

    @Test
    void 오류_문구는_자료가_아니다() {
        // HTTP 200 으로 온다. 표식으로 가르지 않으면 빈 발표본이 성공으로 저장된다
        String notReady = "파일이 존재하지 않습니다. (/C5N_DATA/GID/MRZ/202609/14/marine_wave_kim_rww3_h000_2026091412.txt)\n"
                + "호출한 변수(생산시각, 요청시각 등)에 대응하는 자료가 없습니다.";
        String badEf = "발효시각을 확인하여 주시기 바랍니다.";

        assertThat(ZoneParser.isData(notReady)).isFalse();
        assertThat(ZoneParser.isNotReady(notReady)).isTrue();
        assertThat(ZoneParser.isNotReady(badEf)).isFalse();
        assertThat(ZoneParser.parse(badEf, ZoneLevel.LARGE)).isEmpty();
        assertThat(ZoneParser.message(badEf)).isEqualTo("발효시각을 확인하여 주시기 바랍니다.");
    }

    @Test
    void 깨진_줄은_건너뛰고_나머지는_살린다() {
        String body = LARGE.replace("#7777END", "2026091400 2026091412 xx 1 2\n#7777END");

        assertThat(ZoneParser.parse(body, ZoneLevel.LARGE)).hasSize(2);
    }
}

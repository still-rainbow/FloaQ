package com.floaq.ocean.seaobs;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** sea_obs 고정폭 파싱. 결측 -99 를 값으로 읽으면 화면에 수온 -99℃ 가 오른다 */
class SeaObsParserTest {

    /** 2026-09-13 실제 응답 일부 (EUC-KR 변환 후) */
    private static final String BODY = """
            #START7777
            #            TM       STN                   STN           LON           LAT     WH   WD     WS     WS     TW     TA      PA     HM
            #           KST        ID                    KO           deg           deg      m  deg    m/s    GST      C      C     hPa      %
            B, 202609131600,    22104,               거제도, 128.90000000,  34.76670000,   0.5, 203,   3.4,   4.2,  26.6,  25.4, 1016.7,  77.0, ,=
            C, 202609131600,    22459,               오륙도, 129.12830000,  35.09450000,   0.4, -99, -99.0, -99.0,  25.4, -99.0,  -99.0, -99.0, ,=
            #7777END
            """;

    @Test
    void 관측망_지점_좌표_시각을_읽는다() {
        List<SeaObsStation> stations = SeaObsParser.parse(BODY);

        assertThat(stations).hasSize(2);
        SeaObsStation geoje = stations.getFirst();
        assertThat(geoje.network()).isEqualTo("B");
        assertThat(geoje.stn()).isEqualTo("22104");
        assertThat(geoje.name()).isEqualTo("거제도");
        assertThat(geoje.lat()).isEqualTo(34.76670000);
        assertThat(geoje.lon()).isEqualTo(128.90000000);
        // TM 은 KST 다. UTC 로 읽으면 관측이 9시간 미래가 된다
        assertThat(geoje.observedAt()).isEqualTo(Instant.parse("2026-09-13T07:00:00Z"));
    }

    @Test
    void 결측_99_는_null_이다() {
        // 파고부이(C)는 바람·기압을 주지 않는다. 관측망마다 요소가 갈린다는 §6 경고의 실제 모습
        SeaObsStation buoy = SeaObsParser.parse(BODY).get(1);

        assertThat(buoy.waveHeightM()).isEqualTo(0.4);
        assertThat(buoy.waterTempC()).isEqualTo(25.4);
        assertThat(buoy.windDirDeg()).isNull();
        assertThat(buoy.windSpeedMs()).isNull();
        assertThat(buoy.pressureHpa()).isNull();
        assertThat(buoy.humidityPct()).isNull();
    }

    @Test
    void 주석과_빈_줄은_건너뛴다() {
        assertThat(SeaObsParser.parse("#START7777\n\n#7777END\n")).isEmpty();
    }

    @Test
    void 본문이_없으면_빈_목록이다() {
        // 호출 실패가 null 로 온다. 예외를 던지면 한 소스가 수집 전체를 멈춘다
        assertThat(SeaObsParser.parse(null)).isEmpty();
    }
}

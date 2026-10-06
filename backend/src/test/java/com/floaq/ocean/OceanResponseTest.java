package com.floaq.ocean;

import com.floaq.ocean.client.OceanResponse;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

/** 봉투 3종 판독. 한쪽만 보면 키 만료(31)를 조용히 놓친다 */
class OceanResponseTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    private static JsonNode json(String raw) {
        return MAPPER.readTree(raw);
    }

    @Test
    void response_봉투가_한_겹_있는_형태를_읽는다() {
        // ROMS 활용가이드 PDF 응답 예제
        var response = OceanResponse.of(200, json("""
                {"response":{"header":{"resultCode":"00","resultMsg":"NORMAL_SERVICE"},
                 "body":{"totalCount":2136}}}
                """));

        assertThat(response.isOk()).isTrue();
        assertThat(response.body().path("totalCount").asInt()).isEqualTo(2136);
    }

    @Test
    void response_봉투가_없는_형태도_읽는다() {
        // 260911_ocean-live-check 가 기록한 형태. PDF 와 어긋나 양쪽을 받는다
        var response = OceanResponse.of(200, json("""
                {"header":{"resultCode":"00"},"body":{"totalCount":1}}
                """));

        assertThat(response.isOk()).isTrue();
        assertThat(response.body().path("totalCount").asInt()).isEqualTo(1);
    }

    @Test
    void 게이트웨이_오류는_HTTP_403_에_다른_필드명으로_온다() {
        // 실호출 403. header 가 없어 resultCode 로 읽으면 코드가 빈다
        var response = OceanResponse.of(403, json("""
                {"OpenAPI_ServiceResponse":{"cmmMsgHeader":{
                 "errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR","returnReasonCode":"30"}}}
                """));

        assertThat(response.code()).isEqualTo("30");
        assertThat(response.isFailure()).isTrue();
        assertThat(response.body()).isNull();
    }

    @Test
    void 데이터없음은_실패가_아니다() {
        // 실패로 처리하면 관측 공백마다 알람이 운다
        var response = OceanResponse.of(200, json("""
                {"header":{"resultCode":"03","resultMsg":"NODATA_ERROR"}}
                """));

        assertThat(response.isNoData()).isTrue();
        assertThat(response.isFailure()).isFalse();
    }

    @Test
    void 모르는_코드는_실패로_본다() {
        // 22 쿼터초과 · 31 기한만료 · 99 범위초과. 통과시키면 빈 값이 정상으로 둔갑한다
        var response = OceanResponse.of(200, json("""
                {"header":{"resultCode":"22","resultMsg":"LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"}}
                """));

        assertThat(response.isFailure()).isTrue();
    }

    @Test
    void 본문이_없으면_HTTP_상태로_말한다() {
        var response = OceanResponse.of(500, null);

        assertThat(response.code()).isEqualTo("HTTP_500");
        assertThat(response.isFailure()).isTrue();
    }
}

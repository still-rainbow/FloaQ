package com.floaq.ocean.summary;

import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

/** 목 문장. 진짜처럼 읽히면 LLM 이 켜졌는지 화면에서 구분할 수 없다 */
class OceanSummaryWriterTest {

    private static OceanSummaryWriter writer(String apiKey) {
        return new OceanSummaryWriter(mock(WebClient.class), "https://gms.example/v1", apiKey, "gpt-5-mini");
    }

    @Test
    void 목은_목이라고_밝힌다() {
        var s = writer("").mock(List.of("해상 특보: 발효 중 없음", "파고 0.4m (오륙도, 8.6km)"));

        assertThat(s.mock()).isTrue();
        assertThat(s.model()).isEqualTo("mock");
        assertThat(s.body()).startsWith("수집된 값을 그대로 이은 것입니다");
    }

    @Test
    void 목은_근거를_그대로_들고_간다() {
        var facts = List.of("해상 특보: 발효 중 없음", "수온 25.8℃ (기장, 26.1km)");

        assertThat(writer("").mock(facts).facts()).isEqualTo(facts);
    }

    @Test
    void 특보_유무가_headline_을_가른다() {
        assertThat(writer("").mock(List.of("해상 특보: 발효 중 없음")).headline())
                .isEqualTo("발효 중 해상 특보 없음");
        assertThat(writer("").mock(List.of("해상 특보: [풍랑경보] 발효 중")).headline())
                .isEqualTo("해상 특보 발효 중");
    }

    @Test
    void 조업_해역_판정이_있으면_그_줄로_headline_을_가른다() {
        // 전국에 특보가 있어도 조업 해역이 조용하면 "발효 중"이라 쓰지 않는다
        assertThat(writer("").mock(List.of(
                "조업 해역(부산앞바다·남해동부안쪽먼바다) 해상 특보: 없음",
                "전국 해상 특보: 풍랑주의보 발효 중 (제주도동부앞바다)")).headline())
                .isEqualTo("조업 해역 해상 특보 없음");
        assertThat(writer("").mock(List.of(
                "조업 해역(부산앞바다) 해상 특보: 풍랑경보 발효 중",
                "전국 해상 특보: 풍랑경보 발효 중 (남해동부전해상)")).headline())
                .isEqualTo("조업 해역 해상 특보 발효 중");
    }

    @Test
    void 키가_없으면_부르지_않고_던진다() {
        // 키 없이 부르면 401 을 맞고 그 응답이 크레딧 잔량 오해를 만든다
        assertThatThrownBy(() -> writer("").generate(List.of("파고 0.4m")))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("LLM_API_KEY");
    }
}

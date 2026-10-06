package com.floaq.ocean.summary;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * 요약 문장을 만든다 — 목 또는 LLM provider.
 *
 * LLM provider 는 OpenAI 호환 게이트웨이다. 파라미터·응답 포맷이 OpenAI 공식 문서와 같고
 * 엔드포인트만 치환한다 (계획.md §9.18).
 *
 * ⚠ 이미지를 보내지 않는다. 이미 가진 것(YOLO 결과·수치)을 프리미엄 토큰으로 다시 사는 셈이고,
 * YOLO 는 인터넷 없이 돌지만 LLM 은 안 된다 — 이미지 이해를 LLM 에 의존하면 오프라인에서 기능이 사라진다.
 */
@Slf4j
@Component
public class OceanSummaryWriter {

    /**
     * 판단을 맡기지 않는다. 출항 가부는 기상청 특보 기준이 정하고 LLM 은 그것을 옮긴다.
     *
     * 없는 값을 지어내지 말라고 명시한다 — 숫자를 만들어 내면 그 숫자가 조업 판단에 쓰인다.
     */
    private static final String SYSTEM = """
            너는 한국 연안 소형 어선의 선내 단말에 뜨는 해양 상황 요약을 쓴다.
            규칙:
            - 주어진 값만 쓴다. 값에 없는 숫자·지명·시각을 지어내지 않는다.
            - 출항 가부를 판정하지 않는다. 그건 기상특보 기준이 정한다. 너는 상황을 설명만 한다.
            - 어민이 읽는다. 전문용어를 풀어 쓰고 문장을 짧게 한다.
            - 해파리 출현율은 설문 응답률이라 판단 근거가 아니다. 언급하면 그 단서를 붙인다.
            - body 는 **지금 한 문장 + 앞으로 한 문장**이다.
              · 첫 문장: 지금 상황 (특보 · 파고 · 풍속 · 수온).
              · 둘째 문장: 앞으로의 변화. `A→B` 꼴로 주어진 값과 `다음 …` 으로 주어진 값만 쓴다.
                그런 값이 하나도 없으면 **둘째 문장을 쓰지 않는다.** 없는 추세를 지어내지 않는다.
              · `A→B` 를 옮길 때 방향만 말하지 말고 두 숫자를 다 적는다 — 어민이 크기를 보고 판단한다.
            출력은 JSON 하나: {"headline": "한 줄 15자 내외", "body": "두세 문장"}
            """;

    private final WebClient llm;
    private final String baseUrl;
    private final String apiKey;
    private final String model;

    public OceanSummaryWriter(@Qualifier("llmWebClient") WebClient llm,
                              @Value("${app.llm.base-url:}") String baseUrl,
                              @Value("${app.llm.api-key:}") String apiKey,
                              @Value("${app.llm.model:gpt-4o-mini}") String model) {
        this.llm = llm;
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.model = model;
    }

    /**
     * LLM 없이 규칙으로 만든 문장.
     *
     * 값을 이어 붙이기만 한다 — 해석·판단을 넣지 않는다. 목이 진짜처럼 읽히면
     * LLM 이 켜졌는지 꺼졌는지 화면에서 구분할 수 없고, 그 상태로 발표에 들어간다.
     */
    public OceanSummary mock(List<String> facts) {
        // 조업 해역 판정이 있으면 그 줄이 기준. 전국 줄로 헤드라인을 만들면 남의 해역 특보가 우리 경보가 됨
        String focus = facts.stream().filter(f -> f.startsWith("조업 해역(")).findFirst().orElse(null);
        String warning = focus != null ? focus
                : facts.stream().filter(f -> f.startsWith("해상 특보")).findFirst().orElse(null);
        String prefix = focus != null ? "조업 해역 " : "";
        boolean calm = warning != null && warning.endsWith("없음");
        String headline = warning == null ? "해양 데이터 수집 중"
                : calm ? prefix + (focus != null ? "해상 특보 없음" : "발효 중 해상 특보 없음")
                : prefix + "해상 특보 발효 중";
        return new OceanSummary(headline,
                "수집된 값을 그대로 이은 것입니다. " + String.join(" · ", facts) + ".",
                facts, Instant.now(), "mock", true);
    }

    /** 6종을 한 컨텍스트에 담아 한 번 부른다. 쪼개면 크레딧이 배수가 되고 문장끼리 어긋난다 */
    public OceanSummary generate(List<String> facts) {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException("LLM_API_KEY 가 없다");
        }
        Map<String, Object> body = Map.of(
                "model", model,
                "messages", List.of(
                        Map.of("role", "system", "content", SYSTEM),
                        Map.of("role", "user", "content", String.join("\n", facts))),
                "response_format", Map.of("type", "json_object"),
                // 토큰 과금이라 상한이 곧 비용 상한이다. 실측 출력 75토큰(2026-09-18)이라 300 이면 잘리지 않는다
                "max_tokens", 300);

        JsonNode res = llm.post()
                .uri(baseUrl + "/chat/completions")
                .header("Authorization", "Bearer " + apiKey)
                .bodyValue(body)
                .retrieve()
                .bodyToMono(JsonNode.class)
                .block();

        String content = res == null ? null
                : res.path("choices").path(0).path("message").path("content").asString();
        if (content == null || content.isBlank()) {
            throw new IllegalStateException("빈 응답");
        }
        JsonNode parsed = tools.jackson.databind.json.JsonMapper.builder().build().readTree(content);
        return new OceanSummary(
                parsed.path("headline").asString(),
                parsed.path("body").asString(),
                facts, Instant.now(), model, false);
    }
}

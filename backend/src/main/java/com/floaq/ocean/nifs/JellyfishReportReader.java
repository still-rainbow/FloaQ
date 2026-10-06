package com.floaq.ocean.nifs;

import lombok.extern.slf4j.Slf4j;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 해파리 주간보고 PDF 에서 수치를 꺼낸다.
 *
 * <h2>왜 필요한가</h2>
 * <p>수과원 API 는 <b>제목 한 줄과 첨부 링크만</b> 준다. 지역별 출현율은 그 PDF 안에만 있고,
 * 그래서 화면이 <i>지역별 출현율 수치는 API 가 주지 않아 원문으로 연결합니다</i> 로 물러서 있었다.
 * <b>수치는 실제로 그 안에 있다</b>(2026-09-18 실측 — 종·지난주%·이번주%·고밀도/저밀도 해역).</p>
 *
 * <h2>왜 PDF 를 통째로 안 넘기나</h2>
 * <p>파일 2.18MB 중 <b>93%가 JPEG 지도</b>다. 비전으로 보내면 토큰이 수십 배인데,
 * 정작 우리가 쓰는 숫자는 <b>텍스트층에 있다</b>(ToUnicode CMap 8개, 본문 약 3,900자).
 * 그래서 <b>텍스트만 뽑아 넘긴다</b> — 입력 2천 토큰 안팎이다.</p>
 *
 * <h2>왜 정규식이 아니라 LLM 인가</h2>
 * <p>PDF 는 <b>그리는 순서대로</b> 저장돼 읽는 순서가 뒤엉킨다. 실측 본문이
 * {@code 노무라입깃해파리 · (17% · -> · 18%): · 전남광주 · 고밀도} 처럼 조각나 흩어진다.
 * 짜맞추는 규칙을 손으로 쓰면 <b>양식이 조금만 바뀌어도 조용히 틀린 숫자</b>가 나온다.</p>
 *
 * <h2>비용</h2>
 * <p>주간보고다. {@code srcode} 가 같으면 {@link NifsDetailCache} 가 직전 결과를 그대로 쓰므로
 * <b>실제 호출은 주 1회</b>다. 하루 48회 도는 해양 요약에 비하면 없는 것과 같다.</p>
 *
 * <p>🔴 <b>실패하면 null 이다.</b> 화면은 예전처럼 제목과 원문 링크로 물러선다 —
 * 양식이 바뀌었을 때 <b>조용히 틀린 숫자를 내놓는 것이 제일 나쁘다</b>.</p>
 */
@Slf4j
@Component
public class JellyfishReportReader {

    /** 모델 규칙. <b>값을 지어내지 말라고 명시한다</b> — 출현율은 어민이 조업 판단에 쓰는 숫자다 */
    private static final String SYSTEM = """
            너는 국립수산과학원 해파리 모니터링 주간보고 PDF 에서 뽑은 **순서가 뒤엉킨 텍스트**를 받아
            구조화한다. PDF 라 글자가 조각나고 순서가 섞여 있다.
            규칙:
            - 본문에 있는 값만 쓴다. 없는 종·해역·숫자를 지어내지 않는다.
            - 퍼센트는 (지난주 -> 이번주) 꼴로 나온다. 둘 다 있으면 둘 다 담는다.
            - 해역 이름이 붙어 나오면(예: 전남광주) 그대로 둔다. 쪼개거나 고치지 않는다.
            - 확신이 없는 항목은 그 항목을 통째로 뺀다. 빈 배열이 틀린 값보다 낫다.
            출력은 JSON 하나:
            {"species":[{"name":"노무라입깃해파리","prevPct":17,"pct":18,
                         "high":["전남광주"],"low":["인천","경기"]}],
             "note":"본문에 있는 한 줄 요약. 없으면 빈 문자열"}
            """;

    /** 내려받기 상한. 주간보고가 2.2MB 수준이라 넉넉하되, 이상한 응답에 메모리를 안 준다 */
    private static final int MAX_PDF_BYTES = 24 * 1024 * 1024;

    /**
     * 모델에 넘길 본문 상한(자). 실측 약 3,900자다. 양식이 바뀌어 길어져도
     * 토큰이 폭주하지 않게 자른다 — 앞쪽에 종·출현율 요약이 온다.
     */
    private static final int MAX_TEXT_CHARS = 12_000;

    private static final Duration TIMEOUT = Duration.ofSeconds(30);

    private final WebClient llm;
    private final String baseUrl;
    private final String apiKey;
    private final String model;
    private final boolean enabled;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(TIMEOUT).build();

    public JellyfishReportReader(@Qualifier("llmWebClient") WebClient llm,
                                 @Value("${app.llm.base-url:}") String baseUrl,
                                 @Value("${app.llm.api-key:}") String apiKey,
                                 @Value("${app.llm.model:gpt-4o-mini}") String model,
                                 @Value("${app.llm.enabled:false}") boolean enabled) {
        this.llm = llm;
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.model = model;
        this.enabled = enabled;
    }

    /**
     * @param fileUrl 주간보고 첨부 PDF 주소
     * @return 구조화된 결과. <b>못 읽으면 null</b> — 호출부가 제목·링크로 물러선다
     */
    public Map<String, Object> read(String fileUrl) {
        if (!enabled || apiKey == null || apiKey.isBlank()) {
            return null;                    // 키가 없으면 조용히 건너뛴다. 나머지 수집은 그대로 돈다
        }
        String text = extract(fileUrl);
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return structure(text);
        } catch (Exception e) {
            // 요약과 같은 원칙 — 실패해도 수집 전체를 세우지 않는다. 시끄럽게 남기고 물러선다
            log.warn("[ocean] 해파리 주간보고 구조화 실패 — 제목·링크로 물러선다: {}", e.toString());
            return null;
        }
    }

    /** PDF 를 받아 텍스트만 뽑는다. 이미지는 보지 않는다 */
    private String extract(String fileUrl) {
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(fileUrl)).timeout(TIMEOUT).GET().build();
            HttpResponse<byte[]> res = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
            byte[] body = res.body();
            if (res.statusCode() != 200 || body == null) {
                log.warn("[ocean] 해파리 첨부를 못 받았다 — HTTP {}", res.statusCode());
                return null;
            }
            if (body.length > MAX_PDF_BYTES) {
                log.warn("[ocean] 해파리 첨부가 너무 크다 ({}바이트) — 건너뛴다", body.length);
                return null;
            }
            // 🔴 확장자·Content-Type 을 믿지 않는다. 실제 응답이 application/stream 으로 온다(실측)
            if (body.length < 5 || body[0] != 0x25 || body[1] != 0x50
                    || body[2] != 0x44 || body[3] != 0x46) {
                log.warn("[ocean] 해파리 첨부가 PDF 가 아니다 — 건너뛴다");
                return null;
            }
            try (PDDocument doc = Loader.loadPDF(body)) {
                PDFTextStripper stripper = new PDFTextStripper();
                // 순서를 정렬한다. PDF 는 그리는 순서로 저장돼 그냥 뽑으면 더 엉킨다
                stripper.setSortByPosition(true);
                String text = stripper.getText(doc);
                return text.length() > MAX_TEXT_CHARS ? text.substring(0, MAX_TEXT_CHARS) : text;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        } catch (IOException | RuntimeException e) {
            log.warn("[ocean] 해파리 첨부 읽기 실패 — {}", e.toString());
            return null;
        }
    }

    /** 뒤엉킨 본문을 구조로 세운다 */
    private Map<String, Object> structure(String text) {
        Map<String, Object> body = Map.of(
                "model", model,
                "messages", List.of(
                        Map.of("role", "system", "content", SYSTEM),
                        Map.of("role", "user", "content", text)),
                "response_format", Map.of("type", "json_object"),
                "max_tokens", 700);

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
        JsonMapper mapper = JsonMapper.builder().build();
        JsonNode parsed = mapper.readTree(content);
        JsonNode species = parsed.path("species");
        if (!species.isArray() || species.isEmpty()) {
            // 종이 하나도 없으면 읽은 것이 아니다. 빈 껍데기를 화면에 올리지 않는다
            throw new IllegalStateException("species 가 비었다");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("species", mapper.convertValue(species, List.class));
        out.put("note", parsed.path("note").asString(""));
        out.put("model", model);
        log.info("[ocean] 해파리 주간보고에서 종 {}건을 읽었다", species.size());
        return out;
    }
}

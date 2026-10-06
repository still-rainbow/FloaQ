package com.floaq.ocean.client;

import com.floaq.ocean.OceanApiProperties.Source;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.NullNode;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * 공공데이터 1회 호출 — 인증 파라미터 주입 · URI 조립 · 봉투 판독.
 *
 * 소스별 파라미터·응답 해석은 각 수집기 소관. 여기서 분기하면 소스마다 이 클래스가 자람.
 */
@Slf4j
@Component
public class OceanApiClient {

    /** defaultIfEmpty 가 null 불가. 본문 없는 응답 표식 */
    private static final JsonNode NO_BODY = NullNode.getInstance();
    private static final byte[] NO_BYTES = new byte[0];

    private final WebClient webClient;
    private final OceanCallBudget budget;

    public OceanApiClient(@Qualifier("oceanWebClient") WebClient webClient, OceanCallBudget budget) {
        this.webClient = webClient;
        this.budget = budget;
    }

    /** 예외를 던지지 않음 — 한 소스 장애가 다른 소스 수집을 막으면 안 됨 */
    public OceanResponse get(String name, Source source, String key, Map<String, String> params) {
        // 페이지 단위로 센다. 발급처가 거부하기 시작하면 하루가 끝날 때까지 값이 멈춘다
        if (!budget.tryConsume(name, source.dailyQuota())) {
            log.warn("[ocean] {} — 하루 호출 예산 소진. 수집을 건너뛴다 ({}회)", name, source.dailyQuota());
            return new OceanResponse(0, OceanResponse.QUOTA_GUARD, "하루 호출 예산 소진", null);
        }
        URI uri = buildUri(source, key, params);
        try {
            return webClient.get()
                    .uri(uri)
                    // retrieve() 기각 — 4xx·5xx 에서 본문을 버림.
                    // 게이트웨이 오류 원인 코드가 그 본문에만 있음
                    .exchangeToMono(response -> response.bodyToMono(JsonNode.class)
                            .defaultIfEmpty(NO_BODY)
                            .map(json -> OceanResponse.of(response.statusCode().value(),
                                    json == NO_BODY ? null : json)))
                    .block();
        } catch (Exception e) {
            // 타임아웃·DNS·커넥션 거절. 다음 주기 재시도, 마지막 성공값 유지
            log.warn("[ocean] {} 호출 실패 — {}", name, e.toString());
            return new OceanResponse(0, "ERROR", e.getClass().getSimpleName(), null);
        }
    }

    /**
     * JSON 이 아닌 응답용. 지금은 기상청 sea_obs 하나뿐이다.
     *
     * 바이트로 받아 호출부가 charset 을 정한다. sea_obs 는 EUC-KR 이라
     * 문자열로 바로 받으면(WebClient 기본 UTF-8) 지점명이 깨진다.
     *
     * @return 실패하면 null. 상태 코드는 버린다 — 고정폭 텍스트라 판독할 봉투가 없다
     */
    public String getText(String name, Source source, String key, Map<String, String> params, Charset charset) {
        if (!budget.tryConsume(name, source.dailyQuota())) {
            log.warn("[ocean] {} — 하루 호출 예산 소진. 수집을 건너뛴다 ({}회)", name, source.dailyQuota());
            return null;
        }
        URI uri = buildUri(source, key, params);
        try {
            byte[] body = webClient.get()
                    .uri(uri)
                    .exchangeToMono(response -> response.bodyToMono(byte[].class).defaultIfEmpty(NO_BYTES))
                    .block();
            return body == null || body.length == 0 ? null : new String(body, charset);
        } catch (Exception e) {
            log.warn("[ocean] {} 호출 실패 — {}", name, e.toString());
            return null;
        }
    }

    /**
     * 인증키는 인코딩 없이 그대로 부착.
     *
     * 가이드가 serviceKey 에 URL Encode 된 값을 요구. 재인코딩하면 %2B 가 %252B 가 되어
     * "키는 맞는데 인증 실패" — 응답 메시지가 원인을 말해 주지 않는다.
     * 현재 키는 64자 hex 라 무해하나 재발급 시 달라질 수 있다.
     *
     * 구분자를 고정하지 않는다 — base-url 에 쿼리가 이미 붙은 소스가 있다.
     */
    private URI buildUri(Source source, String key, Map<String, String> params) {
        StringBuilder url = new StringBuilder(source.baseUrl());
        url.append(source.baseUrl().contains("?") ? '&' : '?')
                .append(source.provider().authParam()).append('=').append(key);
        params.forEach((k, v) -> url.append('&').append(k).append('=')
                .append(URLEncoder.encode(v, StandardCharsets.UTF_8)));
        return URI.create(url.toString());
    }
}

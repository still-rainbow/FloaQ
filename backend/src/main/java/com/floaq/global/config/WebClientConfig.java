package com.floaq.global.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * 외부 호출용 WebClient — 해양 공공데이터 6종, LLM provider(LLM).
 *
 * <p><b>타임아웃이 이 설정의 전부다.</b> MVC(블로킹)에서 {@code block()} 으로 동기 호출하므로,
 * 외부가 응답하지 않으면 <b>톰캣 스레드가 그대로 점유된다.</b> 공공데이터 API 한 곳이 느려지면
 * 스레드풀이 고갈되고 사고 기록 수신까지 같이 멈춘다 — 하필 가장 급할 때다.</p>
 *
 * <p>그래서 §6 이 "평시에 미리 받아둔다"고 한 것이다. 이 타임아웃은 그 원칙이 깨졌을 때의 안전망이다.</p>
 */
@Configuration
public class WebClientConfig {

    private static final int CONNECT_TIMEOUT_MS = 5_000;

    /** 공공데이터는 조회 API 라 빨라야 정상이다. 늦으면 이번 수집을 포기하고 다음 주기를 기다린다. */
    private static final int OCEAN_TIMEOUT_SEC = 10;
    private static final int OCEAN_BUFFER_BYTES = 4 * 1024 * 1024;

    /** LLM 생성은 수 초~수십 초. 사전 생성이라 화면이 기다리지 않으므로 길게 잡아도 된다(§9.18). */
    private static final int LLM_TIMEOUT_SEC = 60;
    private static final int LLM_BUFFER_BYTES = 8 * 1024 * 1024;

    @Bean
    public WebClient oceanWebClient() {
        return build(OCEAN_TIMEOUT_SEC, OCEAN_BUFFER_BYTES);
    }

    @Bean
    public WebClient llmWebClient() {
        return build(LLM_TIMEOUT_SEC, LLM_BUFFER_BYTES);
    }

    private WebClient build(int timeoutSec, int bufferBytes) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(Duration.ofSeconds(timeoutSec))
                .doOnConnected(conn ->
                        conn.addHandlerLast(new ReadTimeoutHandler(timeoutSec, TimeUnit.SECONDS)));
        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .codecs(c -> c.defaultCodecs().maxInMemorySize(bufferBytes))
                .build();
    }
}

package com.floaq.global.config;

import tools.jackson.databind.ObjectMapper;
import com.floaq.global.security.PiApiKeyFilter;
import com.floaq.ship.ShipRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 서블릿 필터 등록.
 *
 * <p>관제 웹 JWT 인증은 {@code SecurityConfig} 에 있다. Pi 필터는 Security 체인 밖의
 * 평범한 서블릿 필터로 둔다 — 체인이 {@code /api/pi/**} 를 permitAll 로 통과시키고
 * 이 필터가 막는다. 체인보다 뒤에 돌지만 경로가 겹치지 않아 순서에 기대는 곳이 없다.</p>
 */
@Configuration
public class FilterConfig {

    /**
     * <b>등록 키</b>만 설정값이다. 저장소에 두지 않는다 — {@code .env} → compose → 환경변수.
     * 비워 두면 선박 등록이 401 로 닫힌다(안전한 쪽).
     *
     * <p>선박 키는 설정에 없다 — 등록 때 발급해 {@code ship.edge_key_hash} 에 넣으므로
     * 필터가 {@link ShipRepository} 로 찾는다(docs/api.md §1.1).</p>
     */
    @Bean
    public FilterRegistrationBean<PiApiKeyFilter> piApiKeyFilter(
            @Value("${app.pi.enroll-key:}") String enrollKey,
            ShipRepository ships, ObjectMapper objectMapper) {

        FilterRegistrationBean<PiApiKeyFilter> bean =
                new FilterRegistrationBean<>(new PiApiKeyFilter(enrollKey, ships, objectMapper));
        // 추적 ID 다음. 인증 실패 로그에도 traceId 가 붙어야 nginx 로그와 이어진다
        bean.setOrder(1);
        bean.addUrlPatterns("/api/pi/*");
        return bean;
    }
}

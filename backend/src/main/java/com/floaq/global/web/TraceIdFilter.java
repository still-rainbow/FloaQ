package com.floaq.global.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * 추적 ID 관통 (계획.md §5③).
 *
 * <pre>nginx $request_id → X-Request-Id → MDC traceId → 로그 패턴</pre>
 *
 * <p>nginx 액세스 로그의 {@code rid} 와 앱 로그가 같은 값으로 이어져
 * <b>사고 한 건의 전체 경로를 로그에서 재구성할 수 있다.</b>
 * FloaQ 는 "사고 전후 데이터 저장 → 경위 파악"이 요구사항이라 관측이 부가 기능이 아니다.</p>
 *
 * <p>⚠ nginx 쪽에서 {@code location = /정확경로} 같은 정확일치 블록은 {@code location /api/} 의
 * {@code proxy_set_header} 를 <b>상속받지 않는다.</b> 헤더를 빠뜨리면 하필 그 엔드포인트의
 * 로그만 이어 붙일 수 없다.</p>
 *
 * <p>헤더가 없으면 직접 만든다 — 없다고 추적을 포기하면 로컬·직접 호출이 전부 추적 불가가 된다.</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Request-Id";
    public static final String MDC_KEY = "traceId";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String traceId = request.getHeader(HEADER);
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        }
        MDC.put(MDC_KEY, traceId);
        // 응답에도 실어 준다. 프론트가 오류를 제보할 때 이 값 하나면 서버 로그를 찾을 수 있다
        response.setHeader(HEADER, traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            // 톰캣은 스레드를 재사용한다. 지우지 않으면 다음 요청 로그에 남의 traceId 가 붙는다
            MDC.remove(MDC_KEY);
        }
    }
}

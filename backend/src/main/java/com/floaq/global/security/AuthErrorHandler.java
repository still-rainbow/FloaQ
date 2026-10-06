package com.floaq.global.security;

import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.ErrorResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * 인증·권한 실패를 {@link ErrorResponse} 로 쓴다.
 *
 * <p>이게 없으면 Security 가 <b>빈 본문 401</b> 을 내려 프론트가 {@code code} 로 분기하지 못한다.
 * 필터 단계의 실패라 {@code GlobalExceptionHandler} 까지 오지 않는다.</p>
 */
@Component
@RequiredArgsConstructor
public class AuthErrorHandler implements AuthenticationEntryPoint, AccessDeniedHandler {

    private final ObjectMapper objectMapper;

    /**
     * 둘을 가른다. 화면의 대응이 다르다.
     * <ul>
     *   <li>토큰이 왔는데 틀렸거나 만료 → {@code AUTH_INVALID_TOKEN}. 로그인이 풀린 것이다.</li>
     *   <li>토큰이 아예 없음 → {@code COMMON_UNAUTHORIZED}. 로그인 전이다.</li>
     * </ul>
     */
    @Override
    public void commence(HttpServletRequest request, HttpServletResponse response, AuthenticationException e)
            throws IOException {
        ErrorCode ec = e instanceof OAuth2AuthenticationException
                ? ErrorCode.AUTH_INVALID_TOKEN
                : ErrorCode.UNAUTHORIZED;
        response.setHeader(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
        write(request, response, ec);
    }

    @Override
    public void handle(HttpServletRequest request, HttpServletResponse response, AccessDeniedException e)
            throws IOException {
        write(request, response, ErrorCode.FORBIDDEN);
    }

    private void write(HttpServletRequest request, HttpServletResponse response, ErrorCode ec) throws IOException {
        response.setStatus(ec.getStatus().value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(),
                ErrorResponse.of(ec.getCode(), ec.getMessage(), request.getRequestURI()));
    }
}

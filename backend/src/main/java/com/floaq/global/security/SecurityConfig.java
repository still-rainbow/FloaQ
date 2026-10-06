package com.floaq.global.security;

import com.floaq.auth.entity.UserRole;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.oauth2.server.resource.web.BearerTokenResolver;
import org.springframework.security.oauth2.server.resource.web.DefaultBearerTokenResolver;
import org.springframework.security.web.SecurityFilterChain;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Set;

/**
 * 관제 웹 인증 — {@code Authorization: Bearer <JWT>} (docs/api.md §1.1).
 *
 * <p><b>열어 두는 경로가 이 파일의 절반이다.</b> 인증을 붙이는 순간 막히면 안 되는 사용자가 셋 있다.</p>
 * <ul>
 *   <li>Raspberry Pi — {@code /api/pi/**}. JWT 가 아니라 {@link PiApiKeyFilter} 가 막는다.</li>
 *   <li>선내 kiosk — {@code /api/ocean/**}. <b>로그인이 없다</b>(api.md §9 🔴1). 닫으면 해양 패널이 전부 401 이다.</li>
 *   <li>compose healthcheck — {@code /actuator/**}. 9090·127.0.0.1 로만 열려 있다.</li>
 * </ul>
 *
 * <p>세션을 만들지 않는다(STATELESS). 로그아웃 API 도 없다 — 클라이언트가 토큰을 버린다(api.md §3.1).</p>
 */
@Slf4j
@Configuration
public class SecurityConfig {

    public static final String ISSUER = "floaq";
    public static final String ROLE_CLAIM = "role";

    /** HS256 은 키가 해시 출력(256비트)보다 짧으면 무차별 대입에 약해진다 */
    static final int MIN_SECRET_BYTES = 32;

    /**
     * 토큰 없이 부르는 경로. 여기서는 {@code Authorization} 헤더를 <b>읽지 않는다</b> —
     * 만료된 토큰을 들고 있는 브라우저가 로그인 요청에서 401 을 받아 다시 로그인하지 못하는 일을 막는다.
     */
    private static final Set<String> TOKENLESS_PATHS = Set.of("/api/auth/login", "/api/auth/signup");

    @Bean
    public SecurityFilterChain apiSecurity(HttpSecurity http, AuthErrorHandler errors) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.POST, "/api/auth/login", "/api/auth/signup").permitAll()
                        .requestMatchers("/api/pi/**").permitAll()
                        .requestMatchers("/api/ocean/**").permitAll()
                        // 브라우저 WebSocket 은 헤더를 못 붙인다. 첫 메시지 AUTH 로 인증한다(api.md §6.1)
                        .requestMatchers("/ws", "/ws/**").permitAll()
                        .requestMatchers("/actuator/**").permitAll()
                        // 운영에서는 springdoc 자체가 꺼져 있다(application-prod.yml)
                        .requestMatchers("/swagger-ui.html", "/swagger-ui/**", "/v3/api-docs/**").permitAll()
                        // 막으면 500 이 401 로 둔갑해 로그에서 원인을 못 찾는다
                        .requestMatchers("/error").permitAll()
                        .requestMatchers("/api/admin/**").hasRole(UserRole.SA.name())
                        // 선박 삭제만 /api/admin/** 밖에 있다 — 규격이 배 한 척을 가리키는 경로로 정해져
                        // 있어서다(api.md §3.3). 이 줄이 없으면 아래 anyRequest 로 떨어져 해경도 배를 지운다
                        .requestMatchers(HttpMethod.DELETE, "/api/ships/**").hasRole(UserRole.SA.name())
                        // 사고는 해경(A)과 운영 관리자(SA) 둘 다 본다. 다만 <b>보는 범위가 다르다</b> —
                        // A 는 신고받은 사고만(REPORT·CLOSE), SA 는 취소·신고 전까지 전부다.
                        // 그 가름은 여기가 아니라 AccidentQueryService.scope() 가 한다 —
                        // 경로 권한은 "들어올 수 있나"만 정하고, "무엇이 보이나"는 질의가 정한다(2026-09-18).
                        // ⚠ 상세기획 §5.5 의 "SA 전체 조회"와 이제 맞는다(docs/api.md §8 #6 · §9 5).
                        .requestMatchers("/api/accidents/**")
                        .hasAnyRole(UserRole.A.name(), UserRole.SA.name())
                        .anyRequest().authenticated())
                .oauth2ResourceServer(rs -> rs
                        .bearerTokenResolver(bearerTokenResolver())
                        .jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthenticationConverter()))
                        .authenticationEntryPoint(errors))
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint(errors)
                        .accessDeniedHandler(errors));
        return http.build();
    }

    @Bean
    public SecretKey jwtSigningKey(@Value("${app.auth.jwt-secret:}") String secret) {
        return signingKey(secret);
    }

    @Bean
    public JwtEncoder jwtEncoder(SecretKey jwtSigningKey) {
        return new NimbusJwtEncoder(new ImmutableSecret<>(jwtSigningKey));
    }

    @Bean
    public JwtDecoder jwtDecoder(SecretKey jwtSigningKey) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(jwtSigningKey)
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
        // 기본 검증(exp·nbf) + 발급자. 같은 키를 다른 용도에 쓰게 돼도 그 토큰으로는 들어오지 못한다
        decoder.setJwtValidator(JwtValidators.createDefaultWithIssuer(ISSUER));
        return decoder;
    }

    /** users.password 가 bcrypt(round 12) 다(V1__init.sql 주석) */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    /**
     * 키가 비면 임의 키로 뜨고, 짧으면 기동을 막는다.
     * 비어 있는 것은 "아직 안 넣었다"(로컬)이고 짧은 것은 "잘못 넣었다"라 대응이 다르다.
     */
    static SecretKey signingKey(String secret) {
        if (secret == null || secret.isBlank()) {
            log.warn("FLOAQ_JWT_SECRET 미설정 — 임의 키로 서명합니다. 서버를 재시작하면 모든 로그인이 풀립니다.");
            byte[] random = new byte[MIN_SECRET_BYTES];
            new SecureRandom().nextBytes(random);
            return new SecretKeySpec(random, "HmacSHA256");
        }
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "FLOAQ_JWT_SECRET 은 " + MIN_SECRET_BYTES + "바이트 이상이어야 합니다 (openssl rand -hex 32).");
        }
        return new SecretKeySpec(bytes, "HmacSHA256");
    }

    static BearerTokenResolver bearerTokenResolver() {
        DefaultBearerTokenResolver standard = new DefaultBearerTokenResolver();
        return request -> TOKENLESS_PATHS.contains(request.getRequestURI()) ? null : standard.resolve(request);
    }

    /** {@code role} 클레임 하나를 {@code ROLE_A} 같은 권한으로 바꾼다. {@code hasRole} 이 이 접두어를 본다 */
    private static JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
        authorities.setAuthoritiesClaimName(ROLE_CLAIM);
        authorities.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(authorities);
        return converter;
    }
}

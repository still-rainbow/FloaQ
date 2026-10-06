package com.floaq.global.security;

import com.floaq.auth.TokenService;
import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.test.util.ReflectionTestUtils;

import javax.crypto.SecretKey;
import java.time.Duration;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 토큰 발급과 검증이 서로 맞는지. 둘은 다른 클래스에 있어 한쪽만 바뀌면 로그인은 되는데 모든 요청이 401 이 된다.
 * 전체 기동 없이 {@link SecurityConfig} 의 빈 메서드를 직접 부른다.
 */
class JwtTokenTest {

    private static final String SECRET = "0123456789abcdef0123456789abcdef";

    private final SecurityConfig config = new SecurityConfig();
    private final SecretKey key = SecurityConfig.signingKey(SECRET);

    private static User admin() {
        User user = User.create("kim@kcg.example", "hash", "김민준", UserRole.A, UserStatus.ACTIVE);
        ReflectionTestUtils.setField(user, "userId", 3L);
        return user;
    }

    @Test
    void 발급한_토큰을_검증기가_받는다() {
        TokenService tokens = new TokenService(config.jwtEncoder(key), Duration.ofHours(12));
        TokenService.IssuedToken issued = tokens.issue(admin());

        Jwt jwt = config.jwtDecoder(key).decode(issued.value());

        assertThat(jwt.getSubject()).isEqualTo("3");
        assertThat(jwt.getClaimAsString(SecurityConfig.ROLE_CLAIM)).isEqualTo("A");
        assertThat(jwt.getExpiresAt()).isEqualTo(issued.expiresAt());
    }

    @Test
    void 토큰에_이름이나_이메일을_싣지_않는다() {
        // base64 라 누구나 읽는다
        String value = new TokenService(config.jwtEncoder(key), Duration.ofHours(1)).issue(admin()).value();
        Jwt jwt = config.jwtDecoder(key).decode(value);
        assertThat(jwt.getClaims()).doesNotContainKeys("name", "loginId", "email");
    }

    @Test
    void 다른_키로_서명한_토큰은_거부한다() {
        SecretKey other = SecurityConfig.signingKey("ffffffffffffffffffffffffffffffff");
        String forged = new TokenService(config.jwtEncoder(other), Duration.ofHours(1)).issue(admin()).value();

        assertThatThrownBy(() -> config.jwtDecoder(key).decode(forged)).isInstanceOf(JwtException.class);
    }

    @Test
    void 만료된_토큰은_거부한다() {
        // TokenService 로는 못 만든다 — 수명을 음수로 주면 JwtClaimsSet 이 발급 전에 막는다.
        // 검증기의 허용 오차가 60초라 그보다 충분히 과거로 만든다
        Instant past = Instant.now().minus(Duration.ofMinutes(10));
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(SecurityConfig.ISSUER)
                .issuedAt(past)
                .expiresAt(past.plus(Duration.ofMinutes(5)))
                .subject("3")
                .claim(SecurityConfig.ROLE_CLAIM, "A")
                .build();
        String expired = config.jwtEncoder(key)
                .encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims))
                .getTokenValue();

        assertThatThrownBy(() -> config.jwtDecoder(key).decode(expired)).isInstanceOf(JwtException.class);
    }

    @Test
    void 서명_키가_비면_기동마다_다른_임의_키를_쓴다() {
        assertThat(SecurityConfig.signingKey("").getEncoded())
                .isNotEqualTo(SecurityConfig.signingKey("").getEncoded());
    }

    @Test
    void 서명_키가_32바이트보다_짧으면_기동을_막는다() {
        assertThatThrownBy(() -> SecurityConfig.signingKey("too-short")).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void 로그인_요청에서는_남아_있는_토큰을_읽지_않는다() {
        // 만료된 토큰을 들고 로그인하면 401 이 나서 다시 로그인할 길이 막힌다
        var resolver = SecurityConfig.bearerTokenResolver();

        var login = new MockHttpServletRequest("POST", "/api/auth/login");
        login.addHeader("Authorization", "Bearer stale");
        assertThat(resolver.resolve(login)).isNull();

        var me = new MockHttpServletRequest("GET", "/api/auth/me");
        me.addHeader("Authorization", "Bearer live");
        assertThat(resolver.resolve(me)).isEqualTo("live");
    }
}

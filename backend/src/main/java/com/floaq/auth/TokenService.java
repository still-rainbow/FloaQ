package com.floaq.auth;

import com.floaq.auth.entity.User;
import com.floaq.global.security.SecurityConfig;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;

/**
 * 관제 웹 JWT 발급. 검증은 {@link SecurityConfig} 의 JwtDecoder 가 한다.
 *
 * <p><b>담는 것은 {@code sub}(userId)와 {@code role} 뿐이다.</b> 이름·로그인 ID 는 넣지 않는다 —
 * 토큰은 base64 라 누구나 읽을 수 있고, 계정 정보가 바뀌어도 만료 전까지 옛 값이 남는다.
 * 화면은 {@code /api/auth/me} 로 받는다.</p>
 */
@Component
public class TokenService {

    public record IssuedToken(String value, Instant expiresAt) {
    }

    private final JwtEncoder encoder;
    private final Duration ttl;

    public TokenService(JwtEncoder encoder, @Value("${app.auth.token-ttl:12h}") Duration ttl) {
        this.encoder = encoder;
        this.ttl = ttl;
    }

    public IssuedToken issue(User user) {
        // JWT 의 exp 는 초 단위다. 자르지 않으면 응답의 expiresAt 과 토큰의 exp 가 1초 안쪽으로 어긋난다
        Instant now = Instant.now().truncatedTo(ChronoUnit.SECONDS);
        Instant expiresAt = now.plus(ttl);
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(SecurityConfig.ISSUER)
                .issuedAt(now)
                .expiresAt(expiresAt)
                .subject(String.valueOf(user.getUserId()))
                .claim(SecurityConfig.ROLE_CLAIM, user.getRole().name())
                .build();
        JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
        String value = encoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue();
        return new IssuedToken(value, expiresAt);
    }
}

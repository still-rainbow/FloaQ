package com.floaq.global.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenAPI / Swagger UI (Jira floaq-108).
 *
 * <p><b>인증 스킴을 둘 등록한다.</b> 이 서버는 사용자가 둘이다 —
 * 관제 웹(JWT)과 Raspberry Pi(고정 키 헤더 <b>둘</b>). 하나만 넣으면 Pi 담당이
 * 문서에서 "이건 어떻게 부르나"를 알 수 없다.</p>
 *
 * <p>전역 {@code SecurityRequirement} 는 걸지 않는다 — 걸면 모든 엔드포인트가 JWT 필요로 표시되는데
 * {@code /api/pi/**} 는 JWT 를 쓰지 않아 문서가 거짓말을 한다. 요구 스킴은
 * 컨트롤러에서 {@code @SecurityRequirement} 로 각자 선언한다.</p>
 */
@Configuration
public class OpenApiConfig {

    public static final String JWT_SCHEME = "bearerAuth";
    /** 등록 키 — {@code POST /api/pi/ships} 한 곳. 이름은 IoT 계약(docs/api.json)과 같게 둔다 */
    public static final String SHIP_REGISTER_SCHEME = "shipRegisterKey";
    /** 선박 키 — 그 밖의 모든 Pi 요청 */
    public static final String SHIP_SECRET_SCHEME = "shipSecretKey";

    @Bean
    public OpenAPI floaqOpenApi() {
        return new OpenAPI()
                .info(new Info()
                        .title("FloaQ API")
                        .version("v1")
                        .description("""
                                AIoT 해상 인명 구조 시스템.

                                경로가 셋이고 인증이 다르다.
                                - `/api/**`      관제 웹. JWT (A / SA)
                                - `/api/pi/**`   Raspberry Pi. 등록은 `X-Ship-Register-Key`,
                                  그 밖의 모든 요청은 등록 응답이 준 `X-Ship-Secret-Key`
                                - `/actuator/**` 운영. 9090 포트, 127.0.0.1 바인딩

                                오류 본문은 전부 `{code, message, path, timestamp}` 다.
                                **프론트는 문구가 아니라 `code` 로 분기한다.**
                                """))
                .components(new Components()
                        .addSecuritySchemes(JWT_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.HTTP)
                                .scheme("bearer")
                                .bearerFormat("JWT")
                                .description("관제 웹 로그인 토큰"))
                        .addSecuritySchemes(SHIP_REGISTER_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.APIKEY)
                                .in(SecurityScheme.In.HEADER)
                                .name("X-Ship-Register-Key")
                                .description("선박 등록 신청 전용 공유 시크릿. 아직 ship_id 가 없는 단계에서 쓴다."))
                        .addSecuritySchemes(SHIP_SECRET_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.APIKEY)
                                .in(SecurityScheme.In.HEADER)
                                .name("X-Ship-Secret-Key")
                                .description("등록 응답이 준 선박 키. 만료가 없다 — 엣지에 토큰 수명 관리를 두지 않기 위해서다.")));
    }
}

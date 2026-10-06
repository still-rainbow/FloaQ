package com.floaq.global;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import com.floaq.global.config.FilterConfig;
import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.config.SchedulingConfig;
import com.floaq.global.config.WebClientConfig;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.pi.PiKeys;
import com.floaq.global.security.PiApiKeyFilter;
import com.floaq.ship.ShipRepository;
import com.floaq.ship.entity.Ship;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.security.SecurityScheme;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * global 설정 검증.
 *
 * <p><b>전체 기동({@code @SpringBootTest})을 쓰지 않는다.</b> PostgreSQL·Redis 가 있어야 뜨는데
 * 이 검증에 DB 는 필요 없다 — 인프라에 묶어 두면 로컬에서 아무도 안 돌린다.
 * 설정 클래스만 올려 빈 생성과 필터 동작을 본다.</p>
 */
@SpringJUnitConfig
@ContextConfiguration(classes = {
        OpenApiConfig.class, WebClientConfig.class, SchedulingConfig.class,
        FilterConfig.class, GlobalConfigTest.TestBeans.class,
})
@TestPropertySource(properties = "app.pi.enroll-key=test-secret")
class GlobalConfigTest {

    static class TestBeans {
        /**
         * FilterConfig 가 요구한다. 운영에서는 Boot 가 넣어 준다.
         *
         * <p>⚠⚠ <b>타입이 {@code tools.jackson}(Jackson 3)이어야 한다.</b> Spring Boot 4 가
         * 자동 설정하는 빈이 그것이다. {@code com.fasterxml.jackson}(Jackson 2)도 클래스패스에
         * 있지만(설정 YAML 파싱용) <b>빈은 없다</b> — 그쪽 타입을 요구하면 기동이 실패한다.</p>
         *
         * <p>이 테스트가 협력 객체를 직접 만들어 넣는 바람에 그 실패를 못 잡았다.
         * 실제 기동(bootRun)에서 드러났다 — <b>빈 배선은 컨텍스트를 실제로 올려야 검증된다.</b></p>
         */
        @Bean
        ObjectMapper objectMapper() {
            return JsonMapper.builder().build();
        }

        /**
         * 선박 키 조회용. 실제 저장소 대신 목이다 — 이 테스트는 <b>필터의 분기</b>만 본다.
         * "키가 실제로 DB 에 붙는지"는 {@code PiShipSqlTest} 가 본다.
         */
        @Bean
        ShipRepository shipRepository() {
            ShipRepository repo = mock(ShipRepository.class);
            Ship ship = mock(Ship.class);
            when(ship.getShipId()).thenReturn(SHIP);
            when(repo.findByPiKeyHashAndDeletedFalse(anyString())).thenReturn(Optional.empty());
            when(repo.findByPiKeyHashAndDeletedFalse(PiKeys.hash(SHIP_KEY)))
                    .thenReturn(Optional.of(ship));
            return repo;
        }
    }

    /** 등록된 선박이 들고 있는 선박 키(평문). DB 에는 SHA-256 만 있다 */
    static final String SHIP_KEY = "ship-key-0001";
    static final UUID SHIP = UUID.fromString("01923f6e-0000-7000-8000-00000000c001");

    @Autowired
    OpenAPI openAPI;
    @Autowired
    FilterRegistrationBean<PiApiKeyFilter> piFilterRegistration;
    @Autowired
    WebClient oceanWebClient;
    @Autowired
    WebClient llmWebClient;

    // ── OpenAPI ─────────────────────────────────────────────

    @Test
    void 인증_스킴이_셋이다() {
        // JWT + Pi 키 둘(등록·선박). 빠뜨리면 Pi 담당이 문서에서 호출 방법을 알 수 없다.
        // 하나만 등록하면 Pi 담당이 문서에서 호출 방법을 알 수 없다.
        var schemes = openAPI.getComponents().getSecuritySchemes();
        assertThat(schemes).containsKeys(OpenApiConfig.JWT_SCHEME,
                OpenApiConfig.SHIP_REGISTER_SCHEME, OpenApiConfig.SHIP_SECRET_SCHEME);
        // 이름이 IoT 계약(docs/api.json)과 글자 그대로 같아야 한다 — 다르면 Pi 가 보낸 헤더를 못 읽는다
        assertThat(schemes.get(OpenApiConfig.SHIP_REGISTER_SCHEME).getName()).isEqualTo("X-Ship-Register-Key");
        assertThat(schemes.get(OpenApiConfig.SHIP_SECRET_SCHEME).getName()).isEqualTo("X-Ship-Secret-Key");
    }

    @Test
    void 전역_보안요구를_걸지_않는다() {
        // 걸면 /api/pi/** 까지 JWT 필요로 표시돼 문서가 거짓말을 한다
        assertThat(openAPI.getSecurity()).isNullOrEmpty();
    }

    // ── 스케줄러 ────────────────────────────────────────────

    @Test
    void 부표_두절_스케줄러가_수집과_분리돼_있다(@Autowired TaskScheduler buoyTaskScheduler,
                                  @Autowired TaskScheduler collectTaskScheduler) {
        // 같은 풀을 쓰면 공공데이터 수집이 외부 지연으로 길어질 때 두절 판정이 밀리고,
        // 멀쩡한 부표가 두절로 판정된다 — 오판정이 곧 오경보다 (계획.md §1.4)
        assertThat(buoyTaskScheduler).isNotSameAs(collectTaskScheduler);
    }

    // ── WebClient ───────────────────────────────────────────

    @Test
    void 외부_호출_클라이언트가_용도별로_분리돼_있다() {
        // 타임아웃이 다르다. 공공데이터는 10초, LLM 생성은 60초
        assertThat(oceanWebClient).isNotSameAs(llmWebClient);
    }

    // ── Pi 인증 필터 ──────────────────────────────────────

    @Test
    void Pi_경로에만_걸린다() {
        assertThat(piFilterRegistration.getUrlPatterns()).containsExactly("/api/pi/*");
    }

    /**
     * <b>등록 키는 {@code POST /api/pi/ships} 한 곳만 연다</b> (docs/api.md §1.1).
     * 그 시점엔 선박이 없어 선박 키가 있을 수 없다 — 부트스트랩이라 예외를 둔 것이다.
     */
    @Test
    void 등록_키는_선박_등록만_통과한다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletResponse res = call("/api/pi/ships", "test-secret", chain);

        verify(chain, times(1)).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(200);
    }

    /**
     * <b>이 테스트가 두 키로 나눈 이유 그 자체다.</b> 하나로 두면 등록 키를 가진 쪽이
     * 아무 {@code ship_id} 로나 데이터를 올릴 수 있다. 등록 키는 여러 Pi 에 같은 값으로 깔리므로
     * 한 대만 새어도 전부가 새는 것과 같다.
     */
    @Test
    void 등록_키로는_데이터를_못_올린다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletResponse res = call("/api/pi/accidents", "test-secret", chain);

        verify(chain, never()).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(401);
    }

    /** 선박 키는 데이터 경로를 열고, <b>어느 선박인지를 실어 보낸다</b> — 뒤쪽이 본문과 대조한다. */
    @Test
    void 선박_키는_통과하고_ship_id_를_싣는다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        var req = new MockHttpServletRequest("POST", "/api/pi/accidents");
        req.addHeader("X-Ship-Secret-Key", SHIP_KEY);
        var res = new MockHttpServletResponse();

        piFilterRegistration.getFilter().doFilter(req, res, chain);

        verify(chain, times(1)).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(req.getAttribute(PiApiKeyFilter.SHIP_ID_ATTRIBUTE)).isEqualTo(SHIP);
    }

    /**
     * 반대 방향도 막는다. 선박 키로 등록을 부르면 <b>이미 있는 선박이 또 만들어질</b> 여지가 생긴다 —
     * 등록은 등록 키의 일이다.
     */
    @Test
    void 선박_키로는_등록을_못_한다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        assertThat(call("/api/pi/ships", SHIP_KEY, chain).getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
    }

    /**
     * <b>{@code startsWith} 로 보면 여기가 뚫린다.</b> 등록 키는 여러 Pi 가 공유하므로
     * 상태 확인까지 열리면 {@code shipId} 를 바꿔 가며 남의 선박을 훑을 수 있다.
     */
    @Test
    void 상태_확인은_등록_키로_열리지_않는다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        var req = new MockHttpServletRequest("GET", "/api/pi/ships/" + SHIP);
        req.addHeader("X-Ship-Register-Key", "test-secret");
        var res = new MockHttpServletResponse();

        piFilterRegistration.getFilter().doFilter(req, res, chain);

        verify(chain, never()).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(401);
    }

    @Test
    void 틀린_키는_401_이고_체인을_타지_않는다() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletResponse res = call("/api/pi/accidents", "wrong", chain);

        verify(chain, never()).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(401);
        // 오류 본문이 ErrorResponse 형태여야 한다 — 프론트가 code 로 분기한다
        assertThat(res.getContentAsString()).contains("\"code\":\"PI_UNAUTHORIZED\"");
        assertThat(res.getContentAsString()).contains("\"path\":\"/api/pi/accidents\"");
    }

    @Test
    void 헤더가_없으면_401() throws Exception {
        FilterChain chain = mock(FilterChain.class);
        assertThat(call("/api/pi/accidents", null, chain).getStatus()).isEqualTo(401);
    }

    @Test
    void 등록_키가_비면_등록이_401_로_닫힌다() throws Exception {
        // 안전한 쪽으로 닫힌다. 빈 키를 빈 헤더로 통과시키면 열린 채 배포된다
        var filter = new PiApiKeyFilter("", mock(ShipRepository.class), JsonMapper.builder().build());
        FilterChain chain = mock(FilterChain.class);
        var req = new MockHttpServletRequest("POST", "/api/pi/ships");
        req.addHeader("X-Ship-Register-Key", "");
        var res = new MockHttpServletResponse();

        filter.doFilter(req, res, chain);

        verify(chain, never()).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(401);
    }

    @Test
    void Pi가_아닌_경로는_건드리지_않는다() throws Exception {
        // shouldNotFilter 가 true 라 키 없이도 통과해야 한다 (관제 웹은 JWT 로 따로 막는다)
        FilterChain chain = mock(FilterChain.class);
        MockHttpServletResponse res = call("/api/accidents", null, chain);

        verify(chain, times(1)).doFilter(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
        assertThat(res.getStatus()).isEqualTo(200);
    }

    /**
     * @param key 등록 경로면 {@code X-Ship-Register-Key}, 아니면 {@code X-Ship-Secret-Key} 로 싣는다.
     *            헤더가 둘로 갈렸으므로(docs/api.json) 경로에 맞는 쪽에 넣어야 실제 호출과 같다
     */
    private MockHttpServletResponse call(String uri, String key, FilterChain chain) throws Exception {
        var req = new MockHttpServletRequest("POST", uri);
        if (key != null) {
            req.addHeader("/api/pi/ships".equals(uri) ? "X-Ship-Register-Key" : "X-Ship-Secret-Key", key);
        }
        var res = new MockHttpServletResponse();
        piFilterRegistration.getFilter().doFilter(req, res, chain);
        return res;
    }

    // ── 오류 코드 ───────────────────────────────────────────

    @Test
    void 오류_코드_문자열이_중복되지_않는다() {
        // 중복되면 프론트가 두 가지 사유를 같은 분기로 처리한다
        Set<String> seen = new HashSet<>();
        for (ErrorCode ec : ErrorCode.values()) {
            assertThat(seen.add(ec.getCode()))
                    .withFailMessage("중복된 코드: %s", ec.getCode())
                    .isTrue();
        }
    }

    @Test
    void 이미_X_됨_은_409_다() {
        // 리소스는 있는데 지금 상태와 충돌한 것이다.
        // 404 로 내려보내면 클라이언트가 "사고가 사라졌다"로 읽는다
        assertThat(ErrorCode.ALREADY_REPORTED.getStatus().value()).isEqualTo(409);
        assertThat(ErrorCode.ALREADY_RESOLVED.getStatus().value()).isEqualTo(409);
        assertThat(ErrorCode.ALREADY_CANCELLED.getStatus().value()).isEqualTo(409);
        assertThat(ErrorCode.INVALID_STATE.getStatus().value()).isEqualTo(409);
    }

    @Test
    void kiosk_가_쓰는_거절_사유가_전부_있다() {
        // apps/kiosk/src/pages/Kiosk.tsx 의 REJECT_TEXT 키. 하나라도 없으면 화면에 사유가 안 뜬다
        assertDoesNotThrow(() -> {
            for (String code : new String[]{
                    "ALREADY_REPORTED", "ALREADY_RESOLVED", "ALREADY_CANCELLED",
                    "NO_ACTIVE_INCIDENT", "INVALID_STATE"}) {
                ErrorCode.valueOf(code);
            }
        });
    }

    @Test
    void 업무예외는_코드를_들고_있다() {
        var e = new BusinessException(ErrorCode.ALREADY_REPORTED);
        assertThat(e.getErrorCode().getCode()).isEqualTo("ALREADY_REPORTED");
        assertThat(e.getMessage()).isEqualTo(ErrorCode.ALREADY_REPORTED.getMessage());
    }
}

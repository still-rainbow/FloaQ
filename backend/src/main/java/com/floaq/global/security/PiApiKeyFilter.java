package com.floaq.global.security;

import com.floaq.pi.PiKeys;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.ErrorResponse;
import com.floaq.ship.ShipRepository;
import com.floaq.ship.entity.Ship;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Optional;
import java.util.UUID;

/**
 * Raspberry Pi 전용 인증 — {@code /api/pi/**} + {@code X-Floaq-Pi-Key}.
 *
 * <h2>키가 둘 · 헤더도 둘 (결정 2026-09-17 · docs/api.json)</h2>
 * <ul>
 *   <li><b>{@code X-Ship-Register-Key}</b> — 공용 등록 키. {@code POST /api/pi/ships} <b>한 곳에만</b> 쓴다.
 *       그 시점엔 선박이 없어 선박 키가 있을 수 없다(부트스트랩)</li>
 *   <li><b>{@code X-Ship-Secret-Key}</b> — 등록 응답으로 발급된 선박 키. 그 밖의 모든 Pi 요청이 이것이다</li>
 * </ul>
 *
 * <p>하나로 두면 <b>그 키를 가진 쪽이 아무 {@code ship_id} 로나 데이터를 올릴 수 있다.</b>
 * 선박 키는 <b>키가 곧 선박 증명</b>이라, 뒤쪽 서비스가 페이로드의 {@code ship_id} 를
 * 키의 선박과 대조할 수 있다 — 그 선박을 {@link #SHIP_ID_ATTRIBUTE} 로 실어 보낸다.</p>
 *
 * <p><b>왜 JWT 가 아닌가.</b> Pi 는 사람이 아니라 기계다. 토큰 발급·갱신을 얹으면 Pi에 수명 관리가
 * 생기고, 재부팅이나 두절 복귀 때 갱신에 실패하면 사고 데이터가 통째로 못 올라온다.
 * 고정 키는 만료가 없어 그 실패 경로가 없다.</p>
 *
 * <p>SecurityConfig 가 이 경로를 permitAll 로 열어 두므로 <b>이 필터가 실제 방어선</b>이다.
 * {@code @Component} 로 두지 않고 SecurityConfig 가 직접 만들어 등록한다 — 서블릿 컨테이너에
 * 이중 등록되면 체인 밖에서 한 번 더 돌아 401 이 두 번 쓰인다.</p>
 *
 * <p>⚠ 선박 키 검증은 <b>요청마다 DB 를 한 번 친다</b>({@code uq_ship_edge_key_hash} 인덱스).
 * 선박 1척 · 5초 주기 전제에서는 문제가 없다. 여러 척이 되면 캐시를 넣되,
 * <b>키 폐기가 즉시 반영되지 않는 창</b>이 생긴다는 점을 같이 정해야 한다.</p>
 *
 * <p>⚠ HTTPS 전용이다. 평문 HTTP 로 쓰면 헤더가 그대로 노출된다.</p>
 *
 * <p>⚠ 두 헤더를 같이 보내도 <b>경로가 읽을 것만 읽는다.</b> 둘을 대조하지 않는다 —
 * 대조하면 "둘 다 보내야 한다"가 되고, 등록 시점에는 선박 키가 없어 성립하지 않는다.</p>
 */
@Slf4j
public class PiApiKeyFilter extends OncePerRequestFilter {

    private static final String PI_PATH_PREFIX = "/api/pi/";

    /**
     * <b>헤더가 둘이다</b> (IoT 팀 계약 {@code docs/api.json}, 2026-09-17).
     *
     * <p>한 헤더에 두 값을 넣던 것을 바꿨다. 헤더가 다르면 <b>"한 요청에 키는 하나다"를
     * 문서로 설명할 필요가 없고</b>, 등록 키로 데이터 경로를 찌르는 실수가 애초에 성립하지 않는다 —
     * 그 경로는 등록 헤더를 읽지도 않는다.</p>
     */
    private static final String REGISTER_HEADER = "X-Ship-Register-Key";
    private static final String SECRET_HEADER = "X-Ship-Secret-Key";

    /** 등록 키로 여는 유일한 경로. 여기만 선박 키가 없어도 된다 */
    private static final String ENROLL_PATH = "/api/pi/ships";

    /** 선박 키가 가리키는 선박. 뒤쪽 서비스가 페이로드 {@code ship_id} 를 이 값과 대조한다 */
    public static final String SHIP_ID_ATTRIBUTE = "floaq.pi.shipId";

    private final String enrollKey;
    private final ShipRepository ships;
    private final ObjectMapper objectMapper;

    public PiApiKeyFilter(String enrollKey, ShipRepository ships, ObjectMapper objectMapper) {
        this.enrollKey = enrollKey;
        this.ships = ships;
        this.objectMapper = objectMapper;
        if (enrollKey == null || enrollKey.isBlank()) {
            // 조용히 닫히면 "배포했는데 Pi 가 등록을 못 한다"를 원인 없이 겪는다
            log.warn("FLOAQ_PI_ENROLL_KEY 미설정 — 선박 등록(POST /api/pi/ships)이 전부 401 로 거부됩니다.");
        }
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(PI_PATH_PREFIX);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        // 경로가 읽을 헤더를 정한다. 다른 헤더에 든 값은 쳐다보지 않는다 —
        // 등록 헤더에 선박 키를 넣어도, 그 반대도 통하지 않는다
        if (isEnrollRequest(request)) {
            String presented = request.getHeader(REGISTER_HEADER);
            if (presented == null || presented.isBlank() || !matchesEnrollKey(presented)) {
                writeUnauthorized(response, request.getRequestURI());
                return;
            }
            chain.doFilter(request, response);
            return;
        }

        String presented = request.getHeader(SECRET_HEADER);
        if (presented == null || presented.isBlank()) {
            writeUnauthorized(response, request.getRequestURI());
            return;
        }
        Optional<Ship> ship = ships.findByPiKeyHashAndDeletedFalse(PiKeys.hash(presented));
        if (ship.isEmpty()) {
            // 등록 키를 이 헤더에 넣은 경우도 여기로 떨어진다(해시가 안 맞는다) — 의도한 거절이다
            writeUnauthorized(response, request.getRequestURI());
            return;
        }

        UUID shipId = ship.get().getShipId();
        request.setAttribute(SHIP_ID_ATTRIBUTE, shipId);
        chain.doFilter(request, response);
    }

    /**
     * 등록은 {@code POST /api/pi/ships} <b>정확히 그 경로</b>다.
     * {@code startsWith} 로 보면 {@code GET /api/pi/ships/{id}}(상태 확인)까지 등록 키로 열려
     * 남의 선박 상태를 훑을 수 있게 된다 — 그쪽은 선박 키를 요구해야 한다.
     */
    private boolean isEnrollRequest(HttpServletRequest request) {
        return HttpMethod.POST.matches(request.getMethod())
                && ENROLL_PATH.equals(request.getRequestURI());
    }

    /** 상수 시간 비교. {@code equals} 는 앞자리부터 다른 지점에서 즉시 끊겨 길이·내용이 새어 나간다. */
    private boolean matchesEnrollKey(String presented) {
        if (enrollKey == null || enrollKey.isBlank()) {
            return false;
        }
        return MessageDigest.isEqual(
                enrollKey.getBytes(StandardCharsets.UTF_8),
                presented.getBytes(StandardCharsets.UTF_8));
    }

    private void writeUnauthorized(HttpServletResponse res, String path) throws IOException {
        ErrorCode ec = ErrorCode.PI_UNAUTHORIZED;
        res.setStatus(ec.getStatus().value());
        res.setContentType(MediaType.APPLICATION_JSON_VALUE);
        res.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(res.getWriter(), ErrorResponse.of(ec.getCode(), ec.getMessage(), path));
    }
}

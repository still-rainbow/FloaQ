package com.floaq.pi;

import com.floaq.pi.dto.PiAccident;
import com.floaq.pi.dto.PiEnvelope;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.security.PiApiKeyFilter;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 봉투 검증 (docs/api.md §4.1). */
class PiControllerTest {

    private static final UUID SHIP = UUID.fromString("01923f6e-0000-7000-8000-00000000c001");

    private final PiIngestService ingest = mock(PiIngestService.class);
    private final PiTelemetryService telemetry = mock(PiTelemetryService.class);
    private final PiEventService events = mock(PiEventService.class);
    private final PiFileService files = mock(PiFileService.class);
    private final PiArchiveService archives = mock(PiArchiveService.class);
    private final PiShipService ships = mock(PiShipService.class);
    private final PiController controller =
            new PiController(ingest, telemetry, events, files, archives, ships);

    /** 필터가 키에서 풀어 실어 준 선박. 컨트롤러는 이 값을 그대로 서비스에 넘긴다 */
    private MockHttpServletRequest 인증된_요청() {
        var req = new MockHttpServletRequest("POST", "/api/pi/accidents");
        req.setAttribute(PiApiKeyFilter.SHIP_ID_ATTRIBUTE, SHIP);
        return req;
    }

    private PiEnvelope<PiAccident> envelope(Integer v, List<PiAccident> data) {
        return new PiEnvelope<>("01923f6e-1111-7000-8000-000000000001", v, 1789456675L, data);
    }

    private static void assertCode(org.assertj.core.api.ThrowableAssert.ThrowingCallable call, ErrorCode expected) {
        assertThatThrownBy(call)
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getErrorCode()).isEqualTo(expected));
    }

    /**
     * <b>모르는 버전을 일반 400 과 갈라 두는 것이 핵심이다.</b> Pi 는 이 코드를 보면 행을 버리지 않고
     * 전송만 멈춘다(§4.1 재시도 표). 일반 400 이면 서버가 구버전일 때 Pi 의 모든 전송이
     * 실패로 찍히고 폐기된다 — 되돌릴 수 없는 손실이다.
     */
    @Test
    void 모르는_버전은_PI_UNSUPPORTED_VERSION_이다() {
        assertCode(() -> controller.accidents(envelope(2, List.of()), 인증된_요청()), ErrorCode.PI_UNSUPPORTED_VERSION);
        assertCode(() -> controller.accidents(envelope(null, List.of()), 인증된_요청()), ErrorCode.PI_UNSUPPORTED_VERSION);
        verify(ingest, never()).acceptAccidents(any(), any());
    }

    @Test
    void data_가_없으면_INVALID_INPUT_이다() {
        assertCode(() -> controller.accidents(envelope(1, null), 인증된_요청()), ErrorCode.INVALID_INPUT);
        assertCode(() -> controller.accidents(null, 인증된_요청()), ErrorCode.INVALID_INPUT);
    }

    /** 빈 배열은 오류가 아니다 — 보낼 것이 없는 폴링도 정상 경로다. */
    @Test
    void 빈_배열은_통과한다() {
        when(ingest.acceptAccidents(any(), any())).thenReturn(new PiResult(0, 0, 0, 0));
        assertThat(controller.accidents(envelope(1, List.of()), 인증된_요청()).data())
                .isEqualTo(new PiResult(0, 0, 0, 0));
    }

    /**
     * <b>키의 선박을 그대로 넘긴다.</b> 컨트롤러가 본문의 {@code ship_id} 를 쓰면
     * 보내는 쪽이 정한 값을 그대로 믿는 셈이라 대조가 의미를 잃는다.
     */
    @Test
    void 키의_선박을_서비스로_넘긴다() {
        when(ingest.acceptAccidents(any(), any())).thenReturn(new PiResult(0, 0, 0, 0));
        controller.accidents(envelope(1, List.of()), 인증된_요청());
        verify(ingest).acceptAccidents(any(), eq(SHIP));
    }

    /**
     * 시각 오차는 <b>로그로만</b> 남기고 거절하지 않는다. 바다에는 NTP 가 없고 실내 시연은
     * GPS 미수신이다 — 시각으로 막으면 그때 전송이 통째로 멈춘다.
     */
    @Test
    void 시각이_크게_어긋나도_거절하지_않는다() {
        when(ingest.acceptAccidents(any(), any())).thenReturn(new PiResult(0, 0, 0, 0));
        PiEnvelope<PiAccident> 과거 = new PiEnvelope<>("r", 1, 0L, List.of());
        assertThatCode(() -> controller.accidents(과거, 인증된_요청())).doesNotThrowAnyException();
    }
}

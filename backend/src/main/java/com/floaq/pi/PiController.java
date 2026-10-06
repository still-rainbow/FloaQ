package com.floaq.pi;

import com.floaq.pi.dto.PiAccident;
import com.floaq.pi.dto.PiAccidentState;
import com.floaq.pi.dto.PiBuoy;
import com.floaq.pi.dto.PiCommLoss;
import com.floaq.pi.dto.PiDriftEstimate;
import com.floaq.pi.dto.PiEnvelope;
import com.floaq.pi.dto.PiArchiveResponse;
import com.floaq.pi.dto.PiFileResponse;
import com.floaq.pi.dto.PiImu;
import com.floaq.pi.dto.PiLaunch;
import com.floaq.pi.dto.PiReport;
import com.floaq.pi.dto.PiShipPosition;
import com.floaq.pi.dto.PiShipRegisterRequest;
import com.floaq.pi.dto.PiShipRegisterResponse;
import com.floaq.pi.dto.PiShipStatusResponse;
import com.floaq.global.security.PiApiKeyFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Raspberry Pi → EC2 수신 (docs/api.md §4).
 *
 * <p>인증은 {@code X-Floaq-Pi-Key} 이고 {@link com.floaq.global.security.PiApiKeyFilter} 가
 * 체인 앞에서 막는다 — 이 클래스에는 인증 코드가 없다.</p>
 *
 * <p><b>서버는 사고를 만들지 않는다. 받아 적을 뿐이다</b>(계획.md §9.2) —
 * 인터넷이 끊겨도 감지·신고·종결이 선내에서 돌아야 하기 때문이다.</p>
 */
@Slf4j
@Tag(name = "pi", description = "Raspberry Pi 수신 (X-Floaq-Pi-Key)")
@RestController
@RequestMapping("/api/pi")
@RequiredArgsConstructor
@SecurityRequirement(name = OpenApiConfig.SHIP_SECRET_SCHEME)
public class PiController {

    private final PiIngestService ingest;
    private final PiTelemetryService telemetry;
    private final PiEventService events;
    private final PiFileService files;
    private final PiArchiveService archives;
    private final PiShipService ships;

    /**
     * 선박 등록 신청. <b>이 엔드포인트만 {@code ship_id} 를 요구하지 않는다</b> — 여기서 만들기 때문이다.
     * 인증도 여기만 <b>등록 키</b>다(docs/api.md §1.1).
     */
    @PostMapping("/ships")
    @Operation(summary = "선박 등록 신청 — ship_id·ship_key 발급. 등록 키로 부른다")
    // 이 경로만 등록 키다. 클래스 기본값(선박 키)을 덮어쓴다
    @SecurityRequirement(name = OpenApiConfig.SHIP_REGISTER_SCHEME)
    public ResponseEntity<ApiResponse<PiShipRegisterResponse>> registerShip(
            @Valid @RequestBody PiShipRegisterRequest body) {
        var result = ships.register(body);
        // 재전송을 201 로 주면 Pi 가 "또 만들어졌다"고 읽는다
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK)
                .body(ApiResponse.ok(result.body()));
    }

    @GetMapping("/ships/{shipId}")
    @Operation(summary = "승인 상태 확인 — 선박 키로 부른다. 자기 선박만 볼 수 있다")
    public ApiResponse<PiShipStatusResponse> shipStatus(@PathVariable UUID shipId,
                                                          HttpServletRequest request) {
        return ApiResponse.ok(ships.status(shipId, callerShipId(request)));
    }

    @PostMapping("/accidents")
    @Operation(summary = "사고 upsert — 새 사고면 INSERT, 있으면 상태 단조 규칙으로 갱신")
    public ApiResponse<PiResult> accidents(@RequestBody PiEnvelope<PiAccident> body,
                                            HttpServletRequest request) {
        return ApiResponse.ok(ingest.acceptAccidents(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/accident-states")
    @Operation(summary = "상태 전이 이력 — append-only, 자연키로 멱등")
    public ApiResponse<PiResult> accidentStates(@RequestBody PiEnvelope<PiAccidentState> body,
                                                 HttpServletRequest request) {
        return ApiResponse.ok(ingest.acceptAccidentStates(unwrap(body), callerShipId(request)));
    }

    // ── 고빈도 시계열 ────────────────────────────────────────
    // ⚠ Pi 는 이 경로들을 **정해진 순서로** 민다(dev-iot sync.py TABLES = FK 순서).
    //   앞 경로가 404 면 그 뒤가 통째로 멈춘다 — 하나만 빼놓을 수 없는 묶음이다.

    @PostMapping("/ship-positions")
    @Operation(summary = "선박 위치 — 평시 항적 포함. 자연키 (ship_id, created_at) 로 멱등")
    public ApiResponse<PiResult> shipPositions(@RequestBody PiEnvelope<PiShipPosition> body,
                                               HttpServletRequest request) {
        return ApiResponse.ok(telemetry.acceptShipPositions(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/buoys")
    @Operation(summary = "부표 위치 이력 — 자연키 (accident_id, created_at) 로 멱등")
    public ApiResponse<PiResult> buoys(@RequestBody PiEnvelope<PiBuoy> body,
                                       HttpServletRequest request) {
        return ApiResponse.ok(telemetry.acceptBuoys(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/imus")
    @Operation(summary = "IMU 자세 이력 — 자연키 (accident_id, created_at, imu_position) 로 멱등")
    public ApiResponse<PiResult> imus(@RequestBody PiEnvelope<PiImu> body,
                                      HttpServletRequest request) {
        return ApiResponse.ok(telemetry.acceptImus(unwrap(body), callerShipId(request)));
    }

    // ── 사고 부속 이벤트 ─────────────────────────────────────

    @PostMapping("/launches")
    @Operation(summary = "부표 투하 결과 — 사고당 1행. 결과가 늦게 붙어 upsert 다")
    public ApiResponse<PiResult> launches(@RequestBody PiEnvelope<PiLaunch> body,
                                          HttpServletRequest request) {
        return ApiResponse.ok(events.acceptLaunches(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/comm-losses")
    @Operation(summary = "LoRa 두절 구간 — 시작·복귀 두 번 온다. (accident_id, detected_at) upsert")
    public ApiResponse<PiResult> commLosses(@RequestBody PiEnvelope<PiCommLoss> body,
                                            HttpServletRequest request) {
        return ApiResponse.ok(events.acceptCommLosses(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/drift-estimates")
    @Operation(summary = "표류 추정 이력 — 사고당 현재 1건. 옛 현재를 내리고 넣는다")
    public ApiResponse<PiResult> driftEstimates(@RequestBody PiEnvelope<PiDriftEstimate> body,
                                                HttpServletRequest request) {
        return ApiResponse.ok(events.acceptDriftEstimates(unwrap(body), callerShipId(request)));
    }

    @PostMapping("/reports")
    @Operation(summary = "신고 발신 기록 — 사고당 채널 1행. sent_count 가 줄면 stale")
    public ApiResponse<PiResult> reports(@RequestBody PiEnvelope<PiReport> body,
                                         HttpServletRequest request) {
        return ApiResponse.ok(events.acceptReports(unwrap(body), callerShipId(request)));
    }

    // ── 사고 파일 (R2) ───────────────────────────────────────

    /**
     * 사고 사진 한 장 업로드. <b>Pi 는 R2 자격증명을 갖지 않는다</b> —
     * 여기로 올리면 EC2 가 R2 에 넣고 객체 키를 돌려준다(ref/mqtt-연동-웹_v2 §11).
     *
     * <p><b>경로가 IoT 문서와 다르다.</b> §11 은 {@code POST /api/accidents/{accident_id}/files} 로
     * 적고 있으나 그 경로는 {@code /api/pi/**} 밖이라 {@link PiApiKeyFilter} 가 보지 않고,
     * {@code SecurityConfig} 에서 JWT 대상이라 <b>Pi 가 보내면 401 이 난다.</b>
     * 그래서 {@code /api/pi/} 아래로 옮겼다 — 인증·표기(snake_case)·시각(Unix 초) 규약이 한 벌로 맞는다.
     * dev-iot 에 EC2 업로더가 아직 없어(2026-09-18 확인) Pi 쪽 변경 비용이 0 인 시점이다.
     * ⚠ IoT 팀에 이 경로를 알려야 한다.</p>
     *
     * <p>봉투({@code request_id}·{@code v}·{@code data})를 쓰지 않는 유일한 수신 경로다 —
     * multipart 라 JSON 봉투를 실을 자리가 없다(api.md §4.1 도 {@code archives} 를 예외로 둔다).</p>
     *
     * <p><b>파일 하나당 요청 하나.</b> 여러 장을 묶으면 부분 실패가 지저분해진다.</p>
     */
    @PostMapping(path = "/accidents/{accidentId}/files",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "사고 사진 1장 업로드 — R2 에 넣고 object_key 를 돌려준다")
    public ApiResponse<PiFileResponse> uploadFile(
            @PathVariable UUID accidentId,
            @RequestParam("file") MultipartFile file,
            @RequestParam("file_type") String fileType,
            // DETECT_SNAPSHOT 은 장이 하나라 순번이 없다. 프레임은 순서 없이는 재생이 안 된다
            @RequestParam(value = "sequence_no", required = false) Integer sequenceNo,
            @RequestParam(value = "camera", required = false) String camera,
            @RequestParam(value = "captured_at", required = false) Long capturedAt,
            HttpServletRequest request) {
        return ApiResponse.ok(files.upload(accidentId, callerShipId(request), file,
                fileType, sequenceNo, camera, capturedAt));
    }

    /**
     * 사고 산출물 묶음 하나 (dev-iot {@code iot/pi/floaq/archive.py}).
     *
     * <p>🔴 <b>Pi 가 이미 이 경로로 보내고 있다.</b> 우리 주석은 한때
     * <i>tar 묶음은 기각했다</i> 였으나 현실은 반대였다 — Pi 쪽 전송 스레드가
     * {@code object_key IS NULL} 인 사고를 골라 계속 밀고 있고, 여기가 없으면
     * <b>그 대기열이 영영 안 줄어들어 사진이 R2 에 안 올라간다.</b></p>
     *
     * <p>봉투를 쓰지 않는 두 번째 경로다 — multipart 라 JSON 봉투를 실을 자리가 없다.</p>
     *
     * @param archive tar · tar.gz · mp4. <b>파트의 Content-Type 과 매직 바이트를 둘 다 본다</b>
     */
    @PostMapping(path = "/archives", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "사고 산출물 묶음 업로드 — tar(.gz) 은 풀어 장마다, mp4 는 그대로 R2 에 넣는다")
    public ApiResponse<PiArchiveResponse> uploadArchive(
            @RequestParam("accident_id") UUID accidentId,
            @RequestParam("archive") MultipartFile archive,
            @RequestParam(value = "archive_sha256", required = false) String sha256,
            @RequestParam(value = "created_at", required = false) Long createdAt,
            HttpServletRequest request) {
        return ApiResponse.ok(archives.receive(accidentId, callerShipId(request),
                archive, sha256, createdAt));
    }

    /**
     * 요청을 보낸 선박. <b>{@link PiApiKeyFilter} 가 키에서 풀어 실어 준 값</b>이고,
     * 본문이 아니라 헤더에서 온다 — 본문은 보내는 쪽이 쓰는 값이라 증명이 되지 않는다.
     */
    private UUID callerShipId(HttpServletRequest request) {
        return (UUID) request.getAttribute(PiApiKeyFilter.SHIP_ID_ATTRIBUTE);
    }

    /**
     * 봉투를 벗기고 공통 검증을 한다 (docs/api.md §4.1).
     *
     * <p><b>모르는 {@code v} 를 일반 400 과 갈라 두는 이유</b>: Pi 는
     * {@code PI_UNSUPPORTED_VERSION} 을 보면 행을 버리지 않고 전송만 멈춘다.
     * 일반 400 이면 서버가 구버전일 때 Pi 의 모든 전송이 실패로 찍히고 폐기된다.</p>
     */
    private <T> List<T> unwrap(PiEnvelope<T> body) {
        if (body == null || body.data() == null) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        if (body.v() == null || body.v() != PiEnvelope.SUPPORTED_VERSION) {
            throw new BusinessException(ErrorCode.PI_UNSUPPORTED_VERSION);
        }
        logSkew(body);
        return body.data();
    }

    /**
     * Pi 발행 시각과 서버 수신 시각의 차이를 <b>로그로만</b> 남긴다.
     *
     * <p>거절하지 않는 이유: 바다에는 NTP 가 없고 Pi 는 GPS 시각 기준인데(계획.md §9.5)
     * 실내 시연은 GPS 미수신이다. 시각으로 막으면 그때 전송이 통째로 멈춘다.
     * 멱등·단조 판정도 시각을 쓰지 않는다(§4.2) — 시계 차이에 기대지 않는 설계다.</p>
     */
    private void logSkew(PiEnvelope<?> body) {
        if (body.ts() == null) {
            return;
        }
        long skew = Instant.now().getEpochSecond() - body.ts();
        if (Math.abs(skew) > 60) {
            log.warn("Pi 시각 오차 {}초 (request_id={}). 두절 복귀 중이거나 GPS 미수신일 수 있다",
                    skew, body.requestId());
        }
    }
}

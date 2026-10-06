package com.floaq.accident;

import com.floaq.accident.dto.AccidentDetailView;
import com.floaq.accident.dto.AccidentSummaryView;
import com.floaq.accident.dto.BuoyPositionView;
import com.floaq.accident.dto.ReportView;
import com.floaq.accident.dto.PhotosView;
import com.floaq.accident.dto.ShipPositionView;
import com.floaq.accident.dto.TimelineEntryView;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.global.config.OpenApiConfig;
import com.floaq.global.response.ApiResponse;
import com.floaq.global.response.PageView;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 관제 웹 사고 조회 (docs/api.md §3.4).
 *
 * <p><b>조회 전용이다.</b> 사고 종료·영상 중지 같은 제어는 사고 상태를 직접 바꾸지 않고
 * Pi 에게 명령을 넣는 별도 경로다(§3.5) — 여기 섞으면 "읽기"와 "요청"이 한 컨트롤러에 들어온다.</p>
 *
 * <p>권한은 {@code SecurityConfig} 가 막는다. 관제가 볼 수 있는 범위(신고된 사고만)는
 * {@link AccidentQueryService#VISIBLE} 이고, <b>범위 밖은 404 다</b> — 403 이면
 * "그런 사고가 있다"를 알려주는 셈이다.</p>
 */
@Tag(name = "accidents", description = "사고 조회 (관제 웹)")
@RestController
@RequestMapping("/api/accidents")
@RequiredArgsConstructor
@SecurityRequirement(name = OpenApiConfig.JWT_SCHEME)
public class AccidentController {

    private final AccidentQueryService query;
    private final AccidentCommandService command;
    private final AccidentPhotoService photos;

    @GetMapping
    @Operation(summary = "사고 목록 — 진행 중(REPORT) 먼저, 그다음 발생 시각 내림차순")
    public ApiResponse<PageView<AccidentSummaryView>> list(
            @RequestParam(required = false) List<AccidentStatus> status,
            @RequestParam(required = false) UUID shipId,
            @RequestParam(required = false) Instant from,
            @RequestParam(required = false) Instant to,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(query.list(status, shipId, from, to, page, size));
    }

    @GetMapping("/{accidentId}")
    @Operation(summary = "사고 상세 — 투하·부표·신고·명령·영상")
    public ApiResponse<AccidentDetailView> detail(@PathVariable UUID accidentId) {
        return ApiResponse.ok(query.detail(accidentId));
    }

    @GetMapping("/{accidentId}/timeline")
    @Operation(summary = "타임라인 — 상태 전이와 관제 명령을 시각순으로 섞어서")
    public ApiResponse<List<TimelineEntryView>> timeline(@PathVariable UUID accidentId) {
        return ApiResponse.ok(query.timeline(accidentId));
    }

    /**
     * 부표 궤적. {@code after} 로 이어 받는다 — 화면이 WS {@code BUOY_POS} 를 놓쳤을 때 메우는 용도다.
     * {@code limit} 기본·상한은 3600 — 1초에 한 번이면 한 시간치다. 사고 길이 상한이 아니다(사고는 몇 시간 갈 수 있다).
     */
    @GetMapping("/{accidentId}/buoy-positions")
    @Operation(summary = "부표 실측 궤적 — 측정 시각 오름차순. 추정 궤적은 섞지 않는다")
    public ApiResponse<List<BuoyPositionView>> buoyPositions(
            @PathVariable UUID accidentId,
            @RequestParam(required = false) Instant after,
            @RequestParam(required = false) Integer limit) {
        return ApiResponse.ok(query.buoyPositions(accidentId, after, limit));
    }

    /**
     * 사고 선박 항적. 부표 궤적과 같은 규칙으로 이어 받는다.
     *
     * <p>사고 행의 위도·경도는 감지된 <b>순간</b>의 값이라, 진행 중인 사고에서 배가 움직이면 어긋난다.</p>
     */
    @GetMapping("/{accidentId}/ship-positions")
    @Operation(summary = "사고 선박 항적 — 측정 시각 오름차순. 마지막 점이 지금 배 위치다")
    public ApiResponse<List<ShipPositionView>> shipPositions(
            @PathVariable UUID accidentId,
            @RequestParam(required = false) Instant after,
            @RequestParam(required = false) Integer limit) {
        return ApiResponse.ok(query.shipPositions(accidentId, after, limit));
    }

    /**
     * 사고 접수 — <b>관제 화면이 이 사고를 받았다</b>는 사실을 남긴다.
     *
     * <p>{@code report.acked_at}(DSC 무선 ACK)과 다른 값이다. 멱등이라 화면이 폴링마다 불러도
     * 최초 시각이 유지된다 — {@code created} 가 false 면 이미 접수된 사고다.</p>
     */
    @PostMapping("/{accidentId}/ack")
    @Operation(summary = "사고 접수 — 관제가 받았음을 기록. 멱등(최초 시각 유지)")
    public ApiResponse<Map<String, Boolean>> ack(@PathVariable UUID accidentId) {
        return ApiResponse.ok(Map.of("created", command.ack(accidentId)));
    }

    /**
     * 사고자 발견 — 단계 ④. 멱등이라 두 번 눌러도 최초 시각이 유지된다.
     */
    @PostMapping("/{accidentId}/rescue")
    @Operation(summary = "사고자 발견 — 관제가 찍는다. 멱등(최초 시각 유지)")
    public ApiResponse<Map<String, Boolean>> rescue(@PathVariable UUID accidentId) {
        return ApiResponse.ok(Map.of("created", command.rescue(accidentId)));
    }

    /**
     * 사고 종결 — 단계 ⑤. <b>되돌릴 수 없다.</b> 이미 끝난 사고면 {@code created: false} 다.
     */
    @PostMapping("/{accidentId}/close")
    @Operation(summary = "사고 종결 — 되돌릴 수 없다. 먼저 누른 쪽만 성립")
    public ApiResponse<Map<String, Boolean>> close(@PathVariable UUID accidentId) {
        return ApiResponse.ok(Map.of("created", command.close(accidentId)));
    }

    /**
     * 사진 두 장 — 감지 순간 · 지금. 관제 화면이 몇 초마다 다시 받아 "지금"을 갱신한다.
     *
     * <p>실시간 동영상은 배 안 랜에서만 보여 인터넷의 관제 웹이 닿을 수 없다. 그래서 관제의
     * "지금"은 Pi 가 올리는 가장 최근 사진이다.</p>
     */
    @GetMapping("/{accidentId}/photos")
    @Operation(summary = "사고 사진 — 감지 순간·가장 최근 프레임. R2 presigned URL")
    public ApiResponse<PhotosView> photos(@PathVariable UUID accidentId) {
        return ApiResponse.ok(photos.photos(accidentId));
    }

    @GetMapping("/{accidentId}/reports")
    @Operation(summary = "채널별 신고 발신 기록 — ACK 은 DSC 만 온다")
    public ApiResponse<List<ReportView>> reports(@PathVariable UUID accidentId) {
        return ApiResponse.ok(query.reports(accidentId));
    }
}

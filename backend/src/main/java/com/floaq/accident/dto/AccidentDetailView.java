package com.floaq.accident.dto;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.TriggerSource;

import java.time.Instant;
import java.util.List;

/**
 * 사고 상세 (docs/api.md §3.4). <b>목록 항목과 같은 필드를 평평하게 두고</b> 투하·부표·신고·명령·영상을 더한다.
 *
 * <p>{@link AccidentSummaryView} 를 중첩하지 않는 이유: 명세가 "목록 항목에 더해"이고,
 * 중첩하면 화면이 목록과 상세에서 <b>같은 값을 다른 경로로</b> 읽어야 한다
 * ({@code a.status} vs {@code a.accident.status}). {@code ship} 도 두 번 나온다.</p>
 *
 * <p>{@code commLoss} 는 <b>지금 항상 null 이다.</b> {@code comm_loss} 테이블이 없고 두절 판정 주체가
 * Pi 로 정해졌다 — 서버가 임시로 판정하면 판정 주체가 둘이 되고, 그 둘이 다른 말을 하는 순간
 * 어느 쪽이 맞는지 아무도 모른다(docs/api.md §9 4).
 * <b>화면도 "마지막 수신 N초 전"까지만 쓰고 "두절"이라는 단어를 쓰지 않는다.</b></p>
 */
public record AccidentDetailView(
        java.util.UUID accidentId,
        ShipBriefView ship,
        AccidentType accidentType,
        TriggerSource triggerSource,
        ReportType reportType,
        Integer reportDsc,
        AccidentStatus status,
        Double lat,
        Double lon,
        Instant createdAt,
        Instant reportDueAt,
        Instant reportedAt,
        Instant rescuedAt,
        Instant closedAt,
        /** 저체온증 생존 잔여시간의 입력이다. 없으면 화면이 그 시계를 못 돌린다 */
        Float waterTempC,
        /** 관제가 이 사고를 접수한 시각. report.ackedAt(DSC 무선 ACK)과 다른 값이다 */
        Instant webAckedAt,
        /**
         * 사고가 나던 때의 바다. 없으면 null — 이 칸이 생기기 전 사고이거나 격자·관측 지점이 멀었다.
         * 화면은 이 값을 먼저 쓰고, 없을 때만 해양 조회로 메운다(V20260921_1210)
         */
        OceanSnapView ocean,
        LaunchView launch,
        BuoyStateView buoy,
        Object commLoss,
        List<ReportView> reports,
        MediaView media,
        List<PendingCommandView> pendingCommands) {

    public static AccidentDetailView of(Accident a, ShipBriefView ship, LaunchView launch,
                                        BuoyStateView buoy, List<ReportView> reports,
                                        MediaView media, List<PendingCommandView> pendingCommands) {
        return new AccidentDetailView(
                a.getAccidentId(), ship, a.getAccidentType(), a.getTriggerSource(),
                a.getReportType(), a.getReportDsc(), a.getStatus(), a.getLat(), a.getLon(),
                a.getCreatedAt(), a.getReportDueAt(), a.getReportedAt(), a.getRescuedAt(), a.getClosedAt(),
                a.getWaterTempC(), a.getWebAckedAt(), OceanSnapView.of(a), launch, buoy, null, reports, media, pendingCommands);
    }
}

package com.floaq.accident.dto;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.TriggerSource;

import java.time.Instant;
import java.util.UUID;

/**
 * 사고 목록 항목 (docs/api.md §3.4).
 *
 * <p>{@code lat}·{@code lon} 은 <b>null 일 수 있다</b> — GPS 미수신 사고다.
 * 0,0 으로 채우지 않는다. 그 자리가 곧 거짓말이 된다.</p>
 *
 * <p><b>경과 시간을 내리지 않는다.</b> 시각만 주면 화면이 자기 시계로 센다 —
 * 서버가 계산하면 응답 지연만큼 틀린다.</p>
 */
public record AccidentSummaryView(
        UUID accidentId,
        ShipBriefView ship,
        AccidentType accidentType,
        TriggerSource triggerSource,
        ReportType reportType,
        Integer reportDsc,
        AccidentStatus status,
        Double lat,
        Double lon,
        Instant createdAt,
        Instant reportedAt,
        Instant rescuedAt,
        Instant closedAt,
        /** 저체온증 생존 잔여시간의 입력이다. 없으면 화면이 그 시계를 못 돌린다 */
        Float waterTempC,
        /** 관제가 이 사고를 접수한 시각. report.ackedAt(DSC 무선 ACK)과 다른 값이다 */
        Instant webAckedAt,
        /**
         * 사고가 나던 때의 바다. 없으면 null — 이 칸이 생기기 전 사고이거나 격자·관측 지점이 멀었다.
         * 목록에도 싣는 이유는 <b>지도에 함께 올린 사고마다 표류를 그리기</b> 때문이다(V20260921_1210)
         */
        OceanSnapView ocean) {

    public static AccidentSummaryView of(Accident a, ShipBriefView ship) {
        return new AccidentSummaryView(a.getAccidentId(), ship, a.getAccidentType(), a.getTriggerSource(),
                a.getReportType(), a.getReportDsc(), a.getStatus(), a.getLat(), a.getLon(),
                a.getCreatedAt(), a.getReportedAt(), a.getRescuedAt(), a.getClosedAt(), a.getWaterTempC(), a.getWebAckedAt(), OceanSnapView.of(a));
    }
}

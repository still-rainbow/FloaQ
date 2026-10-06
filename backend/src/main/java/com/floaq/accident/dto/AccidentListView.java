package com.floaq.accident.dto;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.ReportType;

import java.time.Instant;
import java.util.UUID;

/**
 * 사고 목록 한 건 (docs/api.md §3.4 · WEB-03).
 *
 * <p>⚠ {@code accidentType} · {@code triggerSource} · {@code reportedAt} · {@code rescuedAt} 은
 * <b>서버에 컬럼이 없어 항상 null</b> 이다(api.md §9 #5·#13). 그래도 응답에 남겨 둔다 —
 * 팀원의 edge 마이그레이션이 컬럼을 넣는 날 값만 채워지고 <b>화면이 보는 모양은 바뀌지 않는다.</b>
 * 지금 빼 두면 그날 프런트도 같이 고쳐야 한다.</p>
 *
 * <p>{@code lat}·{@code lon} 은 null 일 수 있다 — GPS 미수신 사고다. <b>0,0 으로 채우지 않는다.</b>
 * 채우면 기니 만 앞바다가 사고 지점으로 그려진다.</p>
 */
public record AccidentListView(
        UUID accidentId,
        ShipRef ship,
        String accidentType,
        String triggerSource,
        ReportType reportType,
        Integer reportDsc,
        AccidentStatus status,
        Double lat,
        Double lon,
        Instant createdAt,
        Instant reportedAt,
        Instant rescuedAt,
        Instant closedAt) {

    /** 목록에 필요한 배 정보는 이름뿐이다. 등록번호·톤수는 상세에서 준다 */
    public record ShipRef(UUID shipId, String name) {
    }

    /**
     * @param shipName 배 이름. FK 가 있어 배는 반드시 있지만, 없어도 목록 전체를 실패시키지 않는다 —
     *                 사고 한 건의 이름이 비는 편이 사고 목록이 안 뜨는 것보다 낫다.
     */
    public static AccidentListView of(Accident a, String shipName) {
        return new AccidentListView(
                a.getAccidentId(),
                new ShipRef(a.getShipId(), shipName),
                null,
                null,
                a.getReportType(),
                a.getReportDsc(),
                a.getStatus(),
                a.getLat(),
                a.getLon(),
                a.getCreatedAt(),
                null,
                null,
                a.getClosedAt());
    }
}

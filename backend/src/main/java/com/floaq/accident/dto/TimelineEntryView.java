package com.floaq.accident.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.StateReason;
import com.floaq.pi.entity.CommandState;
import com.floaq.pi.entity.CommandType;

import java.time.Instant;

/**
 * 사고 타임라인 한 줄 (docs/api.md §3.4). 상태 전이와 관제 명령을 <b>한 줄기로 섞어</b> 시각순으로 준다.
 *
 * <p>둘을 따로 주면 화면이 두 배열을 시각으로 합쳐야 하는데, 그 합치기가 화면마다 달라진다.
 * 사고 경위를 설명해야 하는 시스템에서 순서는 서버가 정한다.</p>
 *
 * <p>{@code kind} 로 갈리고 쓰이지 않는 필드는 <b>응답에서 빠진다</b>({@code NON_NULL}) —
 * null 로 채워 보내면 화면이 "값이 없는 것"과 "이 종류에 없는 것"을 구분할 수 없다.</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TimelineEntryView(
        Instant at,
        Kind kind,
        AccidentStatus status,
        StateReason reason,
        CommandType commandType,
        CommandState commandState,
        IssuerView issuedBy) {

    public enum Kind {
        STATE, COMMAND
    }

    /** 명령을 낸 관제 사용자. 종결 주체를 되짚는 값이다(계획.md §9.20). */
    public record IssuerView(Long userId, String name) {
    }

    public static TimelineEntryView state(Instant at, AccidentStatus status, StateReason reason) {
        return new TimelineEntryView(at, Kind.STATE, status, reason, null, null, null);
    }

    public static TimelineEntryView command(Instant at, CommandType type, CommandState state,
                                            IssuerView issuedBy) {
        return new TimelineEntryView(at, Kind.COMMAND, null, null, type, state, issuedBy);
    }
}

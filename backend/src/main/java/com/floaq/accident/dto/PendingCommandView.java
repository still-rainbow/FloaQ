package com.floaq.accident.dto;

import com.floaq.pi.entity.CommandState;
import com.floaq.pi.entity.CommandType;

import java.time.Instant;
import java.util.UUID;

/**
 * 처리 전 명령. 화면이 <b>"종료 요청함"과 "종료됨"을 구분</b>하는 근거다 —
 * ack 전에 상태를 바꿔 그리면 화면이 거짓말을 한다(계획.md §9.9).
 */
public record PendingCommandView(UUID commandId, CommandType type, CommandState state,
                                 Instant issuedAt, Instant expiredAt) {
}

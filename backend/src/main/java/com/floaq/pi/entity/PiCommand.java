package com.floaq.pi.entity;

import com.floaq.accident.entity.AccidentStatus;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.UUID;

/**
 * 관제 → Pi 하행 명령 (V9 · docs/api.md §3.5 · §4.4).
 *
 * <p><b>관제의 제어는 요청이지 상태 변경이 아니다.</b> 웹의 "사고 종료"는 사고 상태를 직접 바꾸지 않고
 * 이 행을 만든다. Pi 가 폴링으로 가져가 처리하고 ack 하면 그때 사고 상태가 따라온다 —
 * 서버가 먼저 바꾸면 인터넷이 끊긴 동안 화면과 선내가 다른 말을 한다(계획.md §9.2·§9.9).</p>
 *
 * <p>서버가 만드는 행이라 <b>단일 PK</b>다. Pi 기원 테이블의 {@code (uuid, created_at)} 복합키
 * 규칙은 여기 해당하지 않는다.</p>
 */
@Entity
@Getter
// ⚠ 클래스는 PiCommand, 테이블은 edge_command. 2026-09-17 개명에서 DB 만 제외했다
@Table(name = "edge_command")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class PiCommand {

    /** uuid v7 = 시간순. Pi 폴링이 이 순서로 받아 간다 */
    @Id
    @Column(name = "command_id", nullable = false, updatable = false)
    private UUID commandId;

    @Column(name = "ship_id", nullable = false, updatable = false)
    private UUID shipId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    @Enumerated(EnumType.STRING)
    @Column(name = "type", nullable = false, length = 16)
    private CommandType type;

    @Enumerated(EnumType.STRING)
    @Column(name = "state", nullable = false, length = 12)
    private CommandState state;

    /** 명령을 낸 관제 사용자 */
    @Column(name = "issued_by", nullable = false)
    private Long issuedBy;

    @Column(name = "issued_at", nullable = false)
    private Instant issuedAt;

    /** Pi 가 폴링으로 가져간 시각. 배달과 처리는 다르다 */
    @Column(name = "delivered_at")
    private Instant deliveredAt;

    @Column(name = "handled_at")
    private Instant handledAt;

    /**
     * 만료 시각. <b>만료 뒤 늦게 온 ack 도 받는다</b> — Pi 가 두절에서 돌아와 처리했을 수 있고,
     * 그때 실제로 일어난 일을 화면이 알아야 한다(docs/api.md §3.5).
     */
    @Column(name = "expired_at")
    private Instant expiredAt;

    @Column(name = "error_code", length = 32)
    private String errorCode;

    /** ack 때 Pi 가 아는 사고 상태. 화면을 실제 상태로 되돌리는 근거다 */
    @Enumerated(EnumType.STRING)
    @Column(name = "accident_status", length = 16)
    private AccidentStatus accidentStatus;
}

package com.floaq.accident.entity;

import com.floaq.global.Uuid7;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.domain.Persistable;

import java.io.Serializable;
import java.time.Instant;
import java.util.UUID;

/**
 * 사고 상태 이력 — 관제 웹 사고 상세의 타임라인 (WEB-04).
 *
 * <p>상태를 {@code accident.status} 에 덮어쓰기만 하면 <b>"언제 무엇에서 무엇으로 바뀌었나"가
 * 사라진다.</b> 오종결 후 재개(계획.md §9.20)처럼 되짚어야 하는 경위가 실재한다.</p>
 */
@Entity
@Getter
@IdClass(AccidentState.AccidentStateId.class)
@Table(name = "accident_state",
        indexes = @Index(name = "ix_state_accident_created", columnList = "accident_id, created_at"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AccidentState implements Persistable<AccidentState.AccidentStateId> {

    /**
     * Pi 가 발급한 UUID v7. <b>위 주석이 "팀 확인 대기"로 남겨 뒀던 것이 확정됐다</b>(2026-09-11) —
     * 배치 INSERT 와 멱등이 함께 풀렸고 자연키 {@code uq_state_accident_status_at} 를 지웠다.
     *
     * <p>⚠ 이 테이블은 하이퍼테이블이 아니다. {@code createdAt} 이 PK 에 들어갈 기술적 이유는 없고,
     * <b>Pi 의 SQLite 스키마와 패턴을 하나로 두려고</b> 넣었다.</p>
     */
    @Id
    @Column(name = "accident_state_id", nullable = false, updatable = false)
    private UUID accidentStateId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private AccidentStatus status;

    /**
     * 직전 상태. 첫 전이(사고 생성)면 null.
     *
     * <p>{@code status} 만 있어도 이력은 복원되지만, <b>늦게 도착한 행이 순서를 깨뜨렸을 때</b>
     * 그것을 알아보려면 각 행이 자기가 무엇에서 왔는지 들고 있어야 한다.</p>
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "prev_status", length = 16)
    private AccidentStatus prevStatus;

    /** 전이 사유 8종. <b>종결 주체도 이 값으로 가른다</b>(계획.md §9.20). */
    @Enumerated(EnumType.STRING)
    @Column(name = "reason", length = 24)
    private StateReason reason;

    /** 무엇이 이 전이를 일으켰나. 키오스크 명령이면 그 {@code request_id}. */
    @Column(name = "caused_by", length = 64)
    private String causedBy;

    /**
     * <b>상태가 변경된 시각. 행이 만들어진 시각이 아니다</b> (ERD 주석).
     * Pi 의 GPS 시계 기준이며 서버가 덮어쓰지 않는다 — 그래서 {@code @CreatedDate} 가 없다.
     */
    @Id
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    // ── Persistable ─────────────────────────────────────────

    /**
     * <b>{@code save()} 가 {@code merge()} 로 빠지는 것을 막는다.</b> PK 가 이미 채워져 있으면
     * Spring Data 는 저장된 적 있는 행으로 보고 SELECT 후 INSERT 한다 — 쿼리가 두 배다.
     * 두절 복귀 시 밀린 전이가 한꺼번에 오는 경로다.
     */
    /**
     * 관제 웹이 남기는 상태 전이 한 줄.
     *
     * <p>사고의 상태는 <b>Pi 가 정하고 서버가 받아 적는 것</b>이 원칙이지만, 종결은 관제도 한다 —
     * 구조가 끝난 것을 아는 쪽이 관제이기 때문이다(계획.md §9.20). 그때 이 줄을 남기지 않으면
     * 사고 상세의 경위에 종결이 빠져, 표에는 끝났다고 적혀 있는데 경위에는 그 일이 없다.</p>
     *
     * <p>⚠ {@code reason} 은 비운다. DB 가 허용하는 사유는 모두 <b>선내 단말이 한 일</b>이라
     * ({@code TABLET_*}) 관제가 쓸 값이 없다 — 억지로 {@code TABLET_CLOSE} 를 적으면
     * "배에서 껐다"는 다른 말이 된다. 누가 했는지는 {@code causedBy} 가 말한다.</p>
     */
    public static AccidentState byControl(UUID accidentId, AccidentStatus status,
                                          AccidentStatus prev, Instant at, String causedBy) {
        AccidentState row = new AccidentState();
        row.accidentStateId = Uuid7.next();
        row.accidentId = accidentId;
        row.status = status;
        row.prevStatus = prev;
        row.causedBy = causedBy;
        row.createdAt = at;
        return row;
    }

    @Override
    public AccidentStateId getId() {
        return new AccidentStateId(accidentStateId, createdAt);
    }

    /**
     * <b>항상 새 행이다.</b> 이 테이블은 append-only 라 수정이 없다 —
     * 같은 PK 가 다시 오면 그건 갱신이 아니라 <b>재전송</b>이고, 제약 위반으로 시끄럽게 실패해야 한다.
     * 조용히 덮어쓰면 "몇 건을 받았나"가 사라진다(계획.md §2).
     */
    @Override
    public boolean isNew() {
        return true;
    }

    // ── 복합 PK ─────────────────────────────────────────────

    /**
     * {@code (accidentStateId, createdAt)}. <b>record 를 쓸 수 없다</b> —
     * JPA 의 {@code @IdClass} 는 기본 생성자를 요구하는데 record 에는 없다.
     *
     * <p>필드 이름이 엔티티 쪽과 <b>글자까지 같아야</b> 매핑된다. 다르면 기동 때 터진다.</p>
     */
    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @EqualsAndHashCode
    public static class AccidentStateId implements Serializable {
        private UUID accidentStateId;
        private Instant createdAt;
    }
}

package com.floaq.report.entity;

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
 * 신고 발신 <b>기록</b>. 서버는 쏘지 않는다 — <b>Pi 가 UDP 로 발신하고 그 사실만 올려보낸다</b>
 * (확정 2026-09-11, 계획.md §9.4).
 *
 * <p>백엔드가 쏘면 §9.2 의 <i>"인터넷이 끊겨도 감지·발사·신고는 그대로 동작"</i> 이 무너진다.
 * 그래서 이 도메인에 UDP 발신기도, 3채널 × 1분 8회 반복 스케줄러도 없다.</p>
 *
 * <p>⚠ <b>ERD 에 {@code channel}·{@code report_type}·{@code status}·{@code sent_count} 가 없다.</b>
 * 상세기획 §6.1 이 "🔴 최우선 — 없으면 기능 불가"로 꼽은 항목이고,
 * 없으면 관제 화면의 <b>신고 상태(S-03)와 채널별 전송 이력(S-05)을 그릴 수 없다.</b></p>
 */
@Entity
@Getter
@IdClass(Report.ReportId.class)
@Table(name = "report",
        indexes = @Index(name = "ix_report_accident_created", columnList = "accident_id, created_at"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Report implements Persistable<Report.ReportId> {

    /** Pi 가 발급한 UUID v7. 신고 기록은 Pi 가 만든다(§9.4) — 서버 채번이면 재전송이 두 건이 된다 */
    @Id
    @Column(name = "report_id", nullable = false, updatable = false)
    private UUID reportId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    /**
     * 전송 좌표. <b>불변 스냅샷이다</b> — 사고 좌표가 나중에 갱신돼도 이 값은 바뀌지 않는다.
     * "그때 어디로 신고했나"가 사라지면 경위를 설명할 수 없다.
     */
    /** 채널별 1행. 자연키 {@code (accident_id, channel)} 로 재전송이 멱등해진다 (V9) */
    @Enumerated(EnumType.STRING)
    @Column(name = "channel", length = 8)
    private ReportChannel channel;

    /** ⚠ {@code accident.report_type}(DISTRESS·URGENCY)과 다른 것이다 — 자동/수동/구조중지 */
    @Enumerated(EnumType.STRING)
    @Column(name = "trigger_kind", length = 8)
    private ReportTriggerKind triggerKind;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", length = 8)
    private ReportStatus status;

    /** 누적 발신 횟수. <b>줄어들면 옛 행이다</b> — 재전송 순서가 뒤바뀐 것이지 발신이 취소된 게 아니다 */
    @Column(name = "sent_count")
    private Integer sentCount;

    /**
     * 첫 발신 시각. <b>{@code createdAt}(행 생성 시각)과 다르다</b> —
     * 인터넷이 없어 {@code SENDING} 조차 못 간 채널은 행이 먼저 생기고 이 값이 null 이다.
     */
    @Column(name = "first_sent_at")
    private Instant firstSentAt;

    @Column(name = "last_sent_at")
    private Instant lastSentAt;

    /** DSC 만 값이 있다. AIS 는 단방향이라 규격상 ACK 가 없다 (DB CHECK 가 막는다) */
    @Column(name = "acked_at")
    private Instant ackedAt;

    /** 확인응답을 보낸 해안국 MMSI 9자리 */
    @Column(name = "acked_by", length = 9)
    private String ackedBy;

    /** 🔴 {@code NO_INTERNET} 은 화면에 반드시 드러낸다 — 없으면 신고가 나간 줄 안다 */
    @Enumerated(EnumType.STRING)
    @Column(name = "fail_reason", length = 16)
    private ReportFailReason failReason;

    @Column(name = "report_lat", nullable = false)
    private Double reportLat;

    @Column(name = "report_lon", nullable = false)
    private Double reportLon;

    /** Pi 가 발신한 시각 */
    @Id
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    // ── Persistable ─────────────────────────────────────────

    /**
     * <b>{@code save()} 가 {@code merge()} 로 빠지는 것을 막는다.</b> PK 가 이미 채워져 있으면
     * Spring Data 는 저장된 적 있는 행으로 보고 SELECT 후 INSERT 한다 — 쿼리가 두 배다.
     * 신고 기록은 건수 자체가 의미라 중복이 특히 나쁘다.
     */
    @Override
    public ReportId getId() {
        return new ReportId(reportId, createdAt);
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
     * {@code (reportId, createdAt)}. <b>record 를 쓸 수 없다</b> —
     * JPA 의 {@code @IdClass} 는 기본 생성자를 요구하는데 record 에는 없다.
     *
     * <p>필드 이름이 엔티티 쪽과 <b>글자까지 같아야</b> 매핑된다. 다르면 기동 때 터진다.</p>
     */
    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @EqualsAndHashCode
    public static class ReportId implements Serializable {
        private UUID reportId;
        private Instant createdAt;
    }
}

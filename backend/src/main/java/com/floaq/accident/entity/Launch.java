package com.floaq.accident.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.domain.Persistable;

import java.time.Instant;
import java.util.UUID;

/**
 * 부표 투하 기록. 사고 1건당 1회 — <b>재투하가 없다</b>(상세기획 E5, 투하 장치 1기).
 * 그래서 PK 가 곧 FK 다.
 *
 * <p>⚠ ERD 의 컬럼명은 {@code accident_id2} 다. ERDCloud 가 같은 테이블로 가는 FK 를
 * 자동 개명한 흔적이며, 그대로 두면 <b>실제 컬럼명이 된다.</b>
 * 여기서는 {@code accident_id} 로 매핑했다 — ERD 수정 대상
 * ([[260910_mqtt-erd-review]] §3.6, 두 번째 지적).</p>
 */
@Entity
@Getter
@Table(name = "launch")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Launch implements Persistable<UUID> {

    @Id
    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    /** 발사 시점의 선박 위치 */
    /** Jetson 탐지 건 식별자. 조준 해의 출처를 되짚는 값 (V9) */
    @Column(name = "detection_id", length = 64)
    private String detectionId;

    @Enumerated(EnumType.STRING)
    @Column(name = "result", length = 8)
    private LaunchResult result;

    @Enumerated(EnumType.STRING)
    @Column(name = "fail_reason", length = 16)
    private LaunchFailReason failReason;

    /**
     * 조준 목표점. <b>명령한 각도와 다를 수 있다</b> — 소프트 리밋에 걸리면 Pi 가 각도를 깎기 때문이다.
     * 그래서 목표점과 실제 각도를 둘 다 받는다. {@code NO_SOLUTION} 이면 null 이다.
     */
    @Column(name = "target_lat")
    private Double targetLat;

    @Column(name = "target_lon")
    private Double targetLon;

    @Column(name = "launch_lat", nullable = false)
    private Double launchLat;

    @Column(name = "launch_lon", nullable = false)
    private Double launchLon;

    /** deg. 수평 발사각 */
    @Column(name = "horizontal_angle", nullable = false)
    private Float horizontalAngle;

    /** deg. 수직 발사각 */
    @Column(name = "vertical_angle", nullable = false)
    private Float verticalAngle;

    /** 0~1. AI 탐지 확신도 */
    @Column(name = "confidence_score")
    private Float confidenceScore;

    /** Pi 의 발사 시각. 서버 수신 시각이 아니다 */
    @Column(name = "created_at")
    private Instant createdAt;

    @Override
    public UUID getId() {
        return accidentId;
    }

    /**
     * 사고당 1행이고 Pi 가 PK 를 준다. {@code save()} 가 {@code merge()} 로 빠져
     * SELECT 를 한 번 더 치는 것을 막는다 — 사고 진행 중에 도는 경로다.
     */
    @Override
    public boolean isNew() {
        return true;
    }
}

package com.floaq.device.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
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
 * IMU 자세·가속도. 사고 구간 보존용이다 (IOT-20 — 30초 단위로 EC2 업로드).
 *
 * <p>⚠ ERD 는 {@code accident_id} 가 <b>NOT NULL</b> 이라 <b>평시 IMU 를 저장할 수 없다.</b>
 * {@code ref/mqtt.md} §5.6 은 {@code accident_id: Uuid | null // 평상시는 null} 이다 — 어긋난다.
 * 다만 계획.md §9.13 이 <i>"웹이 위치를 받는 계기는 사고뿐"</i> 이라 서버 DB 에서는 NOT NULL 이
 * 맞을 수 있다. <b>의도인지 확인 필요</b> — Pi 로컬 DB 는 nullable 이어야 한다.</p>
 */
@Entity
@Getter
@IdClass(Imu.ImuId.class)
@Table(name = "imu",
        indexes = @Index(name = "ix_imu_accident_created", columnList = "accident_id, created_at"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Imu implements Persistable<Imu.ImuId> {

    /** Pi 가 발급한 UUID v7. 근거는 {@link com.floaq.buoy.entity.Buoy#getId()} 와 같다 */
    @Id
    @Column(name = "imu_id", nullable = false, updatable = false)
    private UUID imuId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    /** m/s^2 */
    @Column(name = "accel_x")
    private Float accelX;

    @Column(name = "accel_y")
    private Float accelY;

    @Column(name = "accel_z")
    private Float accelZ;

    /**
     * 자세각(<b>deg</b>).
     *
     * <p>⚠ <b>ERD 주석이 아직 {@code deg/s} 다.</b> {@code ref/mqtt.md} §5.6 이 스스로
     * <i>"ERD 주석이 deg/s 로 되어 있는데 잘못입니다 — 각도(deg)가 맞습니다"</i> 라고 지적했는데
     * 고쳐지지 않았다([[260910_mqtt-erd-review]] §3.5, 두 번째 지적).</p>
     *
     * <p>각속도와 각도는 다른 값이다. 그대로 두면 <b>전복 판정 임계 롤 각</b>
     * (계획.md §9.21 {@code app.report.capsizing-roll-deg})이 무의미해진다 —
     * 침수(101)와 전복 위험(104)을 가르는 값이다.</p>
     */
    @Column(name = "roll", nullable = false)
    private Float roll;

    @Column(name = "pitch", nullable = false)
    private Float pitch;

    /**
     * yaw(방위). ⚠ MPU-6050 은 6축이라 자이로 적분으로만 얻는데 드리프트가 누적된다.
     * 상세기획 §2.2 가 "IMU 오차를 GPS 로 보정"하기로 했다 — 이 값 단독으로 방위를 믿지 않는다.
     */
    @Column(name = "yaw", nullable = false)
    private Float yaw;

    /** 측정 시각. Pi 의 GPS 시계 기준 */
    @Id
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    // ── Persistable ─────────────────────────────────────────

    /**
     * <b>{@code save()} 가 {@code merge()} 로 빠지는 것을 막는다.</b> PK 가 이미 채워져 있으면
     * Spring Data 는 저장된 적 있는 행으로 보고 SELECT 후 INSERT 한다 — 쿼리가 두 배다.
     * 30초 단위로 묶여 올라오는 경로라 배치가 그대로 살아야 한다.
     */
    @Override
    public ImuId getId() {
        return new ImuId(imuId, createdAt);
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
     * {@code (imuId, createdAt)}. <b>record 를 쓸 수 없다</b> —
     * JPA 의 {@code @IdClass} 는 기본 생성자를 요구하는데 record 에는 없다.
     *
     * <p>필드 이름이 엔티티 쪽과 <b>글자까지 같아야</b> 매핑된다. 다르면 기동 때 터진다.</p>
     */
    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @EqualsAndHashCode
    public static class ImuId implements Serializable {
        private UUID imuId;
        private Instant createdAt;
    }
}

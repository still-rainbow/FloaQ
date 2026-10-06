package com.floaq.ship.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.domain.Persistable;

import java.io.Serializable;
import java.time.Instant;
import java.util.UUID;

/**
 * 사고 구간 선박 위치 (V11). <b>사고 중에만 받는다</b> — 평시 항적이 아니다.
 *
 * <p>진행 중인 사고는 서버가 받아 관제로 흘려주면 그만이지만, 그때 적어 두지 않으면
 * <b>끝난 사고를 다시 열었을 때 지도에 배가 없다.</b> 부표({@link com.floaq.buoy.entity.Buoy})를
 * 남기는 것과 같은 이유다.</p>
 *
 * <p>선수방위·속력은 <b>Pi 가 보내 준 값을 그대로 읽는다</b>. 연속된 두 위치로 계산할 수도 있지만,
 * 배가 제자리에서 돌면 두 점이 같아 방위가 나오지 않고, 점 간격이 벌어지면 그사이 선회가 통째로 뭉개진다.
 * 배의 자이로가 재서 보내 주는 값이 있는데 뒤에서 다시 추정할 이유가 없다.</p>
 *
 * <p>⚠ <b>쓰기는 이 엔티티를 거치지 않는다.</b> Pi 수신은 {@code PiTelemetryService} 가 JDBC 로 일괄 INSERT 한다 —
 * 여기 칸을 늘려도 저장 경로는 바뀌지 않는다. 이 엔티티는 관제가 <b>읽을</b> 때만 쓴다.</p>
 */
@Entity
@Getter
@IdClass(ShipPosition.ShipPositionId.class)
@Table(name = "ship_position",
        indexes = @Index(name = "ix_ship_position_accident_created", columnList = "accident_id, created_at"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ShipPosition implements Persistable<ShipPosition.ShipPositionId> {

    /** uuid v7. Pi 가 발급한다 — 재전송이 와도 같은 PK 라 중복 행이 생기지 않는다(V1 ⑤). */
    @Id
    @Column(name = "ship_position_id", nullable = false, updatable = false)
    private UUID shipPositionId;

    @Column(name = "ship_id", nullable = false, updatable = false)
    private UUID shipId;

    /**
     * ⚠ <b>거의 늘 비어 있다.</b> Pi 에는 이 칸이 없고(api.md §0.1 #5), 어느 위치가 어느 사고 것인지
     * 붙이는 규칙이 아직 서지 않아 수신 때 넣지 않는다. 그래서 <b>조회할 때 선박과 사고 기간으로 고른다</b> —
     * 표에 추측을 적어 두면 나중에 어느 행이 사실이고 어느 행이 추정인지 가를 수 없다.
     */
    @Column(name = "accident_id", updatable = false)
    private UUID accidentId;

    @Column(name = "lat", nullable = false)
    private Double lat;

    @Column(name = "lon", nullable = false)
    private Double lon;

    /** knot. 도착 예정 시각 계산의 입력이다(계획.md §9.14) */
    @Column(name = "speed_kn")
    private Float speedKn;

    /** 뱃머리가 향한 방향. 진북 기준 0~360. 지도에서 배 아이콘을 돌리는 데 쓴다 */
    @Column(name = "heading_deg")
    private Float headingDeg;

    /** 선박 GPS 가 위치를 측정한 시각. <b>서버 수신 시각이 아니다.</b> */
    @Id
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Override
    public ShipPositionId getId() {
        return new ShipPositionId(shipPositionId, createdAt);
    }

    /**
     * Pi 가 PK 를 발급하므로 항상 새 행으로 본다. 재전송 중복은 PK 가 막는다 —
     * {@code save()} 가 SELECT 후 INSERT 하는 merge 로 빠지면 행마다 조회가 한 번씩 더 나간다.
     */
    @Override
    public boolean isNew() {
        return true;
    }

    /** {@code (shipPositionId, createdAt)}. {@code @IdClass} 는 기본 생성자를 요구해 record 를 쓸 수 없다. */
    @Getter
    @NoArgsConstructor
    @EqualsAndHashCode
    public static class ShipPositionId implements Serializable {
        private UUID shipPositionId;
        private Instant createdAt;

        public ShipPositionId(UUID shipPositionId, Instant createdAt) {
            this.shipPositionId = shipPositionId;
            this.createdAt = createdAt;
        }
    }
}

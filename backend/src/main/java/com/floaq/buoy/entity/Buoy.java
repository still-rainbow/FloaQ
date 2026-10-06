package com.floaq.buoy.entity;

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
 * 부표 위치 이력. <b>1초마다 한 행</b>이 LoRa 로 들어온다 (IOT-05).
 *
 * <p>⚠ ERD 컬럼명이 {@code accident_id2} 다. {@link com.floaq.accident.entity.Launch} 와 같은
 * ERDCloud 개명 흔적이라 {@code accident_id} 로 매핑했다.</p>
 */
@Entity
@Getter
@IdClass(Buoy.BuoyId.class)
@Table(name = "buoy",
        // 최신 부표 위치는 초당 조회된다 (상세기획 §6.5). 인덱스가 없으면 풀스캔이다
        indexes = @Index(name = "ix_buoy_accident_created", columnList = "accident_id, created_at DESC"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Buoy implements Persistable<Buoy.BuoyId> {

    /**
     * <b>Pi 가 발급한 UUID v7.</b> 서버 채번(IDENTITY)에서 바꿨다 — 두 가지가 함께 풀린다.
     *
     * <p>① <b>멱등</b>: 재전송이 PK 충돌로 막힌다. 예전에는 자연키 UNIQUE 로 막았다.<br>
     * ② <b>배치 INSERT</b>: IDENTITY 는 생성 키를 건별로 받아와야 해서 묶이지 않았다.
     * 1행/초라 두절 복귀 시 밀린 행이 한꺼번에 오는 경로에서 실제로 손해였다.</p>
     *
     * <p>🔴 <b>전제: Pi 가 이 값을 자기 SQLite 에 저장하고 재전송 때 그대로 보낸다.</b>
     * 매번 새로 만들면 중복을 막을 방법이 없다 — 자연키 UNIQUE 를 지웠기 때문이다.</p>
     */
    @Id
    @Column(name = "buoy_id", nullable = false, updatable = false)
    private UUID buoyId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    /** 부표가 매긴 순번. <b>유실 감지용</b> — 번호가 건너뛰면 그 사이 LoRa 패킷이 안 온 것이다 (V9) */
    @Column(name = "seq")
    private Integer seq;

    @Column(name = "buoy_lat", nullable = false)
    private Double lat;

    @Column(name = "buoy_lon", nullable = false)
    private Double lon;

    /**
     * 사람이 부표를 잡았다 (APP-08). 우선순위 4위 — 임팩트가 크고 구현이 쉽다.
     *
     * <p>⚠ 버튼이 안 눌려도 <b>부표 위치는 추정 위치로만 취급</b>한다(상세기획 E9) —
     * 이 값이 false 라고 사람이 없는 것이 아니다. 화면 문구가 그렇게 읽히면 안 된다.</p>
     */
    @Column(name = "is_pressed", nullable = false)
    private boolean pressed;

    /**
     * <b>부표 GPS 가 위치를 측정한 시각</b> (ERD 주석). 서버 수신 시각도, LoRa 수신 시각도 아니다.
     *
     * <p>지도에 찍을 때는 이 값을 쓴다 — LoRa 지연이나 큐 대기 때문에 발행 시각과
     * 몇 초씩 벌어진다({@code ref/mqtt.md} §3.4).</p>
     */
    @Id
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    /**
     * Pi 가 LoRa 로 받은 시각. {@code createdAt}(부표 GPS 측정 시각)과 <b>LoRa 지연만큼 벌어진다</b> —
     * 지도에는 측정 시각을 쓰고 이 값은 지연을 재는 데 쓴다 (V9).
     */
    @Column(name = "received_at")
    private Instant receivedAt;

    /** 수신 신호 세기. 두절이 가까워지는지 보는 단서 (V9) */
    @Column(name = "rssi")
    private Float rssi;

    // ── Persistable ─────────────────────────────────────────

    /**
     * <b>{@code save()} 가 {@code merge()} 로 빠지는 것을 막는다.</b> PK 가 이미 채워져 있으면
     * Spring Data 는 저장된 적 있는 행으로 보고 SELECT 후 INSERT 한다 — 쿼리가 두 배다.
     * <b>1행/초</b>라 이 테이블에서 손해가 가장 크다.
     */
    @Override
    public BuoyId getId() {
        return new BuoyId(buoyId, createdAt);
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
     * {@code (buoyId, createdAt)}. <b>record 를 쓸 수 없다</b> —
     * JPA 의 {@code @IdClass} 는 기본 생성자를 요구하는데 record 에는 없다.
     *
     * <p>필드 이름이 엔티티 쪽과 <b>글자까지 같아야</b> 매핑된다. 다르면 기동 때 터진다.</p>
     */
    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @EqualsAndHashCode
    public static class BuoyId implements Serializable {
        private UUID buoyId;
        private Instant createdAt;
    }
}

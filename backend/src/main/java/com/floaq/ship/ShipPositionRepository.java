package com.floaq.ship;

import com.floaq.ship.entity.ShipPosition;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** 사고 구간 선박 위치 (V11). 쓰기는 Pi 수신이 JDBC 로 하고, 여기는 읽기만 한다. */
public interface ShipPositionRepository
        extends JpaRepository<ShipPosition, ShipPosition.ShipPositionId> {

    /** 마지막으로 받은 배 위치. 상세 지도에 배를 그리는 근거다 */
    Optional<ShipPosition> findFirstByAccidentIdOrderByCreatedAtDesc(UUID accidentId);

    /**
     * 한 배가 <b>그 기간에</b> 보낸 위치. 측정 시각 오름차순.
     *
     * <p>사고 번호로 찾지 않는 이유는 {@code ship_position.accident_id} 가 거의 늘 비어 있기 때문이다 —
     * Pi 에 그 칸이 없고, 붙이는 규칙이 아직 합의 전이다. 그래서 <b>사고가 난 배</b>와
     * <b>감지부터 종결까지</b>로 고른다. 규칙이 서면 이 메서드만 바꾸면 된다.</p>
     *
     * <p>기간 양끝을 늘 채워 넘기므로 조건을 나눌 필요가 없다 — 부표 궤적에서 {@code after} 를
     * 별도 쿼리로 뺐던 것({@code could not determine data type of parameter})과 사정이 다르다.</p>
     */
    List<ShipPosition> findByShipIdAndCreatedAtBetweenOrderByCreatedAtAsc(
            UUID shipId, Instant from, Instant to, Pageable pageable);

    /** 같은 기간의 <b>가장 최근</b> N 개. 부표와 같은 이유다 — 오래된 순으로 자르면 지금 위치가 잘린다 */
    List<ShipPosition> findByShipIdAndCreatedAtBetweenOrderByCreatedAtDesc(
            UUID shipId, Instant from, Instant to, Pageable pageable);
}

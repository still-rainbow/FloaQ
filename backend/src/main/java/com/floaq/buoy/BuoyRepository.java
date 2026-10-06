package com.floaq.buoy;

import com.floaq.buoy.entity.Buoy;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface BuoyRepository extends JpaRepository<Buoy, Buoy.BuoyId> {

    /**
     * 궤적. {@code after} 로 이어 받는다 — 화면이 WS {@code BUOY_POS} 를 놓쳤을 때 메우는 용도다.
     *
     * <p><b>측정 시각 오름차순</b>이고 <b>실측만</b> 준다. 두절 구간의 추정 궤적을 섞으면
     * 어디까지가 실제로 받은 값인지 화면에서 사라진다(docs/api.md §3.4).</p>
     */
    List<Buoy> findByAccidentIdOrderByCreatedAtAsc(UUID accidentId, Pageable pageable);

    /**
     * ⚠ {@code after} 가 있을 때만 쓴다. <b>{@code :after IS NULL OR ...} 로 합치면 PostgreSQL 이
     * 파라미터 타입을 못 정해 거부한다</b>({@code could not determine data type of parameter}) —
     * 선택 조건은 쿼리를 나누거나 Criteria 로 붙인다.
     */
    List<Buoy> findByAccidentIdAndCreatedAtGreaterThanOrderByCreatedAtAsc(UUID accidentId, Instant after,
                                                                          Pageable pageable);

    /**
     * <b>가장 최근</b> N 개. 호출하는 쪽이 뒤집어 시간순으로 쓴다.
     *
     * <p>🔴 오래된 순으로 N 개를 자르면 <b>새 점이 잘린다</b> — 1초에 한 번 오는 부표는 한 시간이
     * 지나면 최신 위치가 영영 안 나와 지도에서 멈춘다(2026-09-21). 실시간 지도에서 필요한 것은
     * 처음 한 시간이 아니라 <b>지금</b>이다.</p>
     */
    List<Buoy> findByAccidentIdOrderByCreatedAtDesc(UUID accidentId, Pageable pageable);

    /** 마지막 실측 위치. <b>통신이 두절돼도 이 값은 남는다</b> — 그래서 상세의 buoy 가 null 이 아니다. */
    Optional<Buoy> findFirstByAccidentIdOrderByCreatedAtDesc(UUID accidentId);

    /** 사람이 부표를 잡은 첫 시각. 없으면 <b>"확인 안 됨"이지 "안 잡았다"가 아니다</b>(E9). */
    Optional<Buoy> findFirstByAccidentIdAndPressedTrueOrderByCreatedAtAsc(UUID accidentId);
}

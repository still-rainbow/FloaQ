package com.floaq.ship;

import com.floaq.ship.entity.Ship;
import com.floaq.ship.entity.ShipStatus;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

/**
 * 선박 등록 승인(W-05)과 사고 목록의 배 이름 조회(docs/api.md §3.4)를 같이 받는다.
 *
 * <p>{@code accident.ship_id} 를 연관관계로 두지 않아 사고를 읽어도 배가 따라오지 않는다.
 * 한 쪽 분량의 id 를 모아 {@code findAllById} 로 한 번에 읽는다 — 행마다 조회하면 N+1 이다.</p>
 */
public interface ShipRepository extends JpaRepository<Ship, UUID> {

    /** 선박 등록 목록 — 상태를 골랐을 때. 논리 삭제된 배는 뺀다 */
    Page<Ship> findByStatusAndDeletedFalse(ShipStatus status, Pageable pageable);

    /** 선박 등록 목록 — 상태를 안 골랐을 때. 반려까지 다 보여준다(계정과 달리 숨길 상태가 없다) */
    Page<Ship> findByDeletedFalse(Pageable pageable);

    /**
     * 등록 멱등. 자연키는 <b>어선 등록번호</b>이고 DB 의 부분 UNIQUE 와 같은 조건이다
     * ({@code uq_ship_registration_no}: {@code is_deleted = false AND status <> 'REJECTED'}).
     *
     * <p>반려된 행을 제외하는 것이 핵심이다 — 같은 배가 고쳐서 다시 신청할 수 있어야 한다.</p>
     */
    Optional<Ship> findByRegistrationNoAndDeletedFalseAndStatusNot(String registrationNo, ShipStatus status);

    /**
     * 선박 키로 선박을 찾는다. <b>요청마다 탄다</b> — {@code uq_ship_edge_key_hash} 인덱스가 받는다.
     *
     * <p>⚠ 승인 상태를 보지 않는다. {@code WAIT} 인 선박도 키로 자기 상태를 조회할 수 있어야 하기
     * 때문이다. <b>데이터 수신만</b> {@code ACTIVE} 를 요구한다(docs/api.md §4.3).</p>
     */
    Optional<Ship> findByPiKeyHashAndDeletedFalse(String piKeyHash);
}

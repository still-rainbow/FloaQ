package com.floaq.accident;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.Optional;
import java.util.UUID;

public interface AccidentRepository extends JpaRepository<Accident, UUID>, AccidentSearchRepository {

    /**
     * 범위 안에서만 찾는다. <b>범위 밖은 빈 값으로 돌려 404 가 되게 한다</b> —
     * 403 이면 "그런 사고가 있다"를 알려주는 셈이다(docs/api.md §3.4).
     */
    Optional<Accident> findByAccidentIdAndStatusIn(UUID accidentId, Collection<AccidentStatus> visible);

    /**
     * 이 배에 아직 안 끝난 사고가 있나. 선박 삭제를 막는 근거다 —
     * 사고 중인 배를 목록에서 지우면 관제가 그 사고를 못 찾는다(api.md §3.3).
     */
    boolean existsByShipIdAndStatusIn(UUID shipId, Collection<AccidentStatus> statuses);
}

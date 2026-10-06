package com.floaq.accident;

import com.floaq.accident.entity.AccidentState;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface AccidentStateRepository
        extends JpaRepository<AccidentState, AccidentState.AccidentStateId> {

    /** 타임라인은 시각 오름차순이다 — 사람이 위에서 아래로 읽는 순서와 같게. */
    List<AccidentState> findByAccidentIdOrderByCreatedAtAsc(UUID accidentId);
}

package com.floaq.ocean;

import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.entity.OceanSnapshot;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** ocean_snapshot upsert·조회. 소스당 1행이라 findById + save 가 곧 upsert */
@Service
@RequiredArgsConstructor
public class OceanSnapshotService {

    private final OceanSnapshotRepository repository;

    /** 실패·데이터없음이면 시도 결과만 갱신 — payload 는 보존(§9.10) */
    @Transactional
    public void record(String source, CollectOutcome outcome, Instant fetchedAt) {
        OceanSnapshot snapshot = repository.findById(source).orElseGet(() -> OceanSnapshot.of(source));
        if (outcome.isSuccess()) {
            snapshot.succeed(outcome.observedAt(), outcome.payload(), fetchedAt,
                    outcome.resultCode(), outcome.resultMsg());
        } else {
            snapshot.attempt(fetchedAt, outcome.resultCode(), outcome.resultMsg());
        }
        repository.save(snapshot);
    }

    @Transactional(readOnly = true)
    public List<OceanSnapshot> findAll() {
        return repository.findAll();
    }

    /** 다른 소스 수집 결과를 참조할 때 (기상특보 → 특보구역 계층) */
    @Transactional(readOnly = true)
    public Optional<OceanSnapshot> find(String source) {
        return repository.findById(source);
    }
}

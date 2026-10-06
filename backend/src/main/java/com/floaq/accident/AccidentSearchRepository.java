package com.floaq.accident;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;

import java.time.Instant;
import java.util.Collection;
import java.util.UUID;

/**
 * 사고 목록 검색. <b>{@code @Query} 로 쓰지 않는 이유가 둘 있다.</b>
 *
 * <p>① <b>선택 조건을 {@code :param IS NULL OR ...} 로 쓰면 PostgreSQL 이 터진다</b> —
 * {@code could not determine data type of parameter}. 파라미터가 {@code IS NULL} 에서만 쓰이면
 * 드라이버가 타입을 정할 수 없다. 조건을 <b>있을 때만 붙이는</b> 것이 맞는 해법이다.</p>
 *
 * <p>② 정렬이 {@code CASE WHEN status = REPORT THEN 0 ELSE 1} 이라 {@code Sort} 로 표현되지 않는다.
 * Criteria 의 {@code selectCase} 는 그걸 그대로 쓴다.</p>
 */
public interface AccidentSearchRepository {

    Page<Accident> search(Collection<AccidentStatus> visible,
                          Collection<AccidentStatus> statuses,
                          UUID shipId,
                          Instant from,
                          Instant to,
                          Pageable pageable);
}

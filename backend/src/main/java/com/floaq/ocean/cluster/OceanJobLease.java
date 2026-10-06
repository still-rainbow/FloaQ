package com.floaq.ocean.cluster;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.Duration;

/**
 * 수집 작업의 주기 · 리스 (ocean_job).
 *
 * 한 UPDATE 로 "주기가 됐고 아무도 안 잡았다"를 확인하며 잡는다 — 인스턴스 둘이 같은 틱에 와도 한쪽만 1행을 바꾼다.
 * 시각 비교는 DB now() 로 한다. 인스턴스 시계가 서로 어긋나도 판정이 한 시계를 본다.
 *
 * 기각: PostgreSQL advisory lock — 세션에 묶여 커넥션 풀과 어긋난다(잡은 커넥션을 풀에 돌려주면 락이 남는다).
 */
@Repository
@RequiredArgsConstructor
public class OceanJobLease {

    private final JdbcTemplate jdbc;
    private final InstanceId instance;

    /**
     * @param intervalSec 마지막 시작 뒤 이만큼 지나야 다시 잡는다
     * @param lease       잡은 인스턴스가 죽어도 이만큼 뒤에는 풀린다
     * @return 잡았으면 true — 호출부가 끝나면 {@link #finish} 한다
     */
    public boolean tryStart(String job, int intervalSec, Duration lease) {
        jdbc.update("INSERT INTO ocean_job (name) VALUES (?) ON CONFLICT (name) DO NOTHING", job);
        return jdbc.update("""
                UPDATE ocean_job
                SET lease_owner = ?, lease_until = now() + ?::float8 * interval '1 second', last_started_at = now()
                WHERE name = ?
                  AND (lease_until IS NULL OR lease_until < now())
                  AND (last_started_at IS NULL OR last_started_at <= now() - ?::float8 * interval '1 second')
                """, instance.value(), lease.toSeconds(), job, intervalSec) == 1;
    }

    /** 내가 잡은 것만 푼다 — 리스가 만료돼 다른 인스턴스가 잡은 뒤라면 그쪽 것을 풀지 않는다 */
    public void finish(String job) {
        jdbc.update("""
                UPDATE ocean_job
                SET lease_owner = NULL, lease_until = NULL, last_finished_at = now()
                WHERE name = ? AND lease_owner = ?
                """, job, instance.value());
    }
}

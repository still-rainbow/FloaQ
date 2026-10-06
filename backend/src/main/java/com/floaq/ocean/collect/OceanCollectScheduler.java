package com.floaq.ocean.collect;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.cluster.OceanJobLease;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * 수집 틱. 소스별 intervalSec 이 실제 주기를 정한다.
 *
 * 전역 크론 1개 기각 — 주기가 10분(기상특보)~24시간(해파리)로 갈려 하나로 못 맞춤.
 * 크론은 "언제 확인하나"만 정하고 "언제 부르나"는 소스가 정함.
 *
 * 여러 인스턴스 (2026-09-15) — "마지막으로 언제 불렀나"와 "누가 부르는 중인가"를 DB(ocean_job)에 둔다.
 * 틱은 인스턴스마다 돌지만 소스 하나는 한 인스턴스만 잡는다. 재기동해도 주기가 이어진다 —
 * 메모리에 두던 때는 재기동마다 전 소스가 즉시 불렸고, 인스턴스를 늘리면 호출이 그 배수였다.
 *   기각: Redis 락 — 락과 데이터가 다른 저장소 · ShedLock — 의존성 추가인데 주기 판단은 여전히 따로 필요
 *
 * ROMS 타일의 조회 즉시 수집은 여기를 거치지 않는다(RomsTileService) — 타일마다 DB 리스를 따로 잡는다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OceanCollectScheduler {

    /**
     * 소스 작업 리스. 인스턴스가 수집 도중 죽으면 그 소스는 최대 이만큼 멈춘다.
     * 30분 근거: 가장 긴 1회가 ROMS 활성 타일 갱신 — 타일당 약 24페이지 × 0.22초 ≈ 5초(추정)라 타일 수백 개를 덮는다.
     *
     * <p>⚠ <b>전국 소해구(2026-09-17)가 이 값의 성격을 바꿨다.</b> 그 소스는 주기가 60초인데
     * 1회가 약 39초다. 인스턴스가 그 39초 안에 죽으면 <b>30분을 쉰다</b> — 전국 한 바퀴가
     * 34분인데 그만큼을 더 기다린다는 뜻이다. 실제로 겪었다(2026-09-17 강제 종료 후 재기동).</p>
     *
     * <p>지금은 고치지 않는다. 소스마다 리스를 다르게 주면 "왜 이 소스만 빨리 풀리나"가
     * 새 질문이 되고, <b>배포 중 재기동은 하루 몇 번뿐</b>이라 실제로 물릴 확률이 낮다.
     * 걸리면 {@code ocean_job} 의 {@code lease_until} 을 지우면 바로 풀린다.
     * 자주 겪으면 그때 소스별 리스(1회 소요의 몇 배)로 올린다.</p>
     */
    static final Duration JOB_LEASE = Duration.ofMinutes(30);

    private final OceanApiProperties props;
    private final List<OceanCollector> collectors;
    private final OceanSnapshotService snapshots;
    private final OceanJobLease leases;

    /** 부표 두절 판정과 스레드 분리 (§1.4 — 외부 지연이 오판정을 만들면 곧 오경보) */
    @Scheduled(cron = "${app.ocean.collect-cron}", scheduler = "collectTaskScheduler")
    public void tick() {
        for (OceanCollector collector : collectors) {
            String name = collector.source();
            Source config = props.sources().get(name);
            if (config == null) {
                // 수집기는 있는데 설정이 없음. 소스 이름 오타의 유일한 단서
                log.warn("[ocean] {} — app.ocean.sources 에 설정 없음", name);
                continue;
            }
            if (!config.enabled() || !start(name, config)) {
                continue;
            }
            try {
                collectOnce(collector, config, name);
            } finally {
                finish(name);
            }
        }
    }

    private boolean start(String name, Source config) {
        try {
            return leases.tryStart(name, config.intervalSec(), JOB_LEASE);
        } catch (RuntimeException e) {
            // DB 가 안 되면 누가 부르는지 모른다 — 부르지 않는다. 인스턴스 수만큼 쿼터를 태우는 것보다 낫다
            log.warn("[ocean] {} — 작업 리스 확인 실패, 건너뛴다: {}", name, e.toString());
            return false;
        }
    }

    private void finish(String name) {
        try {
            leases.finish(name);
        } catch (RuntimeException e) {
            // 못 풀어도 리스가 만료되면 풀린다. 그동안 이 소스가 멈출 뿐 중복 호출은 없다
            log.warn("[ocean] {} — 작업 리스 해제 실패 (만료 {}분 뒤 풀림): {}", name, JOB_LEASE.toMinutes(), e.toString());
        }
    }

    private void collectOnce(OceanCollector collector, Source config, String name) {
        String key = props.keyFor(config);
        if (key == null || key.isBlank()) {
            // 호출하면 401. 쿼터만 태우고 원인은 응답에 안 나옴
            snapshots.record(name, new CollectOutcome("NO_KEY", "인증키 없음", null, null), Instant.now());
            return;
        }
        try {
            CollectOutcome outcome = collector.collect(config, key);
            snapshots.record(name, outcome, Instant.now());
        } catch (Exception e) {
            // 수집기 버그가 다른 소스 수집까지 멈추면 안 됨
            log.error("[ocean] {} 수집기 예외", name, e);
            snapshots.record(name, new CollectOutcome("ERROR", e.getClass().getSimpleName(), null, null),
                    Instant.now());
        }
    }
}

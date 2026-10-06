package com.floaq.global.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

/**
 * 스케줄러.
 *
 * <p><b>부표 두절 판정을 다른 배치와 분리한다 (계획.md §1.4).</b>
 * 공공데이터 수집이 외부 지연으로 길어지면 기본 스케줄러에서는 두절 판정이 뒤로 밀리고,
 * <b>멀쩡한 부표가 두절로 판정된다 — 오판정이 곧 오경보다.</b>
 * 스레드 하나를 더 쓰는 값으로 그 경로를 없앤다.</p>
 *
 * <p>⚠ 부표 두절 판정은 인메모리 스케줄이라 <b>단일 인스턴스 전제</b>다. 다중화하면 같은 판정이 인스턴스 수만큼
 * 중복 실행된다 — 그때는 분산 락이나 리더 선출이 필요하다.
 * 해양 수집은 DB 리스(ocean_job · ocean_roms_tile)로 인스턴스가 여럿이어도 한 번만 부른다(2026-09-15).</p>
 */
@Configuration
@EnableScheduling
public class SchedulingConfig {

    /** 부표 두절 판정 전용. 다른 작업을 여기 얹지 않는다. */
    @Bean
    public TaskScheduler buoyTaskScheduler() {
        return pool(1, "buoy-watch-");
    }

    /**
     * 공공데이터 수집·LLM 요약 사전 생성. 외부 호출이라 느려질 수 있다.
     *
     * 4 근거: 수집 틱 1 · 요약 1 · 조회가 부른 ROMS 타일 즉시 수집 2(RomsTileService).
     * 틱이 긴 타일 갱신을 도는 동안에도 새 바다로 들어간 배의 타일이 막히지 않게.
     */
    @Bean
    public TaskScheduler collectTaskScheduler() {
        return pool(4, "collect-");
    }

    private TaskScheduler pool(int size, String prefix) {
        ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(size);
        scheduler.setThreadNamePrefix(prefix);
        scheduler.setRemoveOnCancelPolicy(true);
        // 종료 시 진행 중인 작업을 기다린다. SIGKILL 되면 수집 도중 값이 반쪽으로 남는다
        scheduler.setWaitForTasksToCompleteOnShutdown(true);
        scheduler.setAwaitTerminationSeconds(10);
        return scheduler;
    }
}

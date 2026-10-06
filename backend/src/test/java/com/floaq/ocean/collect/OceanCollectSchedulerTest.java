package com.floaq.ocean.collect;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.cluster.OceanJobLease;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 수집 틱 — 소스 하나는 DB 리스를 잡은 인스턴스만 부른다.
 *
 * 틀리면 인스턴스 수만큼 같은 소스를 불러 쿼터가 그 배수로 나간다.
 */
class OceanCollectSchedulerTest {

    private static Source source(boolean enabled) {
        return new Source(Provider.DATA_GO_KR, "https://example.invalid", null, Kind.FORECAST,
                null, 0, 3600, 0, enabled);
    }

    private final OceanSnapshotService snapshots = mock(OceanSnapshotService.class);
    private final OceanJobLease leases = mock(OceanJobLease.class);
    private final OceanCollector roms = mock(OceanCollector.class);
    private final OceanCollector warning = mock(OceanCollector.class);

    private static final CollectOutcome OK = new CollectOutcome("00", null, Instant.now(), Map.of("activeTiles", 1));

    @BeforeEach
    void setUp() {
        when(roms.source()).thenReturn("roms");
        when(roms.collect(any(), any())).thenReturn(OK);
        when(warning.source()).thenReturn("weather-warning");
        when(warning.collect(any(), any())).thenReturn(OK);
    }

    private OceanCollectScheduler scheduler(boolean romsEnabled) {
        var props = new OceanApiProperties("0 * * * * *", null,
                Map.of(Provider.DATA_GO_KR, "test-key"),
                Map.of("roms", source(romsEnabled), "weather-warning", source(true)));
        return new OceanCollectScheduler(props, List.of(roms, warning), snapshots, leases);
    }

    @Test
    void 리스를_잡은_소스만_부르고_끝나면_푼다() {
        // 다른 인스턴스가 기상특보를 잡고 있다
        when(leases.tryStart(eq("roms"), anyInt(), any())).thenReturn(true);
        when(leases.tryStart(eq("weather-warning"), anyInt(), any())).thenReturn(false);

        scheduler(true).tick();

        verify(roms).collect(any(), eq("test-key"));
        verify(warning, never()).collect(any(), any());
        verify(snapshots).record(eq("roms"), eq(OK), any());
        verify(leases).finish("roms");
        verify(leases, never()).finish("weather-warning");
    }

    @Test
    void 주기는_소스_설정으로_리스에_넘긴다() {
        // 마지막 시작 시각이 DB 에 있어 재기동해도 주기가 이어진다 — 메모리일 때는 재기동마다 전 소스가 즉시 불렸다
        scheduler(true).tick();

        verify(leases).tryStart("roms", 3600, OceanCollectScheduler.JOB_LEASE);
    }

    @Test
    void 꺼진_소스는_리스도_묻지_않는다() {
        scheduler(false).tick();

        verify(leases, never()).tryStart(eq("roms"), anyInt(), any());
        verify(roms, never()).collect(any(), any());
    }

    @Test
    void 수집기가_던져도_실패로_남기고_리스를_푼다() {
        when(leases.tryStart(anyString(), anyInt(), any())).thenReturn(true);
        when(roms.collect(any(), any())).thenThrow(new IllegalStateException("버그"));

        scheduler(true).tick();

        verify(snapshots).record(eq("roms"), argThat(o -> "ERROR".equals(o.resultCode())), any());
        verify(leases).finish("roms");
        // 한 수집기 버그가 뒤 소스를 막지 않는다
        verify(warning).collect(any(), any());
    }

    @Test
    void 리스를_확인하지_못하면_부르지_않는다() {
        // DB 가 안 되면 누가 부르는지 모른다. 인스턴스 수만큼 부르는 것보다 안 부르는 쪽
        when(leases.tryStart(anyString(), anyInt(), any())).thenThrow(new IllegalStateException("DB 끊김"));

        scheduler(true).tick();

        verify(roms, never()).collect(any(), any());
        verify(warning, never()).collect(any(), any());
    }
}

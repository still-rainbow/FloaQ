package com.floaq.ocean.roms;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import org.junit.jupiter.api.Test;
import org.springframework.scheduling.TaskScheduler;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 조회 쪽 타일 판단 — "본선 근처 값을 갖고 있나"와 "받게 하기".
 */
class RomsTileServiceTest {

    private final RomsTileStore tiles = mock(RomsTileStore.class);
    private final OceanRomsStore store = mock(OceanRomsStore.class);
    private final RomsCollector collector = mock(RomsCollector.class);
    private final TaskScheduler executor = mock(TaskScheduler.class);

    private static OceanApiProperties props(boolean romsEnabled) {
        var roms = new Source(Provider.DATA_GO_KR, "https://example.invalid", null, Kind.FORECAST,
                null, 0, 3600, 0, romsEnabled);
        return new OceanApiProperties("0 * * * * *", null, Map.of(Provider.DATA_GO_KR, "test-key"), Map.of("roms", roms));
    }

    private RomsTileService service(boolean romsEnabled) {
        return new RomsTileService(tiles, store, collector, props(romsEnabled), executor);
    }

    @Test
    void 본선_이웃이_걸치는_타일을_전부_받아야_안이다() {
        // 35.24 ± 한 칸(0.0286°)이 35.25 경계를 넘는다 — 남쪽 타일만 받았으면 북쪽 이웃이 없다
        when(store.lattice()).thenReturn(new RomsLattice(35.0, 129.0, 0.0286, 0.032));
        var south = new RomsTile(140, 516);
        var north = new RomsTile(141, 516);

        when(tiles.collectedAmong(anyList())).thenReturn(Set.of(south));
        assertThat(service(true).covers(35.24, 129.1)).isFalse();

        when(tiles.collectedAmong(anyList())).thenReturn(Set.of(south, north));
        assertThat(service(true).covers(35.24, 129.1)).isTrue();
    }

    @Test
    void 재현_받은_타일이_없으면_가까운_격자가_있어도_밖이다() {
        // 2026-09-15: 옛 해역 가장자리 3.9km 격자를 OK 로 줘 화면이 엉뚱한 칸을 그렸다. 거리로 판정하지 않는다
        when(tiles.collectedAmong(anyList())).thenReturn(Set.of());

        assertThat(service(true).covers(35.1992, 129.267)).isFalse();
    }

    @Test
    void 격자_간격을_모르면_기본_한_칸_폭으로_본다() {
        when(store.lattice()).thenReturn(null);

        service(true).covers(35.125, 129.125);

        verify(tiles).collectedAmong(List.of(new RomsTile(140, 516)));
    }

    @Test
    void 요청은_주변_타일에_관심을_찍고_수집을_넘긴다() {
        // 다른 스레드로 넘기는 대신 그 자리에서 돌린다 — 무엇이 불렸는지만 본다
        when(executor.schedule(any(Runnable.class), any(Instant.class))).thenAnswer(inv -> {
            inv.<Runnable>getArgument(0).run();
            return null;
        });

        assertThat(service(true).request(35.125, 129.125)).isTrue();

        verify(tiles).touch(List.of(new RomsTile(140, 516)));
        verify(collector).collectTile(any(), eq("test-key"), eq(new RomsTile(140, 516)));
    }

    @Test
    void 넘긴_타일은_끝나기_전에는_다시_넘기지_않는다() {
        // 수집 스레드가 아직 안 돌렸다. 60초 폴링마다 같은 작업이 큐에 쌓이지 않게 — 관심 시각은 매번 찍는다
        var s = service(true);

        s.request(35.125, 129.125);
        s.request(35.125, 129.125);

        verify(executor, times(1)).schedule(any(Runnable.class), any(Instant.class));
        verify(tiles, times(2)).touch(anyList());
    }

    @Test
    void 수집이_꺼져_있으면_관심도_찍지_않는다() {
        // 찍어 두면 켜는 순간 하루치 활성 타일을 한꺼번에 받는다.
        // false 를 돌려줘야 조회가 "받는 중"이 아니라 503(사람이 봐야 함)으로 답한다
        assertThat(service(false).request(35.125, 129.125)).isFalse();

        verifyNoInteractions(tiles, executor, collector);
    }
}

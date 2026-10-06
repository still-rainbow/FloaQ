package com.floaq.ocean.summary;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.entity.OceanSnapshot;
import com.floaq.ocean.zone.OceanZoneStore;
import com.floaq.ocean.zone.ZoneLevel;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 크레딧이 새는 길은 하나다 — <b>조회가 LLM 을 부르는 것</b>.
 *
 * 키오스크가 이 API 를 60초마다 친다. 여기가 조용히 풀리면 크레딧이
 * 클라이언트 수 × 폴링 주기로 나가고, 화면은 똑같아 보여서 아무도 모른다.
 */
class OceanSummaryServiceTest {

    /** 부산 앞 — application.yml 기본 위치와 같은 자리 */
    private static final double LAT = 35.05;
    private static final double LON = 129.10;

    private OceanSnapshotService snapshots;
    private OceanSummaryWriter writer;
    private OceanZoneStore zones;

    private static OceanSnapshot snap(String source, Map<String, Object> payload) {
        var s = OceanSnapshot.of(source);
        s.succeed(Instant.parse("2026-09-18T08:00:00Z"), payload, Instant.now(), "00", null);
        return s;
    }

    private OceanSummaryService service(boolean llmEnabled) {
        var props = mock(OceanApiProperties.class);
        when(props.coverage()).thenReturn(new Coverage(LAT, LON, 30));
        return new OceanSummaryService(snapshots, writer, props, zones, llmEnabled);
    }

    @BeforeEach
    void setUp() {
        snapshots = mock(OceanSnapshotService.class);
        when(snapshots.findAll()).thenReturn(List.of(
                snap("weather-warning", Map.of("activeMarineWarnings", List.of()))));
        writer = mock(OceanSummaryWriter.class);
        when(writer.mock(anyList())).thenAnswer(i -> new OceanSummary(
                "목", "목 문장", i.getArgument(0), Instant.now(), "mock", true));
        when(writer.generate(anyList())).thenAnswer(i -> new OceanSummary(
                "요약", "생성된 문장", i.getArgument(0), Instant.now(), "gpt-4o-mini", false));
        zones = mock(OceanZoneStore.class);
        when(zones.cellNow(any(ZoneLevel.class), anyDouble(), anyDouble(), any(Instant.class)))
                .thenReturn(Optional.empty());
    }

    @Test
    void 조회는_몇_번을_해도_LLM_을_부르지_않는다() {
        var service = service(true);

        for (int i = 0; i < 50; i++) {
            service.current(LAT, LON);
        }

        verify(writer, never()).generate(anyList());
    }

    @Test
    void 틱이_연달아_돌아도_30분에_한_번만_부른다() {
        var service = service(true);

        service.tick();
        service.tick();
        service.tick();

        verify(writer, times(1)).generate(anyList());
    }

    @Test
    void 배가_같은_바다에_있으면_만들어_둔_문장을_준다() {
        var service = service(true);
        service.tick();

        // 0.02° ≈ 2km — SAME_SEA_KM(15km) 안이다
        var s = service.current(LAT + 0.02, LON);

        assertThat(s.mock()).isFalse();
        assertThat(s.headline()).isEqualTo("요약");
    }

    @Test
    void 다른_바다에서_조회하면_남의_문장_대신_그_자리_목을_준다() {
        var service = service(true);
        service.tick();

        // 1.0° ≈ 111km — 같은 바다가 아니다
        var s = service.current(LAT + 1.0, LON);

        assertThat(s.mock()).isTrue();
        assertThat(s.shipBased()).isTrue();
        assertThat(s.lat()).isEqualTo(LAT + 1.0);
        // 여기서 새로 만들면 조회가 LLM 을 부르는 길이 열린다
        verify(writer, times(1)).generate(anyList());
    }

    @Test
    void 좌표_없이_조회하면_기본_위치_기준임을_밝힌다() {
        var s = service(false).current(null, null);

        assertThat(s.shipBased()).isFalse();
        assertThat(s.lat()).isEqualTo(LAT);
    }

    @Test
    void LLM_이_꺼져_있으면_틱도_부르지_않는다() {
        var service = service(false);

        service.tick();

        verify(writer, never()).generate(anyList());
        verify(writer).mock(anyList());
    }
}

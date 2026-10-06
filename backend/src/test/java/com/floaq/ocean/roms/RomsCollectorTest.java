package com.floaq.ocean.roms;

import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.cluster.InstanceId;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * ROMS 타일 수집 — 매시 새 예측본 확인 + 활성 타일 갱신, 타일마다 DB 리스.
 *
 * 틀리면 둘 중 하나다 — 같은 예측본을 계속 다시 받거나(쿼터), 새 예측본을 하루 동안 놓친다.
 */
class RomsCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final DateTimeFormatter KST = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
            .withZone(ZoneId.of("Asia/Seoul"));
    private static final Source SOURCE = new Source(Provider.DATA_GO_KR, "https://example.invalid", null,
            Kind.FORECAST, null, 0, 3600, 0, true);

    /** 지금 이후 첫 정시 — 보관 기간 안 */
    private static final Instant NEXT_HOUR = Instant.now().truncatedTo(ChronoUnit.HOURS).plus(1, ChronoUnit.HOURS);

    /** 35.0~35.25 · 129.0~129.25 */
    private static final RomsTile TILE = new RomsTile(140, 516);
    private static final RomsTile OTHER = new RomsTile(141, 516);

    private final OceanApiClient client = mock(OceanApiClient.class);
    private final OceanRomsStore store = mock(OceanRomsStore.class);
    private final RomsTileStore tiles = mock(RomsTileStore.class);
    private final InstanceId instance = mock(InstanceId.class);
    private RomsCollector collector;

    @BeforeEach
    void setUp() {
        collector = new RomsCollector(client, store, tiles, instance);
        when(instance.value()).thenReturn("me");
        when(tiles.generation()).thenReturn(3L);
        when(tiles.stats(any())).thenReturn(new RomsTileStore.Stats(1, 1));
        when(tiles.probeCandidate(anyLong(), any())).thenReturn(Optional.empty());
        when(store.replaceTile(any(), any(), any())).thenReturn(2);
        when(store.latestBaseAt()).thenReturn(Optional.of(NEXT_HOUR));
    }

    /** 한 페이지로 끝나는 응답 (totalCount 2) */
    private static OceanResponse page(double lat, double crsp) {
        String t = KST.format(NEXT_HOUR);
        var body = MAPPER.readTree("""
                {"items":{"item":[
                  {"predcDt":"%s","lat":%s,"lot":129.1,"crdir":212.3,"crsp":%s,"wtem":24.1},
                  {"predcDt":"%s","lat":%s,"lot":129.13,"crdir":200.0,"crsp":0.30,"wtem":24.0}]},
                 "totalCount":2}
                """.formatted(t, lat, crsp, t, lat));
        return new OceanResponse(200, OceanResponse.OK, null, body);
    }

    /** 저장소가 돌려줄 행 — real 컬럼을 거친 값 */
    private static List<RomsGrid> storedOf(double crsp) {
        return List.of(
                new RomsGrid(NEXT_HOUR, 35.1, 129.1, (double) (float) 212.3, (double) (float) crsp, (double) (float) 24.1),
                new RomsGrid(NEXT_HOUR, 35.1, 129.13, (double) (float) 200.0, (double) (float) 0.30, (double) (float) 24.0));
    }

    // ── 타일 하나 ──

    @Test
    void 리스를_못_잡으면_부르지_않는다() {
        // 다른 인스턴스가 받는 중 · 이미 최신 · 방금 실패 — 전부 호출 0
        when(tiles.claim(any(), anyLong(), any(), any(), any(), any())).thenReturn(false);

        assertThat(collector.collectTile(SOURCE, "key", TILE)).isNull();
        verifyNoInteractions(client);
    }

    @Test
    void 받으면_그_타일만_교체하고_받은_세대를_남긴다() {
        when(tiles.claim(eq(TILE), eq(3L), eq("me"), any(), any(), any())).thenReturn(true);
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.1, 0.44));

        var outcome = collector.collectTile(SOURCE, "key", TILE);

        assertThat(outcome.isSuccess()).isTrue();
        verify(store).replaceTile(eq(TILE), any(), any());
        verify(tiles).succeed(TILE, "me", 3L, OceanResponse.OK);
    }

    @SuppressWarnings("unchecked")
    @Test
    void 요청_범위는_타일_경계다() {
        when(tiles.claim(any(), anyLong(), any(), any(), any(), any())).thenReturn(true);
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.1, 0.44));

        collector.collectTile(SOURCE, "key", TILE);

        ArgumentCaptor<Map<String, String>> params = ArgumentCaptor.forClass(Map.class);
        verify(client).get(anyString(), any(), anyString(), params.capture());
        assertThat(params.getValue())
                .containsEntry("ymin", "35.0000").containsEntry("ymax", "35.2500")
                .containsEntry("xmin", "129.0000").containsEntry("xmax", "129.2500");
    }

    @Test
    void 페이지가_실패하면_교체하지_않고_실패로_남긴다() {
        // 반쪽 격자는 "그 방향에 데이터 없음"으로 오독된다. 옛 예측본을 그대로 둔다
        when(tiles.claim(any(), anyLong(), any(), any(), any(), any())).thenReturn(true);
        when(client.get(anyString(), any(), anyString(), any()))
                .thenReturn(new OceanResponse(200, "22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", null));

        var outcome = collector.collectTile(SOURCE, "key", TILE);

        assertThat(outcome.isSuccess()).isFalse();
        verify(store, never()).replaceTile(any(), any(), any());
        verify(tiles).fail(eq(TILE), eq("me"), eq("22"), any());
        verify(tiles, never()).succeed(any(), any(), anyLong(), any());
    }

    @Test
    void 바다가_없는_타일도_받은_것으로_친다() {
        // 안 치면 매 조회가 같은 육지 타일을 다시 부른다
        when(tiles.claim(any(), anyLong(), any(), any(), any(), any())).thenReturn(true);
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.1, 0.44));
        when(store.replaceTile(any(), any(), any())).thenReturn(0);

        var outcome = collector.collectTile(SOURCE, "key", TILE);

        assertThat(outcome.resultCode()).isEqualTo(OceanResponse.NO_DATA);
        verify(tiles).succeed(TILE, "me", 3L, OceanResponse.NO_DATA);
    }

    // ── 매시 확인 ──

    @Test
    void 확인_타일_값이_같으면_세대를_올리지_않는다() {
        when(tiles.probeCandidate(eq(3L), any())).thenReturn(Optional.of(TILE));
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.1, 0.44));
        when(store.storedLike(any())).thenReturn(storedOf(0.44));

        var outcome = collector.collect(SOURCE, "key");

        assertThat(outcome.isSuccess()).isTrue();
        verify(tiles, never()).advanceGeneration(anyLong());
        verify(client, times(1)).get(anyString(), any(), anyString(), any());
    }

    @Test
    void 확인_타일_값이_다르면_세대를_올린다() {
        when(tiles.probeCandidate(eq(3L), any())).thenReturn(Optional.of(TILE));
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.1, 0.44));
        when(store.storedLike(any())).thenReturn(storedOf(0.50));

        collector.collect(SOURCE, "key");

        verify(tiles).advanceGeneration(3L);
    }

    @Test
    void 확인_1페이지에_이_타일_격자가_없으면_판정하지_않는다() {
        // 35.3 은 이 타일 북쪽 밖이다. 비교할 행이 없는 것을 "다르다"로 읽으면 매시 세대를 올려 전부 다시 받는다
        when(tiles.probeCandidate(eq(3L), any())).thenReturn(Optional.of(TILE));
        when(client.get(anyString(), any(), anyString(), any())).thenReturn(page(35.3, 0.44));

        collector.collect(SOURCE, "key");

        verify(store, never()).storedLike(any());
        verify(tiles, never()).advanceGeneration(anyLong());
    }

    @Test
    void 확인이_실패하면_갱신하지_않고_실패로_남긴다() {
        when(tiles.probeCandidate(eq(3L), any())).thenReturn(Optional.of(TILE));
        when(client.get(anyString(), any(), anyString(), any()))
                .thenReturn(new OceanResponse(200, "22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", null));

        var outcome = collector.collect(SOURCE, "key");

        assertThat(outcome.isSuccess()).isFalse();
        assertThat(outcome.resultCode()).isEqualTo("22");
        verify(tiles, never()).dueForRefresh(anyLong(), any(), any());
    }

    // ── 활성 타일 갱신 ──

    @Test
    void 예산이_떨어지면_남은_타일을_부르지_않는다() {
        when(tiles.dueForRefresh(anyLong(), any(), any())).thenReturn(List.of(TILE, OTHER));
        when(tiles.claim(any(), anyLong(), any(), any(), any(), any())).thenReturn(true);
        when(client.get(anyString(), any(), anyString(), any()))
                .thenReturn(new OceanResponse(0, OceanResponse.QUOTA_GUARD, "하루 호출 예산 소진", null));

        var outcome = collector.collect(SOURCE, "key");

        verify(client, times(1)).get(anyString(), any(), anyString(), any());
        assertThat(outcome.resultCode()).isEqualTo(OceanResponse.QUOTA_GUARD);
        // 받은 타일 현황은 남긴다 — 실패는 결과 코드로 드러낸다
        assertThat(outcome.payload()).containsEntry("failedTiles", 1).containsEntry("activeTiles", 1);
    }

    @Test
    void 받을_타일이_없으면_호출하지_않는다() {
        when(tiles.dueForRefresh(anyLong(), any(), any())).thenReturn(List.of());

        var outcome = collector.collect(SOURCE, "key");

        assertThat(outcome.isSuccess()).isTrue();
        verifyNoInteractions(client);
    }
}

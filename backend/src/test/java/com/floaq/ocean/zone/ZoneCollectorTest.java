package com.floaq.ocean.zone;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.roms.RomsTile;
import com.floaq.ocean.roms.RomsTileStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 해구별 예측 수집. 발표는 하루 2회인데 매시 확인한다 — 이미 받았으면 호출하지 않아야 쿼터가 산다.
 */
class ZoneCollectorTest {

    private static final Source CONFIG = new Source(Provider.KMA_APIHUB, "https://example.invalid", null,
            Kind.FORECAST, null, 0, 3600, 1000, true);
    private static final String NOT_READY =
            "파일이 존재하지 않습니다. (/C5N_DATA/GID/MRZ/202609/14/marine_wave_kim_rww3_h075_2026091412.txt)\n"
                    + "호출한 변수(생산시각, 요청시각 등)에 대응하는 자료가 없습니다.";
    private static final Coverage BUSAN = new Coverage(35.05, 129.05, 30);

    private final OceanApiClient client = mock(OceanApiClient.class);
    private final OceanZoneStore store = mock(OceanZoneStore.class);
    private final RomsTileStore tiles = mock(RomsTileStore.class);

    /** 요청 파라미터를 되돌려 한 줄짜리 발표본을 만든다 */
    private static String body(Map<String, String> p, boolean small) {
        return "#START7777\n" + p.get("tma_fc") + " " + p.get("tma_ef") + " 92 " + (small ? "1 " : "")
                + "35.0 129.0 35.5 129.0 35.5 129.5 35.0 129.5 0.6 4.1 53.8 6.6 39.6"
                + (small ? " 20000.0 0.0 26.3 1" : "") + "\n#7777END\n";
    }

    private static Instant latest() {
        return ZoneCollector.latestIssuance(Instant.now());
    }

    @Test
    void 발표시각은_00_12UTC_로_내린다() {
        assertThat(ZoneCollector.latestIssuance(Instant.parse("2026-09-14T11:59:59Z")))
                .isEqualTo(Instant.parse("2026-09-14T00:00:00Z"));
        assertThat(ZoneCollector.latestIssuance(Instant.parse("2026-09-14T12:00:00Z")))
                .isEqualTo(Instant.parse("2026-09-14T12:00:00Z"));
        assertThat(ZoneCollector.latestIssuance(Instant.parse("2026-09-14T23:59:00Z")))
                .isEqualTo(Instant.parse("2026-09-14T12:00:00Z"));
    }

    @Test
    void 요청_시각_형식은_UTC_yyyymmddhh() {
        assertThat(ZoneCollector.tma(Instant.parse("2026-09-17T03:00:00Z"))).isEqualTo("2026091703");
    }

    @Test
    void 이미_받은_발표본이면_호출하지_않는다() {
        when(store.issuance(ZoneLevel.LARGE)).thenReturn(Optional.of(latest()));

        var outcome = new LargeZoneCollector(client, store).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        verifyNoInteractions(client);
    }

    @Test
    void 최신_발표본이_생산_전이면_직전_발표본을_26시각_받는다() {
        String latestTma = ZoneCollector.tma(latest());
        when(store.issuance(ZoneLevel.LARGE)).thenReturn(Optional.empty());
        when(store.replace(eq(ZoneLevel.LARGE), anyList(), any())).thenAnswer(inv -> ((List<?>) inv.getArgument(1)).size());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            return latestTma.equals(p.get("tma_fc")) ? NOT_READY : body(p, false);
        });

        var outcome = new LargeZoneCollector(client, store).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        assertThat(outcome.observedAt()).isEqualTo(latest().minusSeconds(12 * 3600));
        assertThat(outcome.payload()).containsEntry("cellCount", 26);
    }

    @Test
    void 대해구는_전체를_한_번에_묻는다() {
        when(store.issuance(ZoneLevel.LARGE)).thenReturn(Optional.empty());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            assertThat(p).containsEntry("Lzone", "0").doesNotContainKey("Szone").containsEntry("disp", "0");
            return body(p, false);
        });

        new LargeZoneCollector(client, store).collect(CONFIG, "k");

        verify(store).replace(eq(ZoneLevel.LARGE), anyList(), any());
    }

    @Test
    void 중간_시각이_실패하면_저장하지_않는다() {
        // 반쪽 발표본은 슬라이더 중간이 비어 잔잔한 바다로 읽힌다
        AtomicInteger calls = new AtomicInteger();
        when(store.issuance(ZoneLevel.LARGE)).thenReturn(Optional.empty());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            return calls.incrementAndGet() == 10 ? "발효시각을 확인하여 주시기 바랍니다." : body(p, false);
        });

        var outcome = new LargeZoneCollector(client, store).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isFalse();
        verify(store, never()).replace(any(), anyList(), any());
    }

    @Test
    void 두_발표본이_모두_생산_전이면_실패로_남긴다() {
        when(store.issuance(ZoneLevel.LARGE)).thenReturn(Optional.empty());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenReturn(NOT_READY);

        var outcome = new LargeZoneCollector(client, store).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isFalse();
        verify(store, never()).replace(any(), anyList(), any());
    }

    /**
     * 관심 타일 없음(mock 기본 빈 목록) → 기본 위치.
     *
     * <p>{@code nationwide=false} — 기존 검증은 <b>본선 주변 선택 규칙</b>에 대한 것이다.
     * 전국 경로는 {@link #전국이면_대해구_전부를_묻는다()} 와 {@link #전국은_틱마다_나눠_받는다()} 가 본다.</p>
     */
    private SmallZoneCollector small() {
        return small(false);
    }

    private SmallZoneCollector small(boolean nationwide) {
        var props = new OceanApiProperties("0 * * * * *", BUSAN, Map.of(), Map.of());
        return new SmallZoneCollector(client, store, tiles, props, nationwide);
    }

    @Test
    void 소해구는_대해구가_없으면_받지_않는다() {
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of());

        var outcome = small().collect(CONFIG, "k");

        assertThat(outcome.resultCode()).isEqualTo("NO_BASE");
        verifyNoInteractions(client);
    }

    @Test
    void 소해구는_가까운_대해구를_콤마로_묻는다() {
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(92, 5099, 100));
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.empty());
        when(store.replace(eq(ZoneLevel.SMALL), anyList(), any())).thenAnswer(inv -> ((List<?>) inv.getArgument(1)).size());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            // 합집합은 번호순으로 묻는다 — 같은 집합이면 같은 요청이라 로그로 재현하기 쉽다
            assertThat(p).containsEntry("Lzone", "92,100,5099").containsEntry("Szone", "0");
            return body(p, true);
        });

        var outcome = small().collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        assertThat(outcome.payload()).containsEntry("zoneCount", 3);
    }

    @Test
    void 선단이_멀리_가서_해구가_바뀌면_같은_발표본도_다시_받는다() {
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(92, 100));
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.of(latest()));
        when(store.zones(ZoneLevel.SMALL)).thenReturn(List.of(92, 93));
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> body(inv.getArgument(3), true));

        small().collect(CONFIG, "k");

        verify(store).replace(eq(ZoneLevel.SMALL), anyList(), any());
    }

    @Test
    void 해구가_같고_발표본도_같으면_호출하지_않는다() {
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(100, 92));
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.of(latest()));
        when(store.zones(ZoneLevel.SMALL)).thenReturn(List.of(92, 100));

        small().collect(CONFIG, "k");

        verifyNoInteractions(client);
    }

    @Test
    void 해구가_40개를_넘으면_나눠_묻는다() {
        // Lzone 한 번의 상한이 40개(명세). 넘겨 보내면 거부된다
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40)))
                .thenReturn(IntStream.rangeClosed(1, 45).boxed().toList());
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.empty());
        when(store.replace(eq(ZoneLevel.SMALL), anyList(), any())).thenAnswer(inv -> ((List<?>) inv.getArgument(1)).size());
        List<Integer> sizes = new CopyOnWriteArrayList<>();
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            sizes.add(p.get("Lzone").split(",").length);
            return body(p, true);
        });

        var outcome = small().collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        assertThat(sizes).containsOnly(40, 5);
        // 발효 26시각 × 2묶음. 끝 시각 확인은 첫 묶음 것을 다시 쓴다
        assertThat(sizes).hasSize(52);
        assertThat(outcome.payload()).containsEntry("zoneCount", 45).containsEntry("requestChunks", 2);
    }

    @Test
    void 소해구는_생산_전_해구번호_문구를_받아도_직전_발표본으로_물러선다() {
        // 🔴 2026-09-16 실측: 소해구는 파일이 아직 없을 때 "파일이 존재하지 않습니다" 가 아니라
        //    "해구번호를 확인하여 주시기 바랍니다" 를 준다. 같은 해구 목록으로 직전 발표본을 부르면 정상 응답한다
        //    (대해구는 같은 발표본에 자료를 준다 — 번호 문제가 아니라 소해구 파일만 늦게 생산된다).
        //    문구로 생산 여부를 갈랐더니 물러서지 못하고 매 틱 ERROR 로 끝나 /zones?level=small 이 계속 503 이었다.
        String latestTma = ZoneCollector.tma(latest());
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(92, 100));
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.empty());
        when(store.replace(eq(ZoneLevel.SMALL), anyList(), any())).thenAnswer(inv -> ((List<?>) inv.getArgument(1)).size());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            return latestTma.equals(p.get("tma_fc")) ? "해구번호를 확인하여 주시기 바랍니다." : body(p, true);
        });

        var outcome = small().collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        assertThat(outcome.observedAt()).isEqualTo(latest().minusSeconds(12 * 3600));
    }

    @Test
    void 두_발표본이_모두_거부되면_실패로_남긴다() {
        // 진짜 해구 번호 오류는 그대로 드러나야 한다 — 조용히 물러서기만 하면 원인을 영영 못 찾는다
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(92));
        when(store.issuance(ZoneLevel.SMALL)).thenReturn(Optional.empty());
        when(client.getText(any(), any(), any(), anyMap(), any())).thenReturn("해구번호를 확인하여 주시기 바랍니다.");

        var outcome = small().collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isFalse();
        assertThat(outcome.resultCode()).isEqualTo("ERROR");
        verify(store, never()).replace(any(), anyList(), any());
    }

    @Test
    void 관심_타일은_1도_칸으로_묶어_중심마다_해구를_고른다() {
        // 같은 1° 칸의 두 척은 중심 하나, 서해의 배는 따로
        var centers = SmallZoneCollector.centers(List.of(
                RomsTile.of(35.1, 129.1), RomsTile.of(35.6, 129.9), RomsTile.of(37.5, 126.4)), BUSAN);

        assertThat(centers).hasSize(2);
        assertThat(centers.getFirst()).containsExactly(35.5, 129.5);
    }

    @Test
    void 관심_선박이_없으면_기본_위치로_고른다() {
        // 비워 두면 소해구가 영영 안 들어와 화면·요약의 수온·너울이 빈다
        var centers = SmallZoneCollector.centers(List.of(), BUSAN);

        assertThat(centers).hasSize(1);
        assertThat(centers.getFirst()).containsExactly(35.05, 129.05);
        assertThat(SmallZoneCollector.centers(List.of(), null)).isEmpty();
    }


    // ── 전국 소해구 · 나눠 받기 (2026-09-17) ──────────────────

    /** 41개 이상이면 40개씩 나뉜다. 전국 1,330개는 34묶음이다 */
    private static List<Integer> zones(int n) {
        return IntStream.rangeClosed(1, n).boxed().toList();
    }

    @Test
    void 전국이면_대해구_발표본의_번호를_전부_묻는다() {
        // Lzone=0(전체)은 소해구에서 거부된다 — "대해구번호를 입력하세요."(2026-09-17 실호출).
        // 그래서 번호를 다 적어야 한다. 이 테스트가 깨지면 전국이 조용히 본선 주변으로 돌아간 것이다
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(100));
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(0);
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            Map<String, String> p = inv.getArgument(3);
            return body(p, true);
        });

        small(true).collect(CONFIG, "k");

        // 100개 → 3묶음인데 틱당 1묶음이라 아직 완료되지 않는다
        verify(store, never()).promote(any(), any(), any());
        verify(store, never()).replace(any(), anyList(), any());
        verify(store).stage(eq(ZoneLevel.SMALL), any(), eq(0), anyList(), any());
        verify(store, never()).stage(eq(ZoneLevel.SMALL), any(), eq(1), anyList(), any());
    }

    /**
     * <b>이 테스트가 이 기능의 존재 이유다.</b> 884묶음을 한 틱에 받으면 54분 동안
     * 같은 인스턴스의 ROMS·sea-obs·특보가 전부 멈춘다.
     */
    @Test
    void 전국은_틱마다_한_묶음만_받는다() {
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(400));   // 10묶음
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(0);
        AtomicInteger calls = new AtomicInteger();
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            calls.incrementAndGet();
            return body(inv.getArgument(3), true);
        });

        small(true).collect(CONFIG, "k");

        // 확인 1회 + 묶음 1개 × 26 발효시각 − 재사용 1회 = 26.
        // ⚠ 2묶음(52회 ≈ 78초)이면 틱 간격 60초를 넘겨 다음 틱이 리스에 막힌다 — 처리량은 같고 블로킹만 2배다
        assertThat(calls.get()).isEqualTo(26);
    }

    /** 다음 틱은 받아 둔 지점부터 잇는다. 처음부터 다시 받으면 영영 안 끝난다 */
    @Test
    void 이어받을_때는_저장된_묶음_다음부터_받는다() {
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(400));
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(4);
        when(client.getText(any(), any(), any(), anyMap(), any()))
                .thenAnswer(inv -> body(inv.getArgument(3), true));

        small(true).collect(CONFIG, "k");

        verify(store).stage(eq(ZoneLevel.SMALL), any(), eq(4), anyList(), any());
        verify(store, never()).stage(eq(ZoneLevel.SMALL), any(), eq(5), anyList(), any());
        verify(store, never()).stage(eq(ZoneLevel.SMALL), any(), eq(0), anyList(), any());
    }

    /**
     * 이어받는 틱은 <b>생산 여부를 다시 묻지 않는다.</b> 매 틱 1회씩 더 내면
     * 7.4시간 수집에 442회가 더 나간다 — 전량(884회)의 50% 다.
     */
    @Test
    void 이어받을_때는_확인_호출을_하지_않는다() {
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(400));
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(4);
        AtomicInteger calls = new AtomicInteger();
        when(client.getText(any(), any(), any(), anyMap(), any())).thenAnswer(inv -> {
            calls.incrementAndGet();
            return body(inv.getArgument(3), true);
        });

        small(true).collect(CONFIG, "k");

        // 묶음 1개 × 26 발효시각. 확인 호출이 없으니 딱 26 이다
        assertThat(calls.get()).isEqualTo(26);
    }

    /** 마지막 묶음이 차면 본 테이블로 올린다. 그 전에는 절대 올리지 않는다 — 반쪽 발표본이 화면에 뜬다 */
    @Test
    void 마지막_묶음이_차면_본_테이블로_올린다() {
        // 120개 = 3묶음. 앞 틱에서 2묶음을 받아 뒀고 이번 틱이 마지막 하나를 채운다.
        // ⚠ 80개(=2묶음)로 잡으면 limit(2) < chunks(2) 가 거짓이라 **나누지 않는 경로**로 빠진다
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(120));
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(2, 2, 3);
        when(store.promote(any(), any(), any())).thenReturn(360);
        when(client.getText(any(), any(), any(), anyMap(), any()))
                .thenAnswer(inv -> body(inv.getArgument(3), true));

        var outcome = small(true).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        verify(store).promote(eq(ZoneLevel.SMALL), any(), any());
        // 나눠 받을 때는 replace 를 쓰지 않는다 — promote 가 같은 의미를 SQL 안에서 한다
        verify(store, never()).replace(any(), anyList(), any());
    }

    /**
     * 아직 다 못 받았으면 <b>성공으로 주면 안 된다.</b> ok(fc) 로 주면 다음 틱이
     * "이미 받은 발표본"으로 보고 멈춰 영영 완료되지 않는다.
     */
    @Test
    void 받는_중에는_성공으로_주지_않는다() {
        when(store.zones(ZoneLevel.LARGE)).thenReturn(zones(400));
        when(store.stagedChunks(eq(ZoneLevel.SMALL), any())).thenReturn(0);
        when(client.getText(any(), any(), any(), anyMap(), any()))
                .thenAnswer(inv -> body(inv.getArgument(3), true));

        var outcome = small(true).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isFalse();
        assertThat(outcome.resultCode()).isEqualTo("PARTIAL");
    }

    /** 본선 주변(40개)은 한 묶음이라 나누지 않는다. 옛 경로가 그대로 살아 있어야 되돌릴 수 있다 */
    @Test
    void 본선_주변이면_예전처럼_한_번에_받는다() {
        when(store.largeZonesNear(anyDouble(), anyDouble(), eq(40))).thenReturn(List.of(92, 100));
        when(store.replace(any(), anyList(), any())).thenReturn(9);
        when(client.getText(any(), any(), any(), anyMap(), any()))
                .thenAnswer(inv -> body(inv.getArgument(3), true));

        var outcome = small(false).collect(CONFIG, "k");

        assertThat(outcome.isSuccess()).isTrue();
        verify(store).replace(eq(ZoneLevel.SMALL), anyList(), any());
        verify(store, never()).stage(any(), any(), org.mockito.ArgumentMatchers.anyInt(), anyList(), any());
    }

    private static double anyDouble() {
        return org.mockito.ArgumentMatchers.anyDouble();
    }
}

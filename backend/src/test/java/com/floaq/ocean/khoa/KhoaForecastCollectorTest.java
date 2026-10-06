package com.floaq.ocean.khoa;

import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.seaobs.SeaObsStation;
import com.floaq.ocean.seaobs.SeaObsStore;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * KHOA 조류·조석예보 수집 — 지점별 시계열.
 *
 * 단위를 틀리면 조용히 100배 틀린다(유속 cm/s · 조위 cm). 유향은 숫자가 아니라 16방위 한글이다.
 */
class KhoaForecastCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final Source CONFIG = new Source(Provider.DATA_GO_KR, "https://example.invalid", null,
            Kind.FORECAST, null, 0, 86400, 0, true);

    private final OceanApiClient client = mock(OceanApiClient.class);
    private final SeaObsStore store = mock(SeaObsStore.class);

    /** 2026-09-16 실응답 모양 — 봉투에 response 가 없다 */
    private static OceanResponse body(String itemJson) {
        return new OceanResponse(200, OceanResponse.OK, null,
                MAPPER.readTree("{\"items\":{\"item\":%s}}".formatted(itemJson)));
    }

    private static final String CURRENT_ITEM = """
            [{"obsvtrNm":"부산항입구","lot":129.11719,"lat":35.08272,"predcDt":"2026-09-16 00:00",
              "crdir":"북북동","crsp":30.86}]
            """;

    @SuppressWarnings("unchecked")
    private List<SeaObsStation> saved() {
        ArgumentCaptor<List<SeaObsStation>> rows = ArgumentCaptor.forClass(List.class);
        verify(store).record(anyString(), rows.capture(), any());
        return rows.getValue();
    }

    @Test
    void 유향_16방위_한글과_유속_cm_를_바꿔_저장한다() {
        // 30.86 cm/s 를 그대로 두면 표류 반경이 100배가 된다. 유향 "북북동" 은 22.5도
        when(client.get(anyString(), any(), anyString(), anyMap())).thenReturn(body(CURRENT_ITEM));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        var outcome = new CurrentForecastCollector(client, store).collect(CONFIG, "key");

        assertThat(outcome.isSuccess()).isTrue();
        SeaObsStation row = saved().getFirst();
        assertThat(row.currentDirDeg()).isEqualTo(22.5);
        assertThat(row.currentSpeedMs()).isEqualTo(0.3086);
        assertThat(row.name()).isEqualTo("부산항입구");
        // predcDt 에 타임존 표기가 없다. KST 로 읽지 않으면 예보가 9시간 밀린다
        assertThat(row.observedAt()).isEqualTo(Instant.parse("2026-09-15T15:00:00Z"));
    }

    @Test
    void 조위_cm_를_m_로_바꿔_저장한다() {
        when(client.get(anyString(), any(), anyString(), anyMap())).thenReturn(body("""
                [{"obsvtrNm":"부산","lot":129.03527,"lat":35.09638,"predcDt":"2026-09-16 01:00","tdlvHgt":105.47}]
                """));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        new TideForecastCollector(client, store).collect(CONFIG, "key");

        SeaObsStation row = saved().getFirst();
        assertThat(row.tideLevelM()).isEqualTo(1.0547);
        assertThat(row.currentSpeedMs()).isNull();
    }

    @Test
    void 유향을_못_읽으면_null_이다() {
        // 전류(轉流) 시각에 무엇이 오는지 모른다. 0 으로 두면 '북'으로 읽혀 표류 방향이 조용히 틀린다
        when(client.get(anyString(), any(), anyString(), anyMap())).thenReturn(body("""
                [{"obsvtrNm":"부산항입구","lot":129.1,"lat":35.0,"predcDt":"2026-09-16 00:00","crdir":"-","crsp":0.0}]
                """));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        new CurrentForecastCollector(client, store).collect(CONFIG, "key");

        assertThat(saved().getFirst().currentDirDeg()).isNull();
    }

    @Test
    void 지점마다_한_번씩_부르고_obsCode_와_하루치를_넘긴다() {
        when(client.get(anyString(), any(), anyString(), anyMap())).thenReturn(body(CURRENT_ITEM));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        new CurrentForecastCollector(client, store).collect(CONFIG, "key");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> params = ArgumentCaptor.forClass(Map.class);
        // 지점 목록은 리소스 CSV 다 — 203곳(2026-09-16 가이드 코드표)
        verify(client, times(203)).get(anyString(), any(), anyString(), params.capture());
        assertThat(params.getValue()).containsEntry("min", "60").containsEntry("type", "json")
                .containsKey("obsCode").containsKey("reqDate");
    }

    @Test
    void 조석은_오늘과_내일_두_날짜를_부른다() {
        // 오늘치만 받으면 "지금 이후"가 저녁에 1~2점으로 줄고 자정 직전엔 0 이 된다.
        // 실측(2026-09-16 10시 부산): 예보점 13개 · 만조 0건 — "다음 만조"에 답을 못 했다
        when(client.get(anyString(), any(), anyString(), anyMap())).thenReturn(body("""
                [{"obsvtrNm":"부산","lot":129.03527,"lat":35.09638,"predcDt":"2026-09-16 01:00","tdlvHgt":105.47}]
                """));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        new TideForecastCollector(client, store).collect(CONFIG, "key");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> params = ArgumentCaptor.forClass(Map.class);
        // 166지점 × 2일. 조류(203 × 1일)와 달리 화면이 48시간 창을 쓴다
        verify(client, times(332)).get(anyString(), any(), anyString(), params.capture());

        var ymd = DateTimeFormatter.ofPattern("yyyyMMdd");
        var dates = params.getAllValues().stream()
                .map(p -> LocalDate.parse(p.get("reqDate"), ymd)).distinct().sorted().toList();
        assertThat(dates).hasSize(2);
        assertThat(dates.get(1)).isEqualTo(dates.get(0).plusDays(1));
    }

    @Test
    void 예산이_떨어지면_남은_지점을_부르지_않는다() {
        when(client.get(anyString(), any(), anyString(), anyMap()))
                .thenReturn(new OceanResponse(0, OceanResponse.QUOTA_GUARD, "하루 호출 예산 소진", null));

        var outcome = new TideForecastCollector(client, store).collect(CONFIG, "key");

        verify(client, times(1)).get(anyString(), any(), anyString(), anyMap());
        assertThat(outcome.resultCode()).isEqualTo(OceanResponse.QUOTA_GUARD);
        // 한 행도 못 받았으면 기존 값을 덮지 않는다
        verify(store, times(0)).record(anyString(), anyList(), any());
    }

    @Test
    void 한_지점이_데이터_없음이면_건너뛰고_나머지를_받는다() {
        when(client.get(anyString(), any(), anyString(), anyMap()))
                .thenReturn(new OceanResponse(200, OceanResponse.NO_DATA, "데이터없음", null))
                .thenReturn(body(CURRENT_ITEM));
        when(store.record(anyString(), anyList(), any())).thenReturn(1);

        var outcome = new CurrentForecastCollector(client, store).collect(CONFIG, "key");

        assertThat(outcome.isSuccess()).isTrue();
        assertThat(saved()).isNotEmpty();
    }

    @Test
    void 결과가_1건이면_item_이_객체로_온다() {
        // 공공데이터포털 공통 함정. 배열만 보면 1건일 때 0건이 된다
        var single = MAPPER.readTree("""
                {"items":{"item":{"obsvtrNm":"부산","lot":129.0,"lat":35.0,"predcDt":"2026-09-16 00:00","tdlvHgt":10.0}}}
                """);

        assertThat(KhoaForecastCollector.items(single)).hasSize(1);
        assertThat(KhoaForecastCollector.items(MAPPER.readTree("{\"items\":\"\"}"))).isEmpty();
    }

    @Test
    void 지점_목록은_리소스에서_읽는다() {
        var crnt = KhoaStations.load("/ocean/current-forecast-stations.csv");
        var tide = KhoaStations.load("/ocean/tide-forecast-stations.csv");

        assertThat(crnt).hasSize(203);
        assertThat(tide).hasSize(166);
        assertThat(crnt).anyMatch(s -> "16LTC13".equals(s.code()) && "부산항입구".equals(s.name()));
        assertThat(tide).anyMatch(s -> "DT_0005".equals(s.code()) && "부산".equals(s.name()));
        // 없는 리소스는 빈 목록 — 수집기가 "지점 없음"으로 실패를 남긴다
        assertThat(KhoaStations.load("/ocean/없는파일.csv")).isEmpty();
    }
}

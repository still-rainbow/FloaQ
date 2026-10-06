package com.floaq.ocean.nifs;

import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.entity.OceanSnapshot;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 적조는 2단계 호출(목록 → 상세)이다. **같은 보고면 상세를 다시 부르지 않는다** (2026-09-16).
 *
 * 틀리면 하루 24회를 같은 문장 받는 데 쓴다 — 이전 동작이 그랬다.
 */
class RedTideCollectorTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final Source CONFIG = new Source(Provider.NIFS, "https://example.invalid", "nifs-key",
            Kind.ADVISORY, null, 30, 3600, 0, true);

    private final OceanApiClient client = mock(OceanApiClient.class);
    private final OceanSnapshotService snapshots = mock(OceanSnapshotService.class);
    private RedTideCollector collector;

    @BeforeEach
    void setUp() {
        collector = new RedTideCollector(client, snapshots);
        when(snapshots.find(RedTideCollector.SOURCE)).thenReturn(Optional.empty());
        // id 로 목록·상세를 가른다 — 수집기가 같은 base-url 에 id 만 바꿔 부른다
        when(client.get(anyString(), any(), anyString(), anyMap())).thenAnswer(inv -> {
            Map<String, String> params = inv.getArgument(3);
            return "redtideDetail".equals(params.get("id")) ? detail("상세에서 온 진행상황") : list("20260811-001");
        });
    }

    /** 실응답 봉투는 {"header":…,"body":{"item":[…]}} 이고 수집기는 body 를 받는다 */
    private static OceanResponse list(String codNews) {
        return new OceanResponse(200, OceanResponse.OK, null, MAPPER.readTree("""
                {"item":[{"cod_news":"%s","day_report":"20260811",
                  "item2":{"nam_biology":"코클로디니움","txt_seas":"전남 여수","max_density":"1200"}}]}
                """.formatted(codNews)));
    }

    private static OceanResponse detail(String progress) {
        return new OceanResponse(200, OceanResponse.OK, null, MAPPER.readTree("""
                {"item":[{"txt_progress":"%s","txt_breaking":"적조주의보","txt_afterview":"소강 전망","txt_request":"양식장 주의"}]}
                """.formatted(progress)));
    }

    private static OceanSnapshot stored(String codNews, String progress) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("codNews", codNews);
        payload.put("progress", progress);
        var snapshot = OceanSnapshot.of(RedTideCollector.SOURCE);
        snapshot.succeed(Instant.parse("2026-08-11T15:00:00Z"), payload, Instant.now(), "00", null);
        return snapshot;
    }

    @Test
    void 같은_보고면_목록만_부르고_직전_상세를_쓴다() {
        when(snapshots.find(RedTideCollector.SOURCE))
                .thenReturn(Optional.of(stored("20260811-001", "저장된 진행상황")));

        var outcome = collector.collect(CONFIG, "key");

        verify(client, times(1)).get(anyString(), any(), anyString(), anyMap());
        assertThat(outcome.payload()).containsEntry("progress", "저장된 진행상황");
    }

    @Test
    void 새_보고면_상세를_부른다() {
        // 옛 특보 문구를 새 보고에 붙이면 화면이 지난 상황을 지금으로 말한다
        when(snapshots.find(RedTideCollector.SOURCE))
                .thenReturn(Optional.of(stored("20260701-009", "지난달 진행상황")));

        var outcome = collector.collect(CONFIG, "key");

        verify(client, times(2)).get(anyString(), any(), anyString(), anyMap());
        assertThat(outcome.payload()).containsEntry("progress", "상세에서 온 진행상황");
    }

    @Test
    void 저장된_값이_없으면_상세를_부른다() {
        var outcome = collector.collect(CONFIG, "key");

        verify(client, times(2)).get(anyString(), any(), anyString(), anyMap());
        assertThat(outcome.payload()).containsEntry("breaking", "적조주의보");
    }

    @Test
    void 직전_상세가_실패했으면_다시_부른다() {
        // 번호는 같은데 상세 키가 없다 — 그때 상세가 실패했다. 실패가 그대로 굳지 않게 다시 부른다
        Map<String, Object> onlyList = new LinkedHashMap<>();
        onlyList.put("codNews", "20260811-001");
        var snapshot = OceanSnapshot.of(RedTideCollector.SOURCE);
        snapshot.succeed(Instant.now(), onlyList, Instant.now(), "00", null);
        when(snapshots.find(RedTideCollector.SOURCE)).thenReturn(Optional.of(snapshot));

        collector.collect(CONFIG, "key");

        verify(client, times(2)).get(anyString(), any(), anyString(), anyMap());
    }
}

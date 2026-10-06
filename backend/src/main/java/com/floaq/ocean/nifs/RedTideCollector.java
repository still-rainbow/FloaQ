package com.floaq.ocean.nifs;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import com.floaq.ocean.entity.OceanSnapshot;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 수과원 적조정보 — 조업 판단. 특보 체계가 있어 기준이 국가 것이다(§6).
 *
 * 2026-09-13 실호출로 확인한 것
 *   상세 호출 키는 cod_news 다. srcode 가 아니다
 *   목록에는 특보가 없다. 진행상황·특보상황·금후전망·당부사항은 redtideDetail 에만 있다
 *   한 보고에 원인생물이 여럿이라 item2 중첩 배열이 있다
 *   빈 값이 빈 문자열로 온다 (min_density)
 *
 * 2026-09-14 실호출 — 상세 필드명이 PDF 와 다름
 *   txt_progress · txt_breaking · txt_afterview · txt_request · txt_reference
 *   (PDF 의 pstate · sreport · aview · rmatter · etc 아님)
 *
 * 한계: 조사해역이 "전남 여수" 같은 텍스트라 지도에 영역을 못 그린다. 목록으로만 보여준다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RedTideCollector implements OceanCollector {

    public static final String SOURCE = "red-tide";

    private static final String LIST_ID = "redtideList";
    private static final String DETAIL_ID = "redtideDetail";

    /** 적조는 수시 발표라 한 달이면 최신 보고가 반드시 걸린다 */
    private static final int DEFAULT_WINDOW_DAYS = 30;

    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 상세 응답에서만 오는 키. 같은 보고면 직전 값을 그대로 쓴다 */
    private static final List<String> DETAIL_KEYS = List.of("progress", "breaking", "afterview", "request");

    private final OceanApiClient client;
    private final OceanSnapshotService snapshots;

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        LocalDate today = LocalDate.now(SOURCE_ZONE);
        int windowDays = config.windowDays() > 0 ? config.windowDays() : DEFAULT_WINDOW_DAYS;

        OceanResponse list = client.get(SOURCE, config, key, Map.of(
                "id", LIST_ID,
                "sdate", today.minusDays(windowDays).format(YMD),
                "edate", today.format(YMD)));
        if (!list.isOk()) {
            return CollectOutcome.from(list);
        }

        // 목록이 발표일 오름차순이라 마지막이 최신이다. 순서에 기대지 않고 직접 고른다
        JsonNode latest = NifsResponses.items(list.body()).stream()
                .max(Comparator.comparing(n -> String.valueOf(NifsResponses.text(n, "day_report"))))
                .orElse(null);
        if (latest == null) {
            return new CollectOutcome(OceanResponse.NO_DATA, "조회 창에 적조 보고 없음", null, null);
        }

        String codNews = NifsResponses.text(latest, "cod_news");
        Map<String, Object> payload = summary(latest, codNews);
        appendDetail(config, key, codNews, payload);

        Instant reportedAt = parseDay(NifsResponses.text(latest, "day_report"));
        log.info("[ocean] red-tide — 최신 보고 {} ({})", codNews, reportedAt);
        return CollectOutcome.ok(reportedAt, payload);
    }

    private static Map<String, Object> summary(JsonNode latest, String codNews) {
        List<Map<String, Object>> organisms = new ArrayList<>();
        for (JsonNode o : NifsResponses.array(latest.path("item2"))) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", NifsResponses.text(o, "nam_biology"));
            row.put("area", NifsResponses.text(o, "txt_seas"));
            row.put("minDensity", NifsResponses.number(o, "min_density"));
            row.put("maxDensity", NifsResponses.number(o, "max_density"));
            row.put("minWaterTempC", NifsResponses.number(o, "min_watertemp"));
            row.put("maxWaterTempC", NifsResponses.number(o, "max_watertemp"));
            organisms.add(row);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("codNews", codNews);
        payload.put("dayReport", NifsResponses.text(latest, "day_report"));
        payload.put("organisms", organisms);
        return payload;
    }

    /** 상세가 실패해도 목록 값은 살린다. 특보 문구가 없다고 적조 발생 사실까지 버릴 이유가 없다 */
    private void appendDetail(Source config, String key, String codNews, Map<String, Object> payload) {
        if (codNews == null) {
            return;
        }
        // 같은 보고면 내용도 같다 — 상세를 다시 부르지 않는다 (2026-09-16). 평상시 매시 목록 1회만 남는다
        if (NifsDetailCache.reuse(stored(), "codNews", codNews, payload, DETAIL_KEYS)) {
            return;
        }
        OceanResponse detail = client.get(SOURCE, config, key, Map.of("id", DETAIL_ID, "cod_news", codNews));
        if (!detail.isOk()) {
            log.warn("[ocean] red-tide — 상세 실패 {} {}", detail.code(), detail.message());
            return;
        }
        NifsResponses.items(detail.body()).stream().findFirst().ifPresent(d -> {
            payload.put("progress", NifsResponses.plainText(NifsResponses.text(d, "txt_progress")));
            payload.put("breaking", NifsResponses.plainText(NifsResponses.text(d, "txt_breaking")));
            payload.put("afterview", NifsResponses.plainText(NifsResponses.text(d, "txt_afterview")));
            // 양식장 대응 요청. 조업 판단에 직접 쓰이는 문장
            payload.put("request", NifsResponses.plainText(NifsResponses.text(d, "txt_request")));
        });
    }

    /** 직전 성공 payload. 실패한 수집은 payload 를 덮지 않으므로(§9.10) 마지막 성공값이 남아 있다 */
    private Map<String, Object> stored() {
        return snapshots.find(SOURCE).map(OceanSnapshot::getPayload).orElse(null);
    }

    private static Instant parseDay(String raw) {
        if (raw == null) {
            return null;
        }
        try {
            return LocalDate.parse(raw, YMD).atStartOfDay(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] red-tide — day_report 판독 실패: '{}'", raw);
            return null;
        }
    }
}

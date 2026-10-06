package com.floaq.ocean.warning;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.nio.charset.Charset;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 기상청 API허브 wrn_reg.php — 해상 특보구역 계층. 기상특보 수집기가 조업 해역 판정에 씀.
 *
 * 정적 파일 기각 — 구역 개편(2021-07-29 먼바다 세분화)이 조용히 반영 안 됨.
 * 좌표 없음. 코드·이름·상위구역·유효기간뿐 (2026-09-14 실호출).
 *
 * 한계: 수집 순서가 보장되지 않아 기동 직후 첫 기상특보 수집은 계층 없이 돌 수 있음 (다음 주기에 반영).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WarningZoneCollector implements OceanCollector {

    public static final String SOURCE = "warning-zone";

    private static final Charset SOURCE_CHARSET = Charset.forName("EUC-KR");

    /** 해상 특보구역 접두어. L 은 육상 */
    private static final String SEA = "S";

    private final OceanApiClient client;

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        String body = client.getText(SOURCE, config, key, Map.of("tmfc", "0"), SOURCE_CHARSET);
        if (body == null) {
            return new CollectOutcome("ERROR", "응답 없음", null, null);
        }
        if (body.strip().startsWith("{")) {
            // 활용신청 전이면 403 JSON ("활용신청이 필요한 API 입니다")
            log.warn("[ocean] warning-zone — 거부 응답: {}", body.strip().substring(0, Math.min(160, body.strip().length())));
            return new CollectOutcome("DENIED", "API허브 거부 (활용신청·키 확인)", null, null);
        }

        Instant now = Instant.now();
        List<WarningZoneParser.Row> sea = WarningZoneParser.parse(body).stream()
                .filter(r -> r.id().startsWith(SEA))
                .filter(r -> r.validTo() == null || r.validTo().isAfter(now))
                .toList();
        if (sea.isEmpty()) {
            return new CollectOutcome(OceanResponse.NO_DATA, "해상 특보구역 없음", null, null);
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("zoneCount", sea.size());
        payload.put("zones", sea.stream().map(WarningZoneCollector::zone).toList());
        log.info("[ocean] warning-zone — 해상 특보구역 {}개", sea.size());
        // 참조 자료라 관측 시각이 없음. 받은 시각으로 둠
        return CollectOutcome.ok(now, payload);
    }

    private static Map<String, Object> zone(WarningZoneParser.Row r) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", r.id());
        row.put("up", r.up());
        row.put("name", r.name());
        row.put("spec", r.spec());
        return row;
    }
}

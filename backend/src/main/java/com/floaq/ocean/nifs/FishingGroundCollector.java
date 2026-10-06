package com.floaq.ocean.nifs;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 수과원 실시간어장정보 — 수온.
 *
 * 용도는 수질이 아니라 저체온증 생존 시간 추정이다(§6). 부표 발열팩 채택과 논리가 이어진다.
 *
 * 2026-09-13 실호출로 확인한 것
 *   risaList 는 수온만 준다. 염분·용존산소는 없다
 *   한 관측소가 obs_lay(1표층 2중층 3저층)로 여러 행이다. 표층만 쓴다
 *   좌표가 risaList 에 없다. risaCode 를 따로 불러야 lat/lon 을 얻는다
 *   관측소 41곳. 부산권은 기장(bgj8a)
 *
 * **전국 관측소를 싣는다** (2026-09-15). 선박이 여러 척이라 반경·거리는 조회 때 요청 좌표로 잰다(StationNear).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class FishingGroundCollector implements OceanCollector {

    public static final String SOURCE = "fishing-ground";

    private static final String LIST_ID = "risaList";
    private static final String CODE_ID = "risaCode";

    /** 표층. 중층·저층은 저체온증 추정과 무관하고, 안 거르면 한 관측소가 여러 줄이 된다 */
    private static final String SURFACE_LAYER = "1";

    /** 점검 중. 안 거르면 고장난 센서 값이 화면에 오른다 */
    private static final String UNDER_REPAIR = "2";

    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter OBS = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final OceanApiClient client;

    /** 관측소 좌표. 갱신이 "수시"라 한 번 받아 두면 된다. 인스턴스마다 따로 든다 — 캐시일 뿐이다 */
    private final Map<String, StationInfo> stationCache = new ConcurrentHashMap<>();

    private record StationInfo(String name, String sea, double lat, double lon) {
    }

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        if (stationCache.isEmpty() && !loadStations(config, key)) {
            return new CollectOutcome("ERROR", "관측소 좌표를 받지 못했다", null, null);
        }

        OceanResponse response = client.get(SOURCE, config, key, Map.of("id", LIST_ID));
        if (!response.isOk()) {
            return CollectOutcome.from(response);
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        Instant latest = null;

        for (JsonNode item : NifsResponses.items(response.body())) {
            if (!SURFACE_LAYER.equals(NifsResponses.text(item, "obs_lay"))
                    || UNDER_REPAIR.equals(NifsResponses.text(item, "repair_gbn"))) {
                continue;
            }
            StationInfo station = stationCache.get(NifsResponses.text(item, "sta_cde"));
            if (station == null) {
                continue;
            }
            Instant observedAt = parseObservedAt(
                    NifsResponses.text(item, "obs_dat"), NifsResponses.text(item, "obs_tim"));
            if (latest == null || (observedAt != null && observedAt.isAfter(latest))) {
                latest = observedAt;
            }
            rows.add(row(item, station, observedAt));
        }

        if (rows.isEmpty()) {
            return new CollectOutcome(OceanResponse.NO_DATA, "관측소 없음", null, null);
        }
        log.info("[ocean] fishing-ground — 관측소 {}곳 (전국), 관측 {}", rows.size(), latest);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("stationCount", rows.size());
        payload.put("stations", rows);
        return CollectOutcome.ok(latest, payload);
    }

    /** @return 좌표를 하나라도 받았으면 true */
    private boolean loadStations(Source config, String key) {
        OceanResponse response = client.get(SOURCE, config, key, Map.of("id", CODE_ID));
        if (!response.isOk()) {
            log.warn("[ocean] fishing-ground — risaCode 실패 {} {}", response.code(), response.message());
            return false;
        }
        for (JsonNode item : NifsResponses.items(response.body())) {
            Double lat = NifsResponses.number(item, "lat");
            Double lon = NifsResponses.number(item, "lon");
            String code = NifsResponses.text(item, "sta_cde");
            if (code == null || lat == null || lon == null) {
                continue;
            }
            // end_dat 가 있으면 폐소된 관측소다. 담아 두면 값 없는 지점이 화면에 남는다
            if (NifsResponses.text(item, "end_dat") != null) {
                continue;
            }
            stationCache.put(code, new StationInfo(
                    NifsResponses.text(item, "sta_nam_kor"), NifsResponses.text(item, "gru_nam"), lat, lon));
        }
        log.info("[ocean] fishing-ground — 관측소 좌표 {}곳 적재", stationCache.size());
        return !stationCache.isEmpty();
    }

    /** distanceKm 는 싣지 않는다 — 조회 좌표마다 다르다(StationNear 가 붙인다) */
    private static Map<String, Object> row(JsonNode item, StationInfo station, Instant observedAt) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("code", NifsResponses.text(item, "sta_cde"));
        row.put("name", station.name());
        row.put("sea", station.sea());
        row.put("lat", station.lat());
        row.put("lon", station.lon());
        row.put("waterTempC", NifsResponses.number(item, "wtr_tmp"));
        // ISO 문자열. jsonb 에 Instant 를 그대로 두면 epoch 초가 된다
        row.put("observedAt", observedAt == null ? null : observedAt.toString());
        return row;
    }

    private static Instant parseObservedAt(String date, String time) {
        if (date == null || time == null) {
            return null;
        }
        try {
            return LocalDateTime.parse(date + " " + time, OBS).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] fishing-ground — 관측 시각 판독 실패: '{} {}'", date, time);
            return null;
        }
    }
}

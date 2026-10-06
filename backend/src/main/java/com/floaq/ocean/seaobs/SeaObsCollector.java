package com.floaq.ocean.seaobs;

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
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 기상청 해양기상종합관측 sea_obs.php — 파고 · 바람 · 수온.
 *
 * 응답이 JSON 이 아니라 #START7777 ~ #7777END 로 감싼 고정폭 텍스트다.
 * 전용 파서가 필요한 이 성질이 KHOA twRecent 로 갈아탈 후보 근거이기도 하다(§6).
 *
 * 2026-09-13 실호출로 확인한 것
 *   EUC-KR 이다. UTF-8 로 읽으면 지점명이 깨진다
 *   stn=0(전체)이 0.18초 200줄. "25초 타임아웃" 기록은 조건이 달랐던 듯하다
 *   결측이 -99 / -99.0 이다. 안 거르면 수온 -99℃ 가 화면에 오른다
 *
 * **전국 지점을 싣는다** (2026-09-15). 선박이 여러 척이라 수집 시점의 기준 좌표가 없다 —
 * 반경·거리는 조회 때 요청 좌표로 잰다(StationNear). 전국 약 200지점이라 한 행에 담아도 작다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SeaObsCollector implements OceanCollector {

    public static final String SOURCE = "sea-obs";

    /** 전체 지점. 지점을 하나씩 부르면 호출 수가 지점 수만큼 늘고, 전체가 0.2초면 나눌 이유가 없다 */
    private static final String ALL_STATIONS = "0";
    private static final Charset SOURCE_CHARSET = Charset.forName("EUC-KR");
    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter TM = DateTimeFormatter.ofPattern("yyyyMMddHHmm");

    private final OceanApiClient client;
    private final SeaObsStore store;

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        LocalDateTime hour = LocalDateTime.now(SOURCE_ZONE).truncatedTo(ChronoUnit.HOURS);

        // 정시 생산이라 방금 지난 정시에는 아직 없을 수 있다. 없으면 한 시간 뒤로 물러선다
        List<SeaObsStation> stations = fetch(config, key, hour);
        if (stations.isEmpty()) {
            stations = fetch(config, key, hour.minusHours(1));
        }
        if (stations.isEmpty()) {
            return new CollectOutcome(OceanResponse.NO_DATA, "관측 지점 없음", null, null);
        }

        Instant observedAt = stations.getFirst().observedAt();
        log.info("[ocean] sea-obs — 지점 {}곳 (전국), 관측 {}", stations.size(), observedAt);
        return CollectOutcome.ok(observedAt, payload(stations));
    }

    private List<SeaObsStation> fetch(Source config, String key, LocalDateTime hour) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("tm", hour.format(TM));
        params.put("stn", ALL_STATIONS);
        String body = client.getText(SOURCE, config, key, params, SOURCE_CHARSET);
        List<SeaObsStation> all = SeaObsParser.parse(body);
        // 이력도 전국 — 옛 사고 지점 근처 관측이 남아야 한다(OceanRetention)
        if (!all.isEmpty()) {
            store.record(SOURCE, all, Instant.now());
        }
        return all;
    }

    /**
     * 요소별로 값이 나오는 지점이 다르므로 지점 목록을 그대로 싣는다.
     *
     * 대표값 하나로 합치지 않는다 — 파고는 파고부이, 바람은 등표에서 오는데
     * 합치면 서로 다른 위치의 값이 한 줄로 보인다(§6 경고).
     * distanceKm 는 싣지 않는다 — 조회 좌표마다 다르다(StationNear 가 붙인다).
     */
    private static Map<String, Object> payload(List<SeaObsStation> stations) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (SeaObsStation s : stations) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("network", s.network());
            row.put("stn", s.stn());
            row.put("name", s.name());
            row.put("lat", s.lat());
            row.put("lon", s.lon());
            row.put("waveHeightM", s.waveHeightM());
            row.put("windDirDeg", s.windDirDeg());
            row.put("windSpeedMs", s.windSpeedMs());
            row.put("windGustMs", s.windGustMs());
            row.put("waterTempC", s.waterTempC());
            row.put("airTempC", s.airTempC());
            row.put("pressureHpa", s.pressureHpa());
            row.put("humidityPct", s.humidityPct());
            rows.add(row);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("stationCount", rows.size());
        payload.put("stations", rows);
        return payload;
    }
}

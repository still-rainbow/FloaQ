package com.floaq.ocean.khoa;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import com.floaq.ocean.seaobs.SeaObsStation;
import com.floaq.ocean.seaobs.SeaObsStore;
import lombok.extern.slf4j.Slf4j;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * KHOA 지점 시계열 예보 수집 — 조류예보·조석예보 공통 (2026-09-16).
 *
 * 명세 `p-shim/ref/openapi/오픈API 활용가이드_조류예보(시계열).pdf` · `_조석예보(시계열).pdf`
 *
 * 요청  serviceKey · type=json · **obsCode(필수)** · reqDate(기본 오늘) · min(1~60) · numOfRows(≤300)
 * 응답  봉투 `{"header":…,"body":{"items":{"item":[…]}}}` — `response` 없음(2026-09-16 실호출).
 *       `obsvtrNm` · `lot`(경도) · `lat` · `predcDt`(KST "yyyy-MM-dd HH:mm") + 소스별 값
 *
 * **전국 지점을 하루 한 번 받는다.** 지점 선택을 좌표로 못 한다 — 좌표가 목록이 아니라 응답에 있어서,
 * "가까운 지점만"을 고르려면 결국 한 번은 전국을 받아야 한다(KhoaStations 주석).
 * 선박이 여러 척이라 거리는 조회 때 요청 좌표로 잰다(StationNear) — sea-obs·실시간어장과 같은 규칙.
 *
 * ⚠ 1회 수집이 **지점 수 × 일수** 만큼 호출이다(조류 약 200 × 1일 · 조석 약 170 × 2일, 각 0.2~0.3초).
 *    그 소스의 틱이 1분 안팎 잡혀 있고, 그동안 같은 인스턴스의 다음 소스가 밀린다 — 하루 1회라 감수한다.
 * ⚠ 값이 **예보**라 저장 시각(observed_at)이 미래다. 조회는 "그 시각 이후 가장 이른 것"을 고른다(SeaObsStore.forecastFrom).
 */
@Slf4j
public abstract class KhoaForecastCollector implements OceanCollector {

    /** 한 번에 하루치. min=60 이면 24행이라 지점당 1호출로 끝난다 */
    private static final String STEP_MIN = "60";
    private static final String MAX_ROWS = "300";

    /** predcDt 에 타임존 표기가 없다. KHOA 는 KST 다 (ROMS 와 같은 판단, 2026-09-13) */
    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");
    private static final DateTimeFormatter PREDC_DT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    protected final OceanApiClient client;
    private final SeaObsStore store;
    private final String stationResource;

    /** 지점 목록은 리소스라 한 번만 읽는다 */
    private volatile List<KhoaStations.Station> stations;

    protected KhoaForecastCollector(OceanApiClient client, SeaObsStore store, String stationResource) {
        this.client = client;
        this.store = store;
        this.stationResource = stationResource;
    }

    /** 한 행을 만든다. 단위 변환은 구현이 한다 — 원본이 cm/s · cm · 16방위 한글이다 */
    protected abstract SeaObsStation row(KhoaStations.Station station, double lat, double lon,
                                         Instant predcDt, JsonNode item);

    /**
     * 오늘부터 몇 일치를 받나. 1회 수집 = <b>지점 수 × 이 값</b> 만큼의 호출이다.
     *
     * 기본 1(오늘치 24행). 화면이 48시간 창을 쓰는 소스만 늘린다 —
     * 쓰지 않는 소스까지 늘리면 호출만 배가 된다.
     */
    protected int forecastDays() {
        return 1;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        List<KhoaStations.Station> targets = stations();
        if (targets.isEmpty()) {
            // 리소스를 못 읽었다. 호출해 봐야 obsCode 가 없어 전부 거부당한다
            return new CollectOutcome("NO_STATIONS", "예보지점 목록이 비었다", null, null);
        }
        LocalDate today = LocalDate.now(SOURCE_ZONE);
        int days = forecastDays();
        List<SeaObsStation> rows = new ArrayList<>();
        int failed = 0;
        OceanResponse lastFailure = null;
        boolean quotaGone = false;

        for (KhoaStations.Station station : targets) {
            if (quotaGone) {
                break;
            }
            // 실패는 **지점 단위**로 센다 — 한 지점의 이틀이 다 실패해도 "1곳 실패"다
            boolean stationFailed = false;
            for (int day = 0; day < days; day++) {
                OceanResponse response = client.get(source(), config, key,
                        params(station.code(), today.plusDays(day)));
                if (response.isNoData()) {
                    // 그 지점의 그 날짜만 없다. 나머지 날짜·지점은 계속 받는다
                    continue;
                }
                if (!response.isOk()) {
                    stationFailed = true;
                    lastFailure = response;
                    if (OceanResponse.QUOTA_GUARD.equals(response.code())) {
                        // 예산이 없다. 남은 지점도 같은 결과라 부르지 않는다
                        log.warn("[ocean] {} — 예산 소진, {}지점에서 중단", source(), rows.size());
                        quotaGone = true;
                    }
                    // 이 지점의 남은 날짜도 부르지 않는다 — 같은 지점이 연달아 실패하는 원인은 대개 같다
                    break;
                }
                rows.addAll(parse(station, response.body()));
            }
            if (stationFailed) {
                failed++;
            }
        }

        if (rows.isEmpty()) {
            // 한 행도 못 받았다. 기존 값을 덮지 않는다(§9.10)
            return lastFailure != null
                    ? CollectOutcome.from(lastFailure)
                    : new CollectOutcome(OceanResponse.NO_DATA, "예보 없음", null, null);
        }
        int saved = store.record(source(), rows, Instant.now());
        Instant baseAt = rows.stream().map(SeaObsStation::observedAt).min(Instant::compareTo).orElse(null);
        Map<String, Object> payload = payload(rows, saved, targets.size(), failed);
        log.info("[ocean] {} — 지점 {}곳 × {}일 · 행 {}건 저장 (실패 {}곳), 기준 {}",
                source(), targets.size() - failed, days, saved, failed, baseAt);
        return failed > 0 && lastFailure != null
                // 일부는 받았다. 현황은 남기고 결과 코드로 실패를 드러낸다
                ? new CollectOutcome(lastFailure.code(), "지점 %d곳 실패".formatted(failed), baseAt, payload)
                : CollectOutcome.ok(baseAt, payload);
    }

    private List<KhoaStations.Station> stations() {
        List<KhoaStations.Station> loaded = stations;
        if (loaded == null) {
            loaded = KhoaStations.load(stationResource);
            stations = loaded;
        }
        return loaded;
    }

    private Map<String, String> params(String obsCode, LocalDate date) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("type", "json");   // ⚠ 기본값이 xml
        params.put("obsCode", obsCode);
        params.put("reqDate", date.format(YMD));
        params.put("min", STEP_MIN);
        params.put("numOfRows", MAX_ROWS);
        return params;
    }

    private List<SeaObsStation> parse(KhoaStations.Station station, JsonNode body) {
        List<SeaObsStation> rows = new ArrayList<>();
        for (JsonNode item : items(body)) {
            Instant predcDt = parsePredcDt(text(item, "predcDt"));
            Double lat = number(item, "lat");
            Double lon = number(item, "lot");   // ⚠ lon 아니다. ROMS 와 같은 함정
            if (predcDt == null || lat == null || lon == null) {
                continue;
            }
            rows.add(row(station, lat, lon, predcDt, item));
        }
        return rows;
    }

    /** 요약 payload. 지점마다 **지금 이후 가장 이른** 예보 한 줄 — 화면이 "지금 값"으로 읽는 것 */
    private Map<String, Object> payload(List<SeaObsStation> rows, int saved, int stationCount, int failed) {
        Instant now = Instant.now();
        Map<String, SeaObsStation> nearest = new LinkedHashMap<>();
        rows.stream()
                .filter(r -> !r.observedAt().isBefore(now))
                .sorted(Comparator.comparing(SeaObsStation::observedAt))
                .forEach(r -> nearest.putIfAbsent(r.stn(), r));

        List<Map<String, Object>> stationRows = new ArrayList<>();
        for (SeaObsStation s : nearest.values()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("code", s.stn());
            row.put("name", s.name());
            row.put("lat", s.lat());
            row.put("lon", s.lon());
            // ISO 문자열. jsonb 에 Instant 를 그대로 두면 epoch 초가 된다
            row.put("predcDt", s.observedAt().toString());
            putIfPresent(row, "currentDirDeg", s.currentDirDeg());
            putIfPresent(row, "currentSpeedMs", s.currentSpeedMs());
            putIfPresent(row, "tideLevelM", s.tideLevelM());
            stationRows.add(row);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("stationCount", stationRows.size());
        payload.put("requestedStations", stationCount);
        payload.put("failedStations", failed);
        payload.put("rowCount", saved);
        payload.put("stations", stationRows);
        return payload;
    }

    private static void putIfPresent(Map<String, Object> row, String key, Double value) {
        if (value != null) {
            row.put(key, value);
        }
    }

    /** 결측은 null 로 둔다. 0 으로 두면 "유속 0" 과 "값 없음" 이 같아진다 */
    protected static Double number(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() || !value.isNumber() ? null : value.asDouble();
    }

    protected static String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (value.isMissingNode() || value.isNull()) {
            return null;
        }
        String raw = value.asString();
        return raw == null || raw.isBlank() ? null : raw.trim();
    }

    /** 1건이면 item 이 객체, 0건이면 items 가 빈 문자열 — 포털 공통 함정 */
    static List<JsonNode> items(JsonNode body) {
        List<JsonNode> list = new ArrayList<>();
        if (body == null) {
            return list;
        }
        JsonNode item = body.path("items").path("item");
        if (item.isObject()) {
            list.add(item);
        } else if (item.isArray()) {
            item.forEach(list::add);
        }
        return list;
    }

    static Instant parsePredcDt(String raw) {
        if (raw == null) {
            return null;
        }
        try {
            return LocalDateTime.parse(raw.trim(), PREDC_DT).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] predcDt 판독 실패: '{}'", raw);
            return null;
        }
    }
}

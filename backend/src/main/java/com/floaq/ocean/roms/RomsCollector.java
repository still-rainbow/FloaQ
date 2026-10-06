package com.floaq.ocean.roms;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanRetention;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.cluster.InstanceId;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * KHOA ROMS 수치예측모델 — 표류 범위 추정의 유일한 입력 (§6).
 *
 * HF-RADAR 기각: 실측이나 최신이 7시간 전 (2026-09-11 실측).
 *
 * 명세 p-shim/ref/openapi/오픈API 활용가이드_ROMS 수치예측모델.pdf
 *
 * 요청  serviceKey · type=json · ymin·ymax·xmin·xmax(필수, 차이 각각 ≤1도) · pageNo · numOfRows(≤300)
 * 응답  predcDt "2026-09-13 00:00:00"(KST) · lat · lot · crdir(deg) · crsp(m/s) · wtem(℃)
 *
 * 수집 단위 — **0.25° 타일** (2026-09-15, {@link RomsTile}). 조회가 부른 타일만 받는다({@link RomsTileService}).
 *
 * 매시 이 수집기가 하는 일 (스케줄러 리스라 인스턴스 하나만 돈다)
 *   1. 새 예측본 확인 — 지금 세대로 받은 활성 타일 하나를 1페이지만 받아 저장값과 비교, 다르면 세대 +1
 *      예측본은 하루 1회 갱신(2026-09-15 사용자 확인)인데 발표 시각이 응답에 없어 시각으로 못 정한다.
 *      비교는 키 단위라 응답 정렬 순서와 무관 (정렬 순서는 문서에 없음)
 *      기각: 하루 1회 고정 시각 수집 — 생산보다 먼저 부르면 하루를 통째로 놓침
 *   2. 활성 타일 갱신 — 최근 24시간 조회됐고, 옛 세대이거나 받은 지 24시간 지난 타일을 다시 받는다
 *
 * 하루 호출(추정): 확인 24 + 활성 타일 수 × 약 24페이지. 한 척이 한 바다에 머물면 타일 1~4개.
 *
 * ⚠ 한계: 새 예측본인데 확인 1페이지 값이 전부 같으면 놓침 → {@link #FULL_REFRESH} 24시간이 바닥
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RomsCollector implements OceanCollector {

    public static final String SOURCE = "roms";

    /** 가이드 명시 상한. 초과 시 조용히 잘림 */
    private static final int MAX_ROWS_PER_PAGE = 300;

    /**
     * 타일당 페이지 상한 = 18,000건. 설정 실수를 막는 장치이지 쿼터 보호가 아니다 —
     * 쿼터는 OceanCallBudget 이 페이지 단위로 센다.
     *
     * 2026-09-13 실측 totalCount: 0.1° 1,424(5p) · 0.3° 10,324(35p) · 0.5° 29,726(100p).
     * 0.25° 타일은 약 24페이지(면적 비 추정)라 60이면 여유가 있다.
     */
    private static final int MAX_PAGES = 60;

    /**
     * 강제 재수집 간격. 24시간 근거: 예측본 갱신이 하루 1회(2026-09-15 사용자 확인).
     * 1페이지 비교가 새 예측본을 놓쳐도 하루를 넘겨 낡지 않게 하는 바닥
     */
    static final Duration FULL_REFRESH = Duration.ofHours(24);

    /** 타일 수집 리스. 약 24페이지 × 0.22초 ≈ 5초(추정)에 넉넉히 — 인스턴스가 받다 죽으면 이만큼 뒤 다른 인스턴스가 잡는다 */
    static final Duration TILE_LEASE = Duration.ofMinutes(5);

    /** 실패 타일 재시도 간격. 60초 근거: kiosk 조회 폴링 주기 — 매 폴링이 실패 타일을 다시 부르며 쿼터를 태우지 않게 */
    static final Duration RETRY_AFTER = Duration.ofSeconds(60);

    /**
     * 원본에 타임존 표기 없음. KST 확정 (2026-09-13).
     *
     * 근거: 표층 수온 일주기 위상 — 최고 14~17시, 최저 06~09시.
     * UTC 라면 라벨이 05~08시로 찍힘.
     */
    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter PREDC_DT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final OceanApiClient client;
    private final OceanRomsStore store;
    private final RomsTileStore tiles;
    private final InstanceId instance;

    @Override
    public String source() {
        return SOURCE;
    }

    /** 매시 — 새 예측본 확인 + 활성 타일 갱신 */
    @Override
    public CollectOutcome collect(Source config, String key) {
        long generation = tiles.generation();
        Optional<RomsTile> probe = tiles.probeCandidate(generation, RomsTileStore.ACTIVE_WINDOW);
        if (probe.isPresent()) {
            CollectOutcome failed = checkForecast(config, key, probe.get(), generation);
            if (failed != null) {
                // 확인조차 못 불렀다(쿼터·키·장애). 갱신도 같은 결과라 부르지 않는다
                return failed;
            }
        }

        int refreshed = 0;
        int failedTiles = 0;
        CollectOutcome lastFailure = null;
        for (RomsTile tile : tiles.dueForRefresh(tiles.generation(), RomsTileStore.ACTIVE_WINDOW, FULL_REFRESH)) {
            CollectOutcome outcome = collectTile(config, key, tile);
            if (outcome == null) {
                continue;   // 못 잡음 — 다른 인스턴스가 받는 중이거나 재시도 간격 안
            }
            if (outcome.isSuccess() || OceanResponse.NO_DATA.equals(outcome.resultCode())) {
                refreshed++;
                continue;
            }
            failedTiles++;
            lastFailure = outcome;
            if (OceanResponse.QUOTA_GUARD.equals(outcome.resultCode())) {
                // 예산이 없다. 남은 타일도 같은 결과라 부르지 않는다
                break;
            }
        }

        RomsTileStore.Stats stats = tiles.stats(RomsTileStore.ACTIVE_WINDOW);
        Instant baseAt = store.latestBaseAt().orElse(null);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("tileDeg", RomsTile.DEG);
        payload.put("activeTiles", stats.active());
        payload.put("collectedTiles", stats.collected());
        payload.put("generation", tiles.generation());
        payload.put("refreshedTiles", refreshed);
        payload.put("failedTiles", failedTiles);
        // ISO 문자열로 넣는다. jsonb 는 Hibernate 의 Jackson 이 따로 써서 Instant 가 epoch 초가 된다
        payload.put("baseAt", iso(baseAt));
        if (lastFailure != null) {
            // 현황 payload 는 남기고 결과 코드로 실패를 드러낸다 — 받은 타일들은 그대로 유효하다
            return new CollectOutcome(lastFailure.resultCode(),
                    "타일 %d개 실패 — %s".formatted(failedTiles, Objects.toString(lastFailure.resultMsg(), "")),
                    baseAt, payload);
        }
        return CollectOutcome.ok(baseAt, payload);
    }

    /**
     * 새 예측본인가 — 지금 세대로 받은 타일 하나를 1페이지만 받아 저장값과 비교한다.
     *
     * @return 확인 호출 자체가 실패했으면 그 결과. 비교를 마쳤으면(같음·다름·판정 불가) null
     */
    private CollectOutcome checkForecast(Source config, String key, RomsTile tile, long generation) {
        OceanResponse first = client.get(SOURCE, config, key, params(tile, 1));
        if (!first.isOk()) {
            log.warn("[ocean] roms 확인 1페이지 실패 — {} {}", first.code(), first.message());
            return CollectOutcome.from(first);
        }
        // 이웃 타일 경계 점이 섞여 온다 — 이 타일이 갖는 점만 비교한다. 섞으면 이웃이 안 받은 타일일 때 늘 "다르다"
        List<RomsGrid> probe = parseItems(first.body()).stream()
                .filter(g -> tile.owns(g.lat(), g.lon()))
                .toList();
        if (probe.isEmpty()) {
            // 비교할 행이 없다. "다르다"로 읽으면 매시 세대를 올려 활성 타일을 전부 다시 받는다
            log.warn("[ocean] roms {} — 확인 1페이지에 이 타일 격자가 없다. 판정을 건너뛴다", tile);
            return null;
        }
        if (OceanRomsStore.matches(probe, store.storedLike(probe), OceanRetention.cutoff(Instant.now()))) {
            // INFO — 매시 한 줄. debug 면 "확인만 했는지 갱신했는지"를 로그로 가를 수 없음
            log.info("[ocean] roms — 예측본 그대로, 1페이지 확인만 ({})", tile);
            return null;
        }
        if (tiles.advanceGeneration(generation)) {
            log.info("[ocean] roms — 새 예측본 (세대 {} → {}). 활성 타일을 다시 받는다", generation, generation + 1);
        }
        return null;
    }

    /**
     * 타일 하나를 받는다. DB 리스를 잡은 인스턴스만 부른다.
     *
     * @return 못 잡았으면 null (이미 최신 · 다른 인스턴스가 받는 중 · 재시도 간격 안) — 호출 0
     */
    public CollectOutcome collectTile(Source config, String key, RomsTile tile) {
        long generation = tiles.generation();
        String owner = instance.value();
        if (!tiles.claim(tile, generation, owner, TILE_LEASE, RETRY_AFTER, FULL_REFRESH)) {
            return null;
        }
        CollectOutcome outcome;
        try {
            outcome = fetchTile(config, key, tile);
        } catch (RuntimeException e) {
            tiles.fail(tile, owner, "ERROR", e.getClass().getSimpleName());
            throw e;
        }
        if (outcome.isSuccess()) {
            tiles.succeed(tile, owner, generation, OceanResponse.OK);
        } else if (OceanResponse.NO_DATA.equals(outcome.resultCode())) {
            // 바다가 없는 타일. 받은 것으로 친다 — 매 조회가 같은 육지 타일을 다시 부르지 않게
            tiles.succeed(tile, owner, generation, OceanResponse.NO_DATA);
        } else {
            tiles.fail(tile, owner, outcome.resultCode(), outcome.resultMsg());
        }
        return outcome;
    }

    private CollectOutcome fetchTile(Source config, String key, RomsTile tile) {
        List<RomsGrid> grids = new ArrayList<>();
        int totalCount = 0;
        boolean complete = false;

        for (int page = 1; page <= MAX_PAGES; page++) {
            OceanResponse response = client.get(SOURCE, config, key, params(tile, page));
            if (!response.isOk()) {
                // 중간 페이지 실패 시 받은 것도 버림 — 반쪽 격자는 "그 방향에 데이터 없음"으로 오독됨
                log.warn("[ocean] roms {} {}페이지 실패 — {} {}", tile, page, response.code(), response.message());
                return CollectOutcome.from(response);
            }
            JsonNode body = response.body();
            totalCount = intOf(body, "totalCount");
            List<RomsGrid> parsed = parseItems(body);
            grids.addAll(parsed);

            if (parsed.isEmpty() || grids.size() >= totalCount) {
                complete = true;
                break;
            }
        }
        if (!complete) {
            // 반쪽 격자를 저장하지 않는다. API 정렬 순서대로 앞부분만 남아 특정 방향 해역이 통째로 빈다
            log.warn("[ocean] roms {} — {}건 중 {}건에서 페이지 상한", tile, totalCount, grids.size());
            return new CollectOutcome("PAGE_LIMIT",
                    "격자 %d/%d 건에서 페이지 상한".formatted(grids.size(), totalCount), null, null);
        }

        int saved = store.replaceTile(tile, grids, Instant.now());
        if (saved == 0) {
            // 응답 정상 + 격자 0건 = 이 타일에 바다 격자가 없다. 실패 아님
            return new CollectOutcome(OceanResponse.NO_DATA, "타일에 바다 격자 없음", null, null);
        }

        // 모델 발표 시각이 응답에 없다. 가장 이른 예측 시각으로 대신하는 근사다
        Instant baseAt = grids.stream().map(RomsGrid::predcDt).min(Instant::compareTo).orElse(null);
        if (firstForecastAt(grids, Instant.now()) == null) {
            // 예측본이 전부 과거다. 모델이 갱신되지 않았다는 신호이므로 조용히 넘기지 않는다
            log.warn("[ocean] roms {} — 미래 예측이 없다. 예측본이 낡았다 (기준 {})", tile, baseAt);
        }
        log.info("[ocean] roms {} — 격자 {}건 저장 (totalCount {}), 기준 {}", tile, saved, totalCount, baseAt);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("gridCount", saved);
        payload.put("totalCount", totalCount);
        payload.put("baseAt", iso(baseAt));
        return CollectOutcome.ok(baseAt, payload);
    }

    /** 요청 bbox = 타일 경계. 0.25 배수라 부동소수 잔차가 없지만 4자리로 찍는 규칙은 그대로 둔다 */
    private Map<String, String> params(RomsTile tile, int page) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("type", "json");   // ⚠ 기본값이 xml
        params.put("ymin", coord(tile.south()));
        params.put("ymax", coord(tile.north()));
        params.put("xmin", coord(tile.west()));
        params.put("xmax", coord(tile.east()));
        params.put("pageNo", String.valueOf(page));
        params.put("numOfRows", String.valueOf(MAX_ROWS_PER_PAGE));
        return params;
    }

    /**
     * 🔴 bbox 좌표는 소수 4자리로 자른다.
     *
     * 부동소수 잔차가 그대로 실리면 거부된다 (2026-09-13 실측) —
     * {@code ymin=35.048000000000002} 는 resultCode 10 INVALID_REQUEST_PARAMETER_ERROR,
     * {@code ymin=35.0480} 은 정상이다.
     *
     * 4자리 = 11m 로 격자 간격(약 3km)보다 훨씬 촘촘해 선택이 달라지지 않는다.
     * 로캘 무관하게 점을 쓴다 — 일부 로캘은 쉼표를 소수점으로 찍는다.
     */
    static String coordFor(double deg) {
        return coord(deg);
    }

    private static String coord(double deg) {
        return String.format(java.util.Locale.ROOT, "%.4f", deg);
    }

    /**
     * body.items.item[] 파싱.
     *
     * 포털 공통 함정 흡수 — 1건이면 item 이 객체, 0건이면 items 가 빈 문자열.
     */
    static List<RomsGrid> parseItems(JsonNode body) {
        List<RomsGrid> grids = new ArrayList<>();
        if (body == null) {
            return grids;
        }
        JsonNode item = body.path("items").path("item");
        if (item.isObject()) {
            toGrid(item).ifPresent(grids::add);
        } else if (item.isArray()) {
            item.forEach(node -> toGrid(node).ifPresent(grids::add));
        }
        return grids;
    }

    private static Optional<RomsGrid> toGrid(JsonNode node) {
        Instant predcDt = parsePredcDt(stringOf(node, "predcDt"));
        if (predcDt == null) {
            return Optional.empty();
        }
        JsonNode lat = node.path("lat");
        JsonNode lon = node.path("lot");   // ⚠ lon 아님. 틀리면 전부 0 — 지도가 서아프리카를 가리킴
        if (lat.isMissingNode() || lon.isMissingNode()) {
            return Optional.empty();
        }
        return Optional.of(new RomsGrid(predcDt, lat.asDouble(), lon.asDouble(),
                nullableDouble(node, "crdir"),
                nullableDouble(node, "crsp"),
                nullableDouble(node, "wtem")));
    }

    private static int intOf(JsonNode body, String field) {
        JsonNode value = body == null ? null : body.path(field);
        return value == null || !value.isNumber() ? 0 : value.asInt();
    }

    private static String stringOf(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? null : value.asString();
    }

    /** null 유지. 0.0 대체 시 유향이 '북'으로 읽힘 */
    private static Double nullableDouble(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() || !value.isNumber() ? null : value.asDouble();
    }

    /** 형식이 다른 행만 버림 — 수집 전체를 중단시키지 않음 */
    static Instant parsePredcDt(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return LocalDateTime.parse(raw.trim(), PREDC_DT).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] roms — predcDt 판독 실패: '{}'", raw);
            return null;
        }
    }

    private static String iso(Instant at) {
        return at == null ? null : at.toString();
    }

    /**
     * 지금 이후 가장 이른 예측 시각.
     *
     * 예측본이 당일 00시부터 시작해 과거가 섞여 오므로 min(predcDt) 를 쓰면 안 된다.
     *
     * @return 미래 예측이 없으면 null — 예측본이 낡았다는 신호다
     */
    static Instant firstForecastAt(List<RomsGrid> grids, Instant now) {
        return grids.stream().map(RomsGrid::predcDt)
                .filter(t -> !t.isBefore(now))
                .min(Instant::compareTo)
                .orElse(null);
    }
}

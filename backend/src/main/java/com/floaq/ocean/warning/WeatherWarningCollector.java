package com.floaq.ocean.warning;

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
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 기상청 기상특보 — 위험 알리미(APP-02) 판단 기준. 임계치를 만들지 않고 국가 기준 인용 (§6).
 *
 * 오퍼레이션 둘 (같은 서비스·같은 키)
 *   getPwnCd      특보구역별 이벤트. 해역·종류·강도·발표구분이 필드 → 발효 판정
 *   getPwnStatus  기상청이 정리한 현재 발효현황·예비특보 문장 → 화면 요약 · 교차 확인
 *
 * getWthrWrnList(title 파싱) 기각 (2026-09-14) — 해역 없음 · 가운뎃점 문법 두 벌 · "해제예고연장" 함정.
 *
 * 2026-09-14 실호출
 *   response 봉투 있음 (KHOA 와 다름. OceanResponse 가 처리)
 *   숫자·문자열 혼재 — tmFc·warnVar 숫자, command·cancel 문자열. 전부 문자열로 읽어 변환
 *   t6 "o 없 음" — 글자 사이 공백
 *
 * 조업 해역 판정 — 설정 코드(stn-id) + warning-zone 계층(상위·하위 구역). 전국 목록은 그대로 둠.
 * 좌표 판정 기각: 기상청이 특보구역 공간정보를 보유·제공하지 않음 (2026-09-14 회신).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WeatherWarningCollector implements OceanCollector {

    public static final String SOURCE = "weather-warning";

    private static final String CODE_OP = "getPwnCd";
    private static final String STATUS_OP = "getPwnStatus";

    /** 6일 창 107건 (2026-09-14 실측). 태풍철 급증 여유 */
    private static final int ROWS = 1000;

    /** getWthrWrnList 는 7일에 99 거부, getPwnCd 7일은 totalCount 와 반환 건수 불일치 → 6일 */
    private static final int DEFAULT_WINDOW_DAYS = 6;

    /** 상황판 목록 길이 */
    private static final int RECENT_EVENTS = 20;

    /** 현황 문장에서 해상 특보를 알아보는 단어. 교차 확인 전용 */
    private static final List<String> MARINE_WORDS = List.of("풍랑", "폭풍해일", "태풍");

    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");
    private static final DateTimeFormatter TM = DateTimeFormatter.ofPattern("yyyyMMddHHmm");

    private final OceanApiClient client;
    private final OceanSnapshotService snapshots;

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        OceanResponse codes = client.get(SOURCE, operation(config, CODE_OP), key, codeParams(config));
        // 03 = 창 안에 이벤트 없음. 실패 아님
        if (codes.isFailure()) {
            return CollectOutcome.from(codes);
        }
        List<WarningAreaEvent> events = parseEvents(codes.isOk() ? codes.body() : null);

        OceanResponse status = client.get(SOURCE, operation(config, STATUS_OP), key, statusParams());
        JsonNode statusItem = status.isOk() ? items(status.body()).stream().findFirst().orElse(null) : null;
        if (statusItem == null) {
            // 구역 판정은 살림. 요약 문장만 빠짐
            log.warn("[ocean] weather-warning — 특보현황 없음 {} {}", status.code(), status.message());
        }

        List<String> focusCodes = focusCodes(config.stnId());
        WarningZones zones = focusCodes.isEmpty() ? WarningZones.empty() : zones();
        Map<String, Object> payload = payload(events, statusItem, focusCodes, zones);
        crossCheck(payload);
        log.info("[ocean] weather-warning — 해상 이벤트 {}건, 발효 중 {}, 조업 해역 {}",
                payload.get("eventCount"), payload.get("activeMarineWarnings"),
                payload.get("focus") instanceof Map<?, ?> f ? f.get("activeMarineWarnings") : "미설정");
        return CollectOutcome.ok(latestAnnouncement(events, statusItem), payload);
    }

    /** base-url 은 서비스 루트. 오퍼레이션 경로만 붙인 사본 */
    static Source operation(Source config, String op) {
        String base = config.baseUrl().endsWith("/") ? config.baseUrl() : config.baseUrl() + "/";
        return new Source(config.provider(), base + op, config.apiKey(), config.kind(), config.stnId(),
                config.windowDays(), config.intervalSec(), config.dailyQuota(), config.enabled());
    }

    /** "S1311100,S1312010" → 목록. 비면 조업 해역 판정 안 함 */
    static List<String> focusCodes(String raw) {
        if (raw == null || raw.isBlank()) {
            return List.of();
        }
        return Arrays.stream(raw.split(",")).map(String::strip).filter(s -> !s.isEmpty()).distinct().toList();
    }

    /** warning-zone 스냅샷. 없으면 설정 코드만으로 판정 */
    private WarningZones zones() {
        WarningZones zones = snapshots.find(WarningZoneCollector.SOURCE)
                .map(OceanSnapshot::getPayload)
                .map(WarningZones::fromPayload)
                .orElse(WarningZones.empty());
        if (zones.isEmpty()) {
            log.warn("[ocean] weather-warning — 특보구역 계층 없음. 상위 구역 특보는 조업 해역 판정에서 빠짐");
        }
        return zones;
    }

    static List<WarningAreaEvent> parseEvents(JsonNode body) {
        List<WarningAreaEvent> events = new ArrayList<>();
        for (JsonNode item : items(body)) {
            String areaCode = text(item, "areaCode");
            if (areaCode == null) {
                log.warn("[ocean] weather-warning — areaCode 없는 이벤트 건너뜀: {}", item);
                continue;
            }
            Instant start = parseTm(text(item, "startTime"));
            events.add(new WarningAreaEvent(
                    parseTm(text(item, "tmFc")), toInt(text(item, "tmSeq")),
                    areaCode, text(item, "areaName"),
                    toInt(text(item, "warnVar")), toInt(text(item, "warnStress")), toInt(text(item, "command")),
                    "1".equals(text(item, "cancel")),
                    start != null ? start : parseTm(text(item, "endTime"))));
        }
        return events;
    }

    static Map<String, Object> payload(List<WarningAreaEvent> events, JsonNode statusItem) {
        return payload(events, statusItem, List.of(), WarningZones.empty());
    }

    static Map<String, Object> payload(List<WarningAreaEvent> events, JsonNode statusItem,
                                       List<String> focusCodes, WarningZones zones) {
        List<WarningAreaEvent> marine = events.stream()
                .filter(WarningAreaEvent::isMarine)
                .sorted(WarningAreaEvent.NEWEST_FIRST)
                .toList();
        List<WarningAreaEvent> active = WarningAreaEvent.activeMarine(events);

        Map<String, Object> payload = new LinkedHashMap<>();
        // 전국 기준. 기존 키 유지 — 비면 발효 중 해상 특보 없음
        payload.put("activeMarineWarnings", active.stream().map(WarningAreaEvent::name).distinct().toList());
        payload.put("activeAreas", active.stream().map(WeatherWarningCollector::area).toList());
        payload.put("status", status(statusItem));
        payload.put("eventCount", marine.size());
        payload.put("events", marine.stream().limit(RECENT_EVENTS).map(WeatherWarningCollector::event).toList());
        payload.put("focus", focusCodes.isEmpty() ? null : focus(active, focusCodes, zones));
        return payload;
    }

    /** 조업 해역 판정. 전국 목록을 거르지 않고 따로 둠 — 남의 해역 특보가 우리 경보로 읽히지 않게 */
    private static Map<String, Object> focus(List<WarningAreaEvent> active, List<String> codes, WarningZones zones) {
        Set<String> related = zones.related(codes);
        List<WarningAreaEvent> hits = active.stream().filter(e -> related.contains(e.areaCode())).toList();
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("codes", codes);
        // 이름은 계층에서. 모르면 코드 그대로 — 지어내지 않음
        f.put("names", codes.stream().map(c -> Objects.requireNonNullElse(zones.name(c), c)).toList());
        f.put("hierarchy", !zones.isEmpty());
        f.put("relatedCount", related.size());
        f.put("activeMarineWarnings", hits.stream().map(WarningAreaEvent::name).distinct().toList());
        f.put("activeAreas", hits.stream().map(WeatherWarningCollector::area).toList());
        return f;
    }

    /** "o " 머리표와 빈 줄 제거. 문장은 유지 — 해역 구분이 문장 안에 있음 */
    static String clean(String raw) {
        if (raw == null) {
            return null;
        }
        String text = Arrays.stream(raw.split("\\r?\\n"))
                .map(String::trim)
                .map(line -> line.startsWith("o ") ? line.substring(2).trim() : line)
                .filter(line -> !line.isEmpty())
                .collect(Collectors.joining("\n"));
        return text.isEmpty() ? null : text;
    }

    /** "o 없 음" 처럼 머리표·글자 사이 공백이 옴 (2026-09-14 실응답). 원문·정리본 둘 다 받음 */
    public static boolean isNone(String text) {
        String cleaned = clean(text);
        return cleaned == null || cleaned.replaceAll("\\s", "").equals("없음");
    }

    /** 구역 판정과 기상청 현황이 어긋나면 로그. 창 이전 특보가 남은 경우라 판정은 바꾸지 않음 */
    @SuppressWarnings("unchecked")
    private static void crossCheck(Map<String, Object> payload) {
        if (!(payload.get("status") instanceof Map<?, ?> status)) {
            return;
        }
        String current = (String) status.get("current");
        boolean statusMarine = !isNone(current) && MARINE_WORDS.stream().anyMatch(current::contains);
        List<String> active = (List<String>) payload.get("activeMarineWarnings");
        if (active.isEmpty() == statusMarine) {
            log.warn("[ocean] weather-warning — 판정 불일치: 구역 이벤트 {} / 현황 '{}'", active, current);
        }
    }

    private static Map<String, Object> area(WarningAreaEvent e) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("areaCode", e.areaCode());
        row.put("areaName", e.areaName());
        row.put("kind", e.kind());
        row.put("level", e.level());
        row.put("name", e.name());
        row.put("since", iso(e.effectiveAt() != null ? e.effectiveAt() : e.announcedAt()));
        return row;
    }

    private static Map<String, Object> event(WarningAreaEvent e) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("announcedAt", iso(e.announcedAt()));
        row.put("areaName", e.areaName());
        row.put("name", e.name());
        row.put("action", e.action());
        return row;
    }

    private static Map<String, Object> status(JsonNode item) {
        if (item == null) {
            return null;
        }
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("announcedAt", iso(parseTm(text(item, "tmFc"))));
        s.put("effectiveAt", iso(parseTm(text(item, "tmEf"))));
        s.put("current", clean(text(item, "t6")));
        s.put("preliminary", clean(text(item, "t7")));
        s.put("note", clean(text(item, "other")));
        return s;
    }

    private static Instant latestAnnouncement(List<WarningAreaEvent> events, JsonNode statusItem) {
        return events.stream()
                .map(WarningAreaEvent::announcedAt)
                .filter(Objects::nonNull)
                .max(Comparator.naturalOrder())
                .orElseGet(() -> statusItem == null ? null : parseTm(text(statusItem, "tmFc")));
    }

    private Map<String, String> codeParams(Source config) {
        LocalDate today = LocalDate.now(SOURCE_ZONE);
        int windowDays = config.windowDays() > 0 ? config.windowDays() : DEFAULT_WINDOW_DAYS;
        Map<String, String> params = new LinkedHashMap<>();
        params.put("pageNo", "1");
        params.put("numOfRows", String.valueOf(ROWS));
        params.put("dataType", "JSON");
        params.put("fromTmFc", today.minusDays(windowDays).format(YMD));
        params.put("toTmFc", today.format(YMD));
        return params;
    }

    private static Map<String, String> statusParams() {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("pageNo", "1");
        params.put("numOfRows", "10");
        params.put("dataType", "JSON");
        return params;
    }

    private static List<JsonNode> items(JsonNode body) {
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

    private static String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (value.isMissingNode() || value.isNull()) {
            return null;
        }
        String raw = value.asString();
        return raw == null || raw.isBlank() ? null : raw.trim();
    }

    /** 못 읽으면 -1. 미지 코드로 흘러 발효 유지 쪽으로 처리됨 */
    private static int toInt(String raw) {
        if (raw == null) {
            return -1;
        }
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** yyyyMMddHHmm (KST). 0 은 "해당 없음" */
    private static Instant parseTm(String raw) {
        if (raw == null || "0".equals(raw)) {
            return null;
        }
        try {
            return LocalDateTime.parse(raw, TM).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] weather-warning — 시각 판독 실패: '{}'", raw);
            return null;
        }
    }

    /** jsonb 에 Instant 를 그대로 두면 epoch 초가 됨 */
    private static String iso(Instant at) {
        return at == null ? null : at.toString();
    }
}

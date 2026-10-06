package com.floaq.ocean.shipindex;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanUnits;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * KHOA 선박운항지수 — 항해 탭 "언제 갈까"의 참고 지수 (§9.18).
 *
 * 자체 임계치 기각 — KHOA 가 해양·기상·선박조건으로 만든 5단계 지수 인용 (§6 원칙).
 * 출항 판정 근거 아님. 기상특보가 우선. 권역이 넓어(대한해협 하나) 연안 국지 상황은 못 담음.
 *
 * AREA(권역) 7곳만 씀. LINE·PORT·MARINA·YACHT 는 여객선·항만·레저 대상.
 *
 * 2026-09-14 실호출
 *   response 봉투 없음. 7권역 × 20구간 = 140행 (같은 날 오전 112행 — 시각에 따라 구간 수 변동)
 *   구간: 앞 이틀 새벽·오전·오후·밤(00/06/12/18시), 이후 오전·오후(06/12시). 약 6일
 *   lastScrCn 문자열 — 좋음·보통·나쁨·매우나쁨 확인. 매우좋음은 가이드 표기
 *   avgCrsp 단위 kn (ROMS m/s · HF cm/s 와 다름)
 *   응답에 권역 코드 없음, 이름만
 *
 * 한계: 권역 좌표가 없어 본선 위치로 권역 자동 판정 불가 → stn-id 설정값
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ShipIndexCollector implements OceanCollector {

    public static final String SOURCE = "ship-index";

    private static final String CATEGORY = "AREA";

    /** 7권역 × 최대 20구간 = 140 (2026-09-14 실측). 한 페이지로 끝남 */
    private static final int ROWS = 300;

    /** 설정이 비었을 때. app.ocean.area 부산 앞 임시 해역과 같은 권역 */
    private static final String DEFAULT_FOCUS = "AA_0004";

    /** 활용가이드 p.3 선박운항지점 목록 (AREA) */
    static final Map<String, String> AREA_CODES = Map.of(
            "AA_0001", "황해중부", "AA_0002", "황해남부", "AA_0003", "제주해협", "AA_0004", "대한해협",
            "AA_0005", "제주남부", "AA_0006", "동해남부", "AA_0007", "동해중부");

    /** 가이드 5단계. 문자열 비교를 화면마다 흩지 않음 */
    private static final Map<String, Integer> LEVELS = Map.of(
            "매우좋음", 1, "좋음", 2, "보통", 3, "나쁨", 4, "매우나쁨", 5);

    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");

    private final OceanApiClient client;

    /** 권역 하나의 예보 구간 하나 */
    record Slot(String area, Instant at, String slot, String score, Integer level,
                Double currentSpeedMs, Double windSpeedMs, Double waveHeightM) {
    }

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("type", "json");
        params.put("category", CATEGORY);
        params.put("pageNo", "1");
        params.put("numOfRows", String.valueOf(ROWS));
        OceanResponse response = client.get(SOURCE, config, key, params);
        if (!response.isOk()) {
            return CollectOutcome.from(response);
        }

        List<Slot> slots = parse(response.body());
        if (slots.isEmpty()) {
            return new CollectOutcome(OceanResponse.NO_DATA, "운항지수 없음", null, null);
        }
        String focus = config.stnId() == null || config.stnId().isBlank() ? DEFAULT_FOCUS : config.stnId().trim();
        Map<String, Object> payload = payload(slots, focus, Instant.now());

        // 예보 소스 관례 — observedAt 은 가장 이른 예보 구간. 발표 시각이 응답에 없어 근사
        Instant base = slots.stream().map(Slot::at).min(Comparator.naturalOrder()).orElse(null);
        log.info("[ocean] ship-index — {}행, {} 지금 {}", slots.size(), payload.get("focusName"), payload.get("current"));
        return CollectOutcome.ok(base, payload);
    }

    static List<Slot> parse(JsonNode body) {
        List<Slot> slots = new ArrayList<>();
        Set<String> unknown = new LinkedHashSet<>();
        for (JsonNode item : items(body)) {
            String area = text(item, "vslNvgtBrnchCdNm");
            Instant at = parseAt(text(item, "predcYmd"), text(item, "predcTm"));
            if (area == null || at == null) {
                log.warn("[ocean] ship-index — 판독 불가 행 건너뜀: {}", item);
                continue;
            }
            String score = text(item, "lastScrCn");
            Integer level = score == null ? null : LEVELS.get(score);
            if (score != null && level == null) {
                unknown.add(score);
            }
            Double knots = number(item, "avgCrsp");
            slots.add(new Slot(area, at, text(item, "predcNoonSeCd"), score, level,
                    knots == null ? null : round2(OceanUnits.fromKnots(knots)),
                    number(item, "avgWspd"), number(item, "avgWvhgt")));
        }
        if (!unknown.isEmpty()) {
            // 등급 없이 문구만 보임. 행은 버리지 않음
            log.warn("[ocean] ship-index — 모르는 지수 문구 {}", unknown);
        }
        return slots;
    }

    static Map<String, Object> payload(List<Slot> slots, String focusCode, Instant now) {
        Map<String, List<Slot>> byArea = new LinkedHashMap<>();
        slots.forEach(s -> byArea.computeIfAbsent(s.area(), k -> new ArrayList<>()).add(s));
        byArea.values().forEach(list -> list.sort(Comparator.comparing(Slot::at)));

        String focusName = AREA_CODES.get(focusCode);
        if (focusName == null) {
            log.warn("[ocean] ship-index — 모르는 권역 코드 '{}'", focusCode);
        }
        Slot current = focusName == null ? null : currentSlot(byArea.getOrDefault(focusName, List.of()), now);

        List<Map<String, Object>> areas = new ArrayList<>();
        byArea.forEach((name, list) -> {
            Map<String, Object> area = new LinkedHashMap<>();
            area.put("code", codeOf(name));
            area.put("name", name);
            area.put("slots", list.stream().map(ShipIndexCollector::slot).toList());
            areas.add(area);
        });

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("focusCode", focusCode);
        payload.put("focusName", focusName);
        // 화면 FORECAST 문구·stale 판정 기준. 지금 구간의 시작 시각
        payload.put("validAt", current == null ? null : current.at().toString());
        payload.put("current", current == null ? null : slot(current));
        payload.put("areas", areas);
        return payload;
    }

    /** 지금이 속한 구간 = 시작 시각이 now 이하인 마지막 구간. 전부 미래면 첫 구간 */
    static Slot currentSlot(List<Slot> sorted, Instant now) {
        Slot pick = null;
        for (Slot s : sorted) {
            if (s.at().isAfter(now)) {
                break;
            }
            pick = s;
        }
        return pick != null ? pick : sorted.stream().findFirst().orElse(null);
    }

    private static Map<String, Object> slot(Slot s) {
        Map<String, Object> row = new LinkedHashMap<>();
        // ISO 문자열. jsonb 에 Instant 를 그대로 두면 epoch 초가 됨
        row.put("at", s.at().toString());
        row.put("slot", s.slot());
        row.put("score", s.score());
        row.put("level", s.level());
        row.put("currentSpeedMs", s.currentSpeedMs());
        row.put("windSpeedMs", s.windSpeedMs());
        row.put("waveHeightM", s.waveHeightM());
        return row;
    }

    private static String codeOf(String name) {
        return AREA_CODES.entrySet().stream()
                .filter(e -> e.getValue().equals(name))
                .map(Map.Entry::getKey)
                .findFirst().orElse(null);
    }

    /** predcYmd "2026-09-14" + predcTm "06:00" (KST) */
    private static Instant parseAt(String ymd, String tm) {
        if (ymd == null || tm == null) {
            return null;
        }
        try {
            return LocalDate.parse(ymd).atTime(LocalTime.parse(tm)).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            return null;
        }
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

    /** 숫자로도 문자열로도 옴. 빈 값은 null — 0 으로 두면 "파고 0" 과 "값 없음" 이 같아짐 */
    private static Double number(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (value.isNumber()) {
            return value.doubleValue();
        }
        String raw = text(node, field);
        if (raw == null) {
            return null;
        }
        try {
            return Double.valueOf(raw);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static double round2(double v) {
        return Math.round(v * 100) / 100.0;
    }
}

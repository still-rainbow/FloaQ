package com.floaq.ocean.summary;

import com.floaq.ocean.entity.OceanSnapshot;
import com.floaq.ocean.warning.WeatherWarningCollector;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.BiFunction;

/**
 * 수집 결과에서 요약이 쓸 값만 추린다.
 *
 * 이 목록이 LLM 프롬프트의 입력이자 화면에 함께 뜨는 근거다 —
 * 문장만 보여 주면 "그 숫자 어디서 나왔냐"에 답할 수 없다.
 *
 * 호출을 쪼개지 않는다. 6종을 한 컨텍스트에 담아 한 번 부른다 (§9.18) —
 * 카테고리마다 부르면 크레딧이 4배가 되고 문장들끼리 앞뒤가 안 맞는다.
 */
public final class OceanFacts {

    /** 해역명 나열 상한. 전국 발효 시 수십 곳이라 문장이 목록이 됨 */
    private static final int MAX_AREAS = 4;

    /** 예비특보 문장 상한. 원문이 해역·시각을 줄줄이 나열함 */
    private static final int MAX_TEXT = 100;

    private OceanFacts() {
    }

    /** 사람이 읽는 한 줄들. 그대로 프롬프트에 들어가고 그대로 화면에 뜬다 */
    public static List<String> of(List<OceanSnapshot> snapshots) {
        return of(snapshots, (source, payload) -> payload);
    }

    /**
     * @param view 소스별 payload 를 바꿔 읽는다 — 지점 소스는 전국 목록이라 기준 위치 반경으로 잘라 넣는다(StationNear).
     *             자르지 않으면 요약이 200여 지점을 한 줄씩 나열한다
     */
    public static List<String> of(List<OceanSnapshot> snapshots,
                                  BiFunction<String, Map<String, Object>, Map<String, Object>> view) {
        Map<String, Map<String, Object>> by = new LinkedHashMap<>();
        snapshots.forEach(s -> {
            if (s.getPayload() != null) {
                by.put(s.getSource(), view.apply(s.getSource(), s.getPayload()));
            }
        });
        List<String> facts = new ArrayList<>();

        payload(by, "weather-warning").ifPresent(p -> {
            List<String> names = strings(p.get("activeMarineWarnings"));
            if (p.get("focus") instanceof Map<?, ?> focus) {
                // 조업 해역(설정 코드 + 상위 구역) 판정이 먼저. 전국은 따로 — 섞으면 남의 해역 특보가 우리 것으로 읽힘
                List<String> hits = strings(focus.get("activeMarineWarnings"));
                String where = String.join("·", strings(focus.get("names")));
                facts.add(hits.isEmpty() ? "조업 해역(%s) 해상 특보: 없음".formatted(where)
                        : "조업 해역(%s) 해상 특보: %s 발효 중".formatted(where, String.join("·", hits)));
                facts.add(names.isEmpty() ? "전국 해상 특보: 발효 없음"
                        : "전국 해상 특보: " + String.join("·", names) + " 발효 중" + areaSuffix(p.get("activeAreas")));
            } else {
                // 해역은 전국 목록. 본선 구역인지는 판정 안 함 — 요약이 "우리 해역"이라 말하면 안 됨
                facts.add(names.isEmpty() ? "해상 특보: 발효 중 없음"
                        : "해상 특보: " + String.join("·", names) + " 발효 중" + areaSuffix(p.get("activeAreas")));
            }
            if (p.get("status") instanceof Map<?, ?> status
                    && status.get("preliminary") instanceof String pre
                    && !WeatherWarningCollector.isNone(pre)) {
                facts.add("예비특보: " + shorten(pre));
            }
        });

        payload(by, "sea-obs").ifPresent(p -> {
            for (Map<String, Object> st : stations(p)) {
                num(st, "waveHeightM").ifPresent(v ->
                        facts.add("파고 %.1fm (%s, %skm)".formatted(v, st.get("name"), st.get("distanceKm"))));
                num(st, "windSpeedMs").ifPresent(v ->
                        facts.add("풍속 %.1fm/s (%s, %skm)".formatted(v, st.get("name"), st.get("distanceKm"))));
            }
        });

        payload(by, "fishing-ground").ifPresent(p -> {
            for (Map<String, Object> st : stations(p)) {
                num(st, "waterTempC").ifPresent(v ->
                        facts.add("수온 %.1f℃ (%s, %skm)".formatted(v, st.get("name"), st.get("distanceKm"))));
            }
        });

        payload(by, "roms").ifPresent(p -> {
            num(p, "currentSpeedMs").ifPresent(v -> facts.add("표층 유속 %.2fm/s (예측)".formatted(v)));
            num(p, "currentDirDeg").ifPresent(v -> facts.add("유향 %.0f도 (예측)".formatted(v)));
        });

        payload(by, "ship-index").ifPresent(p -> {
            // 권역 평균 지수. 출항 판정 근거가 아님을 문장에 남김
            if (p.get("focusName") != null && p.get("current") instanceof Map<?, ?> c) {
                // 다음 구간을 같이 준다 (2026-09-18) — 요약의 두 번째 문장이 "앞으로"를 말하려면
                // 미래 값이 사실에 있어야 한다. KHOA 등급은 6시간 구간이라 한 칸이 곧 다음 물때다.
                // 해석("나빠진다")은 붙이지 않는다. 두 등급을 나란히 주고 LLM 이 잇게 한다.
                String next = nextSlot(p, c);
                facts.add("선박운항지수 %s: %s %s%s (KHOA 참고지수)"
                        .formatted(p.get("focusName"), c.get("slot"), c.get("score"),
                                next == null ? "" : " → 다음 " + next));
            }
        });

        payload(by, "red-tide").ifPresent(p -> {
            Object breaking = p.get("breaking");
            facts.add(breaking == null ? "적조: 특보 없음"
                    : "적조 특보: " + String.valueOf(breaking).replaceAll("\\s+", " ").trim());
        });

        payload(by, "jellyfish").ifPresent(p -> {
            // 지역별 출현율은 첨부 PDF 에서 읽어 둔 것이다(JellyfishReportReader).
            // 못 읽었으면 report 가 없고, 그때는 예전처럼 제목만 — 없는 수치를 지어내지 않는다
            String detail = jellySpecies(p);
            facts.add("해파리 주간보고: " + p.get("subject")
                    + (detail.isEmpty() ? "" : " — " + detail)
                    + " (설문 응답률이라 판단 근거가 아님)");
        });

        return facts;
    }

    /**
     * 해파리 종별 출현율 한 줄. `노무라입깃해파리 17→18% (고밀도 전남광주)` 꼴.
     *
     * <p>고밀도 해역만 붙인다 — 저밀도는 거의 전국이라 문장이 길어지기만 하고
     * <b>읽는 사람의 판단을 바꾸지 않는다.</b> 원문 전체는 화면이 링크로 연다.</p>
     *
     * @return 읽은 것이 없으면 빈 문자열
     */
    private static String jellySpecies(Map<String, Object> p) {
        if (!(p.get("report") instanceof Map<?, ?> report)
                || !(report.get("species") instanceof List<?> species)) {
            return "";
        }
        List<String> parts = new ArrayList<>();
        for (Object o : species) {
            if (!(o instanceof Map<?, ?> sp) || sp.get("name") == null) {
                continue;
            }
            StringBuilder sb = new StringBuilder(String.valueOf(sp.get("name")));
            Object prev = sp.get("prevPct");
            Object now = sp.get("pct");
            if (now != null) {
                sb.append(' ').append(prev == null ? "" : prev + "→").append(now).append('%');
            }
            if (sp.get("high") instanceof List<?> high && !high.isEmpty()) {
                sb.append(" (고밀도 ").append(String.join("·",
                        high.stream().map(String::valueOf).toList())).append(')');
            }
            parts.add(sb.toString());
        }
        return String.join(" · ", parts);
    }

    /**
     * 설정된 조업 권역에서 지금 구간 **바로 뒤** 구간.
     *
     * <p>권역 코드가 안 맞으면 추정하지 않는다 — 다른 권역의 등급을 이 배의 다음 구간처럼
     * 말하면 그게 조업 판단에 쓰인다.</p>
     *
     * @return `오후 나쁨` 꼴. 없으면 null
     */
    private static String nextSlot(Map<String, Object> p, Map<?, ?> current) {
        Object code = p.get("focusCode");
        if (code == null || !(p.get("areas") instanceof List<?> areas) || current.get("at") == null) {
            return null;
        }
        String at = String.valueOf(current.get("at"));
        for (Object a : areas) {
            if (!(a instanceof Map<?, ?> area) || !code.equals(area.get("code"))
                    || !(area.get("slots") instanceof List<?> slots)) {
                continue;
            }
            return slots.stream()
                    .filter(Map.class::isInstance).map(Map.class::cast)
                    .filter(x -> x.get("at") != null && String.valueOf(x.get("at")).compareTo(at) > 0)
                    .min(Comparator.comparing(x -> String.valueOf(x.get("at"))))
                    .map(x -> "%s %s".formatted(x.get("slot"), x.get("score")))
                    .orElse(null);
        }
        return null;
    }

    private static String areaSuffix(Object value) {
        List<String> areas = new ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> m && m.get("areaName") instanceof String name && !areas.contains(name)) {
                    areas.add(name);
                }
            }
        }
        if (areas.isEmpty()) {
            return "";
        }
        String shown = String.join(", ", areas.subList(0, Math.min(MAX_AREAS, areas.size())));
        return areas.size() > MAX_AREAS
                ? " (%s 외 %d곳)".formatted(shown, areas.size() - MAX_AREAS)
                : " (" + shown + ")";
    }

    private static String shorten(String text) {
        String line = text.replaceAll("\\s+", " ").trim();
        return line.length() > MAX_TEXT ? line.substring(0, MAX_TEXT) + "…" : line;
    }

    private static List<String> strings(Object value) {
        List<String> out = new ArrayList<>();
        if (value instanceof List<?> list) {
            list.forEach(o -> {
                if (o instanceof String s) {
                    out.add(s);
                }
            });
        }
        return out;
    }

    private static Optional<Map<String, Object>> payload(Map<String, Map<String, Object>> by, String source) {
        return Optional.ofNullable(by.get(source));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> stations(Map<String, Object> payload) {
        Object v = payload.get("stations");
        return v instanceof List<?> l ? (List<Map<String, Object>>) l : List.of();
    }

    private static Optional<Double> num(Map<String, Object> map, String key) {
        Object v = map.get(key);
        return v instanceof Number n ? Optional.of(n.doubleValue()) : Optional.empty();
    }
}

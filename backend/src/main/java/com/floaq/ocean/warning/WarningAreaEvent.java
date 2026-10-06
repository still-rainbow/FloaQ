package com.floaq.ocean.warning;

import java.time.Instant;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 특보구역 하나에 내려진 특보 이벤트 한 건 (기상특보 getPwnCd).
 *
 * title 파싱 기각 (2026-09-14) — getWthrWrnList title 은 해역이 없고, 가운뎃점 문법이 두 벌이고,
 * "해제예고연장" 이 부분일치로 해제에 걸림. getPwnCd 는 종류·강도·발표구분·해역이 필드로 옴.
 *
 * @param announcedAt 발표 시각 (tmFc, KST)
 * @param seq         발표번호(월별). 같은 시각 발표의 순서
 * @param kindCode    warnVar. 6 풍랑 · 5 폭풍해일 · 7 태풍 · 1 강풍 …
 * @param levelCode   warnStress. 0 주의보 · 1 경보 · 2 중대경보
 * @param command     1 발표 · 2 해제 · 3 연장 · 6 정정 · 7 변경발표 · 8 변경해제
 * @param cancelled   cancel=1. 취소된 특보
 * @param effectiveAt 발효 시각. 발표면 startTime, 해제면 endTime. 0 이면 null
 */
public record WarningAreaEvent(
        Instant announcedAt, int seq, String areaCode, String areaName,
        int kindCode, int levelCode, int command, boolean cancelled, Instant effectiveAt) {

    /**
     * 조업 판단에 쓰는 종류. 강풍(1)은 육상(L) 구역에만 옴.
     * 2026-09-14 실측 6일 107건 — 풍랑 S구역 75 · 강풍 L구역 30 · 폭풍해일 L구역 2.
     * 폭풍해일은 L 구역이지만 해안 침수라 포함.
     */
    private static final Set<Integer> MARINE = Set.of(5, 6, 7);

    /** 가이드 warnVar 표. 13 열대야는 2026-06-01 추가 */
    private static final Map<Integer, String> KINDS = Map.ofEntries(
            Map.entry(1, "강풍"), Map.entry(2, "호우"), Map.entry(3, "한파"), Map.entry(4, "건조"),
            Map.entry(5, "폭풍해일"), Map.entry(6, "풍랑"), Map.entry(7, "태풍"), Map.entry(8, "대설"),
            Map.entry(9, "황사"), Map.entry(12, "폭염"), Map.entry(13, "열대야"));

    private static final Map<Integer, String> LEVELS = Map.of(0, "주의보", 1, "경보", 2, "중대경보");

    private static final Map<Integer, String> COMMANDS = Map.of(
            1, "발표", 2, "해제", 3, "연장", 6, "정정", 7, "변경발표", 8, "변경해제");

    /** 발효를 끝내는 발표구분. 나머지·미지 코드는 발효 유지 — 놓치는 쪽보다 보이는 쪽이 안전 */
    private static final Set<Integer> RELEASES = Set.of(2, 8);

    /** 최신 먼저. 같은 발표 안에서는 발효가 해제보다 앞 — 모호하면 보이는 쪽 */
    static final Comparator<WarningAreaEvent> NEWEST_FIRST = Comparator
            .comparing(WarningAreaEvent::announcedAt, Comparator.nullsLast(Comparator.reverseOrder()))
            .thenComparing(WarningAreaEvent::seq, Comparator.reverseOrder())
            .thenComparing(WarningAreaEvent::isRelease);

    public boolean isMarine() {
        return MARINE.contains(kindCode);
    }

    public boolean isRelease() {
        return RELEASES.contains(command);
    }

    public String kind() {
        return KINDS.getOrDefault(kindCode, "특보" + kindCode);
    }

    public String level() {
        return LEVELS.getOrDefault(levelCode, "등급" + levelCode);
    }

    public String action() {
        return COMMANDS.getOrDefault(command, "코드" + command);
    }

    /** 풍랑주의보 */
    public String name() {
        return kind() + level();
    }

    /**
     * 지금 발효 중인 해상 특보. (구역, 종류)마다 최신 이벤트 하나만 봄.
     *
     * 강도(주의보·경보)는 키에서 뺌 — 넣으면 경보→주의보 격하 뒤 옛 경보가 해제 없이 남음
     * (2026-09-13 title 방식에서 실제 발생).
     * 취소된 이벤트는 없던 일로 보고 그 이전 이벤트가 이어짐.
     *
     * 한계: 조회 창(6일)보다 먼저 발표되고 이후 변동 없는 특보는 안 보임 → getPwnStatus 로 교차 확인
     */
    public static List<WarningAreaEvent> activeMarine(List<WarningAreaEvent> events) {
        Map<String, WarningAreaEvent> latest = new LinkedHashMap<>();
        events.stream()
                .filter(e -> e.isMarine() && !e.cancelled())
                .sorted(NEWEST_FIRST)
                .forEach(e -> latest.putIfAbsent(e.areaCode() + "|" + e.kindCode(), e));
        return latest.values().stream().filter(e -> !e.isRelease()).toList();
    }
}

package com.floaq.ocean.warning;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 특보구역 계층 — 조업 해역 코드의 상위·하위 구역을 모음.
 *
 * 좌표 판정 기각 — 기상청이 특보구역 공간정보를 보유·제공하지 않음 (2026-09-14 회신).
 * S1 계열만 계층이 이어짐 (부산앞바다 → 남해동부앞바다 → 남해동부전해상 → 남해전해상 → 전해상).
 * S2 연안바다/평수구역은 상위가 전부 S2000000 — 설정에 적은 코드만 해당.
 */
public final class WarningZones {

    public record Zone(String id, String up, String name) {
    }

    private static final WarningZones EMPTY = new WarningZones(List.of());

    private final Map<String, Zone> byId = new LinkedHashMap<>();
    private final Map<String, List<String>> children = new HashMap<>();

    private WarningZones(Collection<Zone> zones) {
        for (Zone z : zones) {
            byId.put(z.id(), z);
        }
        for (Zone z : zones) {
            // S2000000 은 자기 자신이 상위. 자식으로 넣으면 순회가 끝나지 않음
            if (z.up() != null && !z.up().equals(z.id())) {
                children.computeIfAbsent(z.up(), k -> new ArrayList<>()).add(z.id());
            }
        }
    }

    public static WarningZones of(Collection<Zone> zones) {
        return new WarningZones(zones);
    }

    public static WarningZones empty() {
        return EMPTY;
    }

    /** warning-zone 스냅샷 payload → 계층. 모양이 다르면 빈 계층 */
    public static WarningZones fromPayload(Map<String, Object> payload) {
        List<Zone> zones = new ArrayList<>();
        if (payload != null && payload.get("zones") instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> m && m.get("id") instanceof String id) {
                    zones.add(new Zone(id, m.get("up") instanceof String up ? up : null,
                            m.get("name") instanceof String name ? name : null));
                }
            }
        }
        return zones.isEmpty() ? EMPTY : new WarningZones(zones);
    }

    public boolean isEmpty() {
        return byId.isEmpty();
    }

    /** 모르는 코드면 null */
    public String name(String id) {
        Zone z = byId.get(id);
        return z == null ? null : z.name();
    }

    /**
     * 조업 해역 + 상위(그 해역을 덮는 넓은 특보) + 하위(넓은 구역을 설정했을 때 그 안의 특보).
     * 계층을 모르는 코드는 자기 자신만.
     */
    public Set<String> related(Collection<String> focus) {
        Set<String> out = new LinkedHashSet<>();
        for (String code : focus) {
            out.add(code);
            Set<String> seen = new HashSet<>(Set.of(code));
            String up = parentOf(code);
            while (up != null && seen.add(up)) {
                out.add(up);
                up = parentOf(up);
            }
            Deque<String> queue = new ArrayDeque<>(children.getOrDefault(code, List.of()));
            while (!queue.isEmpty()) {
                String child = queue.poll();
                if (out.add(child)) {
                    queue.addAll(children.getOrDefault(child, List.of()));
                }
            }
        }
        return out;
    }

    private String parentOf(String id) {
        Zone z = byId.get(id);
        return z == null ? null : z.up();
    }
}

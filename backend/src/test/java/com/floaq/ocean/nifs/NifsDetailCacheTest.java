package com.floaq.ocean.nifs;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 같은 보고면 상세를 다시 부르지 않는다 (2026-09-16).
 *
 * 틀리면 둘 중 하나다 — 매 수집마다 상세를 다시 부르거나(적조 하루 24회 낭비),
 * 새 보고가 왔는데 옛 특보 문구를 그대로 화면에 띄운다.
 */
class NifsDetailCacheTest {

    private static final List<String> KEYS = List.of("progress", "breaking");

    private static Map<String, Object> payload(String codNews) {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("codNews", codNews);
        return p;
    }

    @Test
    void 같은_보고면_직전_상세를_옮기고_재사용한다() {
        Map<String, Object> stored = payload("20260811-001");
        stored.put("progress", "소강");
        stored.put("breaking", "적조주의보");
        Map<String, Object> now = payload("20260811-001");

        assertThat(NifsDetailCache.reuse(stored, "codNews", "20260811-001", now, KEYS)).isTrue();
        assertThat(now).containsEntry("progress", "소강").containsEntry("breaking", "적조주의보");
    }

    @Test
    void 새_보고면_재사용하지_않는다() {
        // 옛 특보 문구를 새 보고에 붙이면 화면이 지난 상황을 지금으로 말한다
        Map<String, Object> stored = payload("20260811-001");
        stored.put("progress", "소강");
        Map<String, Object> now = payload("20260901-002");

        assertThat(NifsDetailCache.reuse(stored, "codNews", "20260901-002", now, KEYS)).isFalse();
        assertThat(now).doesNotContainKey("progress");
    }

    @Test
    void 직전_상세가_실패했으면_다시_부른다() {
        // 번호는 같지만 상세 키가 없다 — 그때 상세 호출이 실패한 것이다
        Map<String, Object> stored = payload("20260811-001");
        Map<String, Object> now = payload("20260811-001");

        assertThat(NifsDetailCache.reuse(stored, "codNews", "20260811-001", now, KEYS)).isFalse();
    }

    @Test
    void 일부_키만_남아_있으면_그것만_옮긴다() {
        Map<String, Object> stored = payload("20260811-001");
        stored.put("progress", "소강");
        Map<String, Object> now = payload("20260811-001");

        assertThat(NifsDetailCache.reuse(stored, "codNews", "20260811-001", now, KEYS)).isTrue();
        assertThat(now).containsEntry("progress", "소강").doesNotContainKey("breaking");
    }

    @Test
    void 저장된_값이나_보고_번호가_없으면_재사용하지_않는다() {
        Map<String, Object> now = payload("20260811-001");

        assertThat(NifsDetailCache.reuse(null, "codNews", "20260811-001", now, KEYS)).isFalse();
        assertThat(NifsDetailCache.reuse(payload("20260811-001"), "codNews", null, now, KEYS)).isFalse();
    }
}

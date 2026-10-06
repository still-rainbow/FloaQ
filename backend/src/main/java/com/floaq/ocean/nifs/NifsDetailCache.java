package com.floaq.ocean.nifs;

import java.util.List;
import java.util.Map;

/**
 * 수과원 2단계 호출(목록 → 상세)에서 **같은 보고면 상세를 다시 부르지 않는다** (2026-09-16).
 *
 * 적조·해파리는 목록에 없는 문장(특보·원문)이 상세에만 있어 매 수집마다 상세까지 불렀다 —
 * 적조가 하루 48회였고 그중 24회가 같은 내용이었다. 보고 번호가 그대로면 내용도 그대로다.
 *
 * 직전 값은 `ocean_snapshot` 에 남아 있다(마지막 **성공** payload). 상세가 실패했던 수집은 키가 없어 다음 수집이 다시 부른다.
 *
 * ⚠ 같은 번호로 내용만 고쳐 다시 올리면 놓친다. 수과원이 정정할 때 번호를 유지하는지는 확인하지 않았다 —
 *    목록의 발표일(day_report · inpt_date)이 바뀌면 보고 번호도 바뀌는 것을 실응답에서 봤을 뿐이다.
 */
final class NifsDetailCache {

    private NifsDetailCache() {
    }

    /**
     * @param stored  직전 성공 payload. 없으면 null
     * @param idKey   보고 식별 키 — 적조 `codNews` · 해파리 `srcode`
     * @param id      이번 목록에서 고른 보고 번호
     * @param payload 이번 payload. 재사용이면 상세 키를 여기에 옮긴다
     * @param keys    상세 응답에서만 오는 키
     * @return 재사용했으면 true — 호출부는 상세를 부르지 않는다
     */
    static boolean reuse(Map<String, Object> stored, String idKey, String id,
                         Map<String, Object> payload, List<String> keys) {
        if (stored == null || id == null || !id.equals(stored.get(idKey))) {
            return false;
        }
        boolean reused = false;
        for (String key : keys) {
            if (stored.containsKey(key)) {
                payload.put(key, stored.get(key));
                reused = true;
            }
        }
        // 키가 하나도 없으면 그때 상세가 실패한 것이다 — 다시 부른다
        return reused;
    }
}

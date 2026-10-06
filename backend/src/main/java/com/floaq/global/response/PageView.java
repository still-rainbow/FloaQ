package com.floaq.global.response;

import org.springframework.data.domain.Page;

import java.util.List;

/**
 * 목록 응답 — {@code {content, page, size, totalElements, hasNext}} (docs/api.md §1).
 *
 * <p>Spring 의 {@link Page} 를 그대로 내보내지 않는다. 필드가 많고({@code pageable}·{@code sort}…)
 * 버전마다 직렬화 모양이 바뀌어, 화면이 그 모양에 묶이면 부트를 올릴 때 목록이 깨진다.</p>
 */
public record PageView<T>(List<T> content, int page, int size, long totalElements, boolean hasNext) {

    public static <T> PageView<T> of(Page<T> page) {
        return new PageView<>(page.getContent(), page.getNumber(), page.getSize(),
                page.getTotalElements(), page.hasNext());
    }
}

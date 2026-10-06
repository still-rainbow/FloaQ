package com.floaq.pi;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 배치에서 거절된 원소 하나 (docs/api.md §4.1 {@code failed}).
 *
 * @param index 요청 {@code data} 배열에서의 위치. Pi 가 자기 큐의 어느 행인지 찾는 유일한 단서다
 * @param id    그 원소의 식별자(사고면 {@code accident_id}). 없으면 null
 * @param code  {@link com.floaq.global.error.ErrorCode} 값
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record PiFailure(
        @JsonProperty("index") int index,
        @JsonProperty("id") String id,
        @JsonProperty("code") String code) {
}

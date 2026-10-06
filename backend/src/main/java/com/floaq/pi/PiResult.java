package com.floaq.pi;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Pi 수신 결과 집계 (docs/api.md §4.1).
 *
 * <p><b>{@code duplicated} 는 오류가 아니다.</b> 재전송이 그렇게 보이는 것이고,
 * Pi 는 2xx 를 받아야 워터마크를 전진시킨다 — 여기서 400 을 주면 같은 배치가 영원히 돈다.</p>
 *
 * @param received   받은 원소 수
 * @param inserted   새로 반영
 * @param duplicated 같은 자연키가 이미 있고 <b>바뀐 것이 없음</b>
 * @param stale      늦게 도착한 옛 상태라 현재 상태에 반영 안 함. 이력에는 남는다(§4.2)
 */
public record PiResult(
        @JsonProperty("received") int received,
        @JsonProperty("inserted") int inserted,
        @JsonProperty("duplicated") int duplicated,
        @JsonProperty("stale") int stale) {
}

package com.floaq.ocean.collect;

import com.floaq.ocean.client.OceanResponse;

import java.time.Instant;
import java.util.Map;

/**
 * 수집 1회 결과. 성공·실패 같은 타입.
 *
 * 예외 기각 — 한 소스 장애가 스케줄러 루프를 끊어 뒤 순서 소스까지 막음.
 *
 * @param resultCode 실패해도 저장됨 — 화면이 이유를 말할 근거
 * @param payload    실패면 null. 저장 시 기존 값을 덮지 않음
 */
public record CollectOutcome(
        String resultCode,
        String resultMsg,
        Instant observedAt,
        Map<String, Object> payload) {

    public static CollectOutcome ok(Instant observedAt, Map<String, Object> payload) {
        return new CollectOutcome(OceanResponse.OK, null, observedAt, payload);
    }

    public static CollectOutcome from(OceanResponse response) {
        return new CollectOutcome(response.code(), response.message(), null, null);
    }

    public boolean isSuccess() {
        return payload != null;
    }
}

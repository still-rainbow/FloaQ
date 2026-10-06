package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Pi 요청 봉투 (docs/api.md §4.1). Pi 가 MQTT 발행 코드를 그대로 재사용하는 모양이다.
 *
 * @param requestId uuid v7. <b>서버 로그 상관용</b> — 멱등 판정은 {@code data} 원소의 자연키가 한다
 * @param v         스키마 버전. 모르는 값이면 {@code PI_UNSUPPORTED_VERSION}
 * @param ts        Pi 발행 시각(Unix 초). 서버는 수신 시각과의 차이를 로그로만 남긴다
 * @param data      <b>항상 배열.</b> 단건도 길이 1 — 두절 복귀 때 밀린 것이 한꺼번에 오는데,
 *                  건당 요청이면 그 순간 요청 폭주다
 */
public record PiEnvelope<T>(
        @JsonProperty("request_id") String requestId,
        @JsonProperty("v") Integer v,
        @JsonProperty("ts") Long ts,
        @JsonProperty("data") List<T> data) {

    /** 지금 서버가 아는 유일한 버전. */
    public static final int SUPPORTED_VERSION = 1;
}

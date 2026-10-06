package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * {@code POST /api/pi/buoys} 원소 (dev-iot {@code sync.py} pi_buoy).
 *
 * <p><b>⚠ 좌표 컬럼명이 양쪽에서 다르다.</b> Pi 는 {@code lat}/{@code lon},
 * 서버 {@code buoy} 표는 V1 이 {@code buoy_lat}/{@code buoy_lon} 으로 이미 배포됐다(V9 ⑤ 미결).
 * 표를 고치는 대신 <b>여기서 매핑</b>한다 — 하이퍼테이블 컬럼 개명은 청크 전체를 건드린다.</p>
 *
 * <p><b>Pi 의 PK({@code buoy_log_id}, INTEGER)는 받지 않는다.</b> 멱등은 자연키
 * {@code (accident_id, created_at)} 가 보장한다(V9 {@code uq_buoy_accident_measured}).</p>
 *
 * @param seq        부표가 매긴 순번. 유실 감지용
 * @param isPressed  사람이 부표를 잡음(APP-08). ⚠ false 가 "사람이 없다"는 뜻은 아니다
 * @param createdAt  부표 GPS 가 위치를 측정한 시각
 * @param receivedAt Pi 가 LoRa 로 받은 시각. {@code createdAt} 과 다르다 — 두절 판정이 이 값을 본다
 */
public record PiBuoy(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("seq") Integer seq,
        @JsonProperty("lat") Double lat,
        @JsonProperty("lon") Double lon,
        @JsonProperty("is_pressed") Boolean isPressed,
        @JsonProperty("rssi") Float rssi,
        @JsonProperty("created_at") Long createdAt,
        @JsonProperty("received_at") Long receivedAt) {
}

package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * {@code POST /api/pi/drift-estimates} 원소 (dev-iot {@code sync.py} pi_drift_estimate).
 *
 * <p>두절 뒤 부표가 어디까지 흘렀는지의 추정이다. {@code center}+{@code radiusM} 이
 * 지도에 그리는 원이고, {@code input_*} 는 <b>그 원을 그릴 때 쓴 해양 데이터 스냅샷</b>이다.</p>
 *
 * <p>🔴 <b>{@code inputObservedAt} 을 화면에 반드시 같이 띄운다.</b>
 * 3시간 전 조류로 그린 원과 3분 전 것이 똑같이 생겼다 — 구조 판단이 갈리는 값인데
 * 그림만으로는 구분이 안 된다.</p>
 *
 * <p>⚠ Pi 의 {@code comm_loss_id} 는 받지 않는다. Pi 안의 INTEGER 라 서버에서 뜻이 없고
 * {@code sync.py} 도 보내지 않는다(api.md §4.3).</p>
 *
 * @param isCurrent 현재 추정. <b>사고당 1건</b>(부분 UNIQUE {@code uq_drift_estimate_current}) —
 *                  서비스가 옛 행을 먼저 내리고 넣는다
 */
public record PiDriftEstimate(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("base_lat") Double baseLat,
        @JsonProperty("base_lon") Double baseLon,
        @JsonProperty("last_received_at") Long lastReceivedAt,
        @JsonProperty("elapsed_sec") Integer elapsedSec,
        @JsonProperty("center_lat") Double centerLat,
        @JsonProperty("center_lon") Double centerLon,
        @JsonProperty("radius_m") Float radiusM,
        @JsonProperty("input_current_speed") Float inputCurrentSpeed,
        @JsonProperty("input_current_dir") Float inputCurrentDir,
        @JsonProperty("input_wind_speed") Float inputWindSpeed,
        @JsonProperty("input_wind_dir") Float inputWindDir,
        @JsonProperty("input_observed_at") Long inputObservedAt,
        @JsonProperty("is_current") Boolean isCurrent,
        @JsonProperty("created_at") Long createdAt) {
}

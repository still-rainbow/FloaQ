package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.floaq.accident.entity.LaunchFailReason;
import com.floaq.accident.entity.LaunchResult;

import java.util.UUID;

/**
 * {@code POST /api/pi/launches} 원소 (dev-iot {@code sync.py} pi_launch).
 *
 * <p><b>사고당 1행이다</b> — 서버 {@code launch} 표의 PK 가 {@code accident_id} 다.
 * 그래서 멱등이 {@code ON CONFLICT (accident_id) DO UPDATE} 로 자연스럽게 선다.</p>
 *
 * <p><b>{@code FAILED} 도 저장한다</b>(V9 ③). 발사 정확도 피드백의 근거이고,
 * "안 쐈다"와 "쐈는데 실패했다"는 구조 판단이 다르다.</p>
 *
 * @param detectionId Jetson 탐지 건 식별자. 조준 해의 출처 추적용
 * @param targetLat   조준 목표. {@code launchLat} 은 발사 시점 본선 위치라 서로 다르다
 */
public record PiLaunch(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("detection_id") String detectionId,
        @JsonProperty("result") LaunchResult result,
        @JsonProperty("fail_reason") LaunchFailReason failReason,
        @JsonProperty("launch_lat") Double launchLat,
        @JsonProperty("launch_lon") Double launchLon,
        @JsonProperty("target_lat") Double targetLat,
        @JsonProperty("target_lon") Double targetLon,
        @JsonProperty("horizontal_angle") Float horizontalAngle,
        @JsonProperty("vertical_angle") Float verticalAngle,
        @JsonProperty("confidence_score") Float confidenceScore,
        @JsonProperty("created_at") Long createdAt) {
}

package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * {@code POST /api/pi/imus} 원소 (dev-iot {@code sync.py} pi_imu).
 *
 * <p><b>{@code imuPosition} 이 자연키의 일부다</b>(V9 {@code uq_imu_accident_measured},
 * {@code NULLS NOT DISTINCT}). IMU 를 둘 이상 쓰면 같은 초에 온 둘째가
 * {@code (accident_id, created_at)} 만으로는 거부되기 때문이다.</p>
 *
 * <p>⚠ {@code roll}·{@code pitch}·{@code yaw} 는 <b>각도(deg)</b>다. 각속도로 읽으면
 * 전복 판정 임계 롤 각이 무의미해진다(ref/mqtt.md §5.6 이 스스로 정정한 항목).</p>
 *
 * @param imuPosition {@code HULL}|{@code CAMERA_L}|{@code CAMERA_R}. 서버 CHECK 와 같은 값.
 *                    enum 을 만들지 않은 이유 — 장착 위치는 하드웨어 구성이라 늘어난다.
 *                    모르는 값이면 DB CHECK 가 시끄럽게 막는다(조용히 통과시키지 않는다)
 */
public record PiImu(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("imu_position") String imuPosition,
        @JsonProperty("accel_x") Float accelX,
        @JsonProperty("accel_y") Float accelY,
        @JsonProperty("accel_z") Float accelZ,
        @JsonProperty("roll") Float roll,
        @JsonProperty("pitch") Float pitch,
        @JsonProperty("yaw") Float yaw,
        @JsonProperty("heading_deg") Float headingDeg,
        @JsonProperty("created_at") Long createdAt) {
}

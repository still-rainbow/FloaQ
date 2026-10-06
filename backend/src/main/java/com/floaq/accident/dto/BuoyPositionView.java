package com.floaq.accident.dto;

import com.floaq.buoy.entity.Buoy;

import java.time.Instant;

/**
 * 부표 실측 위치 한 점.
 *
 * <p>{@code measuredAt} 은 <b>부표 GPS 가 잰 시각</b>이다. Pi 가 LoRa 로 받은 시각이 아니다 —
 * 둘은 지연만큼 벌어지고, 지도에 찍을 때는 잰 시각이 맞다.</p>
 */
public record BuoyPositionView(Double lat, Double lon, boolean isPressed, Instant measuredAt) {

    public static BuoyPositionView of(Buoy b) {
        return new BuoyPositionView(b.getLat(), b.getLon(), b.isPressed(), b.getCreatedAt());
    }
}

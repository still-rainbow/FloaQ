package com.floaq.accident.dto;

import com.floaq.ship.entity.ShipPosition;

import java.time.Instant;

/**
 * 사고 선박의 위치 한 점.
 *
 * <p>{@code measuredAt} 은 <b>선박 GPS 가 잰 시각</b>이다. 서버가 받은 시각이 아니다 —
 * 부표와 같은 규칙이다({@link BuoyPositionView}). 관제 화면은 이 값으로
 * "마지막으로 소식을 들은 지 얼마나 됐나"를 센다. 그 숫자가 사고 경과로 대신 채워져 있으면
 * 배가 방금 위치를 보냈어도 오래 끊긴 것처럼 보인다.</p>
 *
 * <p>{@code headingDeg} 는 뱃머리 방향(진북 0~360)이다. 없으면 {@code null} 이다 —
 * 0 으로 내려보내면 화면이 <b>정북을 향한다</b>고 읽어 배가 엉뚱한 쪽을 본다.</p>
 */
public record ShipPositionView(Double lat, Double lon, Float speedKn, Float headingDeg, Instant measuredAt) {

    public static ShipPositionView of(ShipPosition p) {
        return new ShipPositionView(p.getLat(), p.getLon(), p.getSpeedKn(), p.getHeadingDeg(), p.getCreatedAt());
    }
}

package com.floaq.accident.entity;

/**
 * 투하 실패 사유 (database/pi.sql {@code pi_launch}).
 *
 * <p>{@code NO_SOLUTION} 은 나머지 셋과 원인이 다르다 — <b>장비가 아니라 계산이 실패한 것</b>이다.
 * Jetson 이 조준 해를 못 냈다는 뜻이고, 이때 {@code targetLat/Lon} 이 null 이다.</p>
 */
public enum LaunchFailReason {
    NOT_LOADED, DEVICE_ERROR, OUT_OF_RANGE, NO_SOLUTION
}

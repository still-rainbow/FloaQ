package com.floaq.accident.dto;

import java.time.Instant;

/**
 * 상세 화면의 부표 현재 상태.
 *
 * <p>⚠ <b>{@code heldAt} 이 null 인 것은 "안 잡았다"가 아니라 "확인 안 됨"이다</b>(E9).
 * 부표를 잡고도 버튼을 못 눌렀을 수 있다 — 화면 문구가 이 둘을 섞으면 안 된다.</p>
 */
public record BuoyStateView(Double lat, Double lon, boolean isPressed,
                            Instant measuredAt, Instant heldAt) {
}

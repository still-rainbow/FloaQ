package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * {@code POST /api/pi/comm-losses} 원소 (dev-iot {@code sync.py} pi_comm_loss).
 *
 * <p><b>두절 판정의 주체는 Pi 다.</b> 서버가 다시 판정하지 않는다 —
 * 부표 신호는 선내에서만 보이고, 서버는 인터넷이 끊긴 구간을 아예 못 본다.</p>
 *
 * <p><b>같은 구간이 두 번 온다.</b> 두절 시작에 한 번({@code recoveredAt} null),
 * 복귀 뒤 한 번({@code recoveredAt} 채워짐). 자연키
 * {@code (accident_id, detected_at)} 로 같은 행을 갱신한다.</p>
 *
 * <p>⚠ Pi 는 이 표에 {@code created_at} 을 보내지 않는다 — 서버가 수신 시각을 쓴다.</p>
 *
 * @param thresholdSec 판정 당시 임계(초). 기준이 바뀌어도 지난 기록의 뜻이 안 흔들리게 박제한다
 * @param lastLat      마지막 수신 위치. 조인 없이 지도에 찍으려고 복사해 온 값이다
 */
public record PiCommLoss(
        @JsonProperty("accident_id") UUID accidentId,
        @JsonProperty("detected_at") Long detectedAt,
        @JsonProperty("last_lat") Double lastLat,
        @JsonProperty("last_lon") Double lastLon,
        @JsonProperty("last_received_at") Long lastReceivedAt,
        @JsonProperty("threshold_sec") Integer thresholdSec,
        @JsonProperty("recovered_at") Long recoveredAt) {
}

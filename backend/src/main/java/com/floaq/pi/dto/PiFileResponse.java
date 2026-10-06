package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * {@code POST /api/pi/accidents/{accident_id}/files} 응답
 * (ref/mqtt-연동-웹_v2 §11 "Pi → EC2 업로드 규약").
 *
 * <p>🔴 <b>{@code objectKey} 를 반드시 돌려준다.</b> Pi 는 이 값을 받아야
 * {@code pi_accident_file.object_key} 를 채우고 그 장을 업로드 완료로 표시한다.
 * 안 돌려주면 Pi 의 대기열({@code object_key IS NULL})이 영영 안 줄어든다.</p>
 *
 * @param duplicated 같은 자연키가 이미 있었다 = 재전송. <b>오류가 아니다</b> —
 *                   응답이 유실돼 Pi 가 다시 보낸 경우가 여기다
 */
public record PiFileResponse(
        @JsonProperty("object_key") String objectKey,
        @JsonProperty("duplicated") boolean duplicated) {
}

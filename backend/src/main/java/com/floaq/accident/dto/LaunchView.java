package com.floaq.accident.dto;

import com.floaq.accident.entity.Launch;
import com.floaq.accident.entity.LaunchFailReason;
import com.floaq.accident.entity.LaunchResult;

import java.time.Instant;

/**
 * 투하 기록. 상세에서 null 이면 <b>수동 신고이거나 투하 기록이 아직 안 올라온 것</b>이다.
 *
 * <p>{@code targetLat/Lon} 과 각도를 <b>둘 다</b> 내리는 이유: 소프트 리밋에 걸리면 Pi 가 각도를
 * 깎으므로 "겨눈 곳"과 "실제로 명령한 각도"가 갈린다. 발사 정확도 피드백은 그 차이를 본다.</p>
 */
public record LaunchView(
        LaunchResult result,
        LaunchFailReason failReason,
        Double launchLat,
        Double launchLon,
        Double targetLat,
        Double targetLon,
        Float horizontalAngle,
        Float verticalAngle,
        Float confidenceScore,
        Instant launchedAt) {

    public static LaunchView of(Launch l) {
        return new LaunchView(l.getResult(), l.getFailReason(), l.getLaunchLat(), l.getLaunchLon(),
                l.getTargetLat(), l.getTargetLon(), l.getHorizontalAngle(), l.getVerticalAngle(),
                l.getConfidenceScore(), l.getCreatedAt());
    }
}

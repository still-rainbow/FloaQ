package com.floaq.accident.dto;

import java.time.Instant;

/**
 * 영상·프레임 상태 (docs/api.md §3.4 · §3.6).
 *
 * <p>진행 중에는 최신 프레임, 종결 후에는 mp4 다 — 두 요구가 시점으로 갈리므로 형식도 갈린다(계획.md §9.6).</p>
 *
 * <p>⚠ <b>{@code latestFrameSeq}·{@code latestFrameAt} 은 지금 항상 null 이다.</b>
 * 프레임 수신({@code POST /api/pi/frames})이 규약 미합의로 보류라 저장된 프레임이 없다(§0.1).
 * "프레임이 0장"이 아니라 "받는 경로가 아직 없다"는 뜻이다.</p>
 */
public record MediaView(Integer latestFrameSeq, Instant latestFrameAt,
                        VideoStatus videoStatus, Instant stoppedAt) {

    public enum VideoStatus {
        /** 진행 중 — 아직 인코딩할 시점이 아니다 */
        NONE, ENCODING, READY, FAILED
    }

    public static MediaView empty() {
        return new MediaView(null, null, VideoStatus.NONE, null);
    }
}

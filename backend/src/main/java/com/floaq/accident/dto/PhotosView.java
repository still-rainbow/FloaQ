package com.floaq.accident.dto;

import java.time.Instant;

/**
 * 진행 중 사고의 사진 두 장 — <b>감지 순간</b>과 <b>지금</b>.
 *
 * <p>진행 중에는 영상이 없다(mp4 는 종결 뒤 한 번 만든다, 계획.md §9.6). 대신 Pi 가 사진을
 * 계속 올리고, 관제는 그중 두 장만 본다: 무엇을 보고 사고로 판단했나(감지 순간),
 * 지금 배 위가 어떤가(가장 최근 프레임).</p>
 *
 * <p>실시간 동영상(Jetson {@code :8080/stream.mjpg})은 <b>배 안 랜에서만 보인다</b> —
 * 인터넷의 관제 웹은 닿을 수 없다. 그래서 관제의 "지금"은 몇 초마다 새로 받는 <b>최신 사진</b>이다.</p>
 *
 * @param detect 감지 순간 한 장. 아직 안 왔으면 null
 * @param latest 사고 뒤 가장 최근 프레임. 아직 안 왔으면 null
 */
public record PhotosView(Photo detect, Photo latest) {

    public static PhotosView empty() {
        return new PhotosView(null, null);
    }

    /**
     * @param url       R2 presigned GET — {@code <img src>} 에 그대로 쓴다. 바이트가 서버를 거치지 않는다
     * @param expiresAt 이 주소가 죽는 시각. 화면은 몇 초마다 새로 받으므로 거의 닿지 않는다
     */
    public record Photo(String url, Instant expiresAt, Instant capturedAt, String camera, Integer seq) {
    }
}

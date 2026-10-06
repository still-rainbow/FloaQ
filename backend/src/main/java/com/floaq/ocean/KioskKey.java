package com.floaq.ocean;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * kiosk 해역 이동 키 — {@code X-Floaq-Kiosk-Key} (결정 2026-09-15, api.md §1.1).
 *
 * 인증이 아니라 쿼터 보호. 조회는 공개이고, 수집 해역 이동(ROMS 약 35페이지 즉시 호출)만 이 키로 가른다 —
 * 공개로 두면 밖에서 60초마다 먼 좌표를 불러 ROMS 하루 예산을 약 4.8시간에 태울 수 있다(설정값 계산).
 *
 * 비밀이 아니라 선내 한정: kiosk 번들은 선내 PC localhost 에서만 서빙돼 공개 인터넷에 나가지 않는다. 웹 번들에는 넣지 않는다.
 *
 * 필터 기각 — 401 로 막을 요청이 아니다. 키가 없어도 조회는 성공해야 한다.
 * HMAC 기각 — 키가 번들 안이라 누구나 같은 키로 서명할 수 있어 얻는 것이 없다.
 *
 * ⚠ 선박 공통 키. 여러 척이면 선박별 키가 필요하다 (pi HMAC 선박별 키와 함께, api.md §9 3-1)
 */
@Slf4j
@Component
public class KioskKey {

    public static final String HEADER = "X-Floaq-Kiosk-Key";

    private final byte[] key;

    public KioskKey(@Value("${app.ocean.kiosk-key:}") String key) {
        this.key = key == null || key.isBlank() ? null : key.getBytes(StandardCharsets.UTF_8);
        if (this.key == null) {
            // 닫힌 쪽이 기본값이다. 다만 조용히 닫히면 "배를 옮겼는데 격자가 안 들어온다"를 원인 없이 겪는다
            log.warn("FLOAQ_KIOSK_KEY 미설정 — kiosk 조회가 수집 해역을 옮기지 못합니다 (조회는 정상, 해역 밖이면 OUTSIDE_AREA_NOT_MOVED)");
        }
    }

    /** 상수 시간 비교. 키 미설정이면 항상 false — 조용히 열리지 않게 */
    public boolean matches(String presented) {
        return key != null && presented != null
                && MessageDigest.isEqual(key, presented.getBytes(StandardCharsets.UTF_8));
    }
}

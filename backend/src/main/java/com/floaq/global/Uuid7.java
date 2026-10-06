package com.floaq.global;

import java.security.SecureRandom;
import java.util.UUID;

/**
 * UUID v7 — 앞 48비트가 Unix 밀리초라 <b>문자열·바이너리 정렬이 곧 시간 순서</b>다 (RFC 9562).
 *
 * <p>왜 {@code UUID.randomUUID()}(v4)가 아닌가: Pi 수신은 두절 복귀 때 수백 행을 한 배치로
 * 넣는다. v4 는 인덱스 삽입 위치가 매번 흩어져 B-tree 페이지가 잘게 쪼개지는데, v7 은 끝에 붙는다.
 * {@code buoy}·{@code imu} 가 하이퍼테이블이라 이 차이가 더 크다.</p>
 *
 * <p>⚠ <b>멱등은 이 값이 아니라 자연키가 보장한다</b>(docs/api.md §4.2). 서버가 채번하므로
 * 재전송 때 값이 달라지고, 그래서 {@code ON CONFLICT} 대상은 반드시 자연키여야 한다 —
 * PK 로 적으면 충돌이 영원히 안 나고 조용히 중복이 쌓인다.</p>
 *
 * <p>같은 밀리초 안의 순서는 보장하지 않는다. 필요해지면 RFC 9562 의 단조 카운터를 넣는다 —
 * 지금은 정렬 기준이 {@code created_at} 이라 필요가 없다.</p>
 */
public final class Uuid7 {

    private static final SecureRandom RANDOM = new SecureRandom();

    private Uuid7() {
    }

    public static UUID next() {
        byte[] bytes = new byte[16];
        RANDOM.nextBytes(bytes);

        long millis = System.currentTimeMillis();
        bytes[0] = (byte) (millis >>> 40);
        bytes[1] = (byte) (millis >>> 32);
        bytes[2] = (byte) (millis >>> 24);
        bytes[3] = (byte) (millis >>> 16);
        bytes[4] = (byte) (millis >>> 8);
        bytes[5] = (byte) millis;

        bytes[6] = (byte) ((bytes[6] & 0x0F) | 0x70);  // version 7
        bytes[8] = (byte) ((bytes[8] & 0x3F) | 0x80);  // variant 10

        long hi = 0;
        long lo = 0;
        for (int i = 0; i < 8; i++) {
            hi = (hi << 8) | (bytes[i] & 0xFFL);
        }
        for (int i = 8; i < 16; i++) {
            lo = (lo << 8) | (bytes[i] & 0xFFL);
        }
        return new UUID(hi, lo);
    }
}

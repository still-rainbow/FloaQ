package com.floaq.ocean;

import java.time.Duration;
import java.time.Instant;

/**
 * 해양 데이터 과거 보관 기간 — 24시간 (2026-09-14 결정).
 *
 * 사고 기록은 늦게 올라올 수 있다. 두절 중 사고는 통신이 돌아온 뒤에야 동기화된다(§9.9).
 * 그때 표류를 다시 계산하려면 **사고 시각의** 유속·바람이 필요한데, 수집값이 최신만 남아 있으면 답이 없다.
 *
 * 24시간 근거: 사고 구간은 최대 1시간(§9.6)이지만 동기화 지연은 두절 시간만큼 늘어난다.
 * 연안을 벗어나 몇 시간씩 끊기는 경우를 덮으려면 3시간으론 부족하다.
 * 저장량은 ROMS 0.3° 해역 24시간 약 1,400행 · 대해구 약 1만 행 · 소해구 약 2,900행 · 부이 관측 약 5천 행으로 무시할 수준이다
 * (격자점 58 · 대해구 1,330 · 소해구 360 · 3시간 프레임 8개 · sea_obs 전국 약 200지점, 2026-09-13~14 실측 기준).
 *
 * Redis 기각 — 값이 이미 PostgreSQL 에 있고, 조회가 "시각 T 에 좌표와 가장 가까운 격자"라 SQL 이 맞다.
 * compose 의 Redis 는 백엔드가 아직 쓰지 않는다 — 이 클래스가 들이면 첫 사용자가 된다.
 * ⚠ 이전 주석의 "영속 설정(AOF) 없음"은 틀렸다. compose 양쪽 다 --appendonly yes (2026-09-17 확인).
 *
 * ⚠ 삭제는 수집 때 한다(별도 정리 작업 없음). 수집이 멈추면 오래된 행도 안 지워진다 — 그 행은 조회 범위 밖이라 해가 없다.
 */
public final class OceanRetention {

    public static final Duration WINDOW = Duration.ofHours(24);

    private OceanRetention() {
    }

    /** 이보다 이른 행은 지운다 */
    public static Instant cutoff(Instant now) {
        return now.minus(WINDOW);
    }

    /** 이 시각을 보관분으로 답할 수 있나 */
    public static boolean covers(Instant at, Instant now) {
        return !at.isBefore(cutoff(now));
    }
}

package com.floaq.accident.entity;

/**
 * 상태 전이 사유 8종 — {@code database/pi.sql} {@code pi_accident_state.reason} CHECK 와 같다.
 *
 * <p><b>종결 주체를 가르는 값이기도 하다</b>(계획.md §9.20). {@code CLOSE} 로 간 사고가
 * 구조로 끝난 것인지 종료된 것인지는 {@code TABLET_RESCUE}/{@code TABLET_CLOSE} 로 갈린다.</p>
 *
 * <p>🔴 <b>관제 웹 종료를 적을 값이 없다.</b> 8종이 전부 선내 동작이다.
 * 후보 {@code WEB_CLOSE} — Pi CHECK 에도 같이 넣어야 해서 IoT 합의 대기(docs/api.md §9 3 #10).
 * 그때까지 관제가 종결하면 사유를 비우고 {@code caused_by} 에 누가 했는지 적는다
 * ({@code AccidentState.byControl}).</p>
 *
 * <p>⚠ 한때 이 자리에 "1시간 자동 종결"과 {@code AUTO_CLOSE} 가 적혀 있었다. <b>그런 동작은 없다</b> —
 * 사고는 사람이 끝낼 때까지 간다. 1시간은 사고 뒤 사진을 찍는 상한이었다(2026-09-21).</p>
 *
 * <p>모르는 값은 400 으로 거절한다 — 조용히 null 로 두면 종결 주체 기록이 사라진다.</p>
 */
public enum StateReason {
    /** AI 감지 → 사고 생성 */
    AI_DETECT,
    /** 투하 완료 → 30초 카운트다운 시작 */
    COUNTDOWN_START,
    /** 카운트다운 만료 → 자동 신고 */
    TIMEOUT,
    TABLET_CANCEL,
    TABLET_REPORT_NOW,
    /** 사람이 유형을 골라 사고를 개시 */
    TABLET_MANUAL,
    /** 구조 확정 → CLOSE */
    TABLET_RESCUE,
    /** 구조 실패·상황 종료 → CLOSE */
    TABLET_CLOSE
}

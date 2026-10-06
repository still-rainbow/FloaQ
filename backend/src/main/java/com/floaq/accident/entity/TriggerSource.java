package com.floaq.accident.entity;

/**
 * 사고를 연 주체 (docs/api.md §4.3).
 *
 * <p>DB CHECK 가 {@code AI} 면 {@code accidentType} 이 {@code MOB} 이도록 강제한다 —
 * <b>AI 감지는 익수만 만든다.</b> 나머지 유형은 사람이 골라야 나온다.</p>
 */
public enum TriggerSource {
    /** Jetson 추론 → Pi 가 사고로 승격 */
    AI,
    /** 키오스크에서 사람이 유형을 골라 개시. 30초 유예 없음 */
    MANUAL
}

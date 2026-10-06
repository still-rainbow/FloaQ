package com.floaq.accident.entity;

/** 투하 결과. {@code FAILED} 도 저장한다 — 발사 정확도 피드백의 근거다 (docs/api.md §4.3). */
public enum LaunchResult {
    SUCCESS, FAILED
}

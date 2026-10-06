package com.floaq.report.entity;

/**
 * 무엇이 이 발신을 일으켰나 — 자동 / 사람이 누름 / 구조 확정에 따른 중지.
 *
 * <p>⚠ {@code accident.report_type}(DISTRESS·URGENCY)과 <b>다른 것이다.</b> 구 ERD 가 둘 다
 * {@code report_type} 이라 불러 뜻이 섞였고, Pi 가 {@code trigger_kind} 로 개명했다(docs/api.md §8 #16).</p>
 */
public enum ReportTriggerKind {
    AUTO, MANUAL, RESCUE
}

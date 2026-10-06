package com.floaq.report.entity;

/**
 * 발신 실패 사유.
 *
 * <p>🔴 <b>{@code NO_INTERNET} 은 화면에 반드시 드러내야 한다</b>(docs/api.md §3.4) —
 * 없으면 사용자는 신고가 나간 줄 안다.</p>
 */
public enum ReportFailReason {
    NO_INTERNET, NO_RECEIVER, TIMEOUT
}

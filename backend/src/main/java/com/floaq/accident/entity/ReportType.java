package com.floaq.accident.entity;

/**
 * 긴급도 — DSC category 규격에서 인용했다 (docs/api.md §1.7 · 계획.md §9.21).
 * 우리가 만든 구분이 아니라서 "그 분류의 근거가 뭐냐"에 답할 수 있다.
 *
 * <p>받는 쪽의 행동이 달라서 한 버튼으로 묶을 수 없다 —
 * 응급 환자를 조난으로 쏘면 구조 세력이 출동한다.</p>
 *
 * <p><b>SAFETY 는 뺐다 (결정 2026-09-17).</b> "내 배에 아무 일도 안 일어났다"는 신고라
 * 사고를 열면 안 되는데, 안 열면 데이터가 갈 곳이 없다. 열면 종결될 계기가 없어
 * {@code closed_at} 이 null 인 행이 쌓이고, {@code uq_accident_active} 때문에
 * <b>진행 중 사고가 있으면 위험물 신고가 막힌다.</b>
 * 되살리려면 별도 테이블({@code safety_broadcast})이 필요하다 — 1차 범위 밖이다.</p>
 *
 * <p>⚠ Pi({@code iot/pi/floaq/contracts/enums.py})는 아직 SAFETY 를 갖고 있다. 전달 필요.</p>
 */
public enum ReportType {
    /** 조난. 구조 세력 출동 */
    DISTRESS,
    /** 긴급. 지원·중계. 사고는 연다 */
    URGENCY
}

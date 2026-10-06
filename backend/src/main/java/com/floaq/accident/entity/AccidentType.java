package com.floaq.accident.entity;

/**
 * 사고 유형 8종 (결정 2026-09-17 · docs/api.md §1.7 · §8 #16).
 *
 * <p>유형을 우리가 정의하지 않고 <b>ITU-R M.493 nature of distress 코드에 대응</b>시켰다 —
 * §6 에서 위험 임계치를 기상청 특보 기준으로 인용한 것과 같은 논리다.</p>
 *
 * <p>DSC 코드 매핑은 <b>Pi 가 한 곳에서만</b> 한다({@code ACCIDENT_ROUTING}).
 * 서버는 {@code accident.report_dsc} 를 받아 적을 뿐 계산하지 않는다 — 두 벌이 되면 갈린다.</p>
 *
 * <p>Pi 도 8종으로 맞췄다 (2026-09-18 {@code dev-iot} 확인 — {@code contracts/enums.py}).
 * {@code HAZARD}·{@code ABANDON_SHIP} 이 빠졌고 {@code ReportType} 에서 {@code SAFETY} 도 사라졌다.</p>
 *
 * <p>⚠ {@code ABANDON_SHIP}(퇴함)을 되살린다면 {@code (DISTRESS, 108)} 이다. 전에 Pi 가
 * {@code (SAFETY, 108)} 로 라우팅했는데 <b>퇴함은 조난이다</b> —
 * DSC 의 <b>category</b> 108(safety)과 <b>nature of distress</b> 108(abandoning ship)이 다른 표다.
 * 다시 넣을 때 또 틀리지 않게 여기 남겨 둔다.</p>
 */
public enum AccidentType {
    /** 익수. AI 자동 감지가 만드는 유일한 유형 (nature 110) */
    MOB,
    /** 화재·폭발 (100) */
    FIRE,
    /** 침수 (101). 롤 각이 임계를 넘으면 Pi 가 104(전복 위험)로 올린다 */
    FLOODING,
    /** 충돌 (102) */
    COLLISION,
    /** 좌초 (103) */
    GROUNDING,
    /** 기관 고장·조종 불능 (106) */
    ENGINE_FAILURE,
    /** 기타 조난 (107) */
    OTHER_DISTRESS,
    /** 응급 환자·부상. URGENCY — 조난 코드에 의료가 없어 {@code report_dsc} 는 null */
    MEDICAL
}

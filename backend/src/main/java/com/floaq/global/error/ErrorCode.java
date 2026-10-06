package com.floaq.global.error;

import lombok.Getter;
import org.springframework.http.HttpStatus;

/**
 * 오류 코드 체계 (Jira floaq-107).
 *
 * <p>{@code code} 값은 {@link com.floaq.global.response.ErrorResponse} 의 {@code code} 로
 * 그대로 노출된다. <b>프론트가 문구가 아니라 이 문자열로 분기하므로 이름을 바꾸면 화면이 깨진다.</b></p>
 *
 * <p>규칙 셋.</p>
 * <ul>
 *   <li><b>{@code 도메인_사유}</b> 형태. 접두어만 보고 어느 도메인이 거절했는지 안다.</li>
 *   <li><b>HTTP 상태를 여기 함께 둔다.</b> 컨트롤러마다 상태를 고르면 같은 사유가 곳마다 다른 코드로 나간다.</li>
 *   <li><b>"이미 X 됨"은 404 가 아니라 409 다.</b> 리소스는 있는데 지금 상태와 충돌한 것이다 —
 *       404 로 내려보내면 클라이언트가 "사고가 사라졌다"로 읽는다.</li>
 * </ul>
 */
@Getter
public enum ErrorCode {

    // ── 공통 ────────────────────────────────────────────────
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "COMMON_INVALID_INPUT", "잘못된 입력입니다."),
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "COMMON_UNAUTHORIZED", "인증이 필요합니다."),
    FORBIDDEN(HttpStatus.FORBIDDEN, "COMMON_FORBIDDEN", "권한이 없습니다."),
    NOT_FOUND(HttpStatus.NOT_FOUND, "COMMON_NOT_FOUND", "리소스를 찾을 수 없습니다."),
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "COMMON_INTERNAL_ERROR", "서버 오류가 발생했습니다."),

    // ── 인증 ────────────────────────────────────────────────
    AUTH_INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "AUTH_INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다."),
    AUTH_INVALID_TOKEN(HttpStatus.UNAUTHORIZED, "AUTH_INVALID_TOKEN", "유효하지 않은 토큰입니다."),
    /** 가입 신청은 했으나 SA 승인 전. 자격증명 오류와 문구가 달라야 사용자가 기다릴 줄 안다 (WEB-02). */
    AUTH_ACCOUNT_PENDING(HttpStatus.FORBIDDEN, "AUTH_ACCOUNT_PENDING", "승인 대기 중인 계정입니다."),
    /** 가입 신청이 반려됨(V5). 비활성화와 문구가 달라야 한다 — 계정이 된 적이 없는 신청이다 (WEB-07). */
    AUTH_ACCOUNT_REJECTED(HttpStatus.FORBIDDEN, "AUTH_ACCOUNT_REJECTED", "반려된 가입 신청입니다."),
    AUTH_ACCOUNT_DELETED(HttpStatus.FORBIDDEN, "AUTH_ACCOUNT_DELETED", "사용할 수 없는 계정입니다."),
    AUTH_ALREADY_REGISTERED(HttpStatus.CONFLICT, "AUTH_ALREADY_REGISTERED", "이미 신청된 계정입니다."),

    // ── 계정 관리 ────────────────────────────────────────────
    /** 승인·반려 대상이 없다. COMMON_NOT_FOUND 로는 화면이 무엇이 없는지 문구를 못 고른다 (api.md §7.3). */
    USER_NOT_FOUND(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "존재하지 않는 계정입니다."),

    // ── Pi(Pi) ────────────────────────────────────────────
    PI_UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "PI_UNAUTHORIZED", "Pi API 인증에 실패했습니다."),
    /**
     * 늦게 도착한 옛 상태가 새 상태를 덮으려 한 경우 (단조 전이 위반).
     * 오류지만 Pi 는 재전송하면 안 된다 — 재전송해도 결과가 같다.
     */
    PI_STALE_STATE(HttpStatus.CONFLICT, "PI_STALE_STATE", "이미 더 나중 상태가 반영돼 있습니다."),
    PI_SHIP_UNKNOWN(HttpStatus.NOT_FOUND, "PI_SHIP_UNKNOWN", "등록되지 않은 선박입니다."),
    /**
     * 등록은 됐지만 아직 승인 전({@code WAIT})이거나 반려됨({@code REJECTED}).
     *
     * <p><b>{@code PI_SHIP_UNKNOWN} 과 갈라 둔 이유</b>: Pi 가 할 일이 다르다.
     * 모르는 선박은 설정 문제라 사람이 풀어야 하지만, 승인 대기는 <b>기다리면 풀린다</b> —
     * Pi 는 큐를 쥐고 화면에 "승인 대기"를 띄우면 되고, 데이터는 승인 뒤에 밀린 것부터 올라간다.</p>
     */
    PI_SHIP_NOT_APPROVED(HttpStatus.FORBIDDEN, "PI_SHIP_NOT_APPROVED", "아직 승인되지 않은 선박입니다."),
    /**
     * 서버가 모르는 스키마 버전({@code v}). <b>일반 400 과 갈라 둔 이유</b>:
     * Pi 는 이 코드를 보면 행을 버리지 않고 전송만 멈춘다(docs/api.md §4.1 재시도 표).
     * 일반 400 으로 주면 서버가 구버전일 때 Pi 의 모든 전송이 실패로 찍히고 폐기된다.
     */
    PI_UNSUPPORTED_VERSION(HttpStatus.BAD_REQUEST, "PI_UNSUPPORTED_VERSION", "지원하지 않는 Pi 스키마 버전입니다."),

    // ── 선박 ────────────────────────────────────────────────
    SHIP_NOT_FOUND(HttpStatus.NOT_FOUND, "SHIP_NOT_FOUND", "존재하지 않는 선박입니다."),
    SHIP_ALREADY_REGISTERED(HttpStatus.CONFLICT, "SHIP_ALREADY_REGISTERED", "이미 등록된 선박입니다."),

    // ── 사고 ────────────────────────────────────────────────
    // ⚠ 아래 셋의 코드 문자열은 kiosk 의 REJECT_TEXT 키와 같아야 한다
    //    (apps/kiosk/src/pages/Kiosk.tsx). 바꾸면 화면에 사유가 안 뜬다.
    ACCIDENT_NOT_FOUND(HttpStatus.NOT_FOUND, "ACCIDENT_NOT_FOUND", "존재하지 않는 사고입니다."),
    ALREADY_REPORTED(HttpStatus.CONFLICT, "ALREADY_REPORTED", "이미 신고가 발신됐습니다."),
    ALREADY_RESOLVED(HttpStatus.CONFLICT, "ALREADY_RESOLVED", "이미 종결된 사고입니다."),
    ALREADY_CANCELLED(HttpStatus.CONFLICT, "ALREADY_CANCELLED", "이미 취소된 사고입니다."),
    NO_ACTIVE_INCIDENT(HttpStatus.NOT_FOUND, "NO_ACTIVE_INCIDENT", "진행 중인 사고가 없습니다."),
    INVALID_STATE(HttpStatus.CONFLICT, "INVALID_STATE", "지금 상태에서는 할 수 없는 동작입니다."),
    /** 동시 사고 1건 (상세기획 E1). DB 의 부분 UNIQUE 인덱스가 같은 규칙을 한 번 더 막는다. */
    ACCIDENT_ALREADY_ACTIVE(HttpStatus.CONFLICT, "ACCIDENT_ALREADY_ACTIVE", "이미 진행 중인 사고가 있습니다."),

    // ── 해양 공공데이터 ──────────────────────────────────────
    /**
     * 수집 실패. <b>빈 값으로 200 을 주지 않는다</b> — "데이터 없음"과 구분되지 않기 때문이다.
     * 화면은 이 코드를 받으면 마지막 캐시 + 경과 시간을 보여준다(계획.md §9.10·§9.18).
     */
    OCEAN_SOURCE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "OCEAN_SOURCE_UNAVAILABLE", "해양 데이터를 가져올 수 없습니다."),
    OCEAN_SOURCE_UNKNOWN(HttpStatus.NOT_FOUND, "OCEAN_SOURCE_UNKNOWN", "등록되지 않은 해양 데이터 소스입니다."),
    /**
     * 보관 기간(24시간) 밖 시각을 물었다. 404 가 아니라 410 — 값이 있었는데 보관 기간이 지나 지웠다.
     * 표류 재계산이 이 코드를 받으면 "그 시각 입력 없음"으로 화면에 밝혀야 한다(OceanRetention).
     */
    OCEAN_OUT_OF_RETENTION(HttpStatus.GONE, "OCEAN_OUT_OF_RETENTION", "보관 기간(24시간)이 지난 시각입니다."),

    // ── 미디어 ──────────────────────────────────────────────
    MEDIA_NOT_FOUND(HttpStatus.NOT_FOUND, "MEDIA_NOT_FOUND", "영상을 찾을 수 없습니다."),
    MEDIA_TOO_LARGE(HttpStatus.CONTENT_TOO_LARGE, "MEDIA_TOO_LARGE", "업로드 용량이 제한을 초과했습니다."),
    // 400 과 가른 이유: Pi 가 할 일이 다르다. 형식이 틀린 건 재시도해도 영영 안 붙는다 —
    // 그 장을 버리고 다음으로 가야 한다. 400 으로 뭉뚱그리면 같은 장을 무한히 다시 보낸다
    MEDIA_UNSUPPORTED_TYPE(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "MEDIA_UNSUPPORTED_TYPE", "지원하지 않는 파일 형식입니다."),
    STORAGE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "STORAGE_UNAVAILABLE", "저장소에 접근할 수 없습니다.");

    private final HttpStatus status;
    private final String code;
    private final String message;

    ErrorCode(HttpStatus status, String code, String message) {
        this.status = status;
        this.code = code;
        this.message = message;
    }
}

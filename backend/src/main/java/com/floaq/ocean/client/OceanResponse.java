package com.floaq.ocean.client;

import tools.jackson.databind.JsonNode;

/**
 * 공공데이터 응답 한 건 — 봉투 제거 + 결과 코드 추출.
 *
 * 봉투 3종 (2026-09-11 실호출 · 활용가이드 PDF)
 *
 * ① {"response":{"header":{…},"body":{…}}}                    ROMS·기상특보
 * ② {"header":{…},"body":{…}}                                 response 없는 변형
 * ③ {"OpenAPI_ServiceResponse":{"cmmMsgHeader":{…}}}          게이트웨이 (HTTP 403)
 *
 * ③ 은 필드명·경로·HTTP 상태가 전부 다름. 한쪽만 보면 키 만료(31)를 조용히 놓침.
 *
 * ROMS 는 ② 다 (2026-09-13 실호출로 확정). 가이드 PDF 응답 예제의 response 는 틀림.
 * ①은 기상특보(1360000) — 같은 data.go.kr 인데 발급 부처가 다름. 명세를 믿지 않고 둘 다 수용.
 */
public record OceanResponse(int httpStatus, String code, String message, JsonNode body) {

    public static final String OK = "00";

    /** 데이터 없음. 실패 아님 — 오류 처리 시 관측 공백마다 알람 */
    public static final String NO_DATA = "03";

    public boolean isOk() {
        return OK.equals(code);
    }

    /** 가이드는 "3", 실호출은 "03". 양쪽 수용 */
    public boolean isNoData() {
        return NO_DATA.equals(code) || "3".equals(code);
    }

    /** 하루 예산 소진. 우리가 막은 것이지 발급처가 거부한 것이 아니다 */
    public static final String QUOTA_GUARD = "QUOTA_GUARD";

    /** 모르는 코드는 전부 실패 — 조용한 성공보다 시끄러운 실패 */
    public boolean isFailure() {
        return !isOk() && !isNoData();
    }

    public static OceanResponse of(int httpStatus, JsonNode root) {
        if (root == null || root.isNull()) {
            // 200 + 본문 없음도 실패
            return new OceanResponse(httpStatus, "HTTP_" + httpStatus, "본문 없음", null);
        }

        // ③ 먼저. header 자체가 없어 ①②로 읽으면 코드가 빔
        JsonNode gateway = root.path("OpenAPI_ServiceResponse").path("cmmMsgHeader");
        if (!gateway.isMissingNode() && !gateway.isNull()) {
            return new OceanResponse(httpStatus,
                    text(gateway, "returnReasonCode", "HTTP_" + httpStatus),
                    text(gateway, "errMsg", null),
                    null);
        }

        JsonNode envelope = root.has("response") ? root.get("response") : root;
        JsonNode header = envelope.path("header");
        JsonNode body = envelope.path("body");
        return new OceanResponse(httpStatus,
                text(header, "resultCode", "HTTP_" + httpStatus),
                text(header, "resultMsg", null),
                body.isMissingNode() || body.isNull() ? null : body);
    }

    private static String text(JsonNode node, String field, String fallback) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? fallback : value.asString();
    }
}

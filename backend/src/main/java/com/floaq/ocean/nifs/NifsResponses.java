package com.floaq.ocean.nifs;

import tools.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;

/**
 * 수과원 응답 공통 처리.
 *
 * 2026-09-13 실호출로 확인한 것
 *   base-url 에 /api/ 가 있어야 한다. 없으면 302 이고 WebClient 는 따라가지 않아 빈 본문이 온다
 *   봉투는 {"header":{...},"body":{"item":[...]}} 로 response 한 겹이 없다
 *   응답은 UTF-8 이다. PDF 의 EUC-KR 은 XML 엔드포인트 쪽이다
 *   빈 값이 null 이 아니라 빈 문자열로 온다. 숫자로 바로 파싱하면 터진다
 *   본문에 HTML 이 섞인다. 그대로 렌더하면 깨지거나 XSS 가 된다
 */
public final class NifsResponses {

    private NifsResponses() {
    }

    public static List<JsonNode> items(JsonNode body) {
        return array(body == null ? null : body.path("item"));
    }

    public static List<JsonNode> array(JsonNode node) {
        List<JsonNode> list = new ArrayList<>();
        if (node == null) {
            return list;
        }
        if (node.isObject()) {
            list.add(node);
        } else if (node.isArray()) {
            node.forEach(list::add);
        }
        return list;
    }

    /** 빈 문자열도 없는 값으로 본다 */
    public static String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (value.isMissingNode() || value.isNull()) {
            return null;
        }
        String raw = value.asString();
        return raw == null || raw.isBlank() ? null : raw.trim();
    }

    /** 빈 문자열이면 null. 0 으로 두면 "밀도 0" 과 "측정 안 함" 이 같아진다 */
    public static Double number(JsonNode node, String field) {
        String raw = text(node, field);
        if (raw == null) {
            return null;
        }
        try {
            return Double.valueOf(raw);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * HTML 태그와 엔티티를 걷어내 평문으로 만든다.
     *
     * 화면이 innerHTML 로 넣을 수 있는 값이라 태그를 남기면 XSS 경로가 된다.
     * 서식을 살릴 이유도 없다 — 대시보드는 한 문단으로만 보여준다(§9.18).
     */
    public static String plainText(String raw) {
        if (raw == null) {
            return null;
        }
        String text = raw.replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("<[^>]*>", "")
                .replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replaceAll("&#\\d+;", "")
                .replaceAll("[ \\t]+", " ")
                .replaceAll("\\n{3,}", "\n\n")
                .trim();
        return text.isEmpty() ? null : text;
    }
}

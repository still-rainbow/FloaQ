package com.floaq.ocean.zone;

import java.util.Locale;

/**
 * 해구 층. 대해구는 전국, 소해구는 본선 주변만 받는다.
 *
 * 한 테이블(ocean_zone)에 둘을 두고 szone 으로 가른다 — 대해구 행은 szone = 0.
 */
public enum ZoneLevel {

    /** 위·경도 0.5° (약 55km). 전국 1,330개 */
    LARGE("szone = 0", 0.5),
    /** 대해구를 3x3 으로 나눈 1/6° (약 18km). 수온·시정·강수·너울이 여기만 있다 */
    SMALL("szone > 0", 0.5 / 3);

    /** SQL 조건. 사용자 입력이 아니라 상수라 문자열로 이어 붙여도 안전하다 */
    final String where;
    private final double stepDeg;

    ZoneLevel(String where, double stepDeg) {
        this.where = where;
        this.stepDeg = stepDeg;
    }

    public double stepDeg() {
        return stepDeg;
    }

    /** API 표기 — large · small */
    public String code() {
        return name().toLowerCase(Locale.ROOT);
    }

    /** @return 모르는 값이면 null — 호출부가 400 으로 답한다 */
    public static ZoneLevel parse(String raw) {
        if (raw == null) {
            return null;
        }
        return switch (raw.trim().toLowerCase(Locale.ROOT)) {
            case "large" -> LARGE;
            case "small" -> SMALL;
            default -> null;
        };
    }
}

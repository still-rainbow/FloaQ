package com.floaq.pi;

import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.Instant;

/**
 * Pi 수신 배치의 null 안전 바인딩.
 *
 * <p><b>왜 따로 두나.</b> {@code setString}·{@code setObject} 에 null 을 넘기면 드라이버가
 * 타입을 못 정해 터지는 경우가 있다. {@code setNull} 로 SQL 타입을 명시해야 한다 —
 * Pi 가 보내는 컬럼 대부분이 nullable 이라 수신 서비스마다 같은 코드가 필요하다.
 * {@link PiIngestService} 안에 private 으로 있던 것을 세 서비스가 쓰게 꺼냈다(2026-09-18).</p>
 *
 * <p><b>시각은 전부 Unix 초다</b>(docs/api.md §1). Pi SQLite 가 INTEGER 로 들고 있고
 * 그대로 보낸다 — 문자열 시각을 받지 않는다.</p>
 */
final class PiBind {

    private PiBind() {
    }

    /** enum 이름. null 이면 null — CHECK 가 있는 컬럼은 여기서 거르지 않고 DB 가 본다 */
    static String name(Enum<?> e) {
        return e == null ? null : e.name();
    }

    static void setText(PreparedStatement ps, int i, String v) throws SQLException {
        if (v == null) {
            ps.setNull(i, Types.VARCHAR);
        } else {
            ps.setString(i, v);
        }
    }

    /** Unix 초 → timestamptz. Pi 가 보내는 모든 시각이 이 경로를 탄다 */
    static void setEpoch(PreparedStatement ps, int i, Long epochSec) throws SQLException {
        if (epochSec == null) {
            ps.setNull(i, Types.TIMESTAMP_WITH_TIMEZONE);
        } else {
            ps.setTimestamp(i, Timestamp.from(Instant.ofEpochSecond(epochSec)));
        }
    }

    static void setInt(PreparedStatement ps, int i, Integer v) throws SQLException {
        if (v == null) {
            ps.setNull(i, Types.INTEGER);
        } else {
            ps.setInt(i, v);
        }
    }

    static void setDouble(PreparedStatement ps, int i, Double v) throws SQLException {
        if (v == null) {
            ps.setNull(i, Types.DOUBLE);
        } else {
            ps.setDouble(i, v);
        }
    }

    /**
     * {@code real} 컬럼용. {@code setDouble} 로 넣어도 PG 가 캐스팅하지만,
     * 정밀도 차이가 로그·비교에서 헷갈리게 나와 자리를 나눠 둔다.
     */
    static void setFloat(PreparedStatement ps, int i, Float v) throws SQLException {
        if (v == null) {
            ps.setNull(i, Types.REAL);
        } else {
            ps.setFloat(i, v);
        }
    }

    /**
     * SQLite 는 boolean 이 없어 Pi 가 0/1 로 들고 있다. Pi {@code sync.py} 가 casts 로
     * 이미 true/false 로 바꿔 보내지만(`is_pressed`·`is_current`), 빠진 값은 null 로 온다.
     *
     * @param fallback 값이 없을 때 쓸 기본. NOT NULL 컬럼이라 null 을 그대로 넣을 수 없다
     */
    static void setBool(PreparedStatement ps, int i, Boolean v, boolean fallback) throws SQLException {
        ps.setBoolean(i, v == null ? fallback : v);
    }
}

package com.floaq.ocean.zone;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * ocean_zone 읽기·쓰기.
 *
 * JPA 기각 — ocean_roms 와 같은 이유. 발표본 캐시를 통째로 교체하므로 엔티티 상태 관리가 줄 것이 없고,
 * 대해구 한 발표본이 3만 4천 행이라 영속성 컨텍스트 적재가 순손해다.
 */
@Slf4j
@Repository
@RequiredArgsConstructor
public class OceanZoneStore {

    /** 같은 발효시각·해구면 새 발표본 값으로 덮는다 — 더 최근 모델 실행이 그 시각의 더 나은 추정이다 */
    private static final String UPSERT = """
            INSERT INTO ocean_zone (tma_fc, tma_ef, lzone, szone, lat_min, lat_max, lon_min, lon_max,
                wave_height_m, wave_period_max_s, wave_dir_deg, wind_speed_ms, wind_dir_deg,
                visibility_m, rain_mm, water_temp_c, swell_level, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tma_ef, lzone, szone) DO UPDATE SET
                tma_fc = EXCLUDED.tma_fc,
                lat_min = EXCLUDED.lat_min, lat_max = EXCLUDED.lat_max,
                lon_min = EXCLUDED.lon_min, lon_max = EXCLUDED.lon_max,
                wave_height_m = EXCLUDED.wave_height_m, wave_period_max_s = EXCLUDED.wave_period_max_s,
                wave_dir_deg = EXCLUDED.wave_dir_deg, wind_speed_ms = EXCLUDED.wind_speed_ms,
                wind_dir_deg = EXCLUDED.wind_dir_deg, visibility_m = EXCLUDED.visibility_m,
                rain_mm = EXCLUDED.rain_mm, water_temp_c = EXCLUDED.water_temp_c,
                swell_level = EXCLUDED.swell_level, fetched_at = EXCLUDED.fetched_at
            """;

    /** 그 층의 최신 발표본. 화면(슬라이더·범례·"이미 받았나")은 이것만 본다 — 보관분은 시각을 지정한 조회에서만 */
    private static String latestIssuance(ZoneLevel level) {
        return "tma_fc = (SELECT max(tma_fc) FROM ocean_zone WHERE " + level.where + ")";
    }

    private static final String COLUMNS = """
            tma_fc, tma_ef, lzone, szone, lat_min, lat_max, lon_min, lon_max,
            wave_height_m, wave_period_max_s, wave_dir_deg, wind_speed_ms, wind_dir_deg,
            visibility_m, rain_mm, water_temp_c, swell_level
            """;

    private final JdbcTemplate jdbc;

    /**
     * 한 층의 새 발표본 반영 — **지금 뒤는 교체, 지금까지는 24시간 보관.**
     *
     * 전량 교체였다(2026-09-14 오전). 새 발표본이 오거나 소해구 해역이 바뀌면 사고 시각의 바람이 사라진다
     * ({@link com.floaq.ocean.OceanRetention}).
     *
     *   발효 > 지금    지우고 새 발표본으로 — 옛 소해구 해역의 미래 칸이 남으면 지금 해역 화면에 섞인다
     *   발효 ≤ 지금    남긴다. 같은 발효시각·해구면 새 값으로 덮는다. "지금"을 덮는 구간도 여기 든다
     *   24시간 전      지운다
     *
     * 한 트랜잭션 — 중간에 실패하면 옛 발표본이 남는다. 비는 것보다 낫다(§9.10).
     *
     * @param cells 빈 목록이면 무동작. 생산 전(NOT_READY) 응답으로 기존 발표본을 지우면 화면이 빈다
     */
    @Transactional
    public int replace(ZoneLevel level, List<ZoneCell> input, Instant fetchedAt) {
        Instant cutoff = com.floaq.ocean.OceanRetention.cutoff(fetchedAt);
        List<ZoneCell> cells = input.stream().filter(c -> !c.tmaEf().isBefore(cutoff)).toList();
        if (cells.isEmpty()) {
            log.warn("[ocean] marine-zone {} — 0칸. 기존 발표본 유지", level.code());
            return 0;
        }
        jdbc.update("DELETE FROM ocean_zone WHERE " + level.where + " AND tma_ef > ?", Timestamp.from(fetchedAt));
        jdbc.update("DELETE FROM ocean_zone WHERE " + level.where + " AND tma_ef < ?", Timestamp.from(cutoff));
        Timestamp fetched = Timestamp.from(fetchedAt);
        jdbc.batchUpdate(UPSERT, cells, 1000, (ps, c) -> {
            bindCell(ps, c);
            ps.setTimestamp(18, fetched);
        });
        return cells.size();
    }

    /**
     * 1~17번 자리를 채운다. 18번부터는 호출부 소관 —
     * {@code ocean_zone} 은 {@code fetched_at}, {@code ocean_zone_pending} 은 {@code chunk_idx}+{@code fetched_at}.
     *
     * <p>두 테이블이 앞 17개를 공유하므로 바인딩을 한 곳에 둔다. 두 벌이면 컬럼을 하나 추가할 때
     * <b>한쪽만 고쳐져 값이 밀린다</b> — 컴파일도 통과하고 예외도 안 난다.</p>
     */
    private static void bindCell(java.sql.PreparedStatement ps, ZoneCell c) throws java.sql.SQLException {
        ps.setTimestamp(1, Timestamp.from(c.tmaFc()));
        ps.setTimestamp(2, Timestamp.from(c.tmaEf()));
        ps.setInt(3, c.lzone());
        ps.setInt(4, c.szone());
        ps.setDouble(5, c.latMin());
        ps.setDouble(6, c.latMax());
        ps.setDouble(7, c.lonMin());
        ps.setDouble(8, c.lonMax());
        setNullable(ps, 9, c.waveHeightM());
        setNullable(ps, 10, c.wavePeriodMaxS());
        setNullable(ps, 11, c.waveDirDeg());
        setNullable(ps, 12, c.windSpeedMs());
        setNullable(ps, 13, c.windDirDeg());
        setNullable(ps, 14, c.visibilityM());
        setNullable(ps, 15, c.rainMm());
        setNullable(ps, 16, c.waterTempC());
        if (c.swellLevel() == null) {
            ps.setNull(17, Types.SMALLINT);
        } else {
            ps.setInt(17, c.swellLevel());
        }
    }


    // ── 전국 소해구 스테이징 (V20260917_1731) ──────────────────────────
    //
    // 전국은 발표본당 884회 · 약 54분이라 한 틱에 몰 수 없다. 틱마다 몇 묶음씩 여기 쌓고,
    // 다 받으면 한 트랜잭션에 ocean_zone 으로 옮긴다.
    //
    // ⚠ ocean_zone 에 바로 쓰면 읽기가 `tma_fc = max(tma_fc)` 로 **반쪽 발표본**을 고른다.
    //   슬라이더 중간이 비면 사람은 그 시각을 "값 없음"이 아니라 잔잔한 바다로 읽는다.

    private static final String STAGE_UPSERT = """
            INSERT INTO ocean_zone_pending (tma_fc, tma_ef, lzone, szone, lat_min, lat_max, lon_min, lon_max,
                wave_height_m, wave_period_max_s, wave_dir_deg, wind_speed_ms, wind_dir_deg,
                visibility_m, rain_mm, water_temp_c, swell_level, chunk_idx, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tma_ef, lzone, szone) DO UPDATE SET
                tma_fc = EXCLUDED.tma_fc,
                lat_min = EXCLUDED.lat_min, lat_max = EXCLUDED.lat_max,
                lon_min = EXCLUDED.lon_min, lon_max = EXCLUDED.lon_max,
                wave_height_m = EXCLUDED.wave_height_m, wave_period_max_s = EXCLUDED.wave_period_max_s,
                wave_dir_deg = EXCLUDED.wave_dir_deg, wind_speed_ms = EXCLUDED.wind_speed_ms,
                wind_dir_deg = EXCLUDED.wind_dir_deg, visibility_m = EXCLUDED.visibility_m,
                rain_mm = EXCLUDED.rain_mm, water_temp_c = EXCLUDED.water_temp_c,
                swell_level = EXCLUDED.swell_level, chunk_idx = EXCLUDED.chunk_idx,
                fetched_at = EXCLUDED.fetched_at
            """;

    /**
     * 묶음 하나를 적재한다. <b>다른 발표본이 쌓여 있으면 먼저 버린다</b> —
     * 새 발표본이 나왔는데 옛 진행분이 남아 있으면 둘이 섞인 채 "완료"로 올라간다.
     *
     * @return 이 발표본으로 지금까지 받은 묶음 수
     */
    @Transactional
    public int stage(ZoneLevel level, Instant fc, int chunkIdx, List<ZoneCell> cells, Instant fetchedAt) {
        jdbc.update("DELETE FROM ocean_zone_pending WHERE " + level.where + " AND tma_fc <> ?",
                Timestamp.from(fc));
        Timestamp fetched = Timestamp.from(fetchedAt);
        jdbc.batchUpdate(STAGE_UPSERT, cells, 1000, (ps, c) -> {
            bindCell(ps, c);
            ps.setInt(18, chunkIdx);
            ps.setTimestamp(19, fetched);
        });
        return stagedChunks(level, fc);
    }

    /** 이 발표본으로 받아 둔 묶음 수. 다음 틱이 이어받을 지점이자 완료 판정이다 */
    public int stagedChunks(ZoneLevel level, Instant fc) {
        Integer n = jdbc.queryForObject(
                "SELECT count(DISTINCT chunk_idx) FROM ocean_zone_pending WHERE " + level.where
                        + " AND tma_fc = ?", Integer.class, Timestamp.from(fc));
        return n == null ? 0 : n;
    }

    /**
     * 스테이징을 본 테이블로 올린다. {@link #replace} 와 <b>같은 의미</b>여야 한다 —
     * 미래 칸은 지우고 새 발표본으로, 지난 칸은 24시간까지 남긴다.
     *
     * <p>메모리로 읽어 올리지 않고 {@code INSERT ... SELECT} 로 옮긴다. 전국 소해구 한 발표본이
     * 약 34,580행이라 왕복하면 그만큼을 힙에 올렸다 내린다.</p>
     *
     * @return 옮긴 행 수. 0 이면 보관 기한 밖이라 남길 것이 없었다는 뜻
     */
    @Transactional
    public int promote(ZoneLevel level, Instant fc, Instant fetchedAt) {
        Instant cutoff = com.floaq.ocean.OceanRetention.cutoff(fetchedAt);
        Timestamp now = Timestamp.from(fetchedAt);
        Timestamp cut = Timestamp.from(cutoff);

        jdbc.update("DELETE FROM ocean_zone WHERE " + level.where + " AND tma_ef > ?", now);
        jdbc.update("DELETE FROM ocean_zone WHERE " + level.where + " AND tma_ef < ?", cut);
        int moved = jdbc.update("""
                INSERT INTO ocean_zone (tma_fc, tma_ef, lzone, szone, lat_min, lat_max, lon_min, lon_max,
                    wave_height_m, wave_period_max_s, wave_dir_deg, wind_speed_ms, wind_dir_deg,
                    visibility_m, rain_mm, water_temp_c, swell_level, fetched_at)
                SELECT tma_fc, tma_ef, lzone, szone, lat_min, lat_max, lon_min, lon_max,
                    wave_height_m, wave_period_max_s, wave_dir_deg, wind_speed_ms, wind_dir_deg,
                    visibility_m, rain_mm, water_temp_c, swell_level, ?
                FROM ocean_zone_pending
                WHERE """ + level.where + """
                  AND tma_fc = ? AND tma_ef >= ?
                ON CONFLICT (tma_ef, lzone, szone) DO UPDATE SET
                    tma_fc = EXCLUDED.tma_fc,
                    wave_height_m = EXCLUDED.wave_height_m, wave_period_max_s = EXCLUDED.wave_period_max_s,
                    wave_dir_deg = EXCLUDED.wave_dir_deg, wind_speed_ms = EXCLUDED.wind_speed_ms,
                    wind_dir_deg = EXCLUDED.wind_dir_deg, visibility_m = EXCLUDED.visibility_m,
                    rain_mm = EXCLUDED.rain_mm, water_temp_c = EXCLUDED.water_temp_c,
                    swell_level = EXCLUDED.swell_level, fetched_at = EXCLUDED.fetched_at
                """, now, Timestamp.from(fc), cut);
        jdbc.update("DELETE FROM ocean_zone_pending WHERE " + level.where);
        return moved;
    }

    /** 진행 중인 발표본. 없으면 empty — 화면이 "받는 중"을 이걸로 판단한다 */
    public Optional<Instant> pendingIssuance(ZoneLevel level) {
        Timestamp t = jdbc.queryForObject(
                "SELECT max(tma_fc) FROM ocean_zone_pending WHERE " + level.where, Timestamp.class);
        return Optional.ofNullable(t).map(Timestamp::toInstant);
    }

    /** 저장된 발표시각. 없으면 empty — 수집기가 "이미 최신인가"를 이걸로 판단한다 */
    public Optional<Instant> issuance(ZoneLevel level) {
        Timestamp t = jdbc.queryForObject("SELECT max(tma_fc) FROM ocean_zone WHERE " + level.where, Timestamp.class);
        return Optional.ofNullable(t).map(Timestamp::toInstant);
    }

    /**
     * 최신 발표본의 대해구 번호. 소해구 수집기가 "같은 해구를 이미 받았나"를 판단한다.
     * 보관분(옛 해역)을 섞으면 집합이 영영 달라 매시 다시 받는다.
     */
    public List<Integer> zones(ZoneLevel level) {
        return jdbc.query("SELECT DISTINCT lzone FROM ocean_zone WHERE " + level.where
                        + " AND " + latestIssuance(level) + " ORDER BY lzone",
                (rs, n) -> rs.getInt("lzone"));
    }

    /** 최신 발표본의 발효시각, 오름차순. 시간 슬라이더 눈금 — 24시간 보관분은 싣지 않는다 */
    public List<Instant> times(ZoneLevel level) {
        return jdbc.query("SELECT DISTINCT tma_ef FROM ocean_zone WHERE " + level.where
                        + " AND " + latestIssuance(level) + " ORDER BY tma_ef",
                (rs, n) -> rs.getTimestamp("tma_ef").toInstant());
    }

    /** 보관분까지 모든 발효시각, 오름차순. 시각을 지정한 조회(사고 시각 재계산)가 프레임을 고를 때 */
    public List<Instant> allTimes(ZoneLevel level) {
        return jdbc.query("SELECT DISTINCT tma_ef FROM ocean_zone WHERE " + level.where + " ORDER BY tma_ef",
                (rs, n) -> rs.getTimestamp("tma_ef").toInstant());
    }

    /**
     * 한 프레임. 그 발효시각을 가진 **가장 새 발표본**만 준다.
     *
     * 소해구 해역이 바뀐 뒤 "지금" 구간에는 옛 해역 칸(옛 발표본)과 새 해역 칸(새 발표본)이 같이 남는다 —
     * 둘 다 주면 지금 해역 화면에 먼 바다 칸이 섞인다. 새 발표본이 덮지 않은 과거 프레임은 옛 발표본 그대로다.
     */
    public List<ZoneCell> cells(ZoneLevel level, Instant tmaEf) {
        Timestamp ef = Timestamp.from(tmaEf);
        return jdbc.query("SELECT " + COLUMNS + " FROM ocean_zone WHERE " + level.where
                        + " AND tma_ef = ? AND tma_fc = (SELECT max(tma_fc) FROM ocean_zone WHERE "
                        + level.where + " AND tma_ef = ?) ORDER BY lzone, szone",
                CELL, ef, ef);
    }

    /**
     * 좌표가 든 칸 하나 — 지금을 덮는 구간의 예측.
     *
     * 전 칸을 읽어 자바에서 고르지 않는다. 전국 소해구는 한 프레임이 약 12,000칸이고
     * 요약은 조회마다 돈다 — 한 행만 가져온다.
     *
     * 발효시각은 <b>지금 이하 가장 늦은 것</b>이다. OceanController.zoneFrame 과 같은 규칙 —
     * 3시간 간격에서 "이후 가장 이른"을 고르면 11시에 14시 예측을 "지금"이라고 말하게 된다.
     * 지금보다 이른 발효시각이 없으면(발표 직후) 가장 이른 것으로 물러선다.
     *
     * @return 좌표가 해구 밖(내륙·격자 밖)이거나 발표본이 없으면 empty
     */
    public Optional<ZoneCell> cellNow(ZoneLevel level, double lat, double lon, Instant now) {
        Timestamp at = Timestamp.from(now);
        return jdbc.query("SELECT " + COLUMNS + " FROM ocean_zone WHERE " + level.where
                        + " AND " + latestIssuance(level)
                        + " AND ? BETWEEN lat_min AND lat_max AND ? BETWEEN lon_min AND lon_max"
                        + " AND tma_ef = (SELECT coalesce(max(t.tma_ef) FILTER (WHERE t.tma_ef <= ?), min(t.tma_ef))"
                        + "               FROM ocean_zone t WHERE " + level.where.replace("szone", "t.szone")
                        + "               AND t.tma_fc = (SELECT max(tma_fc) FROM ocean_zone WHERE " + level.where + "))"
                        + " LIMIT 1",
                CELL, lat, lon, at).stream().findFirst();
    }

    /** 최신 발표본의 전 발효시각 min·max. 슬라이더 색 기준이라 슬라이더와 같은 범위다 */
    public ZoneRange range(ZoneLevel level) {
        return jdbc.query("""
                SELECT min(wave_height_m) w_min, max(wave_height_m) w_max,
                       min(wind_speed_ms) s_min, max(wind_speed_ms) s_max,
                       min(water_temp_c) t_min, max(water_temp_c) t_max
                FROM ocean_zone WHERE """ + " " + level.where + " AND " + latestIssuance(level),
                (ResultSet rs) -> rs.next()
                        ? new ZoneRange(nullable(rs, "w_min"), nullable(rs, "w_max"),
                                nullable(rs, "s_min"), nullable(rs, "s_max"),
                                nullable(rs, "t_min"), nullable(rs, "t_max"))
                        : ZoneRange.EMPTY);
    }

    /**
     * 좌표에서 가까운 대해구 번호. 소해구를 받을 대해구를 고른다.
     *
     * 저장된 대해구 발표본의 첫 발효시각에서 고른다 — 모든 발효시각의 해구 배치가 같다.
     * 파고·풍속이 둘 다 없는 칸은 뺀다 — 전 요소 결측인 대해구 17개가 육지다(2026-09-14 실측).
     * 경도 1° 가 위도 1° 보다 짧다(35°N 에서 0.82배) — 보정하지 않으면 동서로 치우쳐 고른다.
     *
     * @return 대해구 발표본이 없으면 빈 목록
     */
    public List<Integer> largeZonesNear(double lat, double lon, int limit) {
        return jdbc.query("""
                SELECT lzone FROM ocean_zone
                WHERE szone = 0
                  AND tma_ef = (SELECT min(tma_ef) FROM ocean_zone WHERE szone = 0)
                  AND (wave_height_m IS NOT NULL OR wind_speed_ms IS NOT NULL)
                ORDER BY power((lat_min + lat_max) / 2 - ?, 2)
                       + power(((lon_min + lon_max) / 2 - ?) * cos(radians(?)), 2)
                LIMIT ?
                """,
                (rs, n) -> rs.getInt("lzone"), lat, lon, lat, limit);
    }

    private static final RowMapper<ZoneCell> CELL = (rs, n) -> new ZoneCell(
            rs.getTimestamp("tma_fc").toInstant(),
            rs.getTimestamp("tma_ef").toInstant(),
            rs.getInt("lzone"),
            rs.getInt("szone"),
            rs.getDouble("lat_min"), rs.getDouble("lat_max"),
            rs.getDouble("lon_min"), rs.getDouble("lon_max"),
            nullable(rs, "wave_height_m"),
            nullable(rs, "wave_period_max_s"),
            nullable(rs, "wave_dir_deg"),
            nullable(rs, "wind_speed_ms"),
            nullable(rs, "wind_dir_deg"),
            nullable(rs, "visibility_m"),
            nullable(rs, "rain_mm"),
            nullable(rs, "water_temp_c"),
            nullableInt(rs, "swell_level"));

    private static void setNullable(PreparedStatement ps, int index, Double value) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.REAL);
        } else {
            ps.setDouble(index, value);
        }
    }

    /** getDouble 은 NULL 을 0.0 으로 준다 — 파고 0m 로 읽힌다 */
    private static Double nullable(ResultSet rs, String column) throws SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }

    private static Integer nullableInt(ResultSet rs, String column) throws SQLException {
        int value = rs.getInt(column);
        return rs.wasNull() ? null : value;
    }
}

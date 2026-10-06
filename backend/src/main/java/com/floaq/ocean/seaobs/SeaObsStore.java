package com.floaq.ocean.seaobs;

import com.floaq.ocean.OceanRetention;
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
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * ocean_station_obs 읽기·쓰기 — 관측 지점 24시간 이력.
 *
 * JPA 기각 — ocean_roms 와 같은 이유. 행 단위 도메인 상태가 아니라 시간 창 캐시다.
 */
@Slf4j
@Repository
@RequiredArgsConstructor
public class SeaObsStore {

    private static final String UPSERT = """
            INSERT INTO ocean_station_obs (source, stn, observed_at, network, name, lat, lon,
                wave_height_m, wind_dir_deg, wind_speed_ms, wind_gust_ms, water_temp_c,
                air_temp_c, pressure_hpa, humidity_pct,
                current_dir_deg, current_speed_ms, tide_level_m, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, stn, observed_at) DO UPDATE SET
                network = EXCLUDED.network, name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                wave_height_m = EXCLUDED.wave_height_m, wind_dir_deg = EXCLUDED.wind_dir_deg,
                wind_speed_ms = EXCLUDED.wind_speed_ms, wind_gust_ms = EXCLUDED.wind_gust_ms,
                water_temp_c = EXCLUDED.water_temp_c, air_temp_c = EXCLUDED.air_temp_c,
                pressure_hpa = EXCLUDED.pressure_hpa, humidity_pct = EXCLUDED.humidity_pct,
                current_dir_deg = EXCLUDED.current_dir_deg, current_speed_ms = EXCLUDED.current_speed_ms,
                tide_level_m = EXCLUDED.tide_level_m,
                fetched_at = EXCLUDED.fetched_at
            """;

    private static final String COLUMNS = """
            network, stn, name, lat, lon, observed_at,
            wave_height_m, wind_dir_deg, wind_speed_ms, wind_gust_ms,
            water_temp_c, air_temp_c, pressure_hpa, humidity_pct,
            current_dir_deg, current_speed_ms, tide_level_m
            """;

    private static final RowMapper<SeaObsStation> STATION = (rs, n) -> new SeaObsStation(
            rs.getString("network"), rs.getString("stn"), rs.getString("name"),
            rs.getDouble("lat"), rs.getDouble("lon"),
            rs.getTimestamp("observed_at").toInstant(),
            nullable(rs, "wave_height_m"), nullable(rs, "wind_dir_deg"),
            nullable(rs, "wind_speed_ms"), nullable(rs, "wind_gust_ms"),
            nullable(rs, "water_temp_c"), nullable(rs, "air_temp_c"),
            nullable(rs, "pressure_hpa"), nullable(rs, "humidity_pct"),
            nullable(rs, "current_dir_deg"), nullable(rs, "current_speed_ms"),
            nullable(rs, "tide_level_m"));

    private final JdbcTemplate jdbc;

    /**
     * 관측을 이력에 넣고 24시간 지난 행을 지운다.
     *
     * 같은 지점·시각이 다시 오면 덮는다 — 기상청이 품질검사 후 값을 고쳐 다시 줄 수 있다.
     * 같은 응답 안의 중복(지점·시각)은 먼저 온 것만 — 배치 안에서 같은 키가 두 번이면 ON CONFLICT 가 거부한다.
     */
    @Transactional
    public int record(String source, List<SeaObsStation> stations, Instant fetchedAt) {
        Map<String, SeaObsStation> unique = new LinkedHashMap<>();
        Instant cutoff = OceanRetention.cutoff(fetchedAt);
        for (SeaObsStation s : stations) {
            if (s.observedAt().isBefore(cutoff)) {
                continue;
            }
            unique.putIfAbsent(s.stn() + "|" + s.observedAt(), s);
        }
        int expired = jdbc.update("DELETE FROM ocean_station_obs WHERE source = ? AND observed_at < ?",
                source, Timestamp.from(cutoff));
        if (expired > 0) {
            log.debug("[ocean] {} — 보관 기간 지난 관측 {}건 삭제", source, expired);
        }
        if (unique.isEmpty()) {
            return 0;
        }
        List<SeaObsStation> rows = List.copyOf(unique.values());
        Timestamp fetched = Timestamp.from(fetchedAt);
        jdbc.batchUpdate(UPSERT, rows, rows.size(), (ps, s) -> {
            ps.setString(1, source);
            ps.setString(2, s.stn());
            ps.setTimestamp(3, Timestamp.from(s.observedAt()));
            ps.setString(4, s.network());
            ps.setString(5, s.name());
            ps.setDouble(6, s.lat());
            ps.setDouble(7, s.lon());
            setNullable(ps, 8, s.waveHeightM());
            setNullable(ps, 9, s.windDirDeg());
            setNullable(ps, 10, s.windSpeedMs());
            setNullable(ps, 11, s.windGustMs());
            setNullable(ps, 12, s.waterTempC());
            setNullable(ps, 13, s.airTempC());
            setNullable(ps, 14, s.pressureHpa());
            setNullable(ps, 15, s.humidityPct());
            setNullable(ps, 16, s.currentDirDeg());
            setNullable(ps, 17, s.currentSpeedMs());
            setNullable(ps, 18, s.tideLevelM());
            ps.setTimestamp(19, fetched);
        });
        return rows.size();
    }

    /**
     * 지점마다 시각 at 이전(포함) 가장 최근 관측. window 보다 오래된 관측은 "그 시각 값"이 아니라 뺀다.
     *
     * 거리로 거르지 않는다 — 전국 약 200지점이라 거리는 호출부가 Java 로 잰다(SeaObsHistory).
     */
    public List<SeaObsStation> latestAt(String source, Instant at, Duration window) {
        return jdbc.query("SELECT DISTINCT ON (stn) " + COLUMNS + """
                FROM ocean_station_obs
                WHERE source = ? AND observed_at <= ? AND observed_at > ?
                ORDER BY stn, observed_at DESC
                """,
                STATION, source, Timestamp.from(at), Timestamp.from(at.minus(window)));
    }

    /**
     * 지점마다 시각 at **이후 가장 이른** 값. 예보 소스(조류·조석)가 쓴다.
     *
     * 관측(latestAt)과 규칙이 반대다 — 예보는 지난 시각 값을 "지금"으로 보여주면 안 된다(ROMS /current 와 같은 규칙).
     *
     * @param horizon 이만큼 뒤까지만 본다. 넘어가면 그 지점은 값이 없다 — 예보가 끊긴 것이다
     */
    public List<SeaObsStation> forecastFrom(String source, Instant at, Duration horizon) {
        return jdbc.query("SELECT DISTINCT ON (stn) " + COLUMNS + """
                FROM ocean_station_obs
                WHERE source = ? AND observed_at >= ? AND observed_at < ?
                ORDER BY stn, observed_at
                """,
                STATION, source, Timestamp.from(at), Timestamp.from(at.plus(horizon)));
    }

    /**
     * 지점 **한 곳**의 예보 시계열, 시각 오름차순. 조석 곡선을 그린다.
     *
     * forecastFrom 과 나눈 이유: 저쪽은 "지금 값"(지점마다 한 줄)이고 이쪽은 한 지점의 흐름이다.
     * 전 지점의 전 시각을 내리면 조석예보만 166지점 × 24시각이 한 응답에 실린다.
     */
    public List<SeaObsStation> forecastSeries(String source, String stn, Instant from, Duration horizon) {
        return jdbc.query("SELECT " + COLUMNS + """
                FROM ocean_station_obs
                WHERE source = ? AND stn = ? AND observed_at >= ? AND observed_at < ?
                ORDER BY observed_at
                """,
                STATION, source, stn, Timestamp.from(from), Timestamp.from(from.plus(horizon)));
    }

    private static void setNullable(PreparedStatement ps, int index, Double value) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.REAL);
        } else {
            ps.setDouble(index, value);
        }
    }

    /** getDouble 은 NULL 을 0.0 으로 준다 — 풍속 0m/s 로 읽힌다 */
    private static Double nullable(ResultSet rs, String column) throws SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }
}

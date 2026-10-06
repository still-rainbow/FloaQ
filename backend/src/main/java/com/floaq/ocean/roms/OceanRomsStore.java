package com.floaq.ocean.roms;

import com.floaq.ocean.GeoDistance;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * ocean_roms 읽기·쓰기.
 *
 * JPA 기각 — 수천 행이 통째로 들고 남. 영속성 컨텍스트 적재 + 복합키 merge 의 행별 SELECT 가 순손해.
 * 도메인 상태가 아닌 예측본 캐시라 JPA 가 주는 것이 없음.
 */
@Slf4j
@Repository
@RequiredArgsConstructor
public class OceanRomsStore {

    /**
     * ROMS 격자 간격 (2026-09-13 부산 앞 실측).
     *
     * 위도 0.02864° = 3.19km · 경도 0.03197° = 2.91km(35°N). 대각 이웃은 4.31km.
     * 두 칸은 5.8km 부터라 5.0km 가 "한 칸 이내"를 가른다.
     *
     * 최근접 선택의 오차 상한은 반대각선 2.16km 다 — 격자가 모델 것이라 범위를 넓혀도 촘촘해지지 않는다.
     */
    public static final double NEIGHBOR_RADIUS_KM = 5.0;

    /** 지도에 그릴 이웃 겹 수. 1 이면 본선 칸 + 사방 한 칸 = 3x3 */
    private static final int NEIGHBOR_RINGS = 1;

    /**
     * 격자 간격으로 인정하는 최소 차이(도). 1e-4° = 11m —
     * 같은 모델 격자점이 응답마다 부동소수 끝자리만 다를 때 그 차이를 간격으로 읽지 않게.
     */
    private static final double MIN_STEP_DEG = 1e-4;

    /** 같은 격자·시각이면 새 예측본 값으로 덮는다 — 더 최근 모델 실행이 그 시각의 더 나은 추정이다 */
    private static final String UPSERT = """
            INSERT INTO ocean_roms (predc_dt, lat, lon, crdir_deg, crsp_ms, wtem_c, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (predc_dt, lat, lon) DO UPDATE
            SET crdir_deg = EXCLUDED.crdir_deg, crsp_ms = EXCLUDED.crsp_ms,
                wtem_c = EXCLUDED.wtem_c, fetched_at = EXCLUDED.fetched_at
            """;

    private final JdbcTemplate jdbc;

    /**
     * 타일 하나의 새 예측본 반영 — **그 타일의 미래는 교체, 과거는 24시간 보관.**
     *
     *   지금 이후   이 타일 범위만 지우고 새 예측본으로. 남의 타일 미래 칸은 건드리지 않는다
     *   지금 이전   남긴다. 같은 격자·시각이면 새 값으로 덮는다(UPSERT) — 사고 시각 재계산 입력
     *   24시간 전   지운다 (타일 무관)
     *
     * 타일이 갖지 않는 점(반열린 구간 밖, API bbox 가 양끝 포함이라 이웃 경계 점이 섞여 온다)은 저장하지 않는다.
     * 한 트랜잭션. 중단 시 옛 예측본 유지 — 비는 것보다 나음(§9.10).
     *
     * @param input 빈 목록이면 무동작. NODATA 로 기존 예측본을 지우면 표류 추정 입력이 사라짐
     * @return 저장한 행 수. 0 이면 이 타일에 바다 격자가 없다
     */
    @Transactional
    public int replaceTile(RomsTile tile, List<RomsGrid> input, Instant fetchedAt) {
        Instant cutoff = com.floaq.ocean.OceanRetention.cutoff(fetchedAt);
        // 예측본이 당일 00시(KST)부터 온다 — 보관 기간보다 이른 시각은 넣었다가 바로 지울 행이라 거른다
        List<RomsGrid> rows = dedupe(input).stream()
                .filter(g -> !g.predcDt().isBefore(cutoff))
                .filter(g -> tile.owns(g.lat(), g.lon()))
                .toList();
        if (rows.isEmpty()) {
            log.warn("[ocean] roms {} — 격자 0건. 기존 예측본 유지", tile);
            return 0;
        }
        jdbc.update("""
                DELETE FROM ocean_roms
                WHERE predc_dt >= ? AND lat >= ? AND lat < ? AND lon >= ? AND lon < ?
                """, Timestamp.from(fetchedAt), tile.south(), tile.north(), tile.west(), tile.east());
        int expired = jdbc.update("DELETE FROM ocean_roms WHERE predc_dt < ?", Timestamp.from(cutoff));
        if (expired > 0) {
            log.debug("[ocean] roms — 보관 기간 지난 격자 {}건 삭제", expired);
        }
        Timestamp fetched = Timestamp.from(fetchedAt);
        jdbc.batchUpdate(UPSERT, rows, rows.size(), (ps, g) -> {
            ps.setTimestamp(1, Timestamp.from(g.predcDt()));
            ps.setDouble(2, g.lat());
            ps.setDouble(3, g.lon());
            setNullable(ps, 4, g.crdirDeg());
            setNullable(ps, 5, g.crspMs());
            setNullable(ps, 6, g.wtemC());
            ps.setTimestamp(7, fetched);
        });
        return rows.size();
    }

    /**
     * 표류 추정 입력. at 이후 가장 이른 예측 시각에서 최근접 격자 + 그 값의 불확실성.
     *
     * 과거 예측은 반환 안 함. 보간하지 않는 이유는 RomsSample 주석에 있다 — 연안 경계에서 평균은 양쪽 다 틀린 값을 만든다.
     * ⚠ 경도 1도가 위도 1도보다 짧다 (35°N 에서 0.82배). 보정 없으면 동서로 치우쳐 선택.
     */
    public Optional<RomsSample> sample(double lat, double lon, Instant at) {
        return nearest(lat, lon, at).map(grid -> {
            List<Double> speeds = neighborSpeeds(grid);
            Double spread = speeds.size() < 2 ? null
                    : Collections.max(speeds) - Collections.min(speeds);
            return new RomsSample(grid,
                    GeoDistance.round1(GeoDistance.km(lat, lon, grid.lat(), grid.lon())),
                    spread == null ? null : Math.round(spread * 1000) / 1000.0,
                    speeds.size());
        });
    }

    /**
     * 같은 예측 시각에서 한 칸 이내 격자의 유속(자기 자신 포함).
     *
     * 거리 계산을 SQL 에 두면 인덱스를 못 타지만, 한 시각의 격자가 타일 수 × 수십 개라 스캔이 싸다.
     */
    private List<Double> neighborSpeeds(RomsGrid center) {
        return jdbc.query("""
                SELECT crsp_ms
                FROM ocean_roms
                WHERE predc_dt = ?
                  AND crsp_ms IS NOT NULL
                  AND 2 * 6371 * asin(sqrt(
                        power(sin(radians(lat - ?) / 2), 2)
                        + cos(radians(?)) * cos(radians(lat))
                          * power(sin(radians(lon - ?) / 2), 2))) <= ?
                """,
                (rs, n) -> rs.getDouble("crsp_ms"),
                Timestamp.from(center.predcDt()), center.lat(), center.lat(), center.lon(),
                NEIGHBOR_RADIUS_KM);
    }

    public Optional<RomsGrid> nearest(double lat, double lon, Instant at) {
        return jdbc.query("""
                SELECT predc_dt, lat, lon, crdir_deg, crsp_ms, wtem_c
                FROM ocean_roms
                WHERE predc_dt = (SELECT min(predc_dt) FROM ocean_roms WHERE predc_dt >= ?)
                ORDER BY power(lat - ?, 2) + power((lon - ?) * cos(radians(?)), 2)
                LIMIT 1
                """,
                (rs, n) -> new RomsGrid(
                        rs.getTimestamp("predc_dt").toInstant(),
                        rs.getDouble("lat"),
                        rs.getDouble("lon"),
                        nullableDouble(rs, "crdir_deg"),
                        nullableDouble(rs, "crsp_ms"),
                        nullableDouble(rs, "wtem_c")),
                Timestamp.from(at), lat, lon, lat).stream().findFirst();
    }

    /**
     * 확인용 1페이지와 같은 범위의 저장 행. 키 맞추기는 {@link #matches} 가 한다.
     *
     * 키 300개를 IN 으로 넘기지 않고 시각·좌표 범위로 넉넉히 받는다 — 최악이 타일 전 시각인데 1만 행 이내
     */
    public List<RomsGrid> storedLike(List<RomsGrid> probe) {
        if (probe.isEmpty()) {
            return List.of();
        }
        Instant from = probe.stream().map(RomsGrid::predcDt).min(Instant::compareTo).orElseThrow();
        Instant to = probe.stream().map(RomsGrid::predcDt).max(Instant::compareTo).orElseThrow();
        double latMin = probe.stream().mapToDouble(RomsGrid::lat).min().orElseThrow();
        double latMax = probe.stream().mapToDouble(RomsGrid::lat).max().orElseThrow();
        double lonMin = probe.stream().mapToDouble(RomsGrid::lon).min().orElseThrow();
        double lonMax = probe.stream().mapToDouble(RomsGrid::lon).max().orElseThrow();
        return jdbc.query("""
                SELECT predc_dt, lat, lon, crdir_deg, crsp_ms, wtem_c
                FROM ocean_roms
                WHERE predc_dt BETWEEN ? AND ?
                  AND lat BETWEEN ? AND ?
                  AND lon BETWEEN ? AND ?
                """,
                (rs, n) -> new RomsGrid(
                        rs.getTimestamp("predc_dt").toInstant(),
                        rs.getDouble("lat"),
                        rs.getDouble("lon"),
                        nullableDouble(rs, "crdir_deg"),
                        nullableDouble(rs, "crsp_ms"),
                        nullableDouble(rs, "wtem_c")),
                Timestamp.from(from), Timestamp.from(to), latMin, latMax, lonMin, lonMax);
    }

    /**
     * 확인용 행이 저장된 예측본과 같은가 — 같으면 새 예측본이 아니다.
     *
     * 값은 float 로 맞춰 비교한다. 컬럼이 real 이라 0.44 가 0.4399999976 으로 돌아온다 —
     * double 로 비교하면 매번 "바뀜"이 되어 매시 전량을 받는다.
     * 보관 기간 전 행은 저장하지 않으므로(replaceTile) 비교에서 뺀다.
     *
     * @return 비교할 행이 없거나, 저장에 없는 키·다른 값이 하나라도 있으면 false — 모르면 받는 쪽
     */
    static boolean matches(List<RomsGrid> probe, List<RomsGrid> stored, Instant cutoff) {
        Map<GridKey, RomsGrid> byKey = new HashMap<>();
        stored.forEach(g -> byKey.put(new GridKey(g.predcDt(), g.lat(), g.lon()), g));
        int compared = 0;
        for (RomsGrid g : probe) {
            if (g.predcDt().isBefore(cutoff)) {
                continue;
            }
            RomsGrid s = byKey.get(new GridKey(g.predcDt(), g.lat(), g.lon()));
            if (s == null || !sameValue(g.crdirDeg(), s.crdirDeg())
                    || !sameValue(g.crspMs(), s.crspMs()) || !sameValue(g.wtemC(), s.wtemC())) {
                return false;
            }
            compared++;
        }
        return compared > 0;
    }

    /** null 은 null 과만 같다 — 결측이 값으로 바뀐 것도 새 예측본이다 */
    private static boolean sameValue(Double a, Double b) {
        if (a == null || b == null) {
            return a == b;
        }
        return Float.compare(a.floatValue(), b.floatValue()) == 0;
    }

    /**
     * (predc_dt, lat, lon) 중복 제거. 먼저 온 행이 남는다.
     *
     * 페이지를 넘기는 사이 서버 데이터가 바뀌면 경계 행이 두 페이지에 겹쳐 온다.
     * 그대로 넣으면 PK 위반 한 건이 배치 전체를 롤백시켜 예측본이 통째로 안 갱신된다.
     */
    static List<RomsGrid> dedupe(List<RomsGrid> rows) {
        Map<GridKey, RomsGrid> unique = new LinkedHashMap<>();
        for (RomsGrid g : rows) {
            unique.putIfAbsent(new GridKey(g.predcDt(), g.lat(), g.lon()), g);
        }
        int dropped = rows.size() - unique.size();
        if (dropped > 0) {
            log.warn("[ocean] roms — 중복 격자 {}건 제거", dropped);
        }
        return new ArrayList<>(unique.values());
    }

    private record GridKey(Instant predcDt, double lat, double lon) {
    }

    /**
     * 한 격자점의 시각별 예측. 화면의 시계열 차트가 쓴다.
     *
     * 격자를 좌표로 직접 비교한다 — float 동등 비교지만 같은 응답에서 온 값이라 정확히 일치한다.
     * 8일치를 다 주지 않는다. 화면이 읽을 수 있는 창만 준다.
     */
    public List<RomsGrid> series(double lat, double lon, Instant from, int hours) {
        return jdbc.query(
                """
                SELECT predc_dt, lat, lon, crdir_deg, crsp_ms, wtem_c
                FROM ocean_roms
                WHERE lat = ? AND lon = ?
                  AND predc_dt >= ? AND predc_dt < ?
                ORDER BY predc_dt
                """,
                (rs, n) -> new RomsGrid(
                        rs.getTimestamp("predc_dt").toInstant(),
                        rs.getDouble("lat"),
                        rs.getDouble("lon"),
                        nullableDouble(rs, "crdir_deg"),
                        nullableDouble(rs, "crsp_ms"),
                        nullableDouble(rs, "wtem_c")),
                lat, lon, Timestamp.from(from), Timestamp.from(from.plusSeconds(hours * 3600L)));
    }

    /**
     * 가장 최근에 받은 묶음의 첫 예측 시각 — 모델 기준 시각 근사.
     *
     * API 가 발표 시각을 주지 않는다. 예측본이 당일 00시(KST)부터 오고, 보관 컷오프(24시간 전)는 그보다 이르므로
     * 저장된 묶음의 최소 예측 시각이 곧 예측본 시작이다.
     */
    public Optional<Instant> latestBaseAt() {
        Timestamp t = jdbc.queryForObject("""
                SELECT min(predc_dt) FROM ocean_roms
                WHERE fetched_at = (SELECT max(fetched_at) FROM ocean_roms)
                """, Timestamp.class);
        return Optional.ofNullable(t).map(Timestamp::toInstant);
    }

    public List<RomsGrid> neighborhood(double lat, double lon, Instant at, RomsLattice lattice) {
        return neighborhood(lat, lon, at, lattice, NEIGHBOR_RINGS);
    }

    /**
     * @param rings 이웃 겹 수. 1 이면 3x3(지도 칸), 크게 주면 등치선을 그릴 만큼 넓어진다.
     *              등치선은 점이 적으면 선이 각지고, 58점(0.3° 실측)이면 모양이 나온다
     */
    public List<RomsGrid> neighborhood(double lat, double lon, Instant at, RomsLattice lattice, int rings) {
        if (lattice == null) {
            return List.of();
        }
        double latPad = lattice.latStep() * (rings + 0.5);
        double lonPad = lattice.lonStep() * (rings + 0.5);
        return jdbc.query(
                """
                SELECT predc_dt, lat, lon, crdir_deg, crsp_ms, wtem_c
                FROM ocean_roms
                WHERE predc_dt = (SELECT min(predc_dt) FROM ocean_roms WHERE predc_dt >= ?)
                  AND lat BETWEEN ? AND ?
                  AND lon BETWEEN ? AND ?
                ORDER BY lat, lon
                """,
                (rs, n) -> new RomsGrid(
                        rs.getTimestamp("predc_dt").toInstant(),
                        rs.getDouble("lat"),
                        rs.getDouble("lon"),
                        nullableDouble(rs, "crdir_deg"),
                        nullableDouble(rs, "crsp_ms"),
                        nullableDouble(rs, "wtem_c")),
                Timestamp.from(at), lat - latPad, lat + latPad, lon - lonPad, lon + lonPad);
    }

    /**
     * 지금 이후 받을 수 있는 예측 시각. 화면 시간 슬라이더의 눈금.
     *
     * 예측본이 당일 00시부터 오므로 from 이전은 뺀다 — 지난 예측을 슬라이더에 올리면 과거를 "예측"으로 읽는다.
     */
    public List<Instant> forecastTimes(Instant from) {
        return jdbc.query("""
                SELECT DISTINCT predc_dt
                FROM ocean_roms
                WHERE predc_dt >= (SELECT min(predc_dt) FROM ocean_roms WHERE predc_dt >= ?)
                ORDER BY predc_dt
                """,
                (rs, n) -> rs.getTimestamp("predc_dt").toInstant(),
                Timestamp.from(from));
    }

    /**
     * {@link #neighborhood} 와 같은 칸들의 지금 이후 전 시각 min·max.
     *
     * 테이블 전체가 아니라 같은 창으로 자른다 — 다른 타일의 내만·외해 값이 섞이면
     * 본선 주변은 램프 한쪽 끝에 몰려 색 차이가 안 보인다.
     */
    public RomsRange range(double lat, double lon, Instant from, RomsLattice lattice, int rings) {
        if (lattice == null) {
            return RomsRange.EMPTY;
        }
        double latPad = lattice.latStep() * (rings + 0.5);
        double lonPad = lattice.lonStep() * (rings + 0.5);
        return jdbc.query(
                """
                SELECT min(crsp_ms) s_min, max(crsp_ms) s_max, min(wtem_c) t_min, max(wtem_c) t_max
                FROM ocean_roms
                WHERE predc_dt >= (SELECT min(predc_dt) FROM ocean_roms WHERE predc_dt >= ?)
                  AND lat BETWEEN ? AND ?
                  AND lon BETWEEN ? AND ?
                """,
                (ResultSet rs) -> rs.next()
                        ? new RomsRange(nullableDouble(rs, "s_min"), nullableDouble(rs, "s_max"),
                                nullableDouble(rs, "t_min"), nullableDouble(rs, "t_max"))
                        : RomsRange.EMPTY,
                Timestamp.from(from), lat - latPad, lat + latPad, lon - lonPad, lon + lonPad);
    }

    /**
     * 저장된 격자에서 원점·간격을 읽는다.
     *
     * 간격은 **이웃한 서로 다른 좌표값의 최소 차이**다. (최대−최소)/(개수−1) 기각 —
     * 타일이 여러 곳에 흩어져 있으면 사이 빈 구간 때문에 간격이 틀어진다(단일 해역일 때도 과거 보관분 해역이 섞여 같은 문제가 있었다).
     * 육지 결측은 차이를 키울 뿐 줄이지 않아 최소 차이가 곧 격자 간격이다.
     *
     * ⚠ ROMS 격자가 등간격이라는 전제 — 부산 앞 실측이 등간격이었다(2026-09-13).
     *
     * @return 데이터가 없거나 한 축에 값이 하나뿐이면 null — 호출부가 기본 간격을 쓴다
     */
    public RomsLattice lattice() {
        return jdbc.query(
                """
                WITH frame AS (SELECT min(predc_dt) AS t FROM ocean_roms WHERE predc_dt >= ?),
                     lats AS (SELECT DISTINCT lat FROM ocean_roms WHERE predc_dt = (SELECT t FROM frame)),
                     lons AS (SELECT DISTINCT lon FROM ocean_roms WHERE predc_dt = (SELECT t FROM frame))
                SELECT (SELECT min(lat) FROM lats) AS lat_min,
                       (SELECT min(lon) FROM lons) AS lon_min,
                       (SELECT min(d) FROM (SELECT lat - lag(lat) OVER (ORDER BY lat) AS d FROM lats) x
                        WHERE d > ?) AS lat_step,
                       (SELECT min(d) FROM (SELECT lon - lag(lon) OVER (ORDER BY lon) AS d FROM lons) y
                        WHERE d > ?) AS lon_step
                """,
                (ResultSet rs) -> {
                    if (!rs.next()) {
                        return null;
                    }
                    Double latStep = nullableDouble(rs, "lat_step");
                    Double lonStep = nullableDouble(rs, "lon_step");
                    if (latStep == null || lonStep == null) {
                        return null;
                    }
                    return new RomsLattice(rs.getDouble("lat_min"), rs.getDouble("lon_min"), latStep, lonStep);
                },
                // 🔴 지금 이후 첫 예측 시각의 격자로만 잰다 — 과거 보관분에는 지운 타일의 격자가 섞인다
                Timestamp.from(Instant.now()), MIN_STEP_DEG, MIN_STEP_DEG);
    }

    private static void setNullable(PreparedStatement ps, int index, Double value) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.REAL);
        } else {
            ps.setDouble(index, value);
        }
    }

    /** getDouble 은 NULL 을 0.0 으로 반환. 유향 0.0 은 '북'이라 값처럼 보임 */
    private static Double nullableDouble(ResultSet rs, String column) throws SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }
}

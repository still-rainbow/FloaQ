package com.floaq.ocean.roms;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.Duration;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * ocean_roms_tile · ocean_roms_generation 읽기·쓰기.
 *
 * 시각 비교는 전부 DB now() — 인스턴스 시계가 어긋나도 한 시계로 판정한다.
 */
@Repository
@RequiredArgsConstructor
public class RomsTileStore {

    /**
     * 활성 타일 — 이 안에 조회된 타일만 새 예측본 때 다시 받는다.
     * 24시간 근거: 예측본이 하루 1회 갱신(2026-09-15 사용자 확인). 하루 동안 아무도 안 본 바다는 받지 않는다.
     */
    public static final Duration ACTIVE_WINDOW = Duration.ofHours(24);

    private static final RowMapper<RomsTile> TILE =
            (rs, n) -> new RomsTile(rs.getInt("tile_row"), rs.getInt("tile_col"));

    private final JdbcTemplate jdbc;

    /** 관심 표시. 늦은 시각이 이긴다 — 느린 요청이 방금 찍힌 시각을 되돌리지 않게 */
    public void touch(List<RomsTile> tiles) {
        jdbc.batchUpdate("""
                INSERT INTO ocean_roms_tile (tile_row, tile_col, requested_at) VALUES (?, ?, now())
                ON CONFLICT (tile_row, tile_col)
                DO UPDATE SET requested_at = GREATEST(ocean_roms_tile.requested_at, EXCLUDED.requested_at)
                """, tiles, tiles.size(), (ps, t) -> {
            ps.setInt(1, t.row());
            ps.setInt(2, t.col());
        });
    }

    /** 이 중 한 번이라도 받은 타일 (수집 성공 · 바다 없음 포함) */
    public Set<RomsTile> collectedAmong(List<RomsTile> tiles) {
        if (tiles.isEmpty()) {
            return Set.of();
        }
        String in = tiles.stream().map(t -> "(?, ?)").collect(Collectors.joining(", "));
        Object[] args = tiles.stream().flatMap(t -> Stream.of(t.row(), t.col())).toArray();
        return new HashSet<>(jdbc.query("SELECT tile_row, tile_col FROM ocean_roms_tile"
                + " WHERE collected_at IS NOT NULL AND (tile_row, tile_col) IN (" + in + ")", TILE, args));
    }

    public long generation() {
        Long g = jdbc.queryForObject("SELECT generation FROM ocean_roms_generation WHERE id = 1", Long.class);
        return g == null ? 0 : g;
    }

    /**
     * 새 예측본 감지 → 세대 +1. 본 세대에서만 올린다 —
     * 인스턴스 둘이 같은 새 예측본을 보고 두 번 올리면 방금 받은 타일까지 옛 세대가 되어 한 번 더 받는다.
     *
     * @return 올렸으면 true
     */
    public boolean advanceGeneration(long seen) {
        return jdbc.update("""
                UPDATE ocean_roms_generation SET generation = generation + 1, detected_at = now()
                WHERE id = 1 AND generation = ?
                """, seen) == 1;
    }

    /**
     * 수집 리스를 잡는다. 받을 필요가 없거나(최신) 누가 받는 중이거나 방금 실패했으면 못 잡는다 — 호출 0.
     *
     * @param retryAfter  마지막 시도 뒤 이만큼은 다시 잡지 않는다. 실패 타일을 매 조회가 다시 부르며 쿼터를 태우지 않게
     * @param fullRefresh 세대 비교가 새 예측본을 놓쳐도 이만큼 지나면 다시 받는다
     */
    public boolean claim(RomsTile tile, long generation, String owner,
                         Duration lease, Duration retryAfter, Duration fullRefresh) {
        return jdbc.update("""
                UPDATE ocean_roms_tile
                SET lease_owner = ?, lease_until = now() + ?::float8 * interval '1 second', attempted_at = now()
                WHERE tile_row = ? AND tile_col = ?
                  AND (lease_until IS NULL OR lease_until < now())
                  AND (attempted_at IS NULL OR attempted_at <= now() - ?::float8 * interval '1 second')
                  AND (collected_at IS NULL OR generation < ?
                       OR collected_at <= now() - ?::float8 * interval '1 second')
                """, owner, lease.toSeconds(), tile.row(), tile.col(),
                retryAfter.toSeconds(), generation, fullRefresh.toSeconds()) == 1;
    }

    /**
     * 받았다. 바다가 없는 타일(NO_DATA)도 받은 것으로 친다 — 매 조회가 같은 육지 타일을 다시 부르지 않게.
     *
     * @param code 00 성공 · 03 바다 없음. 확인 타일은 00 에서만 고른다
     */
    public void succeed(RomsTile tile, String owner, long generation, String code) {
        jdbc.update("""
                UPDATE ocean_roms_tile
                SET collected_at = now(), generation = ?, result_code = ?, result_msg = NULL,
                    lease_owner = NULL, lease_until = NULL
                WHERE tile_row = ? AND tile_col = ? AND lease_owner = ?
                """, generation, code, tile.row(), tile.col(), owner);
    }

    /** 실패. 이전 수집 값·시각은 그대로 — 옛 예측본이 비는 것보다 낫다(§9.10) */
    public void fail(RomsTile tile, String owner, String code, String message) {
        String msg = message == null || message.length() <= 200 ? message : message.substring(0, 200);
        String c = code == null || code.length() <= 16 ? code : code.substring(0, 16);
        jdbc.update("""
                UPDATE ocean_roms_tile
                SET result_code = ?, result_msg = ?, lease_owner = NULL, lease_until = NULL
                WHERE tile_row = ? AND tile_col = ? AND lease_owner = ?
                """, c, msg, tile.row(), tile.col(), owner);
    }

    /** 다시 받을 활성 타일 — 한 번도 못 받았거나 옛 세대거나 오래됐다. 최근 조회 순 */
    public List<RomsTile> dueForRefresh(long generation, Duration active, Duration fullRefresh) {
        return jdbc.query("""
                SELECT tile_row, tile_col FROM ocean_roms_tile
                WHERE requested_at > now() - ?::float8 * interval '1 second'
                  AND (collected_at IS NULL OR generation < ?
                       OR collected_at <= now() - ?::float8 * interval '1 second')
                ORDER BY requested_at DESC
                """, TILE, active.toSeconds(), generation, fullRefresh.toSeconds());
    }

    /**
     * 새 예측본 확인에 쓸 타일 — 지금 세대로 받은 활성 타일 중 **가장 오래전에** 받은 것.
     *
     * 방금 받은 타일은 이미 새 예측본을 들고 있을 수 있어 비교해도 "같다"가 나온다.
     * 옛 세대 타일은 고르지 않는다 — 이미 옛것인 줄 아는 타일로 비교하면 매시 세대를 올린다.
     * 바다 없는 타일(03)도 뺀다 — 비교할 행이 없으면 늘 "다르다"가 된다.
     */
    public Optional<RomsTile> probeCandidate(long generation, Duration active) {
        return jdbc.query("""
                SELECT tile_row, tile_col FROM ocean_roms_tile
                WHERE requested_at > now() - ?::float8 * interval '1 second'
                  AND generation = ? AND result_code = '00' AND collected_at IS NOT NULL
                ORDER BY collected_at
                LIMIT 1
                """, TILE, active.toSeconds(), generation).stream().findFirst();
    }

    /** 활성 타일 — 소해구가 받을 해역을 고른다 */
    public List<RomsTile> active(Duration active) {
        return jdbc.query("""
                SELECT tile_row, tile_col FROM ocean_roms_tile
                WHERE requested_at > now() - ?::float8 * interval '1 second'
                ORDER BY tile_row, tile_col
                """, TILE, active.toSeconds());
    }

    /** 활성 타일 수 · 그중 받은 수 — 수집 결과 payload */
    public record Stats(int active, int collected) {
    }

    public Stats stats(Duration active) {
        return jdbc.queryForObject("""
                SELECT count(*) AS active, count(collected_at) AS collected FROM ocean_roms_tile
                WHERE requested_at > now() - ?::float8 * interval '1 second'
                """, (rs, n) -> new Stats(rs.getInt("active"), rs.getInt("collected")), active.toSeconds());
    }
}

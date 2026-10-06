package com.floaq.pi;

import com.floaq.global.Uuid7;
import com.floaq.global.error.ErrorCode;
import com.floaq.pi.dto.PiCommLoss;
import com.floaq.pi.dto.PiDriftEstimate;
import com.floaq.pi.dto.PiLaunch;
import com.floaq.pi.dto.PiReport;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.function.Predicate;

import static com.floaq.pi.PiBind.name;
import static com.floaq.pi.PiBind.setBool;
import static com.floaq.pi.PiBind.setDouble;
import static com.floaq.pi.PiBind.setEpoch;
import static com.floaq.pi.PiBind.setFloat;
import static com.floaq.pi.PiBind.setInt;
import static com.floaq.pi.PiBind.setText;

/**
 * Pi 사고 부속 이벤트 수신 — 투하 · 두절 · 표류 추정 · 신고 (docs/api.md §4).
 *
 * <p>{@link PiTelemetryService}(초당 한 행, append-only)와 갈라 둔 이유 —
 * 여기는 넷 다 <b>같은 것이 갱신되며 다시 온다</b>. 투하는 결과가 늦게 붙고, 두절은 복귀 시각이
 * 나중에 채워지고, 신고는 발신 횟수가 누적된다. 그래서 전부 <b>자연키 upsert</b> 다.</p>
 *
 * <p><b>Pi 의 PK 는 받지 않는다</b>(api.md §4.2). {@code launch_id}·{@code comm_loss_id}·
 * {@code estimate_id}·{@code report_id} 는 Pi 안의 INTEGER 라 서버에서 뜻이 없다.
 * 서버가 uuid v7 을 채번하고 <b>중복은 자연키가 막는다</b>.</p>
 *
 * <p><b>배치 하나 = 트랜잭션 하나.</b> 원소 하나가 거절되면 전부 반영하지 않는다(§4.1).</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiEventService {

    private final JdbcTemplate jdbc;
    private final PiIngestSupport support;

    // ── 투하 ─────────────────────────────────────────────────

    /**
     * 사고당 1행이다 — {@code launch} 의 PK 가 곧 {@code accident_id} 다(재투하 없음, E5).
     * 그래서 자연키 upsert 가 PK upsert 와 같아진다.
     *
     * <p>⚠ {@code launch} 에는 {@code updated_at} 이 없다(V1). SET 에 넣으면 기동이 막힌다.</p>
     */
    private static final String UPSERT_LAUNCH = """
            INSERT INTO launch (accident_id, detection_id, result, fail_reason,
                                launch_lat, launch_lon, target_lat, target_lon,
                                horizontal_angle, vertical_angle, confidence_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id) DO UPDATE
               SET detection_id     = EXCLUDED.detection_id,
                   result           = EXCLUDED.result,
                   fail_reason      = EXCLUDED.fail_reason,
                   target_lat       = EXCLUDED.target_lat,
                   target_lon       = EXCLUDED.target_lon,
                   confidence_score = EXCLUDED.confidence_score
            """;

    @Transactional
    public PiResult acceptLaunches(List<PiLaunch> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        List<UUID> ids = data.stream().map(PiLaunch::accidentId).toList();
        support.requireKnownAccidents(ids, callerShipId);
        // launch_lat/lon · 각도는 NOT NULL 이다. DB 가 잡으면 500 이고 어느 행인지 못 알려 준다
        requireEach(data, l -> l.launchLat() != null && l.launchLon() != null
                        && l.horizontalAngle() != null && l.verticalAngle() != null,
                PiLaunch::accidentId, ErrorCode.INVALID_INPUT);

        Set<UUID> existing = support.selectIds(
                "SELECT accident_id FROM launch WHERE accident_id = ANY (?)", ids);

        jdbc.batchUpdate(UPSERT_LAUNCH, data, data.size(), (ps, l) -> {
            ps.setObject(1, l.accidentId());
            setText(ps, 2, l.detectionId());
            setText(ps, 3, name(l.result()));
            setText(ps, 4, name(l.failReason()));
            setDouble(ps, 5, l.launchLat());
            setDouble(ps, 6, l.launchLon());
            setDouble(ps, 7, l.targetLat());
            setDouble(ps, 8, l.targetLon());
            setFloat(ps, 9, l.horizontalAngle());
            setFloat(ps, 10, l.verticalAngle());
            setFloat(ps, 11, l.confidenceScore());
            setEpoch(ps, 12, l.createdAt());
        });

        // ON CONFLICT DO UPDATE 는 갱신도 1을 돌려줘 삽입과 구분이 안 된다 — 미리 읽어 둔 것으로 가른다
        int duplicated = (int) data.stream().filter(l -> existing.contains(l.accidentId())).count();
        return new PiResult(data.size(), data.size() - duplicated, duplicated, 0);
    }

    // ── 두절 ─────────────────────────────────────────────────

    /**
     * 같은 구간이 두 번 온다 — 두절 시작({@code recovered_at} null)과 복귀(채워짐).
     *
     * <p>{@code COALESCE} 가 <b>"1회만 채운다"</b>를 만든다: 복귀 시각은 한 번 박히면 안 바뀐다.
     * 두 번째 복귀 보고가 오더라도 <b>첫 복귀가 사실</b>이기 때문이다.
     * {@code last_received_at} 은 갱신한다 — 두절 중에도 값이 더 정확해질 수 있다.</p>
     */
    private static final String UPSERT_COMM_LOSS = """
            INSERT INTO comm_loss (comm_loss_id, accident_id, detected_at, last_lat, last_lon,
                                   last_received_at, threshold_sec, recovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, detected_at) DO UPDATE
               SET recovered_at     = COALESCE(comm_loss.recovered_at, EXCLUDED.recovered_at),
                   last_received_at = EXCLUDED.last_received_at,
                   updated_at       = now()
            """;

    @Transactional
    public PiResult acceptCommLosses(List<PiCommLoss> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        List<UUID> ids = data.stream().map(PiCommLoss::accidentId).toList();
        support.requireKnownAccidents(ids, callerShipId);
        requireEach(data, c -> c.detectedAt() != null && c.lastLat() != null && c.lastLon() != null
                        && c.lastReceivedAt() != null
                        && c.thresholdSec() != null && c.thresholdSec() > 0,
                PiCommLoss::accidentId, ErrorCode.INVALID_INPUT);

        Set<String> existing = loadKeys(
                "SELECT accident_id, EXTRACT(EPOCH FROM detected_at)::bigint FROM comm_loss"
                        + " WHERE accident_id = ANY (?)", ids);

        jdbc.batchUpdate(UPSERT_COMM_LOSS, data, data.size(), (ps, c) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, c.accidentId());
            setEpoch(ps, 3, c.detectedAt());
            setDouble(ps, 4, c.lastLat());
            setDouble(ps, 5, c.lastLon());
            setEpoch(ps, 6, c.lastReceivedAt());
            setInt(ps, 7, c.thresholdSec());
            setEpoch(ps, 8, c.recoveredAt());
        });

        int duplicated = (int) data.stream()
                .filter(c -> existing.contains(key(c.accidentId(), c.detectedAt()))).count();
        return new PiResult(data.size(), data.size() - duplicated, duplicated, 0);
    }

    // ── 표류 추정 ────────────────────────────────────────────

    /** 이력은 그대로 쌓는다. 같은 {@code (accident_id, created_at)} 이면 재전송이다 */
    private static final String INSERT_DRIFT = """
            INSERT INTO drift_estimate (estimate_id, accident_id, base_lat, base_lon,
                                        last_received_at, elapsed_sec, center_lat, center_lon, radius_m,
                                        input_current_speed, input_current_dir,
                                        input_wind_speed, input_wind_dir, input_observed_at,
                                        is_current, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, created_at) DO NOTHING
            """;

    /**
     * 🔴 <b>먼저 옛 행을 내린다.</b> {@code uq_drift_estimate_current}(부분 UNIQUE)가 있어
     * 안 내리고 넣으면 배치 전체가 롤백된다.
     */
    private static final String DEMOTE_CURRENT = """
            UPDATE drift_estimate SET is_current = false, updated_at = now()
             WHERE accident_id = ? AND is_current
            """;

    @Transactional
    public PiResult acceptDriftEstimates(List<PiDriftEstimate> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        List<UUID> ids = data.stream().map(PiDriftEstimate::accidentId).toList();
        support.requireKnownAccidents(ids, callerShipId);
        requireEach(data, d -> d.baseLat() != null && d.baseLon() != null
                        && d.centerLat() != null && d.centerLon() != null
                        && d.radiusM() != null && d.radiusM() > 0
                        && d.lastReceivedAt() != null && d.elapsedSec() != null
                        && d.createdAt() != null,
                PiDriftEstimate::accidentId, ErrorCode.INVALID_INPUT);

        Set<String> existing = loadKeys(
                "SELECT accident_id, EXTRACT(EPOCH FROM created_at)::bigint FROM drift_estimate"
                        + " WHERE accident_id = ANY (?)", ids);

        // 한 배치에 같은 사고의 현재 추정이 여럿 올 수 있다(두절 복귀 때 밀린 것이 한꺼번에 온다).
        // 그중 **가장 나중 것만** 현재로 둔다 — 부분 UNIQUE 는 사고당 1건만 허용한다
        Set<PiDriftEstimate> current = latestCurrentPerAccident(data);
        for (UUID accidentId : new HashSet<>(ids)) {
            jdbc.update(DEMOTE_CURRENT, accidentId);
        }

        int[][] affected = jdbc.batchUpdate(INSERT_DRIFT, data, data.size(), (ps, d) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, d.accidentId());
            setDouble(ps, 3, d.baseLat());
            setDouble(ps, 4, d.baseLon());
            setEpoch(ps, 5, d.lastReceivedAt());
            setInt(ps, 6, d.elapsedSec());
            setDouble(ps, 7, d.centerLat());
            setDouble(ps, 8, d.centerLon());
            setFloat(ps, 9, d.radiusM());
            setFloat(ps, 10, d.inputCurrentSpeed());
            setFloat(ps, 11, d.inputCurrentDir());
            setFloat(ps, 12, d.inputWindSpeed());
            setFloat(ps, 13, d.inputWindDir());
            setEpoch(ps, 14, d.inputObservedAt());
            setBool(ps, 15, current.contains(d), false);
            setEpoch(ps, 16, d.createdAt());
        });

        int inserted = PiIngestSupport.countAffected(affected);
        int duplicated = (int) data.stream()
                .filter(d -> existing.contains(key(d.accidentId(), d.createdAt()))).count();
        // ⚠ 재전송된 행은 is_current 가 갱신되지 않는다(DO NOTHING). 그 사고의 현재 추정이
        //   방금 전부 내려갔으므로, 재전송만 온 배치는 현재 추정이 잠깐 비어 보일 수 있다.
        //   Pi 가 새 추정을 5초마다 보내므로 다음 배치에서 복구된다 — 지금 없는 문제는 안 푼다(계획.md)
        return new PiResult(data.size(), inserted, duplicated, 0);
    }

    /** 사고별로 {@code isCurrent} 인 것 중 {@code createdAt} 이 가장 큰 하나만 남긴다 */
    private Set<PiDriftEstimate> latestCurrentPerAccident(List<PiDriftEstimate> data) {
        Map<UUID, PiDriftEstimate> best = new LinkedHashMap<>();
        for (PiDriftEstimate d : data) {
            if (!Boolean.TRUE.equals(d.isCurrent())) {
                continue;
            }
            best.merge(d.accidentId(), d,
                    (a, b) -> Comparator.comparingLong(PiDriftEstimate::createdAt).compare(a, b) >= 0 ? a : b);
        }
        return new HashSet<>(best.values());
    }

    // ── 신고 ─────────────────────────────────────────────────

    /**
     * 사고당 <b>채널 1행</b>. 같은 채널이 두 행이면 "몇 번 보냈나"가 둘로 쪼개진다.
     *
     * <p>{@code ON CONFLICT} 대상이 부분 UNIQUE 인덱스라 {@code WHERE} 절을 그대로 적어야
     * Postgres 가 그 인덱스를 고른다(V9 {@code uq_report_accident_channel}).</p>
     *
     * <p>⚠ {@code report} 에는 {@code updated_at} 이 없다(V1). {@code created_at} 은 PK 의 일부라
     * 갱신하지 않는다 — 첫 행 생성 시각이 그대로 남는다.</p>
     */
    private static final String UPSERT_REPORT = """
            INSERT INTO report (report_id, accident_id, channel, trigger_kind, status, sent_count,
                                report_lat, report_lon, first_sent_at, last_sent_at,
                                acked_at, acked_by, fail_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, channel) WHERE channel IS NOT NULL DO UPDATE
               SET trigger_kind  = EXCLUDED.trigger_kind,
                   status        = EXCLUDED.status,
                   sent_count    = EXCLUDED.sent_count,
                   report_lat    = EXCLUDED.report_lat,
                   report_lon    = EXCLUDED.report_lon,
                   first_sent_at = COALESCE(report.first_sent_at, EXCLUDED.first_sent_at),
                   last_sent_at  = EXCLUDED.last_sent_at,
                   acked_at      = COALESCE(report.acked_at, EXCLUDED.acked_at),
                   acked_by      = COALESCE(report.acked_by, EXCLUDED.acked_by),
                   fail_reason   = EXCLUDED.fail_reason
            """;

    @Transactional
    public PiResult acceptReports(List<PiReport> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        List<UUID> ids = data.stream().map(PiReport::accidentId).toList();
        support.requireKnownAccidents(ids, callerShipId);
        // channel 이 없으면 부분 UNIQUE 밖이라 멱등이 통째로 깨진다 — 같은 신고가 무한히 쌓인다.
        // report_lat/lon · created_at 은 NOT NULL 이다
        requireEach(data, r -> r.channel() != null && r.status() != null
                        && r.reportLat() != null && r.reportLon() != null && r.createdAt() != null,
                PiReport::accidentId, ErrorCode.INVALID_INPUT);

        // sent_count 는 누적이다. 줄어들면 늦게 도착한 옛 행이라 반영하지 않는다(§4.3)
        Map<String, Integer> sentCounts = loadSentCounts(ids);
        List<PiReport> fresh = new ArrayList<>();
        int stale = 0;
        int duplicated = 0;
        for (PiReport r : data) {
            Integer known = sentCounts.get(key(r.accidentId(), r.channel().name()));
            int incoming = r.sentCount() == null ? 0 : r.sentCount();
            if (known == null) {
                fresh.add(r);
            } else if (incoming < known) {
                stale++;
            } else {
                fresh.add(r);
                duplicated++;
            }
        }

        jdbc.batchUpdate(UPSERT_REPORT, fresh, fresh.size(), (ps, r) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, r.accidentId());
            setText(ps, 3, name(r.channel()));
            setText(ps, 4, name(r.triggerKind()));
            setText(ps, 5, name(r.status()));
            setInt(ps, 6, r.sentCount());
            setDouble(ps, 7, r.reportLat());
            setDouble(ps, 8, r.reportLon());
            setEpoch(ps, 9, r.firstSentAt());
            setEpoch(ps, 10, r.lastSentAt());
            setEpoch(ps, 11, r.ackedAt());
            setText(ps, 12, r.ackedBy());
            setText(ps, 13, name(r.failReason()));
            // 🔴 created_at 에 first_sent_at 을 쓰지 않는다 — 아직 못 쏜 채널은 그 값이 NULL 이고
            //    PK 가 (report_id, created_at) 이라 행 자체가 못 들어간다(V9 ④)
            setEpoch(ps, 14, r.createdAt());
        });

        return new PiResult(data.size(), fresh.size() - duplicated, duplicated, stale);
    }

    private Map<String, Integer> loadSentCounts(List<UUID> accidentIds) {
        UUID[] param = new HashSet<>(accidentIds).stream()
                .filter(java.util.Objects::nonNull).toArray(UUID[]::new);
        Map<String, Integer> out = new HashMap<>();
        if (param.length == 0) {
            return out;
        }
        jdbc.query("SELECT accident_id, channel, COALESCE(sent_count, 0) FROM report"
                                + " WHERE accident_id = ANY (?) AND channel IS NOT NULL",
                        (rs, rowNum) -> Map.entry(
                                key(rs.getObject(1, UUID.class), rs.getString(2)), rs.getInt(3)),
                        (Object) param)
                .forEach(e -> out.put(e.getKey(), e.getValue()));
        return out;
    }

    // ── 공통 ─────────────────────────────────────────────────

    /**
     * {@code (uuid, 시각)} 복합 자연키를 미리 읽어 둔다.
     *
     * <p>{@code ON CONFLICT DO UPDATE} 는 삽입과 갱신이 똑같이 1을 돌려줘
     * {@code inserted}/{@code duplicated} 를 가를 수 없다. 그래서 먼저 읽는다.</p>
     *
     * <p>시각은 <b>epoch 초로 맞춰 비교</b>한다 — Pi 가 초 단위로 보내고 서버가 timestamptz 로
     * 들고 있어, 객체로 비교하면 타임존·정밀도에서 어긋난다.</p>
     */
    private Set<String> loadKeys(String sql, List<UUID> accidentIds) {
        UUID[] param = new HashSet<>(accidentIds).stream()
                .filter(java.util.Objects::nonNull).toArray(UUID[]::new);
        if (param.length == 0) {
            return Set.of();
        }
        return new HashSet<>(jdbc.query(sql,
                (rs, rowNum) -> key(rs.getObject(1, UUID.class), rs.getLong(2)),
                (Object) param));
    }

    private static String key(UUID id, Object part) {
        return id + "|" + part;
    }

    /**
     * 배치 전체를 되돌리기 전에 <b>어느 원소가 문제인지</b> 실어 준다(§4.1 {@code failed}).
     * DB 제약에 맡기면 500 이 되고 Pi 는 같은 배치를 영원히 다시 보낸다.
     */
    private <T> void requireEach(List<T> data, Predicate<T> ok,
                                 Function<T, Object> label, ErrorCode code) {
        List<PiFailure> failures = new ArrayList<>();
        for (int i = 0; i < data.size(); i++) {
            T row = data.get(i);
            if (row == null || !ok.test(row)) {
                failures.add(new PiFailure(i,
                        row == null ? "null" : String.valueOf(label.apply(row)), code.getCode()));
            }
        }
        if (!failures.isEmpty()) {
            throw new PiBatchException(code, failures);
        }
    }
}

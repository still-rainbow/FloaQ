package com.floaq.pi;

import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.StateReason;
import com.floaq.ocean.OceanAt;
import com.floaq.pi.dto.PiAccident;
import com.floaq.pi.dto.PiAccidentState;
import com.floaq.global.Uuid7;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static com.floaq.pi.PiBind.name;
import static com.floaq.pi.PiBind.setDouble;
import static com.floaq.pi.PiBind.setEpoch;
import static com.floaq.pi.PiBind.setInt;
import static com.floaq.pi.PiBind.setText;

/**
 * Pi(Pi) 수신 — docs/api.md §4.
 *
 * <p><b>왜 JPA 가 아니라 JDBC 인가.</b> 계획.md §2 가 적어 둔 그대로다 —
 * <i>"고빈도 삽입은 JPA 로 건당 저장하지 않는다. JDBC 배치로 내린다."</i>
 * 그리고 멱등의 실제 장치가 {@code ON CONFLICT (자연키) DO NOTHING} 인데
 * Spring Data JPA 의 {@code save()} 로는 그 구문을 쓸 수 없다.
 * 조회(관제 웹)는 그대로 JPA 다 — <b>쓰기만 JDBC</b>.</p>
 *
 * <p><b>배치 하나 = 트랜잭션 하나.</b> 원소 하나가 거절되면 전부 반영하지 않는다(§4.1) —
 * 일부만 들어가면 Pi 가 어디까지 성공했는지 알 수 없다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiIngestService {

    private final JdbcTemplate jdbc;

    private final OceanAt oceanAt;
    /** 선행 조건 검사는 {@link PiTelemetryService}·{@link PiEventService} 와 공유한다(2026-09-18 추출) */
    private final PiIngestSupport support;

    // ── 사고 upsert ──────────────────────────────────────────

    private static final String INSERT_ACCIDENT = """
            INSERT INTO accident (accident_id, ship_id, accident_type, trigger_source, report_type,
                                  report_dsc, status, accident_lat, accident_lon, report_due_at,
                                  wait_sec, rescued_at, closed_at, model_version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            """;

    /**
     * 갱신 가능한 필드만 건드린다 (docs/api.md §4.3).
     *
     * <p>{@code COALESCE} 가 <b>"1회만 채운다"</b>를 SQL 한 줄로 만든다 —
     * {@code rescued_at}·{@code closed_at} 은 계획.md §9.20 의 중복 종결 가드이고,
     * 좌표는 "null 이었을 때만" 채운다. 나머지 컬럼은 불변이라 아예 SET 에 없다.</p>
     */
    private static final String UPDATE_ACCIDENT = """
            UPDATE accident
               SET status        = ?,
                   report_due_at = ?,
                   rescued_at    = COALESCE(rescued_at, ?),
                   closed_at     = COALESCE(closed_at, ?),
                   accident_lat  = COALESCE(accident_lat, ?),
                   accident_lon  = COALESCE(accident_lon, ?),
                   updated_at    = now()
             WHERE accident_id = ?
            """;

    @Transactional
    public PiResult acceptAccidents(List<PiAccident> data, UUID callerShipId) {
        requireWellFormed(data);
        requireCallerOwnsShips(data, callerShipId);

        Map<UUID, AccidentStatus> existing = loadStatuses(
                data.stream().map(PiAccident::accidentId).toList());

        List<PiAccident> toInsert = new ArrayList<>();
        List<PiAccident> toUpdate = new ArrayList<>();
        int duplicated = 0;
        int stale = 0;

        for (PiAccident a : data) {
            AccidentStatus current = existing.get(a.accidentId());
            if (current == null) {
                toInsert.add(a);
            } else if (a.status().rank() > current.rank()) {
                toUpdate.add(a);
            } else if (a.status().rank() < current.rank()) {
                // 옛 행이다. 상태뿐 아니라 다른 필드도 반영하지 않는다 (§4.2)
                stale++;
            } else {
                // 같은 순위 — 상태는 그대로 두고 채울 수 있는 필드만 채운다
                toUpdate.add(a);
                duplicated++;
            }
        }

        try {
            insertAccidents(toInsert);
            updateAccidents(toUpdate);
        } catch (DuplicateKeyException e) {
            // uq_accident_active — 선박당 진행 중 1건. 앞 사고의 종결이 아직 안 올라온 것이다.
            // Pi 가 updated_at 순서로 보내면 생기지 않는다. 재시도로 풀린다 (§4.2)
            log.warn("진행 중 사고 중복 — 앞 사고의 종결이 아직 안 올라왔을 수 있다", e);
            throw new BusinessException(ErrorCode.ACCIDENT_ALREADY_ACTIVE);
        }

        // 새로 생긴 사고에만 그때의 바다를 박는다. 이미 있던 사고는 이미 박혀 있다
        stampOcean(toInsert);

        int inserted = toInsert.size() + toUpdate.size() - duplicated;
        return new PiResult(data.size(), inserted, duplicated, stale);
    }

    private static final String STAMP_OCEAN = """
            UPDATE accident
               SET ocean_current_speed_ms = ?, ocean_current_dir_deg = ?,
                   ocean_wind_speed_ms    = ?, ocean_wind_dir_deg    = ?,
                   ocean_spread_ms        = ?, ocean_observed_at     = ?
             WHERE accident_id = ? AND ocean_observed_at IS NULL
            """;

    /**
     * 사고가 나던 때의 바다를 사고 행에 박는다 (V20260921_1210).
     *
     * <p>관측값은 24시간만 보관한다. 지금 안 받아 두면 <b>내일이면 이 사고의 바다를 아무도 모른다</b> —
     * 왜 그만큼 떠내려갔는지, 생존 예상이 왜 그렇게 짧았는지의 근거가 통째로 사라진다.</p>
     *
     * <p>🔴 <b>실패해도 수신을 실패시키지 않는다.</b> 사고를 받아 두는 것이 이 요청의 일이고,
     * 해양 값은 곁들이다 — 격자가 없거나 관측 지점이 멀다고 사고가 반려되면 본말이 뒤집힌다.
     * 못 채운 칸은 비어 있고, 화면은 그때 "기록이 남아 있지 않다"고 말한다.</p>
     */
    private void stampOcean(List<PiAccident> rows) {
        for (PiAccident a : rows) {
            if (a.lat() == null || a.lon() == null || a.createdAt() == null) {
                continue;
            }
            try {
                Instant when = Instant.ofEpochSecond(a.createdAt());
                oceanAt.at(a.lat(), a.lon(), when).ifPresent(snap -> jdbc.update(STAMP_OCEAN,
                        snap.currentSpeedMs(), snap.currentDirDeg(),
                        snap.windSpeedMs(), snap.windDirDeg(),
                        snap.spreadMs(), Timestamp.from(snap.observedAt()),
                        a.accidentId()));
            } catch (RuntimeException e) {
                log.warn("사고 해황 기록 실패 — accident_id={} ({})", a.accidentId(), e.getMessage());
            }
        }
    }

    private void insertAccidents(List<PiAccident> rows) {
        if (rows.isEmpty()) {
            return;
        }
        jdbc.batchUpdate(INSERT_ACCIDENT, rows, rows.size(), (ps, a) -> {
            ps.setObject(1, a.accidentId());
            ps.setObject(2, a.shipId());
            setText(ps, 3, name(a.accidentType()));
            setText(ps, 4, name(a.triggerSource()));
            setText(ps, 5, name(a.reportType()));
            setInt(ps, 6, a.reportDsc());
            setText(ps, 7, name(a.status()));
            setDouble(ps, 8, a.lat());
            setDouble(ps, 9, a.lon());
            setEpoch(ps, 10, a.reportDueAt());
            setInt(ps, 11, a.waitSec());
            setEpoch(ps, 12, a.rescuedAt());
            setEpoch(ps, 13, a.closedAt());
            setText(ps, 14, a.modelVersion());
            setEpoch(ps, 15, a.createdAt());
        });
    }

    private void updateAccidents(List<PiAccident> rows) {
        if (rows.isEmpty()) {
            return;
        }
        jdbc.batchUpdate(UPDATE_ACCIDENT, rows, rows.size(), (ps, a) -> {
            setText(ps, 1, name(a.status()));
            setEpoch(ps, 2, a.reportDueAt());
            setEpoch(ps, 3, a.rescuedAt());
            setEpoch(ps, 4, a.closedAt());
            setDouble(ps, 5, a.lat());
            setDouble(ps, 6, a.lon());
            ps.setObject(7, a.accidentId());
        });
    }

    // ── 상태 이력 ────────────────────────────────────────────

    /**
     * 자연키로 멱등. <b>{@code ON CONFLICT} 대상이 PK 가 아니라는 점이 핵심이다</b> —
     * PK 는 서버가 매번 새로 채번하므로 그걸로 걸면 충돌이 영원히 안 나고 중복이 조용히 쌓인다.
     */
    private static final String INSERT_STATE = """
            INSERT INTO accident_state (accident_state_id, accident_id, status, prev_status,
                                        reason, caused_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, status, created_at) DO NOTHING
            """;

    /**
     * 첫 {@code REPORT} 시각을 사고 행에 비정규화한다 (docs/api.md §3.4).
     * {@code WHERE reported_at IS NULL} 이라 재전송돼도 첫 값이 유지된다.
     */
    private static final String SET_REPORTED_AT = """
            UPDATE accident SET reported_at = ?, updated_at = now()
             WHERE accident_id = ? AND reported_at IS NULL
            """;

    /**
     * 끝난 사고를 사고 행에도 반영한다 — {@code CLOSE}·{@code CANCEL} 줄이 오면 종료 시각과 상태를 채운다.
     *
     * <p>🔴 <b>전에는 이 줄이 없었다</b>(2026-09-21). {@code REPORT} 줄로는 {@code reported_at} 을 채우면서
     * 끝나는 줄로는 아무것도 안 했다. 그래서 상태 줄이 사고 행보다 먼저 오거나, 사고 행 전송이
     * 실패해 재시도 대기에 걸리면 <b>경위에는 "종결"이 있는데 사고는 계속 진행 중</b>이었다 —
     * 키오스크에서 종료를 눌러도 관제에는 종료 시각이 안 들어왔다.</p>
     *
     * <p>{@code closed_at IS NULL} 에만 쓴다 — 중복 종결 가드(계획.md §9.20)와 같다. 사고 행이
     * 나중에 와서 같은 값을 다시 적어도 {@code COALESCE} 가 첫 값을 지킨다.</p>
     *
     * <p>상태는 <b>앞으로만</b> 바꾼다. 이미 끝난 사고(CLOSE·CANCEL)를 다른 끝으로 덮지 않는다.</p>
     */
    private static final String SET_CLOSED = """
            UPDATE accident SET status = ?, closed_at = ?, updated_at = now()
             WHERE accident_id = ? AND closed_at IS NULL
               AND status NOT IN ('CLOSE', 'CANCEL')
            """;

    /**
     * 구조로 끝났으면 발견 시각도 채운다. 키오스크의 "구조 완료"는 발견과 종결을
     * 한 번에 한다(Pi orchestrator {@code rescue} → {@code rescued_at=now, closed_at=now}).
     */
    private static final String SET_RESCUED = """
            UPDATE accident SET rescued_at = ?, updated_at = now()
             WHERE accident_id = ? AND rescued_at IS NULL
            """;

    @Transactional
    public PiResult acceptAccidentStates(List<PiAccidentState> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        support.requireKnownAccidents(data.stream().map(PiAccidentState::accidentId).toList(), callerShipId);

        // ⚠ 이 오버로드는 int[][] 를 준다 — 청크별 배열이다. 한 겹 더 돈다
        int[][] affected = jdbc.batchUpdate(INSERT_STATE, data, data.size(), (ps, s) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, s.accidentId());
            setText(ps, 3, name(s.status()));
            setText(ps, 4, name(s.prevStatus()));
            setText(ps, 5, name(s.reason()));
            setText(ps, 6, s.causedBy());
            setEpoch(ps, 7, s.createdAt());
        });

        int inserted = 0;
        for (int[] chunk : affected) {
            for (int n : chunk) {
                // ON CONFLICT DO NOTHING 이라 0 이면 같은 자연키가 이미 있다 = 재전송
                if (n > 0) {
                    inserted++;
                }
            }
        }

        for (PiAccidentState s : data) {
            if (s.createdAt() == null) {
                continue;
            }
            Timestamp at = Timestamp.from(Instant.ofEpochSecond(s.createdAt()));
            if (s.status() == AccidentStatus.REPORT) {
                jdbc.update(SET_REPORTED_AT, at, s.accidentId());
            } else if (s.status() == AccidentStatus.CLOSE || s.status() == AccidentStatus.CANCEL) {
                jdbc.update(SET_CLOSED, s.status().name(), at, s.accidentId());
                if (s.reason() == StateReason.TABLET_RESCUE) {
                    jdbc.update(SET_RESCUED, at, s.accidentId());
                }
            }
        }

        // 이력은 append-only 라 stale 이 없다 — 늦게 온 행도 그대로 남긴다 (§4.2)
        return new PiResult(data.size(), inserted, data.size() - inserted, 0);
    }

    // ── 선행 조건 ────────────────────────────────────────────

    /**
     * DB CHECK 가 잡기 전에 걸러 낸다.
     *
     * <p><b>왜 DB 에 맡기지 않나.</b> 제약 위반은 {@code DataIntegrityViolationException} 으로 올라와
     * 500 이 되고, 그 본문에는 {@code failed} 가 없다 — Pi 는 배치의 어느 행이 문제인지 모른 채
     * 같은 것을 영원히 다시 보낸다. docs/api.md §4.3 도 이 경우를 400 으로 적고 있다.</p>
     *
     * <p>{@code WAIT} 인데 {@code report_due_at} 이 없으면 <b>카운트다운을 그릴 수 없고 Pi 가 언제
     * 쏠지도 모른다</b>. 값이 빠진 것 자체가 사고다.</p>
     */
    private void requireWellFormed(List<PiAccident> data) {
        List<PiFailure> failures = new ArrayList<>();
        for (int i = 0; i < data.size(); i++) {
            PiAccident a = data.get(i);
            boolean ok = a.accidentId() != null
                    && a.status() != null
                    && a.reportType() != null
                    && a.createdAt() != null
                    && (a.status() != AccidentStatus.WAIT || a.reportDueAt() != null)
                    && (a.status() == AccidentStatus.CLOSE || a.closedAt() == null);
            if (!ok) {
                failures.add(new PiFailure(i, String.valueOf(a.accidentId()),
                        ErrorCode.INVALID_INPUT.getCode()));
            }
        }
        if (!failures.isEmpty()) {
            throw new PiBatchException(ErrorCode.INVALID_INPUT, failures);
        }
    }

    /**
     * 페이로드의 {@code ship_id} 가 <b>키의 선박과 같은지</b> 본다 (docs/api.md §1.1 · §4.3).
     *
     * <p><b>이것이 "한 키로 아무 {@code ship_id} 나 올릴 수 있다"를 닫는 자리다.</b>
     * 키는 헤더에서 오고 {@code ship_id} 는 본문에서 온다 — 본문은 보내는 쪽이 쓰는 값이라
     * 그것만으로는 아무것도 증명하지 못한다.</p>
     */
    private void requireCallerOwnsShips(List<PiAccident> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);

        List<PiFailure> failures = new ArrayList<>();
        for (int i = 0; i < data.size(); i++) {
            UUID shipId = data.get(i).shipId();
            if (shipId == null || !shipId.equals(callerShipId)) {
                failures.add(new PiFailure(i, String.valueOf(shipId),
                        ErrorCode.PI_SHIP_UNKNOWN.getCode()));
            }
        }
        if (!failures.isEmpty()) {
            throw new PiBatchException(ErrorCode.PI_SHIP_UNKNOWN, failures);
        }
    }

    private Map<UUID, AccidentStatus> loadStatuses(List<UUID> ids) {
        UUID[] param = new HashSet<>(ids).stream().filter(java.util.Objects::nonNull).toArray(UUID[]::new);
        Map<UUID, AccidentStatus> out = new HashMap<>();
        if (param.length == 0) {
            return out;
        }
        // 람다 1인자는 ResultSetExtractor·RowCallbackHandler 양쪽에 걸려 모호하다. 2인자 RowMapper 로 고정한다
        jdbc.query("SELECT accident_id, status FROM accident WHERE accident_id = ANY (?)",
                        (rs, rowNum) -> Map.entry(rs.getObject(1, UUID.class),
                                AccidentStatus.valueOf(rs.getString(2))),
                        (Object) param)
                .forEach(e -> out.put(e.getKey(), e.getValue()));
        return out;
    }
}

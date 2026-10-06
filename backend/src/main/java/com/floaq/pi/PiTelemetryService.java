package com.floaq.pi;

import com.floaq.global.Uuid7;
import com.floaq.global.error.ErrorCode;
import com.floaq.pi.dto.PiBuoy;
import com.floaq.pi.dto.PiImu;
import com.floaq.pi.dto.PiShipPosition;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.function.Predicate;

import static com.floaq.pi.PiBind.setBool;
import static com.floaq.pi.PiBind.setDouble;
import static com.floaq.pi.PiBind.setEpoch;
import static com.floaq.pi.PiBind.setFloat;
import static com.floaq.pi.PiBind.setInt;
import static com.floaq.pi.PiBind.setText;

/**
 * Pi 고빈도 시계열 수신 — 선박 위치 · 부표 · IMU (docs/api.md §4).
 *
 * <p>셋 다 <b>하이퍼테이블</b>이고 초당 한 행씩 들어온다. {@link PiIngestService} 와 갈라 둔 이유 —
 * 사고 본체(upsert·상태 단조)와 달리 여기는 전부 <b>append-only</b> 다.
 * 늦게 온 행도 그대로 남긴다({@code stale} 이 늘 0인 이유).</p>
 *
 * <p><b>왜 JPA 가 아니라 JDBC 인가.</b> 계획.md §2 — "고빈도 삽입은 JPA 로 건당 저장하지 않는다."
 * 그리고 멱등의 실제 장치가 {@code ON CONFLICT (자연키) DO NOTHING} 인데 {@code save()} 로는 못 쓴다.</p>
 *
 * <p><b>배치 하나 = 트랜잭션 하나.</b> 원소 하나가 거절되면 전부 반영하지 않는다(§4.1).</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiTelemetryService {

    private final JdbcTemplate jdbc;
    private final PiIngestSupport support;

    // ── 선박 위치 ────────────────────────────────────────────

    /**
     * ⚠ {@code accident_id} 를 넣지 않는다(항상 NULL).
     *
     * <p>Pi 에 그 컬럼이 없다(api.md §0.1 #5). "서버가 수신 시각으로 붙인다"가 제안이지만
     * <b>아직 합의 전이다</b> — 규칙이 서기 전에 값을 넣으면 나중에 어느 행이 추정이고
     * 어느 행이 사실인지 가를 수 없다. 비워 두면 나중에 한 번에 채울 수 있다.</p>
     */
    private static final String INSERT_SHIP_POSITION = """
            INSERT INTO ship_position (ship_position_id, ship_id, accident_id,
                                       lat, lon, speed_kn, heading_deg, accuracy_m, created_at)
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ship_id, created_at) DO NOTHING
            """;

    @Transactional
    public PiResult acceptShipPositions(List<PiShipPosition> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        // 🔴 본문의 ship_id 가 **키의 선박과 같은지** 본다. 본문은 보내는 쪽이 쓰는 값이라
        //    그것만으로는 아무것도 증명하지 못한다 (api.md §1.1)
        requireEach(data, p -> p.shipId() != null && p.shipId().equals(callerShipId),
                PiShipPosition::shipId, ErrorCode.PI_SHIP_UNKNOWN);
        requireEach(data, p -> p.lat() != null && p.lon() != null && p.createdAt() != null,
                PiShipPosition::shipId, ErrorCode.INVALID_INPUT);

        int[][] affected = jdbc.batchUpdate(INSERT_SHIP_POSITION, data, data.size(), (ps, p) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, p.shipId());
            setDouble(ps, 3, p.lat());
            setDouble(ps, 4, p.lon());
            setFloat(ps, 5, p.speedKn());
            setFloat(ps, 6, p.headingDeg());
            setFloat(ps, 7, p.accuracyM());
            setEpoch(ps, 8, p.createdAt());
        });
        return appendOnlyResult(data.size(), affected);
    }

    // ── 부표 ─────────────────────────────────────────────────

    /**
     * ⚠ 좌표 컬럼명이 양쪽에서 다르다 — Pi {@code lat}/{@code lon} → 서버 {@code buoy_lat}/{@code buoy_lon}.
     * V1 이 그 이름으로 이미 배포돼 표를 못 고친다(V9 ⑤). 매핑은 여기 한 줄로 끝난다.
     */
    private static final String INSERT_BUOY = """
            INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed,
                              seq, received_at, rssi, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, created_at) DO NOTHING
            """;

    @Transactional
    public PiResult acceptBuoys(List<PiBuoy> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        support.requireKnownAccidents(data.stream().map(PiBuoy::accidentId).toList(), callerShipId);
        requireEach(data, b -> b.lat() != null && b.lon() != null && b.createdAt() != null,
                PiBuoy::accidentId, ErrorCode.INVALID_INPUT);

        int[][] affected = jdbc.batchUpdate(INSERT_BUOY, data, data.size(), (ps, b) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, b.accidentId());
            setDouble(ps, 3, b.lat());
            setDouble(ps, 4, b.lon());
            // NOT NULL DEFAULT false. ⚠ false 가 "사람이 없다"는 뜻은 아니다(E9) — 잡지 않았을 뿐이다
            setBool(ps, 5, b.isPressed(), false);
            setInt(ps, 6, b.seq());
            setEpoch(ps, 7, b.receivedAt());
            setFloat(ps, 8, b.rssi());
            setEpoch(ps, 9, b.createdAt());
        });
        return appendOnlyResult(data.size(), affected);
    }

    // ── IMU ──────────────────────────────────────────────────

    /**
     * {@code ON CONFLICT} 에 {@code imu_position} 이 들어간다 —
     * IMU 두 개를 동시에 쓰면 같은 초에 온 둘째가 {@code (accident_id, created_at)} 만으로는 거부된다.
     * 대응 제약이 {@code NULLS NOT DISTINCT} 라 {@code imu_position} 이 NULL 인 행도 멱등하다(V9 ⑥).
     */
    private static final String INSERT_IMU = """
            INSERT INTO imu (imu_id, accident_id, accel_x, accel_y, accel_z,
                             roll, pitch, yaw, imu_position, heading_deg, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, created_at, imu_position) DO NOTHING
            """;

    @Transactional
    public PiResult acceptImus(List<PiImu> data, UUID callerShipId) {
        support.requireApprovedShip(callerShipId);
        support.requireKnownAccidents(data.stream().map(PiImu::accidentId).toList(), callerShipId);
        // roll·pitch·yaw 는 NOT NULL 이다. DB 가 잡으면 500 이 되고 어느 행인지 못 알려 준다 —
        // Pi 가 같은 배치를 영원히 다시 보낸다(§4.3 이 이 경우를 400 으로 적는다)
        requireEach(data, i -> i.roll() != null && i.pitch() != null && i.yaw() != null
                        && i.createdAt() != null,
                PiImu::accidentId, ErrorCode.INVALID_INPUT);

        int[][] affected = jdbc.batchUpdate(INSERT_IMU, data, data.size(), (ps, i) -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, i.accidentId());
            setFloat(ps, 3, i.accelX());
            setFloat(ps, 4, i.accelY());
            setFloat(ps, 5, i.accelZ());
            setFloat(ps, 6, i.roll());
            setFloat(ps, 7, i.pitch());
            setFloat(ps, 8, i.yaw());
            setText(ps, 9, i.imuPosition());
            setFloat(ps, 10, i.headingDeg());
            setEpoch(ps, 11, i.createdAt());
        });
        return appendOnlyResult(data.size(), affected);
    }

    // ── 공통 ─────────────────────────────────────────────────

    /**
     * 이력은 append-only 라 {@code stale} 이 없다 — 늦게 온 행도 그대로 남긴다(§4.2).
     * 반영 0건은 같은 자연키가 이미 있다는 뜻이고 그건 <b>재전송</b>이다.
     */
    private PiResult appendOnlyResult(int received, int[][] affected) {
        int inserted = PiIngestSupport.countAffected(affected);
        return new PiResult(received, inserted, received - inserted, 0);
    }

    /**
     * 배치 전체를 되돌리기 전에 <b>어느 원소가 문제인지</b> 실어 준다.
     *
     * <p>DB 제약에 맡기면 {@code DataIntegrityViolationException} → 500 이고 본문에 {@code failed} 가 없다.
     * Pi 는 어느 행이 문제인지 모른 채 같은 배치를 영원히 다시 보낸다.</p>
     */
    private <T> void requireEach(List<T> data, Predicate<T> ok,
                                 java.util.function.Function<T, Object> label, ErrorCode code) {
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

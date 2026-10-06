package com.floaq.pi;

import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.StateReason;
import com.floaq.accident.entity.TriggerSource;
import com.floaq.pi.dto.PiAccident;
import com.floaq.pi.dto.PiAccidentState;
import com.floaq.global.error.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * <b>SQL 의미를 증명하는 테스트.</b> {@link PiIngestServiceTest} 는 목이라 여기까지 못 본다.
 *
 * <p>여기서 지키는 것은 하나다 — <b>{@code ON CONFLICT} 대상이 PK 가 아니라 자연키여야 한다</b>
 * (docs/api.md §4.2). PK 로 바꾸면 서버가 매번 새 uuid 를 채번하므로 충돌이 영원히 안 나고
 * <b>중복이 조용히 쌓인다.</b> 사람이 눈으로 보고 알아챌 방법이 없는 종류라 테스트로 고정한다.</p>
 *
 * <p>⚠ 로컬에 PostgreSQL 컨테이너가 떠 있어야 한다({@code infra/docker-compose.yml}).
 * {@code FloaqApplicationTests.contextLoads} 와 같은 전제이고, CI 는 {@code bootJar -x test} 라
 * 영향이 없다.</p>
 */
@SpringBootTest
@Transactional
class PiIngestSqlTest {

    private static final UUID SHIP = UUID.fromString("01923f6e-0000-7000-8000-00000000f001");
    private static final UUID ACC = UUID.fromString("01923f6e-0000-7000-8000-00000000fa01");

    @Autowired
    private PiIngestService ingest;

    @Autowired
    private JdbcTemplate jdbc;

    @BeforeEach
    void 시험선() {
        jdbc.update("""
                INSERT INTO ship (ship_id, name, has_buoy, is_deleted, created_at, status)
                VALUES (?, '시험선', true, false, now(), 'ACTIVE')
                ON CONFLICT (ship_id) DO NOTHING
                """, SHIP);
    }

    /**
     * {@code report_due_at} 은 {@code WAIT} 일 때만 넣는다 —
     * {@code ck_accident_due} 가 {@code status <> 'WAIT' OR report_due_at IS NOT NULL} 이다.
     */
    private PiAccident 사고(AccidentStatus status, Long closedAt) {
        Long due = status == AccidentStatus.WAIT ? 1789456700L : null;
        return new PiAccident(ACC, SHIP, AccidentType.MOB, TriggerSource.AI, ReportType.DISTRESS,
                110, status, 35.1, 129.05, due, 30, null, closedAt, "yolo11n-0.3", 1789456670L);
    }

    private PiAccidentState 이력(AccidentStatus status, long createdAt) {
        return new PiAccidentState(ACC, status, null, StateReason.AI_DETECT, "req-1", createdAt);
    }

    private int 이력행수() {
        return jdbc.queryForObject(
                "SELECT count(*) FROM accident_state WHERE accident_id = ?", Integer.class, ACC);
    }

    // ── 자연키 멱등 ──────────────────────────────────────────

    /**
     * <b>이 테스트가 깨지면 Pi 의 재전송이 중복 행을 만들고 있다는 뜻이다.</b>
     * 서버가 PK 를 채번하므로 PK 로는 절대 충돌하지 않는다 — 막는 것은 자연키뿐이다.
     */
    @Test
    void 같은_이력을_두_번_보내도_한_행이다() {
        ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP);

        assertThat(ingest.acceptAccidentStates(List.of(이력(AccidentStatus.DETECT, 1789456670L)), SHIP).inserted())
                .isEqualTo(1);
        assertThat(ingest.acceptAccidentStates(List.of(이력(AccidentStatus.DETECT, 1789456670L)), SHIP).duplicated())
                .isEqualTo(1);
        assertThat(이력행수()).isEqualTo(1);
    }

    /** 자연키는 {@code (accident_id, status, created_at)} 이라 시각이 다르면 다른 행이다. */
    @Test
    void 시각이_다르면_다른_이력이다() {
        ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP);
        ingest.acceptAccidentStates(List.of(
                이력(AccidentStatus.DETECT, 1789456670L),
                이력(AccidentStatus.DETECT, 1789456671L)), SHIP);
        assertThat(이력행수()).isEqualTo(2);
    }

    // ── 상태 단조가 DB 에서도 성립하는가 ─────────────────────

    @Test
    void 늦게_온_옛_상태는_현재_상태를_되돌리지_않는다() {
        ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP);
        ingest.acceptAccidents(List.of(사고(AccidentStatus.WAIT, null)), SHIP);

        assertThat(ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP).stale()).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT status FROM accident WHERE accident_id = ?", String.class, ACC))
                .isEqualTo("WAIT");
    }

    // ── 종결 1회 (계획.md §9.20) ─────────────────────────────

    /**
     * {@code COALESCE(closed_at, ?)} 가 <b>중복 종결 가드</b>다. 두 번째 종결 시각이 와도
     * 첫 값이 유지된다 — 언제 닫혔는지가 나중에 바뀌면 사고 경위가 흔들린다.
     */
    @Test
    void 종결_시각은_한_번만_채워진다() {
        ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP);
        ingest.acceptAccidents(List.of(사고(AccidentStatus.REPORT, null)), SHIP);
        ingest.acceptAccidents(List.of(사고(AccidentStatus.CLOSE, 1789460000L)), SHIP);

        // 같은 순위로 다시 와서 다른 종결 시각을 밀어 넣으려는 상황
        ingest.acceptAccidents(List.of(사고(AccidentStatus.CLOSE, 1789470000L)), SHIP);

        assertThat(jdbc.queryForObject(
                "SELECT extract(epoch FROM closed_at)::bigint FROM accident WHERE accident_id = ?",
                Long.class, ACC)).isEqualTo(1789460000L);
    }

    // ── 동시 사고 1건 ────────────────────────────────────────

    /**
     * {@code uq_accident_active} 부분 UNIQUE 가 실제로 걸려 있는지 본다.
     * 인덱스가 사라지면 한 선박에 진행 중 사고가 여러 건 생기고, 그때 화면은 아무 말도 하지 않는다.
     */
    @Test
    void 선박당_진행중_사고는_하나다() {
        ingest.acceptAccidents(List.of(사고(AccidentStatus.DETECT, null)), SHIP);

        UUID 다른사고 = UUID.fromString("01923f6e-0000-7000-8000-00000000fa02");
        PiAccident 둘째 = new PiAccident(다른사고, SHIP, AccidentType.FIRE, TriggerSource.MANUAL,
                ReportType.DISTRESS, 100, AccidentStatus.DETECT, null, null, null, 30, null, null, null, 1789456680L);

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(둘째), SHIP))
                .isInstanceOf(BusinessException.class);
    }

    /**
     * DB 까지 가기 전에 걸러야 한다. 제약 위반이 500 으로 새면 본문에 {@code failed} 가 없어
     * <b>Pi 가 어느 행이 문제인지 모른 채 같은 배치를 영원히 다시 보낸다.</b>
     */
    @Test
    void WAIT_인데_report_due_at_이_없으면_400_이고_failed_가_붙는다() {
        PiAccident 잘못된 = new PiAccident(ACC, SHIP, AccidentType.MOB, TriggerSource.AI,
                ReportType.DISTRESS, 110, AccidentStatus.WAIT, null, null,
                null, 30, null, null, null, 1789456670L);

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(잘못된), SHIP))
                .isInstanceOf(PiBatchException.class)
                .satisfies(e -> {
                    PiBatchException ex = (PiBatchException) e;
                    assertThat(ex.getErrorCode().getStatus().value()).isEqualTo(400);
                    assertThat(ex.getFailures()).hasSize(1);
                    assertThat(ex.getFailures().get(0).index()).isZero();
                });
    }

    // ── V9 가 실제로 적용됐는가 ──────────────────────────────

    /**
     * V9 가 만든 자연키 3개가 DB 에 있는지 직접 확인한다.
     * 마이그레이션이 안 돌았거나 누가 지우면 위 멱등 테스트들이 전부 의미를 잃는다.
     */
    @Test
    void V9_의_자연키_제약이_존재한다() {
        List<String> 제약 = jdbc.queryForList("""
                SELECT conname FROM pg_constraint
                 WHERE conname IN ('uq_buoy_accident_measured', 'uq_imu_accident_measured',
                                   'uq_state_accident_status_at', 'uq_ship_position_measured')
                """, String.class);
        assertThat(제약).containsExactlyInAnyOrder(
                "uq_buoy_accident_measured", "uq_imu_accident_measured",
                "uq_state_accident_status_at", "uq_ship_position_measured");
    }

    /**
     * {@code imu} 자연키는 {@code NULLS NOT DISTINCT} 여야 한다. 아니면 {@code imu_position} 이
     * null 인 행은 <b>UNIQUE 가 있어도 재전송이 그대로 중복된다</b> — PG 기본은 NULL 끼리 서로 다르다.
     */
    @Test
    void imu_자연키는_NULL_을_같은_값으로_본다() {
        Boolean nullsNotDistinct = jdbc.queryForObject("""
                SELECT i.indnullsnotdistinct
                  FROM pg_constraint c JOIN pg_index i ON i.indexrelid = c.conindid
                 WHERE c.conname = 'uq_imu_accident_measured'
                """, Boolean.class);
        assertThat(nullsNotDistinct).isTrue();
    }
}

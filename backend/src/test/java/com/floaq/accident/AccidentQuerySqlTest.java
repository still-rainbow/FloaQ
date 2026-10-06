package com.floaq.accident;

import com.floaq.accident.dto.AccidentSummaryView;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 사고 조회 (docs/api.md §3.4). 실 DB 로 돈다 — 정렬과 범위 규칙이 <b>전부 SQL 에 있어서</b>
 * 목으로는 아무것도 증명되지 않는다.
 *
 * <p>⚠ 로컬 PostgreSQL 이 떠 있어야 한다. {@code FloaqApplicationTests.contextLoads} 와 같은 전제.</p>
 */
@SpringBootTest
@Transactional
class AccidentQuerySqlTest {

    private static final UUID SHIP = UUID.fromString("01923f6e-0000-7000-8000-00000000c001");
    private static final Instant BASE = Instant.parse("2026-09-14T03:00:00Z");

    @Autowired
    private AccidentQueryService query;

    @Autowired
    private JdbcTemplate jdbc;

    @BeforeEach
    void 시험선() {
        선박(SHIP, "제7금양호");
    }

    private void 선박(UUID id, String name) {
        jdbc.update("""
                INSERT INTO ship (ship_id, name, has_buoy, is_deleted, created_at, status)
                VALUES (?, ?, true, false, now(), 'ACTIVE')
                ON CONFLICT (ship_id) DO NOTHING
                """, id, name);
    }

    /** 기본 선박에 사고를 만든다. <b>진행 중은 선박당 1건뿐</b>이므로 여러 건이면 {@link #사고(String, AccidentStatus, int, UUID)} 를 쓴다. */
    private UUID 사고(String suffix, AccidentStatus status, int minutesAgo) {
        return 사고(suffix, status, minutesAgo, SHIP);
    }

    /**
     * {@code uq_accident_active} 가 <b>선박당 진행 중(DETECT·WAIT·REPORT) 1건</b>을 강제한다 —
     * 여러 건을 만들려면 선박을 나눠야 한다. 제약이 실제로 살아 있다는 뜻이라 우회하지 않고 맞춘다.
     *
     * <p>{@code ck_accident_due} 도 함께 만족시킨다 — {@code WAIT} 이면 {@code report_due_at} 이 필수다.</p>
     */
    private UUID 사고(String suffix, AccidentStatus status, int minutesAgo, UUID shipId) {
        UUID id = UUID.fromString("01923f6e-0000-7000-8000-0000000c" + suffix);
        Instant at = BASE.minus(minutesAgo, ChronoUnit.MINUTES);
        java.sql.Timestamp due = status == AccidentStatus.WAIT ? ts(at.plusSeconds(30)) : null;
        jdbc.update("""
                INSERT INTO accident (accident_id, ship_id, report_type, report_dsc, status,
                                      accident_lat, accident_lon, accident_type, trigger_source,
                                      report_due_at, created_at, updated_at)
                VALUES (?, ?, 'DISTRESS', 110, ?, 35.07, 129.08, 'MOB', 'AI', ?, ?, now())
                """, id, shipId, status.name(), due, ts(at));
        return id;
    }

    /** 진행 중 사고를 하나 더 만들어야 할 때 쓰는 별도 선박. */
    private UUID 다른선박(String suffix, String name) {
        UUID id = UUID.fromString("01923f6e-0000-7000-8000-00000000c" + suffix);
        선박(id, name);
        return id;
    }

    // ── 볼 수 있는 범위 ──────────────────────────────────────

    /**
     * {@code DETECT}·{@code WAIT} 는 아직 선내에서 판단 중이고 취소될 수 있다.
     * 관제에 보이면 <b>취소된 사고가 "있었던 일"로 남는다.</b>
     */
    @Test
    void 신고_전_사고는_목록에_없다() {
        // 진행 중은 선박당 1건이라 DETECT·WAIT 를 각각 다른 선박에 둔다(uq_accident_active).
        // ⚠ 선박으로 좁혀서 본다 — 전체 조회로 단언하면 로컬 DB 에 남은 사고가 있을 때 깨진다
        UUID 가배 = 다른선박("101", "가배");
        UUID 나배 = 다른선박("102", "나배");
        사고("0001", AccidentStatus.DETECT, 10, 가배);
        사고("0002", AccidentStatus.WAIT, 9, 나배);
        사고("0003", AccidentStatus.CANCEL, 8);
        UUID 보임 = 사고("0004", AccidentStatus.REPORT, 7);

        assertThat(query.list(null, 가배, null, null, 0, 20).content()).isEmpty();
        assertThat(query.list(null, 나배, null, null, 0, 20).content()).isEmpty();
        assertThat(query.list(null, SHIP, null, null, 0, 20).content())
                .extracting(AccidentSummaryView::accidentId).containsExactly(보임);
    }

    /**
     * 범위 밖은 <b>404 다. 403 이 아니다</b> — 403 이면 "그런 사고가 있다"를 알려주는 셈이고,
     * ID 를 바꿔 가며 찔러 보면 어느 선박에 사고가 있었는지가 새어 나간다.
     */
    @Test
    void 범위_밖_사고는_403_이_아니라_404_다() {
        UUID 진행전 = 사고("0011", AccidentStatus.WAIT, 5);

        assertThatThrownBy(() -> query.detail(진행전))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getErrorCode())
                        .isEqualTo(ErrorCode.ACCIDENT_NOT_FOUND));
    }

    @Test
    void 없는_사고도_같은_404_다() {
        assertThatThrownBy(() -> query.detail(UUID.fromString("01923f6e-dead-7000-8000-00000000ffff")))
                .isInstanceOf(BusinessException.class);
    }

    // ── 정렬 ────────────────────────────────────────────────

    /**
     * <b>진행 중이 항상 위다</b>(W-02 진행 중 상단 고정). 종결된 사고가 아무리 최근이어도 아래로 간다 —
     * 관제가 먼저 봐야 하는 것은 지금 벌어지고 있는 일이다.
     */
    @Test
    void 진행중이_먼저_그다음_최신순() {
        UUID 오래된_진행중 = 사고("0021", AccidentStatus.REPORT, 100);
        UUID 최근_종결 = 사고("0022", AccidentStatus.CLOSE, 1);
        UUID 오래된_종결 = 사고("0023", AccidentStatus.CLOSE, 50);

        assertThat(query.list(null, SHIP, null, null, 0, 20).content())
                .extracting(AccidentSummaryView::accidentId)
                .containsExactly(오래된_진행중, 최근_종결, 오래된_종결);
    }

    // ── 필터 ────────────────────────────────────────────────

    @Test
    void status_로_거를_수_있다() {
        사고("0031", AccidentStatus.REPORT, 10);
        UUID 종결 = 사고("0032", AccidentStatus.CLOSE, 9);

        assertThat(query.list(List.of(AccidentStatus.CLOSE), SHIP, null, null, 0, 20).content())
                .extracting(AccidentSummaryView::accidentId).containsExactly(종결);
    }

    /** {@code status} 로 범위 밖 값을 넣어도 범위가 뚫리면 안 된다. */
    @Test
    void status_필터로_범위를_넘을_수_없다() {
        사고("0041", AccidentStatus.WAIT, 10);

        assertThat(query.list(List.of(AccidentStatus.WAIT), SHIP, null, null, 0, 20).content())
                .isEmpty();
    }

    @Test
    void 기간으로_거를_수_있다() {
        // 둘 다 REPORT 라 선박을 나눈다 (uq_accident_active)
        UUID 다배 = 다른선박("105", "다배");
        사고("0051", AccidentStatus.REPORT, 200, 다배);
        UUID 최근 = 사고("0052", AccidentStatus.REPORT, 5);
        Instant 기준 = BASE.minus(60, ChronoUnit.MINUTES);

        // 기준보다 오래된 사고는 그 선박으로 좁혀 봐도 안 나온다
        assertThat(query.list(null, 다배, 기준, null, 0, 20).content()).isEmpty();
        assertThat(query.list(null, SHIP, 기준, null, 0, 20).content())
                .extracting(AccidentSummaryView::accidentId).containsExactly(최근);
    }

    // ── 상세 ────────────────────────────────────────────────

    @Test
    void 상세는_선박_정보와_빈_목록을_준다() {
        UUID id = 사고("0061", AccidentStatus.REPORT, 3);

        var detail = query.detail(id);
        assertThat(detail.ship().name()).isEqualTo("제7금양호");
        // 목록 항목과 같은 필드가 평평하게 있어야 한다 — 화면이 목록·상세에서 같은 경로로 읽는다
        assertThat(detail.accidentId()).isEqualTo(id);
        assertThat(detail.status()).isEqualTo(AccidentStatus.REPORT);
        assertThat(detail.launch()).isNull();
        // 투하가 없으면 buoy 도 null 이다. "두절"이 아니라 "투하 자체가 없었다"는 뜻
        assertThat(detail.buoy()).isNull();
        assertThat(detail.reports()).isEmpty();
        assertThat(detail.pendingCommands()).isEmpty();
        // comm_loss 테이블이 없어 항상 null — 서버가 임시 판정하면 판정 주체가 둘이 된다
        assertThat(detail.commLoss()).isNull();
    }

    /**
     * <b>통신이 두절돼도 buoy 는 null 이 아니다</b> — 마지막 실측이 남는다.
     * {@code heldAt} 은 처음 눌린 시각이고, 이후 값이 false 로 돌아와도 유지된다.
     */
    @Test
    void 부표는_마지막_실측과_처음_잡힌_시각을_준다() {
        UUID id = 사고("0071", AccidentStatus.REPORT, 3);
        부표(id, 35.10, 129.10, false, BASE.plusSeconds(10));
        부표(id, 35.11, 129.11, true, BASE.plusSeconds(20));
        부표(id, 35.12, 129.12, false, BASE.plusSeconds(30));

        var buoy = query.detail(id).buoy();
        assertThat(buoy.lat()).isEqualTo(35.12);
        assertThat(buoy.measuredAt()).isEqualTo(BASE.plusSeconds(30));
        assertThat(buoy.heldAt()).isEqualTo(BASE.plusSeconds(20));
    }

    // ── 부표 궤적 ───────────────────────────────────────────

    @Test
    void 궤적은_측정시각_오름차순이고_after_로_이어받는다() {
        UUID id = 사고("0081", AccidentStatus.REPORT, 3);
        부표(id, 35.10, 129.10, false, BASE.plusSeconds(10));
        부표(id, 35.11, 129.11, false, BASE.plusSeconds(20));
        부표(id, 35.12, 129.12, false, BASE.plusSeconds(30));

        assertThat(query.buoyPositions(id, null, null))
                .extracting(p -> p.measuredAt().getEpochSecond())
                .containsExactly(BASE.plusSeconds(10).getEpochSecond(),
                        BASE.plusSeconds(20).getEpochSecond(),
                        BASE.plusSeconds(30).getEpochSecond());

        assertThat(query.buoyPositions(id, BASE.plusSeconds(20), null)).hasSize(1);
    }

    /** {@code limit} 은 3600 을 넘길 수 없다 — 1Hz × 사고 후 상한 1시간(계획.md §9.6). */
    @Test
    void limit_은_상한을_넘지_못한다() {
        UUID id = 사고("0091", AccidentStatus.REPORT, 3);
        부표(id, 35.10, 129.10, false, BASE.plusSeconds(10));

        assertThat(query.buoyPositions(id, null, 999_999)).hasSize(1);
        assertThat(query.buoyPositions(id, null, 0)).hasSize(1);
    }

    /**
     * PostgreSQL 드라이버는 {@code Instant} 의 SQL 타입을 추론하지 못한다 —
     * {@code PiIngestService} 가 {@code setTimestamp} 를 쓰는 이유와 같다.
     */
    private static java.sql.Timestamp ts(Instant at) {
        return java.sql.Timestamp.from(at);
    }

    private void 부표(UUID accidentId, double lat, double lon, boolean pressed, Instant at) {
        jdbc.update("""
                INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed, created_at)
                VALUES (gen_random_uuid(), ?, ?, ?, ?, ?)
                """, accidentId, lat, lon, pressed, ts(at));
    }
}

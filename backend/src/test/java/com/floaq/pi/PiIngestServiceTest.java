package com.floaq.pi;

import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.StateReason;
import com.floaq.accident.entity.TriggerSource;
import com.floaq.pi.dto.PiAccident;
import com.floaq.ocean.OceanAt;
import com.floaq.pi.dto.PiAccidentState;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ParameterizedPreparedStatementSetter;
import org.springframework.jdbc.core.RowMapper;

import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pi 수신의 <b>분류 규칙</b> 검증 (docs/api.md §4.2). DB 없이 {@code JdbcTemplate} 을 목으로 둔다.
 *
 * <p>⚠ <b>여기서 증명되지 않는 것</b>: {@code ON CONFLICT (자연키) DO NOTHING} 이 실제로 중복을
 * 막는지와 배치 롤백. 그건 SQL 의미라 목으로는 확인할 수 없다 — {@link PiIngestSqlTest} 가 맡는다.</p>
 */
class PiIngestServiceTest {

    private static final UUID SHIP = UUID.fromString("01923f6e-0000-7000-8000-000000000001");
    private static final UUID ACC = UUID.fromString("01923f6e-0000-7000-8000-0000000000a1");

    private JdbcTemplate jdbc;
    private PiIngestService ingest;

    @BeforeEach
    void setUp() {
        jdbc = mock(JdbcTemplate.class);
        // 선행 조건 검사는 PiIngestSupport 로 빠졌다(2026-09-18). 같은 목 jdbc 를 주므로
        // 아래 스텁(선박 승인·사고 존재)이 그대로 걸린다
        ingest = new PiIngestService(jdbc, mock(OceanAt.class), new PiIngestSupport(jdbc));
        // 선박·사고 존재 확인은 기본으로 통과시킨다. 개별 테스트가 필요하면 덮어쓴다
        when(jdbc.queryForList(anyString(), eq(UUID.class), any(Object[].class)))
                .thenReturn(List.of(SHIP, ACC));
        // 승인 게이트 — 기본은 승인된 선박
        when(jdbc.queryForList(anyString(), eq(String.class), any(Object[].class)))
                .thenReturn(List.of("ACTIVE"));
        when(jdbc.batchUpdate(anyString(), any(List.class), anyInt(), any(ParameterizedPreparedStatementSetter.class)))
                .thenAnswer(inv -> new int[][]{new int[((List<?>) inv.getArgument(1)).size()]});
    }

    /** 현재 DB 에 있는 사고 상태를 흉내 낸다. {@code null} 이면 "아직 없는 사고". */
    private void existing(AccidentStatus status) {
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenAnswer(inv -> {
            if (status == null) {
                return List.of();
            }
            RowMapper<?> mapper = inv.getArgument(1);
            ResultSet rs = mock(ResultSet.class);
            when(rs.getObject(1, UUID.class)).thenReturn(ACC);
            when(rs.getString(2)).thenReturn(status.name());
            return new ArrayList<>(List.of(mapper.mapRow(rs, 0)));
        });
    }

    /** {@code WAIT} 에는 {@code report_due_at} 이 있어야 한다 — 없으면 requireWellFormed 가 거른다. */
    private PiAccident accident(AccidentStatus status) {
        Long due = status == AccidentStatus.WAIT ? 1789456700L : null;
        return new PiAccident(ACC, SHIP, AccidentType.MOB, TriggerSource.AI, ReportType.DISTRESS,
                110, status, 35.1, 129.05, due, 30, null, null, "yolo11n-0.3", 1789456670L);
    }

    // ── 상태 단조 (§4.2) ─────────────────────────────────────

    @Test
    void 처음_오는_사고는_insert() {
        existing(null);
        assertThat(ingest.acceptAccidents(List.of(accident(AccidentStatus.DETECT)), SHIP))
                .isEqualTo(new PiResult(1, 1, 0, 0));
    }

    @Test
    void 순위가_올라가면_반영한다() {
        existing(AccidentStatus.DETECT);
        assertThat(ingest.acceptAccidents(List.of(accident(AccidentStatus.WAIT)), SHIP))
                .isEqualTo(new PiResult(1, 1, 0, 0));
    }

    /**
     * 같은 순위는 {@code stale} 이 아니다 — 상태는 그대로 두고 채울 수 있는 필드만 반영한다.
     * 재전송이 이 경로를 탄다.
     */
    @Test
    void 같은_순위는_duplicated_이고_갱신은_시도한다() {
        existing(AccidentStatus.DETECT);
        assertThat(ingest.acceptAccidents(List.of(accident(AccidentStatus.DETECT)), SHIP))
                .isEqualTo(new PiResult(1, 0, 1, 0));
        // 좌표·종결 시각을 채울 수 있으므로 UPDATE 자체는 나간다
        verify(jdbc).batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class));
    }

    /**
     * <b>낮은 순위가 오면 아무것도 건드리지 않는다.</b> 두절 복귀 때 순서가 뒤바뀐 옛 행이고,
     * 상태뿐 아니라 다른 필드도 반영하면 안 된다 — 이미 지나간 사실로 현재를 덮게 된다.
     */
    @Test
    void 늦게_온_옛_상태는_stale_이고_쿼리를_내지_않는다() {
        existing(AccidentStatus.WAIT);
        assertThat(ingest.acceptAccidents(List.of(accident(AccidentStatus.DETECT)), SHIP))
                .isEqualTo(new PiResult(1, 0, 0, 1));
        verify(jdbc, never()).batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class));
    }

    /** 시각을 비교하지 않는다 — Pi 와 서버의 시계 차이에 기대지 않기 위해서다(§4.2). */
    @Test
    void 판정에_시각을_쓰지_않는다() {
        existing(AccidentStatus.WAIT);
        PiAccident 아주_최근에_만들어진_옛상태 = new PiAccident(ACC, SHIP, AccidentType.MOB,
                TriggerSource.AI, ReportType.DISTRESS, 110, AccidentStatus.DETECT,
                null, null, null, 30, null, null, null, Long.MAX_VALUE / 1000);
        assertThat(ingest.acceptAccidents(List.of(아주_최근에_만들어진_옛상태), SHIP).stale()).isEqualTo(1);
    }

    /**
     * {@code WAIT} 인데 {@code report_due_at} 이 없으면 <b>카운트다운을 그릴 수 없고 Pi 가 언제
     * 쏠지도 모른다.</b> DB 의 {@code ck_accident_due} 가 잡기 전에 걸러 400 + {@code failed} 로 준다 —
     * 제약 위반이 500 으로 새면 본문에 {@code failed} 가 없어 Pi 가 같은 배치를 영원히 다시 보낸다.
     */
    @Test
    void WAIT_에_report_due_at_이_없으면_형식_오류다() {
        existing(null);
        PiAccident 잘못된 = new PiAccident(ACC, SHIP, AccidentType.MOB, TriggerSource.AI,
                ReportType.DISTRESS, 110, AccidentStatus.WAIT, null, null, null, 30, null, null, null, 1L);

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(잘못된), SHIP))
                .isInstanceOf(PiBatchException.class)
                .satisfies(e -> assertThat(((PiBatchException) e).getErrorCode())
                        .isEqualTo(ErrorCode.INVALID_INPUT));
        verify(jdbc, never()).batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class));
    }

    /** {@code CLOSE} 가 아닌데 종결 시각이 오면 모순이다 — {@code ck_accident_closed} 와 같은 규칙. */
    @Test
    void 종결_상태가_아닌데_closed_at_이_오면_형식_오류다() {
        existing(null);
        PiAccident 잘못된 = new PiAccident(ACC, SHIP, AccidentType.MOB, TriggerSource.AI,
                ReportType.DISTRESS, 110, AccidentStatus.DETECT, null, null, null, 30, null, 1789460000L, null, 1L);

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(잘못된), SHIP))
                .isInstanceOf(PiBatchException.class);
    }

    // ── 선행 조건과 failed (§4.1) ────────────────────────────

    @Test
    void 모르는_선박이면_배치_전체를_거절하고_index_를_싣는다() {
        UUID unknown = UUID.fromString("01923f6e-dead-7000-8000-000000000999");
        when(jdbc.queryForList(anyString(), eq(UUID.class), any(Object[].class)))
                .thenReturn(List.of(SHIP));

        PiAccident bad = new PiAccident(ACC, unknown, AccidentType.MOB, TriggerSource.AI,
                ReportType.DISTRESS, 110, AccidentStatus.DETECT, null, null, null, 30, null, null, null, 1L);

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(accident(AccidentStatus.DETECT), bad), SHIP))
                .isInstanceOf(PiBatchException.class)
                .satisfies(e -> {
                    PiBatchException ex = (PiBatchException) e;
                    assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.PI_SHIP_UNKNOWN);
                    // Pi 가 자기 큐의 어느 행인지 찾는 유일한 단서다
                    assertThat(ex.getFailures()).containsExactly(
                            new PiFailure(1, unknown.toString(), "PI_SHIP_UNKNOWN"));
                });
    }

    /**
     * 사고 행이 아직 안 올라온 것은 <b>순서 문제이지 영구 실패가 아니다</b>.
     * Pi 는 그 원소를 보류하고 사고를 먼저 보낸 뒤 다시 보낸다(§4.1 재시도 표).
     */
    @Test
    void 사고가_없으면_이력을_거절하고_ACCIDENT_NOT_FOUND_를_준다() {
        UUID missing = UUID.fromString("01923f6e-dead-7000-8000-0000000000ff");
        when(jdbc.queryForList(anyString(), eq(UUID.class), any(Object[].class)))
                .thenReturn(List.of(ACC));

        List<PiAccidentState> data = List.of(
                new PiAccidentState(ACC, AccidentStatus.DETECT, null, StateReason.AI_DETECT, null, 1L),
                new PiAccidentState(missing, AccidentStatus.DETECT, null, StateReason.AI_DETECT, null, 2L));

        assertThatThrownBy(() -> ingest.acceptAccidentStates(data, SHIP))
                .isInstanceOf(PiBatchException.class)
                .satisfies(e -> assertThat(((PiBatchException) e).getFailures())
                        .containsExactly(new PiFailure(1, missing.toString(), "ACCIDENT_NOT_FOUND")));
    }

    // ── 동시 사고 1건 ────────────────────────────────────────

    /**
     * {@code uq_accident_active} 위반은 <b>재시도로 풀리는 상태</b>다 — 앞 사고의 종결이 아직
     * 안 올라온 것뿐이다. 일반 500 으로 새면 Pi 가 영구 실패로 보고 큐를 멈춘다.
     */
    @Test
    void 진행중_사고_충돌은_ACCIDENT_ALREADY_ACTIVE_로_바꾼다() {
        existing(null);
        when(jdbc.batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class)))
                .thenThrow(new DuplicateKeyException("uq_accident_active"));

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(accident(AccidentStatus.DETECT)), SHIP))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getErrorCode())
                        .isEqualTo(ErrorCode.ACCIDENT_ALREADY_ACTIVE));
    }

    // ── 상태 이력 집계 ───────────────────────────────────────

    /** {@code ON CONFLICT DO NOTHING} 이 0 을 돌려주면 그건 재전송이다. 오류가 아니다. */
    @Test
    void 이력은_affected_0_을_duplicated_로_센다() {
        when(jdbc.batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class)))
                .thenReturn(new int[][]{{1, 0, 1}});

        List<PiAccidentState> data = List.of(
                new PiAccidentState(ACC, AccidentStatus.DETECT, null, StateReason.AI_DETECT, null, 1L),
                new PiAccidentState(ACC, AccidentStatus.WAIT, AccidentStatus.DETECT, StateReason.COUNTDOWN_START, null, 2L),
                new PiAccidentState(ACC, AccidentStatus.CANCEL, AccidentStatus.WAIT, StateReason.TABLET_CANCEL, null, 3L));

        // 이력은 append-only 라 stale 이 없다 — 늦게 온 행도 그대로 남긴다
        assertThat(ingest.acceptAccidentStates(data, SHIP)).isEqualTo(new PiResult(3, 2, 1, 0));
    }

    /** 첫 {@code REPORT} 만 사고 행에 비정규화한다. 다른 상태는 건드리지 않는다. */
    @Test
    void REPORT_이력이_오면_reported_at_을_채운다() {
        when(jdbc.batchUpdate(anyString(), any(List.class), anyInt(),
                any(ParameterizedPreparedStatementSetter.class)))
                .thenReturn(new int[][]{{1, 1}});

        ingest.acceptAccidentStates(List.of(
                new PiAccidentState(ACC, AccidentStatus.WAIT, AccidentStatus.DETECT, StateReason.COUNTDOWN_START, null, 1L),
                new PiAccidentState(ACC, AccidentStatus.REPORT, AccidentStatus.WAIT, StateReason.TIMEOUT, null, 2L)), SHIP);

        verify(jdbc).update(anyString(), any(java.sql.Timestamp.class), eq(ACC));
    }

    // ── 순위 정의 ────────────────────────────────────────────

    /**
     * 순위는 상태머신의 전이 방향과 같아야 한다. 어긋나면 정상 전이가 {@code stale} 로 버려진다 —
     * 화면이 조용히 옛 상태에 멈춘다.
     */
    @Test
    void 순위는_전이_방향과_일치한다() {
        Map<AccidentStatus, AccidentStatus> 전이 = Map.of(
                AccidentStatus.DETECT, AccidentStatus.WAIT,
                AccidentStatus.WAIT, AccidentStatus.REPORT,
                AccidentStatus.REPORT, AccidentStatus.CLOSE);
        전이.forEach((from, to) -> assertThat(to.rank())
                .as("%s → %s", from, to)
                .isGreaterThan(from.rank()));
        assertThat(AccidentStatus.CANCEL.rank()).isGreaterThan(AccidentStatus.WAIT.rank());
    }
}

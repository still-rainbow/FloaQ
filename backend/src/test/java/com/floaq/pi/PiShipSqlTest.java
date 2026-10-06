package com.floaq.pi;

import com.floaq.accident.entity.AccidentStatus;
import com.floaq.accident.entity.AccidentType;
import com.floaq.accident.entity.ReportType;
import com.floaq.accident.entity.TriggerSource;
import com.floaq.pi.dto.PiAccident;
import com.floaq.pi.dto.PiShipRegisterRequest;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.ship.ShipRepository;
import com.floaq.ship.entity.ShipStatus;
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
 * 선박 등록과 <b>승인 게이트</b> (docs/api.md §1.1 · §4.3).
 *
 * <p>여기서 고정하는 것 셋이다.
 * <ol>
 *   <li><b>등록이 멱등이다</b> — 응답이 유실돼 Pi 가 다시 보내도 선박이 늘지 않는다</li>
 *   <li><b>선박 키가 한 번만 나간다</b> — 서버에 해시만 남아 두 번째는 줄 수 없다(줄 수 있으면 해시로 둔 의미가 없다)</li>
 *   <li><b>승인 전에는 데이터를 받지 않는다</b> — 승인 안 된 선박의 사고가 관제에 뜨면
 *       실제 선박인지 누가 키를 들고 장난친 것인지 구분할 방법이 없다</li>
 * </ol>
 *
 * <p>⚠ 로컬 PostgreSQL 이 떠 있어야 한다({@code infra/docker-compose.yml}) — {@link PiIngestSqlTest} 와 같은 전제.</p>
 */
@SpringBootTest
@Transactional
class PiShipSqlTest {

    @Autowired
    private PiShipService service;
    @Autowired
    private PiIngestService ingest;
    @Autowired
    private ShipRepository ships;
    @Autowired
    private JdbcTemplate jdbc;

    private PiShipRegisterRequest 신청(String regNo) {
        return new PiShipRegisterRequest("시험선-" + regNo, regNo, "440123456", true,
                new java.math.BigDecimal("3.2"), new java.math.BigDecimal("1.5"));
    }

    // ── 등록 ────────────────────────────────────────────────

    @Test
    void 등록하면_ship_id_와_ship_key_가_나온다() {
        var r = service.register(신청("PI-T-001"));

        assertThat(r.created()).isTrue();
        assertThat(r.body().shipId()).isNotNull();
        assertThat(r.body().shipKey()).hasSize(64);          // 32바이트 hex
        assertThat(r.body().status()).isEqualTo(ShipStatus.WAIT);
    }

    /** <b>평문을 저장하면 덤프 한 번으로 전 선박이 뚫린다.</b> DB 에는 해시만 있어야 한다. */
    @Test
    void 평문_키는_DB_에_남지_않는다() {
        var r = service.register(신청("PI-T-002"));
        String stored = jdbc.queryForObject(
                "SELECT edge_key_hash FROM ship WHERE ship_id = ?", String.class, r.body().shipId());

        assertThat(stored).isEqualTo(PiKeys.hash(r.body().shipKey()));
        assertThat(stored).isNotEqualTo(r.body().shipKey());
    }

    /**
     * <b>응답이 유실되면 Pi 는 같은 요청을 다시 보낸다.</b> 멱등이 아니면 재시도마다 선박이 늘고
     * 그중 어느 것이 진짜인지 아무도 모른다 — 관제 목록이 중복으로 찬다.
     */
    @Test
    void 같은_등록번호로_다시_보내면_같은_선박이다() {
        var first = service.register(신청("PI-T-003"));
        var again = service.register(신청("PI-T-003"));

        assertThat(again.created()).isFalse();
        assertThat(again.body().shipId()).isEqualTo(first.body().shipId());
    }

    /** 키는 해시로만 남아 <b>서버도 평문을 만들어 낼 수 없다</b>. 재전송에 null 이 정직한 답이다. */
    @Test
    void 재전송에는_키를_주지_않는다() {
        service.register(신청("PI-T-004"));
        assertThat(service.register(신청("PI-T-004")).body().shipKey()).isNull();
    }

    /** 키로 선박을 찾는 것이 필터의 인증 그 자체다 — 이 조회가 깨지면 모든 Pi 요청이 401 이 된다. */
    @Test
    void 발급된_키로_선박을_찾을_수_있다() {
        var r = service.register(신청("PI-T-005"));
        assertThat(ships.findByPiKeyHashAndDeletedFalse(PiKeys.hash(r.body().shipKey()))
                .map(s -> s.getShipId())).contains(r.body().shipId());
    }

    // ── 상태 확인 ───────────────────────────────────────────

    /** 남의 선박 상태를 id 를 바꿔 가며 훑을 수 있으면 안 된다. 403 이 아니라 404 다 — 존재 자체를 알리지 않는다. */
    @Test
    void 남의_선박_상태는_볼_수_없다() {
        var mine = service.register(신청("PI-T-006"));
        var other = service.register(신청("PI-T-007"));

        assertThatThrownBy(() -> service.status(other.body().shipId(), mine.body().shipId()))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getErrorCode())
                        .isEqualTo(ErrorCode.PI_SHIP_UNKNOWN));
    }

    // ── 승인 게이트 ─────────────────────────────────────────

    private PiAccident 사고(UUID shipId) {
        return new PiAccident(UUID.fromString("01923f6e-0000-7000-8000-00000000fb01"), shipId,
                AccidentType.MOB, TriggerSource.AI, ReportType.DISTRESS, 110,
                AccidentStatus.DETECT, 35.1, 129.05, null, 30, null, null, "yolo11n-0.3", 1789456670L);
    }

    /**
     * <b>WAIT 인 선박의 데이터는 받지 않는다.</b> Pi 는 이 코드를 보면 큐를 쥐고 기다렸다가
     * 승인된 뒤 밀린 것부터 보낸다(§4.1) — 받아서 섞어 두는 것보다 낫다.
     */
    @Test
    void 승인_전_선박의_데이터는_거절한다() {
        var r = service.register(신청("PI-T-008"));
        UUID shipId = r.body().shipId();

        assertThatThrownBy(() -> ingest.acceptAccidents(List.of(사고(shipId)), shipId))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getErrorCode())
                        .isEqualTo(ErrorCode.PI_SHIP_NOT_APPROVED));
    }

    @Test
    void 승인되면_받는다() {
        var r = service.register(신청("PI-T-009"));
        UUID shipId = r.body().shipId();
        jdbc.update("UPDATE ship SET status = 'ACTIVE' WHERE ship_id = ?", shipId);

        assertThat(ingest.acceptAccidents(List.of(사고(shipId)), shipId).inserted()).isEqualTo(1);
    }

    /**
     * <b>키가 곧 선박 증명이다.</b> 본문의 {@code ship_id} 는 보내는 쪽이 쓰는 값이라
     * 대조하지 않으면 한 척의 키로 <b>아무 선박의 사고나 만들어 낼 수 있다</b>.
     */
    @Test
    void 남의_ship_id_로는_올릴_수_없다() {
        var mine = service.register(신청("PI-T-010"));
        var other = service.register(신청("PI-T-011"));
        jdbc.update("UPDATE ship SET status = 'ACTIVE' WHERE ship_id IN (?, ?)",
                mine.body().shipId(), other.body().shipId());

        assertThatThrownBy(() -> ingest.acceptAccidents(
                List.of(사고(other.body().shipId())), mine.body().shipId()))
                .isInstanceOf(PiBatchException.class);
    }
}

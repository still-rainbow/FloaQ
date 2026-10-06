package com.floaq.ocean.client;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.Date;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;

/**
 * 소스별 하루 호출 예산 — ocean_call_budget.
 *
 * 없으면 어떻게 되나 — 쿼터를 다 쓴 뒤에는 발급처가 거부하기 시작하고,
 * 그때부터 **하루가 끝날 때까지 모든 소스의 값이 멈춘다.** 화면은 마지막 값을 계속 보여주므로
 * 무엇이 언제 멈췄는지 알 수 없다.
 *
 * 페이지 단위로 센다. {@code Source.callsPerDay()} 는 주기만 보고 페이지를 모른다 — ROMS 는 1회가 수십 페이지다.
 *
 * DB 에 센다 (2026-09-15). 발급처 한도는 계정 단위라 인스턴스 합계가 기준이다 —
 * 메모리일 때는 인스턴스마다 따로 세어 합계가 예산의 배수였고, 재배포하면 0 부터 다시 셌다.
 * 한 문장(INSERT … ON CONFLICT … WHERE used < limit)으로 올려 인스턴스 둘이 동시에 마지막 한 칸을 가져가지 않는다.
 *
 * ⚠ 실제 잔량은 발급처만 안다. 이건 우리 쪽 안전장치이지 정산이 아니다.
 * ⚠ DB 가 안 되면 예외다 — 호출부(수집기)가 실패로 기록한다. 세지 못하는 채로 부르지 않는다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OceanCallBudget {

    /** 발급처가 자정에 리셋하므로 한국 날짜로 센다 */
    private static final ZoneId RESET_ZONE = ZoneId.of("Asia/Seoul");

    /** 지난 날 행 보관. 7일 — 쿼터 소진 경위를 며칠 뒤에 확인할 여유 */
    private static final int KEEP_DAYS = 7;

    private final JdbcTemplate jdbc;

    /** 이 인스턴스가 옛 행을 마지막으로 지운 날. 하루 한 번만 지운다 */
    private volatile LocalDate cleanedOn;

    /**
     * 한 번 부를 자리를 확보한다.
     *
     * @param limit 하루 상한. <b>0 이면 미확인</b>이라 막지 않는다 —
     *              모르는 것을 위반으로 판정하면 진짜 위반이 묻힌다
     * @return 예산이 남았으면 true. false 면 호출부가 수집을 건너뛴다
     */
    public boolean tryConsume(String source, int limit) {
        if (limit <= 0) {
            return true;
        }
        LocalDate today = LocalDate.now(RESET_ZONE);
        cleanUp(today);
        List<Integer> used = jdbc.query("""
                INSERT INTO ocean_call_budget (day, source, used) VALUES (?, ?, 1)
                ON CONFLICT (day, source) DO UPDATE SET used = ocean_call_budget.used + 1
                WHERE ocean_call_budget.used < ?
                RETURNING used
                """, (rs, n) -> rs.getInt(1), Date.valueOf(today), source, limit);
        if (used.isEmpty()) {
            return false;
        }
        // 다 쓰기 전에 한 번 알린다. 다 쓴 뒤에 알면 이미 값이 멈춘 뒤다
        if (used.getFirst() == limit * 8 / 10) {
            log.warn("[ocean] {} — 하루 예산의 80% 사용 ({}/{})", source, used.getFirst(), limit);
        }
        return true;
    }

    public int used(String source) {
        List<Integer> used = jdbc.query("SELECT used FROM ocean_call_budget WHERE day = ? AND source = ?",
                (rs, n) -> rs.getInt(1), Date.valueOf(LocalDate.now(RESET_ZONE)), source);
        return used.isEmpty() ? 0 : used.getFirst();
    }

    private void cleanUp(LocalDate today) {
        if (today.equals(cleanedOn)) {
            return;
        }
        cleanedOn = today;
        jdbc.update("DELETE FROM ocean_call_budget WHERE day < ?", Date.valueOf(today.minusDays(KEEP_DAYS)));
    }
}

package com.floaq.ocean.client;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 하루 호출 예산 — DB 한 문장으로 센다.
 *
 * 인스턴스 합계가 발급처 한도의 기준이다. 상한 판정이 SQL 조건(used < limit)에 있어
 * 두 인스턴스가 동시에 마지막 한 칸을 가져가지 못한다 — 그 경합 자체는 DB 가 보장하므로 여기서는 호출 계약만 본다.
 */
class OceanCallBudgetTest {

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final OceanCallBudget budget = new OceanCallBudget(jdbc);

    @SuppressWarnings("unchecked")
    private void afterIncrement(List<Integer> returned) {
        when(jdbc.query(anyString(), any(RowMapper.class), any(), any(), any())).thenReturn((List) returned);
    }

    @Test
    void 상한이_0_이면_미확인이라_막지도_세지도_않는다() {
        // 모르는 것을 위반으로 판정하면 진짜 위반이 묻힌다. NIFS·기상청은 상한을 모른다
        for (int i = 0; i < 100; i++) {
            assertThat(budget.tryConsume("red-tide", 0)).isTrue();
        }
        verifyNoInteractions(jdbc);
    }

    @Test
    void 올릴_자리가_있으면_true() {
        afterIncrement(List.of(1));

        assertThat(budget.tryConsume("roms", 3)).isTrue();
    }

    @Test
    void 상한에_닿아_행이_안_바뀌면_false() {
        // ON CONFLICT … WHERE used < limit 가 아무 행도 돌려주지 않았다 = 이미 다 썼다
        afterIncrement(List.of());

        assertThat(budget.tryConsume("roms", 3)).isFalse();
    }

    @SuppressWarnings("unchecked")
    @Test
    void 소스와_상한을_SQL_조건으로_넘긴다() {
        // 소스마다 따로 센다 — 한 소스가 예산을 다 써도 다른 소스는 계속 돌아야 한다
        afterIncrement(List.of(1));

        budget.tryConsume("sea-obs", 10_000);

        verify(jdbc).query(anyString(), any(RowMapper.class), any(), eq("sea-obs"), eq(10_000));
    }
}

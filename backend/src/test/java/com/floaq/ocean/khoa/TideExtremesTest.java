package com.floaq.ocean.khoa;

import com.floaq.ocean.khoa.TideExtremes.Kind;
import com.floaq.ocean.seaobs.SeaObsStation;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 만조·간조 추출.
 *
 * 틀리면 "다음 만조 17시"가 조용히 한 칸 밀린다 — 곡선은 그대로라 화면에서 눈치채기 어렵다.
 */
class TideExtremesTest {

    private static final Instant T0 = Instant.parse("2026-09-16T00:00:00Z");

    /** 1시간 간격 조위(m) 시계열 */
    private static List<SeaObsStation> series(Double... levels) {
        List<SeaObsStation> rows = new ArrayList<>();
        for (int i = 0; i < levels.length; i++) {
            rows.add(new SeaObsStation(null, "DT_0005", "부산", 35.09638, 129.03527,
                    T0.plusSeconds(3600L * i),
                    null, null, null, null, null, null, null, null,
                    null, null, levels[i]));
        }
        return rows;
    }

    @Test
    void 반일주기에서_만조와_간조를_번갈아_뽑는다() {
        // 부산 조석 모양 — 약 6시간마다 뒤집힌다
        var out = TideExtremes.of(series(0.4, 0.8, 1.3, 1.5, 1.2, 0.6, 0.2, 0.5, 1.1));

        assertThat(out).hasSize(2);
        assertThat(out.get(0).kind()).isEqualTo(Kind.HIGH);
        assertThat(out.get(0).levelM()).isEqualTo(1.5);
        assertThat(out.get(0).at()).isEqualTo(T0.plusSeconds(3 * 3600));
        assertThat(out.get(1).kind()).isEqualTo(Kind.LOW);
        assertThat(out.get(1).levelM()).isEqualTo(0.2);
    }

    @Test
    void 양_끝은_극값이_아니다() {
        // 첫 점 1.5 가 이 창의 최고, 끝 점 1.4 가 상승 중이지만 둘 다 잡지 않는다 —
        // 창이 거기서 잘린 것이지 거기가 꼭대기라는 뜻이 아니다. 48시간 조회의 양 끝이 늘 이 모양이다
        var out = TideExtremes.of(series(1.5, 1.2, 0.6, 0.2, 0.9, 1.4));

        assertThat(out).singleElement().satisfies(e -> {
            assertThat(e.kind()).isEqualTo(Kind.LOW);
            assertThat(e.levelM()).isEqualTo(0.2);
        });
    }

    @Test
    void 단조_구간에는_극값이_없다() {
        // 계속 빠지기만 하는 창. "다음 만조"가 이 창 밖이라는 뜻이다 — 아무거나 하나 집으면 시각이 틀린다
        assertThat(TideExtremes.of(series(1.5, 1.2, 0.6, 0.2))).isEmpty();
    }

    @Test
    void 평탄한_꼭대기는_한_번만_잡는다() {
        // 소수 둘째 자리에서 같은 값이 두 시각에 온다. 두 번 잡으면 "만조 두 번"이 된다
        assertThat(TideExtremes.of(series(0.4, 1.5, 1.5, 0.6))).singleElement()
                .satisfies(e -> assertThat(e.at()).isEqualTo(T0.plusSeconds(3600)));
    }

    @Test
    void 결측_옆은_판정하지_않는다() {
        // 건너뛴 값이 진짜 꼭대기일 수 있다 — 옆 점을 극값으로 세우면 시각이 틀린다
        assertThat(TideExtremes.of(series(0.4, 1.2, null, 1.4, 0.6))).isEmpty();
    }

    @Test
    void 점이_모자라면_빈_목록() {
        assertThat(TideExtremes.of(series(1.0, 1.2))).isEmpty();
        assertThat(TideExtremes.of(List.of())).isEmpty();
    }
}

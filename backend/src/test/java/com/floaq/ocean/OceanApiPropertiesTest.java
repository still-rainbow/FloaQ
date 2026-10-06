package com.floaq.ocean;

import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.OceanApiProperties.Provider;
import com.floaq.ocean.OceanApiProperties.Source;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** 쿼터 판정과 키 해석 — 설정만 보고 판단할 수 있어야 한다. */
class OceanApiPropertiesTest {

    private static Source src(Provider p, String ownKey) {
        return new Source(p, "https://example.test", ownKey, Kind.OBSERVATION, null, 0, 1800, 0, true);
    }

    /**
     * 발급 단위가 발급처마다 다르다.
     * data.go.kr 은 키 하나로 여러 API 를 쓰고, NIFS 는 API 마다 키가 따로 나온다.
     */
    @Test
    void 소스_전용_키가_발급처_공용_키보다_우선한다() {
        var props = new OceanApiProperties("0 0 * * * *", null,
                Map.of(Provider.DATA_GO_KR, "공용키"),
                Map.of("nifs", src(Provider.NIFS, "NIFS전용키"),
                        "khoa", src(Provider.DATA_GO_KR, null)));

        assertThat(props.keyFor(props.sources().get("nifs"))).isEqualTo("NIFS전용키");
        assertThat(props.keyFor(props.sources().get("khoa"))).isEqualTo("공용키");
    }

    @Test
    void 둘_다_없으면_null_이다() {
        // 호출부가 "키 없음"으로 처리해 기동 로그에 어느 소스가 막혔는지 찍는다.
        // 빈 문자열을 키로 오해해 401 을 맞는 것보다 낫다
        var props = new OceanApiProperties("0 0 * * * *", null,
                Map.of(), Map.of("x", src(Provider.NIFS, null)));

        assertThat(props.keyFor(props.sources().get("x"))).isNull();
    }

    @Test
    void 공백_키는_없는_것으로_본다() {
        var props = new OceanApiProperties("0 0 * * * *", null,
                Map.of(Provider.NIFS, "공용키"),
                Map.of("x", src(Provider.NIFS, "   ")));

        assertThat(props.keyFor(props.sources().get("x"))).isEqualTo("공용키");
    }

    @Test
    void 해상풍_3분_수집은_개발계정_쿼터를_넘는다() {
        // 명세서·상세기획 §8 이 "3분 간격"이라고 적었는데 개발계정은 하루 50회다
        // (260906_ocean-api P1). 3분이면 480회 — 운영계정 없이는 불가능하다.
        var 해상풍 = new Source(Provider.DATA_GO_KR, "https://apis.data.go.kr/...", null, Kind.OBSERVATION, null, 0, 180, 50, true);

        assertThat(해상풍.callsPerDay()).isEqualTo(480);
        assertThat(해상풍.exceedsQuota()).isTrue();
    }

    @Test
    void 주기를_30분으로_낮추면_들어온다() {
        var 해상풍 = new Source(Provider.DATA_GO_KR, "https://apis.data.go.kr/...", null, Kind.OBSERVATION, null, 0, 1800, 50, true);

        assertThat(해상풍.callsPerDay()).isEqualTo(48);
        assertThat(해상풍.exceedsQuota()).isFalse();
    }

    @Test
    void 쿼터를_모르면_판정하지_않는다() {
        // 0 은 "미확인"이다. 모르는 것을 위반으로 경고하면 진짜 경고가 묻힌다
        var 미확인 = new Source(Provider.KHOA, "https://...", null, Kind.OBSERVATION, null, 0, 60, 0, true);

        assertThat(미확인.exceedsQuota()).isFalse();
    }

    @Test
    void 기본_위치는_좌표_범위와_양수_반경이어야_유효하다() {
        assertThat(new Coverage(35.05, 129.05, 30).isValid()).isTrue();
        assertThat(new Coverage(95, 129.05, 30).isValid()).isFalse();
        assertThat(new Coverage(35.05, 181, 30).isValid()).isFalse();
        // 반경 0 이면 지점 소스가 전부 잘려 "관측 없음"으로 보인다
        assertThat(new Coverage(35.05, 129.05, 0).isValid()).isFalse();
    }
}

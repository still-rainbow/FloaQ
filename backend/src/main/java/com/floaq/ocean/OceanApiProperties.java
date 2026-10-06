package com.floaq.ocean;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.util.Map;

/**
 * 해양 공공데이터 소스 설정 (계획.md §6).
 *
 * 키 발급 단위가 발급처마다 다르다. 이 차이가 이 클래스 구조의 이유다.
 *
 * data-go-kr   공공데이터포털   키 1개로 여러 API   KHOA 6종 · 기상특보 · 해상풍
 * kma-apihub   기상청 API허브   키 1개             sea_obs.php
 * nifs         국립수산과학원   **API 마다 키가 따로 나온다**  적조 · 해파리 · 실시간어장
 *
 * 그래서 키를 발급처 단위(keys)로 두되, 소스별 덮어쓰기(Source.apiKey)를
 * 허용한다. 발급처 단위만 두면 NIFS 가 안 들어가고, 소스 단위만 두면 data.go.kr 쪽에서
 * 같은 키를 여러 줄에 복사하게 되어 재발급 때 한 줄을 빠뜨린다.
 *
 * 키는 저장소에 두지 않는다. infra/.env → compose environment →
 * 환경변수 → application.yml 의 ${...}.
 * 선내 PC 가 공공데이터를 직접 호출하지 않는 이유도 이것이다(계획.md §9.13) —
 * 프론트 번들에 키가 박히고 선박 수만큼 쿼터가 곱해진다.
 */
@ConfigurationProperties(prefix = "app.ocean")
public record OceanApiProperties(
        String collectCron,
        /** 좌표가 없는 곳의 기준 위치 · 지점 반경. 선박을 따라가지 않는다 */
        Coverage coverage,
        /** 발급처 공용 인증키. NIFS 처럼 API 별로 키가 나오는 곳은 여기 대신 소스에 적는다 */
        @DefaultValue Map<Provider, String> keys,
        /** 소스별 설정. 맵의 키가 소스 식별자 */
        @DefaultValue Map<String, Source> sources) {

    /**
     * 키 발급처.
     *
     * 인증키를 싣는 쿼리 파라미터 이름이 발급처마다 다르다. 셋 다 확인했다 —
     * 하드코딩해 두면 새 소스를 붙일 때 이름을 다시 찾지 않아도 된다.
     * 틀리면 "키는 맞는데 인증 실패"가 나는데, 응답 메시지가 그 원인을 말해 주지 않는다.
     */
    public enum Provider {
        /** 공공데이터포털. 키 하나로 여러 API */
        DATA_GO_KR("serviceKey"),
        /** 기상청 API허브. 키 하나 */
        KMA_APIHUB("authKey"),
        /** 국립수산과학원. ⚠ API 마다 키가 따로 나온다 */
        NIFS("key"),
        /** 바다누리 자체 계정 계열. 우리 6종에는 쓰이지 않는다 */
        KHOA("serviceKey");

        private final String authParam;

        Provider(String authParam) {
            this.authParam = authParam;
        }

        public String authParam() {
            return authParam;
        }
    }

    /**
     * 좌표가 없는 곳의 기준 — `/sources` 에 lat·lon 이 없을 때 · 요약 · 관심 선박이 없을 때의 소해구.
     *
     * 선박 위치는 조회 좌표가 정한다. ROMS 는 조회된 곳의 0.25° 타일만 받는다(RomsTile).
     * 이전의 수집 해역(Area — bbox 하나를 마지막 조회 선박이 옮김)은 기각했다(2026-09-15): 배 두 척이면 해역을 서로 빼앗는다.
     *
     * @param stationRadiusKm 지점 소스(sea_obs · 실시간어장)를 자르는 반경. bbox 로 자르면 한 칸 차이로 통째로 빈다 —
     *                        0.1° bbox 에서 sea_obs 1곳 / 수과원 0곳이었다(2026-09-13 실측)
     */
    public record Coverage(double defaultLat, double defaultLon, @DefaultValue("30") double stationRadiusKm) {

        public boolean isValid() {
            return defaultLat >= -90 && defaultLat <= 90
                    && defaultLon >= -180 && defaultLon <= 180
                    && stationRadiusKm > 0;
        }
    }

    /**
     * 소스의 성질. 화면이 시각을 뭐라고 부를지가 여기서 갈린다 (§9.18).
     *
     * 셋을 나누지 않으면 "17시간 전 관측"처럼 방금 받은 예보가 낡은 값으로 보인다.
     */
    public enum Kind {
        /** 실제로 잰 값. observedAt 은 관측 시각 — "30분 전 관측" */
        OBSERVATION,
        /**
         * 모델이 계산한 미래 값. observedAt 은 모델 기준 시각 — "17시 예측값".
         *
         * 경과 시간을 신선도로 읽으면 안 된다. 값이 유효한 시각은 payload 의 validAt 이다.
         */
        FORECAST,
        /** 기관이 낸 발표. observedAt 은 발표 시각 — "2일 전 발표" */
        ADVISORY
    }

    /**
     * @param provider    어느 발급처인가
     * @param baseUrl     엔드포인트. 미확인이면 비워 두고 enabled: false —
     *                    주소를 지어내면 "키가 틀렸나 주소가 틀렸나"를 구분할 수 없게 된다
     * @param apiKey      이 소스 전용 키. 비면 발급처 공용 키(keys)를 쓴다
     * @param kind        관측·예보·발표. 화면의 시각 문구가 이것으로 갈린다
     * @param stnId       지점·권역·구역 코드. 선박운항지수 권역(AA_0004) · 기상특보 조업 해역(S1311100,S1312010 쉼표)
     * @param windowDays  기간 조회 소스의 조회 창(일). 0 이면 기간 조회가 아니다.
     *                    상한이 API 마다 다르다 — 기상특보 6일, 해파리 1년
     * @param intervalSec 수집 주기(초). 화면의 "몇 분 전 관측" 표기 근거
     * @param dailyQuota  하루 호출 상한. 0 이면 미확인 — 모르는 것을 위반으로 경고하지 않는다
     * @param enabled     끌 수 있어야 한다. 일정이 밀리면 기능을 빼는 것보다 소스를 끄는 편이 싸다
     */
    public record Source(
            Provider provider,
            String baseUrl,
            String apiKey,
            @DefaultValue("OBSERVATION") Kind kind,
            String stnId,
            @DefaultValue("0") int windowDays,
            int intervalSec,
            @DefaultValue("0") int dailyQuota,
            @DefaultValue("false") boolean enabled) {

        /** 이 주기로 하루 종일 돌면 몇 번 부르나 */
        public int callsPerDay() {
            return intervalSec <= 0 ? 0 : 86_400 / intervalSec;
        }

        /** 쿼터를 넘기는 설정인가. 미확인(0)이면 판단하지 않는다 */
        public boolean exceedsQuota() {
            return dailyQuota > 0 && callsPerDay() > dailyQuota;
        }

        public boolean hasOwnKey() {
            return apiKey != null && !apiKey.isBlank();
        }
    }

    /**
     * 이 소스가 쓸 인증키. 소스 전용 키가 우선이고 없으면 발급처 공용 키다.
     *
     * @return 없으면 null — 호출부가 "키 없음"으로 처리한다
     */
    public String keyFor(Source source) {
        return source.hasOwnKey() ? source.apiKey() : keys().get(source.provider());
    }
}

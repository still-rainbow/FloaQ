package com.floaq.ocean.khoa;

import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.seaobs.SeaObsStation;
import com.floaq.ocean.seaobs.SeaObsStore;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;

/**
 * KHOA 조석예보(시계열) — 예보지점의 조위.
 *
 * 쓰임: 항해 카테고리 "언제 갈까"(§9.18). 표류 추정과 무관하다 — 조위는 높이지 흐름이 아니다.
 *
 * 2026-09-16 실호출 (`DT_0005` 부산)
 *   봉투에 `response` 없음 · 하루 24행 · `tdlvHgt` **cm**(105.47) · `predcDt` KST
 *
 * ⚠ `apps/web/src/mock/data.ts` 에 "다음 정조 16:12 · 조위 128cm" 목 값이 남아 있다(2026-09-14 확인).
 *    이 소스가 들어오면 그 자리를 실제 값으로 바꿔야 한다 — kiosk 는 2026-09-13 에 목을 뺐다.
 */
@Component
public class TideForecastCollector extends KhoaForecastCollector {

    public static final String SOURCE = "tide-forecast";

    /** 활용가이드 PDF 코드표에서 뽑았다 (2026-09-16). DT_·SO_·IE_ 계열 */
    private static final String STATIONS = "/ocean/tide-forecast-stations.csv";

    /** 조위 원본 cm → m */
    private static final double CM_PER_M = 100.0;

    public TideForecastCollector(OceanApiClient client, SeaObsStore store) {
        super(client, store, STATIONS);
    }

    @Override
    public String source() {
        return SOURCE;
    }

    /**
     * 오늘 + 내일 (2026-09-16).
     *
     * 오늘치만 받으면 "지금 이후"가 저녁에 1~2점으로 줄고 자정 직전엔 0 이 된다 —
     * 화면의 용도가 <b>"다음 만조 언제냐"</b>라 오늘 남은 구간만으로는 답이 안 나온다.
     * 실측(2026-09-16 10시, 부산 DT_0005): 예보점 13개 · 간조 1건 · **만조 0건**.
     *
     * 조류예보는 1일 그대로 — 화면에 쓰지 않는다(항해 탭 유속은 ROMS 격자가 답한다).
     */
    @Override
    protected int forecastDays() {
        return 2;
    }

    @Override
    protected SeaObsStation row(KhoaStations.Station station, double lat, double lon,
                                Instant predcDt, JsonNode item) {
        Double tideCm = number(item, "tdlvHgt");
        return new SeaObsStation(
                null, station.code(), name(station, item), lat, lon, predcDt,
                null, null, null, null, null, null, null, null,
                null, null,
                tideCm == null ? null : tideCm / CM_PER_M);
    }

    private static String name(KhoaStations.Station station, JsonNode item) {
        String responded = text(item, "obsvtrNm");
        return responded != null ? responded : station.name();
    }
}

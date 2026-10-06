package com.floaq.ocean.khoa;

import com.floaq.ocean.OceanUnits;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.seaobs.SeaObsStation;
import com.floaq.ocean.seaobs.SeaObsStore;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;

/**
 * KHOA 조류예보(시계열) — 예보지점의 유향·유속.
 *
 * 쓰임: 연안 보조. ROMS 격자가 약 3km 라 연안에서 육지와 섞이는데([[260913_ocean-collector]] §7),
 * 이쪽은 지점 값이라 그 자리에서 정확하다. **표류 추정 입력은 여전히 ROMS 단독이다** — 조류예보는
 * 조석에 의한 흐름만이라 해류·취송류가 빠진다(2026-09-14 확인).
 *
 * 2026-09-16 실호출 (`16LTC13` 부산항입구)
 *   봉투에 `response` 없음 · 하루 24행 · `crdir` **"북북동"** 같은 **16방위 한글** · `crsp` **cm/s**(30.86)
 *   ⚠ 가이드 PDF 의 XML 예제(`crdir=164.10`, `obsrvnDt`)는 틀렸다. 응답표와 실호출이 맞다
 */
@Component
public class CurrentForecastCollector extends KhoaForecastCollector {

    public static final String SOURCE = "current-forecast";

    /** 활용가이드 PDF 코드표에서 뽑았다 (2026-09-16). 목록 API 가 없다 */
    private static final String STATIONS = "/ocean/current-forecast-stations.csv";

    public CurrentForecastCollector(OceanApiClient client, SeaObsStore store) {
        super(client, store, STATIONS);
    }

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    protected SeaObsStation row(KhoaStations.Station station, double lat, double lon,
                                Instant predcDt, JsonNode item) {
        Double speedCmS = number(item, "crsp");
        return new SeaObsStation(
                null, station.code(), name(station, item), lat, lon, predcDt,
                null, null, null, null, null, null, null, null,
                // 16방위 한글 → deg. 못 읽으면 null 이다 — 0 으로 두면 '북'으로 읽힌다
                OceanUnits.degreesOfKorean16(text(item, "crdir")),
                speedCmS == null ? null : OceanUnits.fromCmPerSec(speedCmS),
                null);
    }

    /** 응답의 지점명이 먼저다. 가이드 표기와 다르면 실제 값을 남긴다 */
    private static String name(KhoaStations.Station station, JsonNode item) {
        String responded = text(item, "obsvtrNm");
        return responded != null ? responded : station.name();
    }
}

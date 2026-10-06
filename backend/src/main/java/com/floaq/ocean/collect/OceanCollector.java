package com.floaq.ocean.collect;

import com.floaq.ocean.OceanApiProperties.Source;

/**
 * 소스 1종의 수집기. 빈으로 등록하면 스케줄러가 집어 감.
 *
 * 공통 파서 기각 — 응답이 격자 배열(ROMS) / 특보구역 이벤트+현황 문장(기상특보) / 2단계+중첩배열(적조) /
 * 고정폭 텍스트(sea_obs) 로 갈림. 공통화하면 함정이 한 클래스로 모임.
 */
public interface OceanCollector {

    /** app.ocean.sources 키와 같아야 함 */
    String source();

    /** 실패도 결과. 예외를 던지지 않음 */
    CollectOutcome collect(Source config, String key);
}

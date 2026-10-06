package com.floaq.ocean.summary;

import java.time.Instant;
import java.util.List;

/**
 * 해양 상황 요약 한 덩어리.
 *
 * LLM 은 판단하지 않는다. 출항 가부와 위험 알림은 결정론적 규칙(기상청 특보 기준)이 정하고,
 * LLM 은 그 판정과 수집값을 사람 말로 옮긴다 (계획.md §9.18).
 *
 * @param headline  한 줄. 화면 맨 위
 * @param body      두세 문장
 * @param facts     요약이 근거로 삼은 값. 문장만 두면 "그 숫자 어디서 나왔냐"에 답할 수 없다
 * @param model     생성 모델. 목이면 "mock"
 * @param mock      LLM 을 부르지 않고 규칙으로 만든 문장인가
 * @param lat       이 문장이 선 기준 좌표. null 이면 기준을 모른다(수집값이 아예 없는 경우)
 * @param shipBased 본선 좌표 기준인가. false 면 서버 기본 위치(app.ocean.coverage) 기준이라
 *                  <b>문장 속 지점·거리가 이 배와 무관하다</b> — 화면이 그것을 밝혀야 한다
 */
public record OceanSummary(
        String headline,
        String body,
        List<String> facts,
        Instant generatedAt,
        String model,
        boolean mock,
        Double lat,
        Double lon,
        boolean shipBased) {

    /** 기준 좌표를 모르는 자리(writer 의 목·생성)용. 좌표는 서비스가 나중에 붙인다 */
    public OceanSummary(String headline, String body, List<String> facts,
                        Instant generatedAt, String model, boolean mock) {
        this(headline, body, facts, generatedAt, model, mock, null, null, false);
    }

    public OceanSummary at(double lat, double lon, boolean shipBased) {
        return new OceanSummary(headline, body, facts, generatedAt, model, mock, lat, lon, shipBased);
    }
}

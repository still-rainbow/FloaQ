package com.floaq.ocean.dto;

import com.floaq.ocean.OceanApiProperties.Kind;
import com.floaq.ocean.entity.OceanSnapshot;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

/**
 * 대시보드 1행. 값과 함께 경과 시간·수집 주기를 반드시 내린다 (§9.18).
 *
 * 갱신 주기가 3분~주간으로 5자리수 차이라, 병기하지 않으면 오래된 값을 오늘 값으로 읽음.
 *
 * stale 판정 안 함 — 임계를 서버가 정하면 근거 없는 숫자가 됨. 화면이 값으로 그림.
 *
 * @param kind   OBSERVATION "30분 전 관측" · FORECAST "17시 예측값" · ADVISORY "2일 전 발표".
 *               예보의 ageSec 를 신선도로 읽으면 방금 받은 값이 낡아 보인다
 * @param ageSec observedAt 이후 경과 초. 성공 이력이 없으면 null.
 *               예보는 모델 기준 시각 이후 경과이지 데이터가 낡은 정도가 아니다
 */
public record OceanSourceView(
        String source,
        Kind kind,
        Instant observedAt,
        Instant fetchedAt,
        Long ageSec,
        int intervalSec,
        String resultCode,
        String resultMsg,
        Map<String, Object> payload) {

    public static OceanSourceView of(OceanSnapshot snapshot, Kind kind, int intervalSec, Instant now) {
        Instant observedAt = snapshot.getObservedAt();
        return new OceanSourceView(
                snapshot.getSource(),
                kind,
                observedAt,
                snapshot.getFetchedAt(),
                observedAt == null ? null : Duration.between(observedAt, now).toSeconds(),
                intervalSec,
                snapshot.getResultCode(),
                snapshot.getResultMsg(),
                snapshot.getPayload());
    }

    /** payload 만 바꾼 행 — 지점 소스를 조회 좌표로 자를 때 (StationNear) */
    public OceanSourceView withPayload(Map<String, Object> next) {
        return new OceanSourceView(source, kind, observedAt, fetchedAt, ageSec, intervalSec, resultCode, resultMsg, next);
    }
}

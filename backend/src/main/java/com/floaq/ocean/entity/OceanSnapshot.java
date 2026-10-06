package com.floaq.ocean.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;
import java.util.Map;

/**
 * 소스별 최신 수집 결과. 이력 아닌 캐시 (V2__ocean.sql).
 *
 * observedAt · payload    마지막 **성공** 값
 * fetchedAt · resultCode  마지막 **시도** 결과
 *
 * 실패 시 payload 유지 — 지우면 "키 만료"와 "그 해역에 값 없음"이 화면에서 같은 모습(§9.10).
 */
@Getter
@Entity
@Table(name = "ocean_snapshot")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class OceanSnapshot {

    /** app.ocean.sources 키 */
    @Id
    @Column(length = 32)
    private String source;

    /**
     * 원본의 기준 시각. 소스 종류(Kind)에 따라 뜻이 다르다.
     *
     * OBSERVATION 관측 시각  · FORECAST 모델 기준 시각 · ADVISORY 발표 시각
     *
     * 예보에서 이 값의 경과 시간을 신선도로 읽으면 안 된다 — 값이 유효한 시각은 payload.validAt 이다.
     */
    private Instant observedAt;

    /**
     * 정규화(SI) 값.
     *
     * String 기각 — jsonb 에 매핑 시 Hibernate 가 JSON 문자열 하나로 감싸
     * "{\"a\":1}" 로 저장. 꺼낼 때까지 안 드러남.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    private Map<String, Object> payload;

    @Column(nullable = false)
    private Instant fetchedAt;

    @Column(nullable = false, length = 16)
    private String resultCode;

    @Column(length = 200)
    private String resultMsg;

    private OceanSnapshot(String source) {
        this.source = source;
    }

    public static OceanSnapshot of(String source) {
        return new OceanSnapshot(source);
    }

    public void succeed(Instant observedAt, Map<String, Object> payload, Instant fetchedAt, String code, String msg) {
        this.observedAt = observedAt;
        this.payload = payload;
        attempt(fetchedAt, code, msg);
    }

    /** 실패·데이터없음. payload·observedAt 불변 */
    public void attempt(Instant fetchedAt, String code, String msg) {
        this.fetchedAt = fetchedAt;
        this.resultCode = code;
        // 컬럼 200자. 외부 메시지 길이는 우리가 못 정함
        this.resultMsg = msg == null || msg.length() <= 200 ? msg : msg.substring(0, 200);
    }
}

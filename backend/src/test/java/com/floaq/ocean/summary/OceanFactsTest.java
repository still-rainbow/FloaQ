package com.floaq.ocean.summary;

import com.floaq.ocean.entity.OceanSnapshot;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 요약이 근거로 삼는 값. 이 목록이 프롬프트 입력이자 화면에 함께 뜨는 근거다.
 *
 * 입력은 2026-09-13 실수집 payload 모양이다.
 */
class OceanFactsTest {

    private static OceanSnapshot snap(String source, Map<String, Object> payload) {
        var s = OceanSnapshot.of(source);
        s.succeed(Instant.parse("2026-09-13T08:00:00Z"), payload, Instant.now(), "00", null);
        return s;
    }

    @Test
    void 발효_중_특보가_없으면_없다고_적는다() {
        var facts = OceanFacts.of(List.of(
                snap("weather-warning", Map.of("activeMarineWarnings", List.of()))));

        assertThat(facts).containsExactly("해상 특보: 발효 중 없음");
    }

    @Test
    void 발효_중이면_이름을_싣는다() {
        var facts = OceanFacts.of(List.of(
                snap("weather-warning", Map.of("activeMarineWarnings", List.of("풍랑주의보")))));

        assertThat(facts.getFirst()).contains("풍랑주의보").contains("발효 중");
    }

    @Test
    void 발효_해역을_함께_싣는다() {
        var facts = OceanFacts.of(List.of(snap("weather-warning", Map.of(
                "activeMarineWarnings", List.of("풍랑주의보"),
                "activeAreas", List.of(Map.of("areaName", "부산앞바다"), Map.of("areaName", "남해동부안쪽먼바다"))))));

        assertThat(facts.getFirst()).contains("부산앞바다").contains("남해동부안쪽먼바다");
    }

    @Test
    void 예비특보가_있으면_싣고_없음이면_뺀다() {
        var with = OceanFacts.of(List.of(snap("weather-warning", Map.of(
                "activeMarineWarnings", List.of(),
                "status", Map.of("preliminary", "(1) 풍랑 예비특보\n09월 15일 새벽 : 남해동부앞바다")))));
        assertThat(with).anyMatch(f -> f.startsWith("예비특보") && f.contains("남해동부앞바다"));

        // 실응답은 "없 음" 처럼 공백이 섞여 온다
        var none = OceanFacts.of(List.of(snap("weather-warning", Map.of(
                "activeMarineWarnings", List.of(),
                "status", Map.of("preliminary", "없 음")))));
        assertThat(none).noneMatch(f -> f.startsWith("예비특보"));
    }

    @Test
    void 운항지수는_참고지수라고_적는다() {
        var facts = OceanFacts.of(List.of(snap("ship-index", Map.of(
                "focusName", "대한해협",
                "current", Map.of("slot", "오후", "score", "보통")))));

        assertThat(facts).anyMatch(f -> f.contains("대한해협") && f.contains("보통") && f.contains("참고지수"));
    }

    @Test
    void 조업_해역_판정과_전국_목록을_따로_적는다() {
        var facts = OceanFacts.of(List.of(snap("weather-warning", Map.of(
                "activeMarineWarnings", List.of("풍랑주의보"),
                "activeAreas", List.of(Map.of("areaName", "제주도동부앞바다")),
                "focus", Map.of("names", List.of("부산앞바다", "남해동부안쪽먼바다"),
                        "activeMarineWarnings", List.of())))));

        assertThat(facts).contains("조업 해역(부산앞바다·남해동부안쪽먼바다) 해상 특보: 없음");
        assertThat(facts).anyMatch(f -> f.startsWith("전국 해상 특보: 풍랑주의보") && f.contains("제주도동부앞바다"));
    }

    @Test
    void 지점과_거리를_함께_적는다() {
        // 파고와 바람이 다른 지점에서 온다. 어디 값인지 빼면 요약이 거짓이 된다
        var facts = OceanFacts.of(List.of(snap("sea-obs", Map.of("stations", List.of(
                Map.of("name", "오륙도", "distanceKm", 8.6, "waveHeightM", 0.4),
                Map.of("name", "부산", "distanceKm", 4.9, "windSpeedMs", 5.3))))));

        assertThat(facts).anyMatch(f -> f.startsWith("파고 0.4m") && f.contains("오륙도") && f.contains("8.6km"));
        assertThat(facts).anyMatch(f -> f.startsWith("풍속 5.3m/s") && f.contains("부산"));
    }

    @Test
    void 예측값은_예측이라고_적는다() {
        var facts = OceanFacts.of(List.of(
                snap("roms", Map.of("currentSpeedMs", 0.31, "currentDirDeg", 285.73))));

        assertThat(facts).anyMatch(f -> f.contains("0.31m/s") && f.contains("예측"));
        assertThat(facts).anyMatch(f -> f.contains("286도") && f.contains("예측"));
    }

    @Test
    void 해파리는_판단_근거가_아님을_붙인다() {
        // 제공기관이 직접 적어 둔 한계다. 요약 문장에 그대로 따라가야 한다
        var facts = OceanFacts.of(List.of(
                snap("jellyfish", Map.of("subject", "주간보고 19차"))));

        assertThat(facts.getFirst()).contains("판단 근거가 아님");
    }

    @Test
    void 해파리_출현율을_읽었으면_종별로_붙인다() {
        // 첨부 PDF 에서 읽어 둔 값(JellyfishReportReader). 고밀도만 붙인다 —
        // 저밀도는 거의 전국이라 문장만 길어지고 판단을 바꾸지 않는다
        var report = Map.of("species", List.of(
                Map.of("name", "노무라입깃해파리", "prevPct", 17, "pct", 18,
                        "high", List.of("전남광주"), "low", List.of("인천", "경기")),
                Map.of("name", "보름달물해파리", "prevPct", 14, "pct", 10,
                        "high", List.of("전남광주", "경남"), "low", List.of())));
        var facts = OceanFacts.of(List.of(
                snap("jellyfish", Map.of("subject", "주간보고 20회차", "report", report))));

        assertThat(facts.getFirst())
                .contains("노무라입깃해파리 17→18%")
                .contains("고밀도 전남광주")
                .contains("보름달물해파리 14→10%")
                .contains("고밀도 전남광주·경남")
                // 한계 문구는 수치가 붙어도 그대로 따라간다 — 이 숫자로 조업을 판단하면 안 된다
                .contains("판단 근거가 아님")
                // 저밀도는 안 붙인다
                .doesNotContain("인천");
    }

    @Test
    void 해파리_출현율을_못_읽었으면_제목만_남는다() {
        // 🔴 report 가 없으면 없는 수치를 지어내지 않는다. 화면은 원문 링크로 물러선다
        var facts = OceanFacts.of(List.of(
                snap("jellyfish", Map.of("subject", "주간보고 20회차"))));

        assertThat(facts.getFirst()).isEqualTo(
                "해파리 주간보고: 주간보고 20회차 (설문 응답률이라 판단 근거가 아님)");
    }

    @Test
    void payload_가_없으면_그_소스는_빠진다() {
        // 실패한 소스가 "값 0"으로 들어가면 요약이 없는 사실을 말하게 된다
        var empty = OceanSnapshot.of("roms");
        empty.attempt(Instant.now(), "22", "쿼터 초과");

        assertThat(OceanFacts.of(List.of(empty))).isEmpty();
    }
}

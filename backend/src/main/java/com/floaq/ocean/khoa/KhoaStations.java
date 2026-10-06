package com.floaq.ocean.khoa;

import lombok.extern.slf4j.Slf4j;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * KHOA 예보지점 목록 — 활용가이드 PDF 코드표에서 뽑아 리소스로 둔다 (2026-09-16).
 *
 * **목록 API 가 없다.** 조류·조석예보는 `obsCode` 가 필수인데 코드를 주는 엔드포인트가 없어
 * 가이드 PDF 의 "예보지점 목록" 표가 유일한 출처다(`p-shim/ref/openapi/`).
 * 좌표는 목록에 없고 **응답의 lat·lot 로 온다** — 그래서 지점 선택을 좌표로 못 하고 전국을 받는다.
 *
 * ⚠ KHOA 가 지점을 늘리면 이 파일이 낡는다. 응답이 `NODATA` 면 그 지점만 조용히 빠진다 —
 *    가이드가 갱신되면 CSV 를 다시 뽑아야 한다(추출 절차는 [[260916_khoa-forecast]]).
 */
@Slf4j
public final class KhoaStations {

    /** @param code obsCode. 숫자·영문·하이픈·밑줄이 섞인다 (예 16LTC13 · DT_0005 · 01MP-2 · JejuStrait) */
    public record Station(String code, String name) {
    }

    private KhoaStations() {
    }

    /**
     * @param resource 클래스패스 경로. 첫 줄은 헤더(code,name)
     * @return 코드 중복은 먼저 온 것만. 못 읽으면 빈 목록 — 호출부가 "지점 없음"으로 실패를 남긴다
     */
    public static List<Station> load(String resource) {
        Map<String, Station> unique = new LinkedHashMap<>();
        try (InputStream in = KhoaStations.class.getResourceAsStream(resource)) {
            if (in == null) {
                log.error("[ocean] 지점 목록을 찾을 수 없다 — {}", resource);
                return List.of();
            }
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
                String line = reader.readLine();   // 헤더
                while ((line = reader.readLine()) != null) {
                    String row = line.trim();
                    if (row.isEmpty()) {
                        continue;
                    }
                    // 지점명에 쉼표가 없다(가이드 표 확인). 그래도 2개로만 나눠 이름 쪽에 남긴다
                    String[] parts = row.split(",", 2);
                    if (parts.length < 2 || parts[0].isBlank()) {
                        continue;
                    }
                    unique.putIfAbsent(parts[0].trim(), new Station(parts[0].trim(), parts[1].trim()));
                }
            }
        } catch (Exception e) {
            log.error("[ocean] 지점 목록 읽기 실패 — {}", resource, e);
            return List.of();
        }
        return new ArrayList<>(unique.values());
    }
}

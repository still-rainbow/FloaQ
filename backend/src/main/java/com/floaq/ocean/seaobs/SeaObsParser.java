package com.floaq.ocean.seaobs;

import lombok.extern.slf4j.Slf4j;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;

/**
 * sea_obs.php 고정폭 텍스트 파서.
 *
 * 실제 응답 (2026-09-13, EUC-KR 변환 후)
 *
 * #START7777
 * #            TM       STN    STN KO      LON        LAT    WH   WD    WS   WS   TW   TA     PA    HM
 * #           KST        ID                deg        deg     m  deg   m/s  GST    C    C    hPa     %
 * B, 202609131600,  22101,    덕적도, 126.01880000, 37.23610000, 0.1, 273, 2.0, 2.9, 24.8, 22.9, 1017.7, 68.0, ,=
 * #7777END
 */
@Slf4j
final class SeaObsParser {

    /** 결측 표식. 숫자로 파싱하면 그대로 값이 되어 수온 -99℃ 가 화면에 오른다 */
    private static final double MISSING = -99.0;
    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter TM = DateTimeFormatter.ofPattern("yyyyMMddHHmm");

    /** 헤더 주석과 데이터 줄을 가르는 문자 */
    private static final char COMMENT = '#';

    /** 마지막 두 칸은 비고와 종결 표식이라 쓰지 않는다 */
    private static final int MIN_FIELDS = 14;

    private SeaObsParser() {
    }

    static List<SeaObsStation> parse(String body) {
        List<SeaObsStation> stations = new ArrayList<>();
        if (body == null || body.isBlank()) {
            return stations;
        }
        for (String line : body.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || trimmed.charAt(0) == COMMENT) {
                continue;
            }
            String[] f = trimmed.split(",");
            if (f.length < MIN_FIELDS) {
                continue;
            }
            Instant observedAt = parseTm(f[1].trim());
            Double lat = number(f[5]);
            Double lon = number(f[4]);
            if (observedAt == null || lat == null || lon == null) {
                // 좌표 없는 줄은 해역 필터를 못 지나므로 여기서 버린다
                continue;
            }
            stations.add(new SeaObsStation(
                    f[0].trim(), f[2].trim(), f[3].trim(), lat, lon, observedAt,
                    number(f[6]), number(f[7]), number(f[8]), number(f[9]),
                    number(f[10]), number(f[11]), number(f[12]), number(f[13])));
        }
        return stations;
    }

    private static Instant parseTm(String raw) {
        try {
            return LocalDateTime.parse(raw, TM).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] sea-obs — TM 판독 실패: '{}'", raw);
            return null;
        }
    }

    /** 결측이면 null. 0.0 이나 -99 로 두면 계산에 섞여 들어간다 */
    private static Double number(String raw) {
        try {
            double value = Double.parseDouble(raw.trim());
            return value <= MISSING ? null : value;
        } catch (NumberFormatException e) {
            return null;
        }
    }
}

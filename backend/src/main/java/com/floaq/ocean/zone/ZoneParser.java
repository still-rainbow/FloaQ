package com.floaq.ocean.zone;

import lombok.extern.slf4j.Slf4j;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.time.temporal.ChronoField;
import java.util.ArrayList;
import java.util.List;

/**
 * marine_large_zone · marine_small_zone 텍스트 파서 (disp=0, 공백 구분).
 *
 * 실제 응답 (2026-09-14, EUC-KR 변환 후)
 *
 * #START7777
 * #   TMA_FC     TMA_EF LZONE LAT_LB  LON_LB  LAT_LT  LON_LT  LAT_RT  LON_RT  LAT_RB  LON_RB  WH_SIG  WVPRD_MAX  WVDR  WS  WD
 * 2026091400 2026091412    92   35.0   129.0    35.5   129.0    35.5   129.5    35.0   129.5   0.6   4.1   53.8   6.6   39.6
 * #7777END
 *
 * 소해구는 LZONE 뒤에 SZONE 이 끼고, 끝에 VS·RAIN·TW·SWELL 넷이 더 붙는다(2026-07-01 00UTC 발표본부터).
 *
 * 🔴 **오류도 HTTP 200 이다.** 본문이 한글 문구 한 줄로 온다 —
 *    "파일이 존재하지 않습니다. (...h000_2026091412.txt)" (발표본 생산 전) · "발효시각을 확인하여 주시기 바랍니다."
 *    그래서 {@link #START} 표식으로 자료 여부를 먼저 가른다.
 */
@Slf4j
public final class ZoneParser {

    /** 자료 본문의 시작 표식. 없으면 오류 문구다 */
    public static final String START = "#START7777";

    /** 결측. 숫자로 두면 파고 -999m 가 화면에 오른다 */
    private static final double MISSING = -999.0;

    /** 원자료 시각은 UTC yyyymmddhh. 분이 없어 기본값을 채워야 LocalDateTime 으로 읽힌다 */
    static final DateTimeFormatter TMA = new DateTimeFormatterBuilder()
            .appendPattern("uuuuMMddHH")
            .parseDefaulting(ChronoField.MINUTE_OF_HOUR, 0)
            .toFormatter();

    /** 대해구 16칸 · 소해구 17칸(2026-07-01 이전) 또는 21칸 */
    private static final int LARGE_FIELDS = 16;
    private static final int SMALL_FIELDS_OLD = 17;

    private ZoneParser() {
    }

    /** 자료 본문인가. false 면 오류 문구 — {@link #message} 로 읽는다 */
    public static boolean isData(String body) {
        return body != null && body.contains(START);
    }

    /** 오류 문구 첫 줄. 로그·스냅샷 사유용 */
    public static String message(String body) {
        if (body == null || body.isBlank()) {
            return "빈 응답";
        }
        String first = body.strip().lines().findFirst().orElse("").strip();
        return first.length() <= 200 ? first : first.substring(0, 200);
    }

    /**
     * 발표본을 아직 생산하지 않았다는 응답인가.
     *
     * 🔴 <b>이 판정으로 "물러설지"를 정하지 말 것</b> (2026-09-16).
     *    소해구는 파일이 아직 없을 때 이 문구가 아니라 <b>"해구번호를 확인하여 주시기 바랍니다"</b> 를 준다 —
     *    같은 해구 목록으로 직전 발표본을 부르면 정상 응답하고, 대해구는 같은 발표본에 자료를 준다(실측으로 가름).
     *    그래서 {@link ZoneCollector} 는 문구와 무관하게 직전 발표본을 한 번 더 시도하고,
     *    둘 다 실패할 때만 실패로 남긴다. 이 메서드는 <b>로그 문구를 고르는 데만</b> 쓴다.
     */
    public static boolean isNotReady(String body) {
        return body != null && (body.contains("파일이 존재하지 않습니다") || body.contains("대응하는 자료가 없습니다"));
    }

    public static List<ZoneCell> parse(String body, ZoneLevel level) {
        List<ZoneCell> cells = new ArrayList<>();
        if (!isData(body)) {
            return cells;
        }
        int min = level == ZoneLevel.SMALL ? SMALL_FIELDS_OLD : LARGE_FIELDS;
        int offset = level == ZoneLevel.SMALL ? 1 : 0;   // SZONE 한 칸
        for (String line : body.split("\\R")) {
            String trimmed = line.strip();
            if (trimmed.isEmpty() || trimmed.charAt(0) == '#') {
                continue;
            }
            String[] f = trimmed.split("\\s+");
            if (f.length < min) {
                log.warn("[ocean] marine-zone — 칸 수 부족({}): '{}'", f.length, trimmed);
                continue;
            }
            try {
                cells.add(cell(f, level, offset));
            } catch (RuntimeException e) {
                // 한 줄 판독 실패로 발표본 전체를 버리지 않는다
                log.warn("[ocean] marine-zone — 줄 판독 실패: '{}'", trimmed);
            }
        }
        return cells;
    }

    private static ZoneCell cell(String[] f, ZoneLevel level, int o) {
        double latLb = Double.parseDouble(f[3 + o]);
        double lonLb = Double.parseDouble(f[4 + o]);
        double latLt = Double.parseDouble(f[5 + o]);
        double lonLt = Double.parseDouble(f[6 + o]);
        double latRt = Double.parseDouble(f[7 + o]);
        double lonRt = Double.parseDouble(f[8 + o]);
        double latRb = Double.parseDouble(f[9 + o]);
        double lonRb = Double.parseDouble(f[10 + o]);
        int v = 11 + o;
        boolean extra = level == ZoneLevel.SMALL && f.length >= v + 9;
        return new ZoneCell(
                time(f[0]), time(f[1]),
                Integer.parseInt(f[2]),
                level == ZoneLevel.SMALL ? Integer.parseInt(f[3]) : 0,
                Math.min(latLb, latRb), Math.max(latLt, latRt),
                Math.min(lonLb, lonLt), Math.max(lonRt, lonRb),
                number(f[v]), number(f[v + 1]), number(f[v + 2]), number(f[v + 3]), number(f[v + 4]),
                extra ? number(f[v + 5]) : null,
                extra ? number(f[v + 6]) : null,
                extra ? number(f[v + 7]) : null,
                extra ? swell(f[v + 8]) : null);
    }

    static Instant time(String raw) {
        return LocalDateTime.parse(raw, TMA).toInstant(ZoneOffset.UTC);
    }

    /** 결측이면 null */
    private static Double number(String raw) {
        double value = Double.parseDouble(raw);
        return value <= MISSING ? null : value;
    }

    /** 너울은 1~4 만 값이다. -999 · 0 · 범위 밖은 null — CHECK 제약과 같은 규칙 */
    private static Integer swell(String raw) {
        double value = Double.parseDouble(raw);
        return value >= 1 && value <= 4 ? (int) value : null;
    }
}

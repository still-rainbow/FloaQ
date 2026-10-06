package com.floaq.ocean.warning;

import lombok.extern.slf4j.Slf4j;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 기상청 API허브 wrn_reg.php (특보구역) 고정폭 텍스트 파서.
 *
 * 2026-09-14 실호출
 *   EUC-KR · 머리말 #START7777 ~ #7777END, 데이터 줄은 # 없음
 *   REG_ID TM_ST TM_ED REG_SP REG_UP REG_KO(고정폭) REG_NAME
 *   루트 상위코드 00000000 · S2000000 은 자기 자신이 상위
 */
@Slf4j
public final class WarningZoneParser {

    /** 약어·정식명은 두 칸 이상 공백으로 가름. 이름 안 한 칸 공백은 이름으로 둠 */
    private static final Pattern LINE = Pattern.compile(
            "^(\\S{8})\\s+(\\d{12})\\s+(\\d{12})\\s+(\\S+)\\s+(\\S{8})\\s+(.+?)(?:\\s{2,}(\\S.*?))?\\s*$");

    private static final String NO_PARENT = "00000000";
    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter TM = DateTimeFormatter.ofPattern("yyyyMMddHHmm");

    private WarningZoneParser() {
    }

    /** @param up 상위 구역. 루트면 null */
    public record Row(String id, Instant validFrom, Instant validTo, String spec, String up,
                      String shortName, String name) {
    }

    public static List<Row> parse(String body) {
        List<Row> rows = new ArrayList<>();
        if (body == null) {
            return rows;
        }
        int skipped = 0;
        for (String raw : body.split("\\r?\\n")) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            Matcher m = LINE.matcher(line);
            if (!m.matches()) {
                skipped++;
                continue;
            }
            String shortName = m.group(6).strip();
            rows.add(new Row(m.group(1), tm(m.group(2)), tm(m.group(3)), m.group(4),
                    NO_PARENT.equals(m.group(5)) ? null : m.group(5),
                    shortName, m.group(7) == null ? shortName : m.group(7).strip()));
        }
        if (skipped > 0) {
            // 형식이 바뀌면 조용히 줄어듦. 건수를 남김
            log.warn("[ocean] warning-zone — 판독 못 한 줄 {}개", skipped);
        }
        return rows;
    }

    private static Instant tm(String raw) {
        try {
            return LocalDateTime.parse(raw, TM).atZone(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            return null;
        }
    }
}

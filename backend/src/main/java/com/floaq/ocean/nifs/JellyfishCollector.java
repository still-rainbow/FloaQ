package com.floaq.ocean.nifs;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import com.floaq.ocean.entity.OceanSnapshot;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 수과원 해파리정보 — 이번 주 해역 출현 동향.
 *
 * 제공기관이 한계를 직접 적어 둔 데이터다. 원문 그대로 화면에 함께 띄운다(§6).
 *
 * 2026-09-13 실호출로 확인한 것
 *   jellyList 는 게시판 목록이다. 수치가 아니라 제목과 board_idx 만 준다
 *   상세는 jellyDetail 에 board_idx 를 srcode 로 넘기면 속보·주간보고 둘 다 나온다
 *   jellyDetail2 는 어떤 코드를 넣어도 빈 배열이다 (2026-09-14 재확인)
 *
 * 2026-09-14 실호출
 *   주간보고 board_context 는 제목 한 줄뿐 — 내용은 첨부 PDF
 *   첨부는 item2.board_file. 1건이면 객체, 여러 건이면 배열
 *
 * 한계: 지역 12곳 x 3종 출현율 수치는 jellyDetail2 에 있다는데 그 코드를 얻을 방법이 없다.
 * 대신 원문 첨부로 연결한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JellyfishCollector implements OceanCollector {

    public static final String SOURCE = "jellyfish";

    private static final String LIST_ID = "jellyList";
    private static final String DETAIL_ID = "jellyDetail";

    /** 주간보고가 주 1회라 한 달이면 최근 4회가 걸린다. 검색 기간 상한은 1년 */
    private static final int DEFAULT_WINDOW_DAYS = 30;

    /** gbn 0 = 주간보고, 1 = 속보. 동향은 주간보고가 준다 */
    private static final String WEEKLY_REPORT = "0";

    private static final ZoneId SOURCE_ZONE = ZoneId.of("Asia/Seoul");
    private static final DateTimeFormatter YMD = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 제공기관 원문. 화면에 이 값을 반드시 함께 띄운다 */
    private static final String CAVEAT =
            "출현율은 설문 응답률이며 대량 출현의 결정적 판단 근거로 이용될 수 없음 (국립수산과학원)";

    /** 상세 응답에서만 오는 키. 같은 보고면 직전 값을 그대로 쓴다 */
    private static final List<String> DETAIL_KEYS = List.of("text", "files", "report");

    private final OceanApiClient client;
    private final OceanSnapshotService snapshots;
    private final JellyfishReportReader reports;

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        LocalDate today = LocalDate.now(SOURCE_ZONE);
        int windowDays = config.windowDays() > 0 ? config.windowDays() : DEFAULT_WINDOW_DAYS;

        OceanResponse list = client.get(SOURCE, config, key, Map.of(
                "id", LIST_ID,
                "sdate", today.minusDays(windowDays).format(YMD),
                "edate", today.format(YMD)));
        if (!list.isOk()) {
            return CollectOutcome.from(list);
        }

        JsonNode latest = NifsResponses.items(list.body()).stream()
                .filter(n -> WEEKLY_REPORT.equals(NifsResponses.text(n, "gbn")))
                .max(Comparator.comparing(n -> String.valueOf(NifsResponses.text(n, "inpt_date"))))
                .orElse(null);
        if (latest == null) {
            return new CollectOutcome(OceanResponse.NO_DATA, "조회 창에 주간보고 없음", null, null);
        }

        String srcode = NifsResponses.text(latest, "board_idx");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("srcode", srcode);
        payload.put("subject", NifsResponses.text(latest, "board_subject"));
        payload.put("writer", NifsResponses.text(latest, "board_writer"));
        payload.put("caveat", CAVEAT);
        appendDetail(config, key, srcode, payload);

        Instant reportedAt = parseDay(NifsResponses.text(latest, "inpt_date"));
        log.info("[ocean] jellyfish — 최신 주간보고 {} ({})", srcode, reportedAt);
        return CollectOutcome.ok(reportedAt, payload);
    }

    /** 상세가 실패해도 제목은 살린다. 화면이 "이번 주 보고가 있다"까지는 말할 수 있다 */
    private void appendDetail(Source config, String key, String srcode, Map<String, Object> payload) {
        if (srcode == null) {
            return;
        }
        // 주간보고는 주 1회인데 수집은 하루 1회다 — 같은 보고면 상세를 다시 부르지 않는다 (2026-09-16)
        if (NifsDetailCache.reuse(stored(), "srcode", srcode, payload, DETAIL_KEYS)) {
            return;
        }
        OceanResponse detail = client.get(SOURCE, config, key, Map.of("id", DETAIL_ID, "srcode", srcode));
        if (!detail.isOk()) {
            log.warn("[ocean] jellyfish — 상세 실패 {} {}", detail.code(), detail.message());
            return;
        }
        NifsResponses.items(detail.body()).stream().findFirst().ifPresent(d -> {
            payload.put("text", NifsResponses.plainText(NifsResponses.text(d, "board_context")));
            List<String> files = attachments(d);
            payload.put("files", files);
            appendReport(payload, files);
        });
    }

    /**
     * 첨부 PDF 에서 지역별 출현율을 꺼내 {@code payload.report} 에 넣는다 (2026-09-18).
     *
     * <p>여기가 <b>새 보고를 처음 본 순간</b>이다 — 위 {@code reuse} 가 같은 {@code srcode} 를
     * 걸러 주므로 <b>PDF 읽기와 LLM 호출이 주 1회</b>로 묶인다. 수집은 하루 1회지만
     * 주간보고는 주 1회라, 여기 안 두면 같은 PDF 를 이레 내내 다시 읽는다.</p>
     *
     * <p>🔴 <b>못 읽으면 넣지 않는다.</b> 그러면 화면이 예전처럼 제목과 원문 링크로 물러선다 —
     * 양식이 바뀌었을 때 조용히 틀린 숫자를 올리는 것보다 낫다. 수집 자체는 성공으로 둔다.</p>
     */
    private void appendReport(Map<String, Object> payload, List<String> files) {
        if (files == null || files.isEmpty()) {
            return;
        }
        Map<String, Object> report = reports.read(files.getFirst());
        if (report != null) {
            payload.put("report", report);
        }
    }

    /** 직전 성공 payload. 실패한 수집은 payload 를 덮지 않으므로(§9.10) 마지막 성공값이 남아 있다 */
    private Map<String, Object> stored() {
        return snapshots.find(SOURCE).map(OceanSnapshot::getPayload).orElse(null);
    }

    /** 첨부 원문 주소. 화면이 링크로 여는 값이라 https 만 통과 — javascript: 등 차단 */
    static List<String> attachments(JsonNode detail) {
        return NifsResponses.array(detail.path("item2")).stream()
                .map(f -> NifsResponses.text(f, "board_file"))
                .filter(url -> url != null && url.startsWith("https://"))
                .toList();
    }

    private static Instant parseDay(String raw) {
        if (raw == null) {
            return null;
        }
        try {
            return LocalDate.parse(raw, YMD).atStartOfDay(SOURCE_ZONE).toInstant();
        } catch (Exception e) {
            log.warn("[ocean] jellyfish — inpt_date 판독 실패: '{}'", raw);
            return null;
        }
    }
}

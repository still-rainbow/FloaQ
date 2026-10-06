package com.floaq.ocean.zone;

import com.floaq.ocean.OceanApiProperties.Source;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.client.OceanResponse;
import com.floaq.ocean.collect.CollectOutcome;
import com.floaq.ocean.collect.OceanCollector;
import lombok.extern.slf4j.Slf4j;

import java.nio.charset.Charset;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

import static java.time.temporal.ChronoUnit.HOURS;

/**
 * 기상청 해구별 예측 수집 — 대해구·소해구 공통.
 *
 * 명세 API허브 "7. 해구별 예측데이터 조회" · 2026-09-14 실호출
 *
 * 요청  tma_fc(발표 UTC yyyymmddhh) · tma_ef(발효, **필수**) · Lzone(콤마, 0 = 전체, 최대 40개) · Szone(소해구) · disp=0
 * 응답  EUC-KR 공백 구분 텍스트. 발효시각 하나에 한 번 — 발표본 하나가 26회(+0~75시간 3시간 간격)
 *
 * 발표는 하루 2회(00·12UTC)지만 생산 지연을 모른다 — 12UTC 발표본이 11:19 UTC 에도 없었다(실측).
 * 그래서 매시 확인하되 **이미 받은 발표본이면 호출하지 않는다.** 확인 비용은 생산 전일 때 1회뿐이다.
 *
 * 해구가 40개를 넘으면 나눠 묻는다(2026-09-15, 선박 여러 척) — 발표본 하나가 26회 × 묶음 수.
 *
 * ⚠ 수집 틱은 인스턴스 안에서 소스를 순서대로 돈다. 새 발표본을 받는 1회는 대해구 26회 × 0.4초 + 소해구 26회 × 1.4초 × 묶음 수로
 *   그동안 그 인스턴스의 다른 소스가 밀린다(하루 2번). 다른 인스턴스는 제 소스를 잡는다(ocean_job 리스).
 */
@Slf4j
public abstract class ZoneCollector implements OceanCollector {

    /** 원자료 EUC-KR. UTF-8 로 읽으면 오류 문구가 깨져 "생산 전"을 가르지 못한다 */
    private static final Charset SOURCE_CHARSET = Charset.forName("EUC-KR");

    /** 마지막 발효시각. +78h 는 "발효시각을 확인하여 주시기 바랍니다"(2026-09-14 실호출) */
    static final int LAST_HOUR = 75;
    static final int STEP_HOURS = 3;
    /** 발표 간격. 00·12UTC */
    static final int ISSUE_HOURS = 12;
    /** Lzone 한 번에 넣을 수 있는 상한 (명세 "최대 40개") */
    static final int MAX_LZONE = 40;

    protected final OceanApiClient client;
    protected final OceanZoneStore store;
    private final ZoneLevel level;

    protected ZoneCollector(OceanApiClient client, OceanZoneStore store, ZoneLevel level) {
        this.client = client;
        this.store = store;
        this.level = level;
    }

    /**
     * 받을 대해구 번호.
     *
     * @return null 이면 전체(Lzone=0). 빈 목록이면 고를 근거가 없다 — 수집하지 않는다
     */
    protected abstract List<Integer> targetZones();

    /**
     * 한 틱에 받을 묶음 수. 기본은 무제한 — <b>대해구는 Lzone=0 한 묶음이라 나눌 것이 없다.</b>
     *
     * <p>소해구 전국만 이걸 내린다. 884묶음 × 3.69초 ≈ 54분을 한 틱에 몰면 그동안
     * 같은 인스턴스의 ROMS·sea-obs·특보가 전부 멈춘다(수집 틱이 소스를 순서대로 돈다).</p>
     */
    protected int chunksPerTick() {
        return Integer.MAX_VALUE;
    }

    @Override
    public CollectOutcome collect(Source config, String key) {
        List<Integer> zones = targetZones();
        if (zones != null && zones.isEmpty()) {
            // 소해구는 대해구 발표본에서 가까운 해구를 고른다 — 대해구가 아직 없으면 고를 근거가 없다
            return new CollectOutcome("NO_BASE", "대해구 발표본이 없어 받을 소해구를 고를 수 없다", null, null);
        }
        List<List<Integer>> chunks = chunks(zones);
        Optional<Instant> stored = store.issuance(level);
        boolean sameZones = zones == null || new HashSet<>(zones).equals(new HashSet<>(store.zones(level)));
        Instant latest = latestIssuance(Instant.now());

        // 🔴 첫 발표본을 못 받으면 **문구와 무관하게** 직전 발표본을 본다 (2026-09-16).
        //    소해구는 파일이 아직 없을 때 "파일이 존재하지 않습니다" 가 아니라
        //    **"해구번호를 확인하여 주시기 바랍니다"** 를 준다(대해구는 같은 발표본에 정상 응답 — 실측으로 가름).
        //    문구로 생산 여부를 갈랐더니 소해구가 물러서지 못하고 매 틱 ERROR 로 끝났고,
        //    /zones?level=small 이 계속 503 이었다. 해구 번호 자체는 멀쩡했다(같은 목록으로 직전 발표본은 정상).
        //    두 발표본이 다 실패할 때만 ERROR 로 남긴다 — 진짜 해구 번호 오류는 그대로 드러난다.
        String lastReason = null;
        boolean allNotReady = true;

        // 최신 발표본 → 없으면 직전 발표본. 그보다 옛것은 +75시간이 이미 거의 지나 받을 이유가 없다
        for (Instant fc : List.of(latest, latest.minus(ISSUE_HOURS, HOURS))) {
            if (sameZones && stored.filter(fc::equals).isPresent()) {
                // 이미 받은 발표본이다. 호출 0 — 매시 확인이 쿼터를 쓰지 않게
                return CollectOutcome.ok(fc, payload(fc, null, zones, chunks.size()));
            }
            // 이어받는 중이면 생산 여부를 다시 묻지 않는다 — 이미 받아 본 발표본이다.
            // 매 틱 확인 호출을 1회씩 더 내면 7.4시간 수집에 442회가 더 나간다(전량 884회의 50%)
            if (chunksPerTick() < chunks.size() && store.stagedChunks(level, fc) > 0) {
                return fetchIssuance(config, key, fc, zones, chunks, null);
            }
            // 마지막 발효시각부터 묻는다(첫 묶음만). 생산 중인 발표본은 앞 시각만 있고 뒤가 없다 — 끝이 있으면 전부 있다
            String last = fetch(config, key, fc, fc.plus(LAST_HOUR, HOURS), chunks.getFirst());
            if (last == null) {
                lastReason = "호출 실패";
                allNotReady = false;
                log.warn("[ocean] {} — {} 호출 실패. 직전 발표본을 본다", source(), fc);
                continue;
            }
            if (!ZoneParser.isData(last)) {
                lastReason = ZoneParser.message(last);
                if (ZoneParser.isNotReady(last)) {
                    log.info("[ocean] {} — {} 발표본 생산 전. 직전 발표본을 본다", source(), fc);
                } else {
                    // 해구 목록을 함께 남긴다 — 진짜 번호 오류라면 이 로그가 유일한 단서다
                    allNotReady = false;
                    log.warn("[ocean] {} — {} 받지 못함: {} (해구 {}). 직전 발표본을 본다",
                            source(), fc, lastReason, describe(zones));
                }
                continue;
            }
            return fetchIssuance(config, key, fc, zones, chunks, last);
        }
        return allNotReady
                ? new CollectOutcome(OceanResponse.NO_DATA, "최근 두 발표본이 모두 생산 전이다", null, null)
                : new CollectOutcome("ERROR", lastReason, null, null);
    }

    /**
     * @param firstLast 첫 묶음의 마지막 발효시각 응답 — 확인에 쓴 것을 다시 부르지 않는다.
     *                  <b>이어받는 틱(done &gt; 0)에서는 쓰지 않는다</b> — 그 묶음은 이미 받아 뒀다
     */
    private CollectOutcome fetchIssuance(Source config, String key, Instant fc, List<Integer> zones,
                                         List<List<Integer>> chunks, String firstLast) {
        int limit = chunksPerTick();
        boolean split = limit < chunks.size();
        // 나눠 받지 않으면 예전 그대로 — 한 번에 전부 받아 replace 한다
        if (!split) {
            List<ZoneCell> cells = new ArrayList<>();
            for (int i = 0; i < chunks.size(); i++) {
                CollectOutcome bad = fetchChunk(config, key, fc, chunks, i, i == 0 ? firstLast : null, cells);
                if (bad != null) {
                    return bad;
                }
            }
            int saved = store.replace(level, cells, Instant.now());
            if (saved == 0) {
                return new CollectOutcome(OceanResponse.NO_DATA, "칸 0건", null, null);
            }
            log.info("[ocean] {} — 발표 {} · {}시각 · {}칸 저장 (묶음 {})",
                    source(), fc, LAST_HOUR / STEP_HOURS + 1, saved, chunks.size());
            return CollectOutcome.ok(fc, payload(fc, saved, zones, chunks.size()));
        }

        // ── 나눠 받기 (전국 소해구) ──────────────────────────
        // 진행 지점을 스테이징에서 읽는다. 커서 테이블을 따로 두면 커서와 저장분이 어긋났을 때
        // 빠진 묶음을 모른 채 "완료"로 올린다
        int done = store.stagedChunks(level, fc);
        int end = Math.min(done + limit, chunks.size());
        for (int i = done; i < end; i++) {
            List<ZoneCell> cells = new ArrayList<>();
            CollectOutcome bad = fetchChunk(config, key, fc, chunks, i,
                    i == 0 ? firstLast : null, cells);
            if (bad != null) {
                // 받은 데까지는 남긴다. 다음 틱이 이 묶음부터 다시 시작한다 —
                // 여기서 전부 버리면 일시 오류 하나에 54분이 날아간다
                return bad;
            }
            store.stage(level, fc, i, cells, Instant.now());
        }
        done = store.stagedChunks(level, fc);
        if (done < chunks.size()) {
            log.info("[ocean] {} — 발표 {} 받는 중 {}/{} 묶음", source(), fc, done, chunks.size());
            // ⚠ ok 가 아니다. ok(fc) 로 주면 다음 틱이 "이미 받은 발표본"으로 보고 멈춘다
            return new CollectOutcome("PARTIAL",
                    "%d/%d 묶음".formatted(done, chunks.size()), null, null);
        }

        int saved = store.promote(level, fc, Instant.now());
        if (saved == 0) {
            return new CollectOutcome(OceanResponse.NO_DATA, "칸 0건", null, null);
        }
        log.info("[ocean] {} — 발표 {} · {}시각 · {}칸 저장 (묶음 {}, 나눠 받음)",
                source(), fc, LAST_HOUR / STEP_HOURS + 1, saved, chunks.size());
        return CollectOutcome.ok(fc, payload(fc, saved, zones, chunks.size()));
    }

    /**
     * 묶음 하나의 26개 발효시각을 받아 {@code out} 에 담는다.
     *
     * @param cached 이 묶음의 마지막 발효시각을 이미 받아 뒀으면 그 본문. 아니면 null
     * @return 실패면 그 사유, 성공이면 null. <b>반쪽 발표본을 저장하지 않는다</b> —
     *         슬라이더 중간이 비면 그 시각을 "값 없음"이 아니라 잔잔한 바다로 읽는다
     */
    private CollectOutcome fetchChunk(Source config, String key, Instant fc,
                                      List<List<Integer>> chunks, int i, String cached,
                                      List<ZoneCell> out) {
        for (int h = 0; h <= LAST_HOUR; h += STEP_HOURS) {
            String body = cached != null && h == LAST_HOUR
                    ? cached
                    : fetch(config, key, fc, fc.plus(h, HOURS), chunks.get(i));
            if (!ZoneParser.isData(body)) {
                String reason = ZoneParser.message(body);
                log.warn("[ocean] {} — {} +{}h 실패 (묶음 {}/{}), 이 묶음을 버린다: {}",
                        source(), fc, h, i + 1, chunks.size(), reason);
                return new CollectOutcome("ERROR", "+%dh 실패 — %s".formatted(h, reason), null, null);
            }
            out.addAll(ZoneParser.parse(body, level));
        }
        return null;
    }

    /** @param zones null 이면 전체(Lzone=0) */
    private String fetch(Source config, String key, Instant fc, Instant ef, List<Integer> zones) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("tma_fc", tma(fc));
        params.put("tma_ef", tma(ef));
        params.put("Lzone", zones == null ? "0" : zones.stream().map(String::valueOf).collect(Collectors.joining(",")));
        if (level == ZoneLevel.SMALL) {
            params.put("Szone", "0");
        }
        params.put("disp", "0");
        return client.getText(source(), config, key, params, SOURCE_CHARSET);
    }

    /** 40개씩 묶는다. 전체(null)는 한 묶음 */
    static List<List<Integer>> chunks(List<Integer> zones) {
        if (zones == null) {
            return Collections.singletonList(null);
        }
        List<List<Integer>> out = new ArrayList<>();
        for (int i = 0; i < zones.size(); i += MAX_LZONE) {
            out.add(zones.subList(i, Math.min(zones.size(), i + MAX_LZONE)));
        }
        return out;
    }

    private Map<String, Object> payload(Instant fc, Integer cellCount, List<Integer> zones, int chunkCount) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("level", level.code());
        // ISO 문자열로 넣는다 — jsonb 는 Hibernate 의 Jackson 이 따로 써서 Instant 가 epoch 초가 된다
        payload.put("issuedAt", fc.toString());
        payload.put("timeCount", LAST_HOUR / STEP_HOURS + 1);
        if (cellCount != null) {
            payload.put("cellCount", cellCount);
        }
        if (zones != null) {
            payload.put("zoneCount", zones.size());
            payload.put("requestChunks", chunkCount);
        }
        return payload;
    }

    /** 로그용 해구 목록. 전체를 한 줄에 싣는다 — 재현에 전부 필요하다 */
    private static String describe(List<Integer> zones) {
        if (zones == null) {
            return "전체";
        }
        // 전국이면 1,330개다. 다 찍으면 로그를 읽을 수 없고 진짜 단서가 묻힌다
        List<Integer> head = zones.size() <= 20 ? zones : zones.subList(0, 20);
        return zones.size() + "개 " + head + (zones.size() > 20 ? " …" : "");
    }

    /** 지금 기준 가장 최근 발표시각(00·12UTC). 생산됐는지는 모른다 */
    static Instant latestIssuance(Instant now) {
        ZonedDateTime utc = now.atZone(ZoneOffset.UTC);
        return utc.truncatedTo(ChronoUnit.DAYS).withHour(utc.getHour() >= ISSUE_HOURS ? ISSUE_HOURS : 0).toInstant();
    }

    static String tma(Instant t) {
        return ZoneParser.TMA.format(t.atOffset(ZoneOffset.UTC).toLocalDateTime());
    }
}

package com.floaq.ocean.summary;

import com.floaq.ocean.GeoDistance;
import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.OceanSnapshotService;
import com.floaq.ocean.StationNear;
import com.floaq.ocean.zone.OceanZoneStore;
import com.floaq.ocean.zone.ZoneCell;
import com.floaq.ocean.zone.ZoneLevel;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 해양 상황 요약 — 사전 생성 + 캐시 (계획.md §9.18).
 *
 * <h2>LLM 호출 지점은 {@link #tick()} 하나다</h2>
 * 조회는 절대 LLM 을 부르지 않는다. 부르면 크레딧이 <b>클라이언트 수 × 폴링 주기</b>로 나간다 —
 * 키오스크는 수십 초마다 이 API 를 친다. 조회에서 캐시가 안 맞으면 목 문장으로 물러선다.
 * ({@link #MIN_CALL_GAP} 가 그 위에 한 번 더 상한을 건다 — 2026-09-18 사용자 요구)
 *
 * <h2>기준 좌표는 본선이다 (2026-09-18 변경)</h2>
 * 전에는 서버 기본 위치(app.ocean.coverage) 하나였다. 배가 거기를 벗어나면 요약 속
 * 지점·거리가 이 배와 무관해진다. 이제 마지막으로 요약을 조회한 본선 좌표를 기준으로 만든다.
 *
 * <p>⚠ <b>요약은 여전히 하나다.</b> 선박마다 만들면 LLM 호출이 선박 수만큼 곱해진다.
 * 그래서 다른 배가 조회하면 <b>그 배 좌표로 만든 목</b>을 준다 — 남의 배 기준 문장을
 * 이 배 것처럼 보여주지 않는다. 여러 척을 실제로 운영하게 되면 그때 선박별로 가른다.</p>
 *
 * <p>⚠ 메모리 캐시다. 재기동하면 다음 틱(최대 10분)까지 목 문장이 나간다.
 * 인스턴스마다 따로 만든다 — 다중화하면 인스턴스 수만큼 부른다.</p>
 */
@Slf4j
@Service
public class OceanSummaryService {

    /**
     * 갱신 여부를 <b>확인</b>하는 주기. 실제 호출은 {@link #MIN_CALL_GAP} 가 정한다.
     *
     * 크론을 30분으로 두면 재기동·배 이동 직후 최대 30분을 목으로 버틴다.
     * 확인만 자주 하고 호출은 상한으로 막는다 — 확인은 공짜다(DB 조회).
     */
    private static final String TICK = "0 */10 * * * *";

    /** LLM 호출 최소 간격. 30분마다 1회가 상한이다 — 배가 몇 척이든, 조회가 몇 번이든 (2026-09-18 사용자 요구) */
    private static final Duration MIN_CALL_GAP = Duration.ofMinutes(30);

    /**
     * 이 거리 안이면 "같은 바다"로 보고 만들어 둔 문장을 그대로 쓴다.
     *
     * 근거: 요약이 인용하는 지점 값을 {@code coverage.stationRadiusKm}(기본 30km) 반경으로 자른다.
     * 그 절반을 넘게 움직이면 인용할 관측소 집합이 바뀔 수 있다 — 그때부터 다른 바다다.
     */
    private static final double SAME_SEA_KM = 15;

    /** 이보다 오래 조회가 없으면 본선이 없다고 보고 기본 위치로 돌아간다. 키오스크 폴링(수십 초)보다 훨씬 길다 */
    private static final Duration SHIP_TTL = Duration.ofHours(1);

    /**
     * 추이를 몇 시간 앞으로 보나. 6시간 — 해구 예보 구간이 3시간 단위라 한 칸 건너뛴 값이고,
     * 조업 한 물때가 대략 그 길이다. 더 멀리 보면 예보 자체가 흐려진다
     */
    private static final Duration TREND_AHEAD = Duration.ofHours(6);

    /** coverage 미설정 시 지점 자르기 반경. Coverage 기본값과 같다 */
    private static final double FALLBACK_RADIUS_KM = 30;

    private static final DateTimeFormatter HOUR = DateTimeFormatter.ofPattern("H시").withZone(ZoneId.of("Asia/Seoul"));

    /** 기상청 너울 위험 등급 (ZoneCell.swellLevel) */
    private static final String[] SWELL = {"", "관심", "주의", "경계", "위험"};

    private final OceanSnapshotService snapshots;
    private final OceanSummaryWriter writer;
    private final OceanApiProperties props;
    private final OceanZoneStore zones;
    private final boolean llmEnabled;

    /** 마지막으로 요약을 조회한 본선 좌표. 다음 틱이 이 자리 기준으로 문장을 만든다 */
    private volatile Ship lastSeen;
    private volatile Cached cached;
    /** 마지막 LLM 호출 시각. null 이면 이번 기동에서 아직 안 불렀다 */
    private volatile Instant lastCallAt;

    private record Ship(double lat, double lon, Instant seenAt) {
    }

    private record Cached(double lat, double lon, OceanSummary summary) {
    }

    public OceanSummaryService(OceanSnapshotService snapshots, OceanSummaryWriter writer, OceanApiProperties props,
                               OceanZoneStore zones, @Value("${app.llm.enabled:false}") boolean llmEnabled) {
        this.snapshots = snapshots;
        this.writer = writer;
        this.props = props;
        this.zones = zones;
        this.llmEnabled = llmEnabled;
    }

    /**
     * @param lat 본선 좌표. 주면 지점 값을 그 반경으로 잘라 요약하고, 다음 틱의 기준이 된다.
     *            없으면 서버 기본 위치 기준이라 문장 속 거리가 이 배와 무관하다
     */
    public OceanSummary current(Double lat, Double lon) {
        Instant now = Instant.now();
        boolean ship = lat != null && lon != null;
        if (ship) {
            lastSeen = new Ship(lat, lon, now);
        }
        double[] base = base(lat, lon);
        if (base == null) {
            // 기본 위치도 없고 좌표도 안 왔다 — 자를 기준이 없으니 전국 값 그대로
            return fromFacts(OceanFacts.of(snapshots.findAll()), null, false);
        }
        Cached c = cached;
        if (c != null && GeoDistance.km(base[0], base[1], c.lat(), c.lon()) <= SAME_SEA_KM) {
            return c.summary();
        }
        // 캐시가 다른 바다 것이다. 여기서 LLM 을 부르지 않는다 — 조회마다 크레딧이 나간다
        return fromFacts(facts(base[0], base[1]), base, ship);
    }

    /**
     * 갱신이 필요하고 상한을 지날 때만 LLM 을 부른다.
     *
     * 필요 판단 셋 — ① 캐시 없음 ② 본선이 {@link #SAME_SEA_KM} 넘게 옮김 ③ 문장이 {@link #MIN_CALL_GAP} 넘게 묵음.
     */
    @Scheduled(cron = TICK, scheduler = "collectTaskScheduler")
    public void tick() {
        Instant now = Instant.now();
        Ship s = lastSeen;
        boolean shipFresh = s != null && s.seenAt().isAfter(now.minus(SHIP_TTL));
        double[] base = shipFresh ? new double[]{s.lat(), s.lon()} : base(null, null);
        if (base == null) {
            return;
        }
        Cached c = cached;
        boolean sameSea = c != null && GeoDistance.km(base[0], base[1], c.lat(), c.lon()) <= SAME_SEA_KM;
        boolean stale = c == null || c.summary().generatedAt().isBefore(now.minus(MIN_CALL_GAP));
        if (sameSea && !stale) {
            return;
        }
        boolean canCall = llmEnabled
                && (lastCallAt == null || !now.isBefore(lastCallAt.plus(MIN_CALL_GAP)));
        if (!canCall && sameSea) {
            // 묵었지만 같은 바다다. 목으로 덮으면 멀쩡한 문장이 규칙 나열로 퇴화한다 —
            // 화면은 generatedAt 으로 경과를 보여주므로 그대로 둔다
            return;
        }
        List<String> facts = facts(base[0], base[1]);
        if (facts.isEmpty()) {
            cached = new Cached(base[0], base[1], empty().at(base[0], base[1], shipFresh));
            return;
        }
        OceanSummary made;
        if (canCall) {
            try {
                made = writer.generate(facts);
                lastCallAt = now;
            } catch (Exception e) {
                // LLM 이 실패해도 화면은 돌아야 한다. 목으로 물러서고 그것을 표시한다.
                // lastCallAt 은 올린다 — 실패가 반복되면 10분마다 재시도하며 크레딧·지연만 쌓인다
                lastCallAt = now;
                log.warn("[ocean] 요약 생성 실패 — 목으로 대체한다: {}", e.toString());
                made = writer.mock(facts);
            }
        } else {
            made = writer.mock(facts);
        }
        cached = new Cached(base[0], base[1], made.at(base[0], base[1], shipFresh));
    }

    /**
     * 사람이 눌러 <b>지금</b> 부른다 — 30분 상한(`MIN_CALL_GAP`)을 건너뛴다.
     *
     * <p>왜 필요한가: 평소 경로는 <b>조회가 LLM 을 부르지 않는다.</b> 실제 호출은 10분 틱에서만
     * 일어나고 그 위에 30분 상한이 있어, 키를 새로 넣거나 문장을 다시 보고 싶어도
     * <b>최대 30분을 기다려야 확인이 된다.</b> 시연 준비와 장애 확인에서 그 대기가 문제였다.</p>
     *
     * <p>🔴 <b>누를 때마다 크레딧이 나간다.</b> 그래서 자동 경로에는 절대 붙이지 않는다 —
     * 컨트롤러가 kiosk 키를 확인하고, 화면에서는 사람이 누르는 버튼 하나만 이걸 부른다.</p>
     *
     * <p><b>부른 자리 기준이다.</b> 넘어온 좌표로 사실을 모으고 그 좌표로 캐시를 덮는다 —
     * 누른 사람이 보고 있는 바다의 문장이어야 한다. `lastSeen` 도 같이 옮겨서
     * 다음 틱이 엉뚱한 자리로 되돌리지 않게 한다.</p>
     *
     * @return 실패해도 목으로 물러선 문장을 담아 돌려준다. {@code note} 가 그 이유다 —
     *         <b>조용히 목으로 바꾸면 "버튼이 안 먹는다"</b>가 된다
     */
    public Refreshed refreshNow(double lat, double lon) {
        Instant now = Instant.now();
        lastSeen = new Ship(lat, lon, now);
        List<String> facts = facts(lat, lon);
        if (facts.isEmpty()) {
            OceanSummary s = empty().at(lat, lon, true);
            cached = new Cached(lat, lon, s);
            return new Refreshed(s, "수집된 값이 없어 부를 것이 없습니다");
        }
        if (!llmEnabled) {
            OceanSummary s = writer.mock(facts).at(lat, lon, true);
            cached = new Cached(lat, lon, s);
            return new Refreshed(s, "app.llm.enabled 가 꺼져 있습니다");
        }
        try {
            OceanSummary s = writer.generate(facts).at(lat, lon, true);
            lastCallAt = now;
            cached = new Cached(lat, lon, s);
            return new Refreshed(s, null);
        } catch (Exception e) {
            // 수동 호출은 실패를 삼키지 않는다. 다만 화면은 돌아야 하므로 목을 함께 준다
            lastCallAt = now;
            log.warn("[ocean] 수동 요약 생성 실패 — 목으로 대체한다: {}", e.toString());
            OceanSummary s = writer.mock(facts).at(lat, lon, true);
            cached = new Cached(lat, lon, s);
            return new Refreshed(s, e.toString());
        }
    }

    /** @param note null 이면 진짜 LLM 응답. 아니면 목으로 물러선 이유 */
    public record Refreshed(OceanSummary summary, String note) {
    }

    /** @return 좌표가 없고 기본 위치도 미설정이면 null */
    private double[] base(Double lat, Double lon) {
        if (lat != null && lon != null) {
            return new double[]{lat, lon};
        }
        Coverage coverage = props.coverage();
        return coverage == null ? null : new double[]{coverage.defaultLat(), coverage.defaultLon()};
    }

    private OceanSummary fromFacts(List<String> facts, double[] base, boolean ship) {
        OceanSummary s = facts.isEmpty() ? empty() : writer.mock(facts);
        return base == null ? s : s.at(base[0], base[1], ship);
    }

    private OceanSummary empty() {
        return new OceanSummary("수집된 해양 데이터가 없습니다",
                "아직 받은 값이 없어 상황을 설명할 수 없습니다. 수집이 도는지 확인이 필요합니다.",
                List.of(), Instant.now(), "none", true);
    }

    /** 지점 소스는 전국을 들고 있다 — 자르지 않으면 요약이 200여 지점을 한 줄씩 나열한다 */
    private List<String> facts(double lat, double lon) {
        Coverage coverage = props.coverage();
        double radius = coverage == null ? FALLBACK_RADIUS_KM : coverage.stationRadiusKm();
        List<String> facts = new ArrayList<>(OceanFacts.of(snapshots.findAll(),
                (source, payload) -> StationNear.SOURCES.contains(source)
                        ? StationNear.filter(payload, lat, lon, radius)
                        : payload));
        zoneFact(lat, lon).ifPresent(facts::add);
        zoneTrendFact(lat, lon).ifPresent(facts::add);
        return facts;
    }

    /**
     * 앞으로 어떻게 되나 — <b>요약의 두 번째 문장이 설 자리</b> (2026-09-18 요청).
     *
     * <p>지금까지 넘기던 사실은 <b>전부 "현재"</b>였다. 그래서 문장이 "지금 이렇다"에서 끝났다.
     * 어민이 알고 싶은 것은 "지금 나가면 <b>이따</b> 어떤가"다.</p>
     *
     * <p>{@link #TREND_AHEAD} 뒤 같은 칸의 예보를 지금 값과 나란히 놓는다. 해석은 붙이지 않는다 —
     * "나빠진다"는 말을 우리가 만들면 근거 없는 판단이 된다. <b>두 숫자를 주고 LLM 이 잇게 한다.</b></p>
     *
     * <p>🔴 <b>파고·풍속은 대해구에서만 온다.</b> 소해구(1/6°)는 그 두 값이 전 칸 null 이고
     * 시정·강수·수온만 있다(2026-09-18 실측, `/api/ocean/zones`). 그래서 값마다 층을 갈라 뽑는다 —
     * 한 층만 보면 파고·풍속이 통째로 빠진다(`zoneFact` 가 실제로 그 상태였다).</p>
     *
     * @return 앞뒤 값이 둘 다 있는 항목이 하나도 없으면 empty — 그 줄만 빠진다
     */
    private Optional<String> zoneTrendFact(double lat, double lon) {
        Instant now = Instant.now();
        Instant later = now.plus(TREND_AHEAD);
        List<String> parts = new ArrayList<>();
        try {
            // 파고·풍속 — 대해구에만 있다
            ZoneCell a = zones.cellNow(ZoneLevel.LARGE, lat, lon, now).orElse(null);
            ZoneCell b = zones.cellNow(ZoneLevel.LARGE, lat, lon, later).orElse(null);
            if (a != null && b != null && !a.tmaEf().equals(b.tmaEf())) {
                if (a.waveHeightM() != null && b.waveHeightM() != null) {
                    parts.add("파고 %.1f→%.1fm".formatted(a.waveHeightM(), b.waveHeightM()));
                }
                if (a.windSpeedMs() != null && b.windSpeedMs() != null) {
                    parts.add("풍속 %.1f→%.1fm/s".formatted(a.windSpeedMs(), b.windSpeedMs()));
                }
            }
            // 수온 — 소해구에만 있다
            ZoneCell sa = zones.cellNow(ZoneLevel.SMALL, lat, lon, now).orElse(null);
            ZoneCell sb = zones.cellNow(ZoneLevel.SMALL, lat, lon, later).orElse(null);
            if (sa != null && sb != null && !sa.tmaEf().equals(sb.tmaEf())
                    && sa.waterTempC() != null && sb.waterTempC() != null) {
                parts.add("수온 %.1f→%.1f도".formatted(sa.waterTempC(), sb.waterTempC()));
            }
        } catch (Exception e) {
            // 요약은 부가 정보다. 추이 조회가 죽어도 나머지 줄로 문장을 만든다
            log.warn("[ocean] 해구 추이 조회 실패 — 요약에서 뺀다: {}", e.toString());
            return Optional.empty();
        }
        return parts.isEmpty() ? Optional.empty()
                : Optional.of("%d시간 뒤 해구 예보(지금→그때): %s"
                        .formatted(TREND_AHEAD.toHours(), String.join(" · ", parts)));
    }

    /**
     * 본선이 든 소해구 칸의 예측.
     *
     * 특보는 구역 단위라 좌표로 고를 수 없지만(기상청이 특보구역 경계를 제공하지 않는다, 2026-09-14 회신)
     * <b>해구는 좌표 격자라 본선 칸을 정확히 집는다.</b> 위치 기반 정보는 이 줄이 진다 (2026-09-18 결정).
     *
     * @return 본선이 해구 밖이거나 발표본이 없으면 empty — 요약에서 그 줄만 빠진다
     */
    private Optional<String> zoneFact(double lat, double lon) {
        Instant now = Instant.now();
        ZoneCell c;
        ZoneLevel level = ZoneLevel.SMALL;
        try {
            c = zones.cellNow(ZoneLevel.SMALL, lat, lon, now).orElse(null);
            if (c == null) {
                // 소해구는 전국을 34분에 걸쳐 받는다(V11) — 기동 직후·수집 중이면 본선 칸이 아직 없다.
                // 대해구는 한 번에 전국 1,330칸이라 거의 늘 있다. 2026-09-18 로컬 DB 가 실제로 이 상태였다
                level = ZoneLevel.LARGE;
                c = zones.cellNow(ZoneLevel.LARGE, lat, lon, now).orElse(null);
            }
        } catch (Exception e) {
            // 요약은 부가 정보다. 해구 조회가 죽어도 나머지 줄로 문장을 만든다
            log.warn("[ocean] 본선 해구 조회 실패 — 요약에서 뺀다: {}", e.toString());
            return Optional.empty();
        }
        if (c == null) {
            return Optional.empty();
        }
        List<String> parts = new ArrayList<>();
        // 🔴 소해구를 집었으면 파고·풍속이 **전 칸 null** 이다 (2026-09-18 실측) — 대해구에서 따로 가져온다.
        //    안 그러면 이 줄이 "수온 26.4도" 한 항목으로 끝나고, 정작 조업 판단에 쓰는 두 값이 빠진다.
        ZoneCell wind = c;
        if (level == ZoneLevel.SMALL) {
            wind = zones.cellNow(ZoneLevel.LARGE, lat, lon, now).orElse(null);
        }
        if (wind != null && wind.waveHeightM() != null) {
            parts.add("파고 %.1fm".formatted(wind.waveHeightM()));
        }
        if (wind != null && wind.windSpeedMs() != null) {
            parts.add("풍속 %.1fm/s".formatted(wind.windSpeedMs()));
        }
        if (c.waterTempC() != null) {
            parts.add("수온 %.1f도".formatted(c.waterTempC()));
        }
        if (c.swellLevel() != null && c.swellLevel() >= 1 && c.swellLevel() < SWELL.length) {
            parts.add("너울 " + SWELL[c.swellLevel()]);
        }
        // 칸 크기를 밝힌다 — 대해구(55km)를 "본선 위치"라고만 하면 화면이 실제보다 촘촘한 척을 한다.
        // "예측"도 붙인다 — 관측으로 읽으면 지금 그렇다는 뜻이 된다
        String where = level == ZoneLevel.SMALL ? "본선 위치 소해구(약 18km)" : "본선 위치 대해구(약 55km)";
        return parts.isEmpty() ? Optional.empty()
                : Optional.of("%s 예측(%s 기준): %s".formatted(where, HOUR.format(c.tmaEf()), String.join(" · ", parts)));
    }
}

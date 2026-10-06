package com.floaq.ocean;

import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.ApiResponse;
import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.dto.OceanSourceView;
import com.floaq.ocean.dto.RomsCellView;
import com.floaq.ocean.dto.RomsGridView;
import com.floaq.ocean.dto.RomsPointView;
import com.floaq.ocean.dto.RomsSeriesView;
import com.floaq.ocean.dto.StationObsView;
import com.floaq.ocean.dto.TideSeriesView;
import com.floaq.ocean.dto.ZoneGridView;
import com.floaq.ocean.khoa.TideForecastCollector;
import com.floaq.ocean.roms.OceanRomsStore;
import com.floaq.ocean.roms.RomsLattice;
import com.floaq.ocean.roms.RomsTileService;
import com.floaq.ocean.seaobs.SeaObsCollector;
import com.floaq.ocean.seaobs.SeaObsHistory;
import com.floaq.ocean.seaobs.SeaObsStore;
import com.floaq.ocean.summary.OceanSummary;
import com.floaq.ocean.summary.OceanSummaryService;
import com.floaq.ocean.zone.OceanZoneStore;
import com.floaq.ocean.zone.ZoneLevel;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;

/**
 * 해양 공공데이터 조회. 외부 API 를 요청 시점에 부르지 않음 — 수집기가 미리 받아 둠(§6).
 *
 * 값이 없을 때를 셋으로 가른다. 뭉치면 화면이 대응을 못 고른다.
 *   200 + 값                            정상
 *   200 + null OUTSIDE_AREA             본선 주변 타일을 아직 못 받았다. 수집을 넘겼으니 곧 들어온다 — **오류가 아니다**
 *   200 + null OUTSIDE_AREA_NOT_MOVED   못 받았는데 kiosk 키가 없어 수집을 부르지 않았다 — 기다려도 안 들어온다
 *   503                                 키는 맞는데 ROMS 수집이 꺼져 있거나 인증키가 없다 — 사람이 봐야 한다
 *
 * 선박 여러 척 (2026-09-15) — 수집 해역 하나를 옮기지 않는다. ROMS 는 조회 좌표의 0.25° 타일을 받고(RomsTileService),
 * 지점 소스는 전국을 저장해 조회 좌표로 자른다(StationNear). 메시지 이름(OUTSIDE_AREA…)은 kiosk 호환으로 유지한다.
 */
@Tag(name = "ocean", description = "해양 공공데이터")
@RestController
@RequestMapping("/api/ocean")
@RequiredArgsConstructor
public class OceanController {

    /** 설정이 없을 때 지점 반경 — app.ocean.coverage.station-radius-km 기본값과 같다 */
    private static final double DEFAULT_STATION_RADIUS_KM = 30;

    private final OceanApiProperties props;
    private final OceanSnapshotService snapshots;
    private final OceanRomsStore romsStore;
    private final RomsTileService tiles;
    private final OceanSummaryService summaries;
    private final OceanZoneStore zoneStore;
    private final SeaObsStore obsStore;
    private final KioskKey kioskKey;

    /**
     * 소스별 최신값.
     *
     * 지점 소스(sea-obs · fishing-ground)는 전국이 저장돼 있어 조회 좌표 반경으로 잘라 거리를 붙인다.
     * 좌표가 없으면 기본 위치(app.ocean.coverage)로 자른다 — 그대로 내리면 200여 지점이 매 폴링에 실린다.
     */
    @GetMapping("/sources")
    @Operation(summary = "소스별 최신값 + 경과 시간 · lat·lon 을 주면 지점 소스를 그 좌표 반경으로 자른다")
    public ApiResponse<List<OceanSourceView>> sources(@RequestParam(required = false) Double lat,
                                                      @RequestParam(required = false) Double lon) {
        Instant now = Instant.now();
        Coverage coverage = props.coverage();
        boolean hasPoint = lat != null && lon != null;
        double radius = coverage == null ? DEFAULT_STATION_RADIUS_KM : coverage.stationRadiusKm();
        List<OceanSourceView> views = snapshots.findAll().stream()
                .map(s -> {
                    var config = props.sources().get(s.getSource());
                    OceanSourceView view = OceanSourceView.of(s,
                            config == null ? null : config.kind(),
                            config == null ? 0 : config.intervalSec(),
                            now);
                    if (!StationNear.SOURCES.contains(s.getSource())) {
                        return view;
                    }
                    if (hasPoint) {
                        return view.withPayload(StationNear.filter(view.payload(), lat, lon, radius));
                    }
                    return coverage == null ? view : view.withPayload(StationNear.filter(
                            view.payload(), coverage.defaultLat(), coverage.defaultLon(), radius));
                })
                .sorted(Comparator.comparing(OceanSourceView::source))
                .toList();
        return ApiResponse.ok(views);
    }

    /**
     * 해양 상황 요약. 사전 생성된 것을 그대로 준다 (§9.18).
     *
     * 조회 때 LLM 을 부르지 않는다 — 지연이 화면에 드러나고 크레딧은 호출 횟수로 나간다.
     * 이 API 는 키오스크가 수십 초마다 친다. 실제 호출은 30분에 1회가 상한이다(OceanSummaryService).
     *
     * `mock: true` 면 LLM 이 꺼져 있거나 실패해 규칙으로 만든 문장이다. 화면이 그것을 밝혀야 한다.
     * `shipBased: false` 면 기본 위치 기준이라 문장 속 지점·거리가 그 배와 무관하다 — 이것도 밝혀야 한다.
     */
    @GetMapping("/summary")
    @Operation(summary = "해양 상황 요약 (사전 생성 · LLM 꺼져 있으면 목 · lat·lon 을 주면 본선 기준)")
    public ApiResponse<OceanSummary> summary(@RequestParam(required = false) Double lat,
                                             @RequestParam(required = false) Double lon) {
        return ApiResponse.ok(summaries.current(lat, lon));
    }

    /**
     * 요약을 <b>지금</b> 다시 만든다 — 사람이 버튼을 눌렀을 때만 (2026-09-18 요청).
     *
     * <p>평소 경로(`GET /summary`)는 <b>조회가 LLM 을 부르지 않는다.</b> 실제 호출은 10분 틱에서만
     * 일어나고 그 위에 30분 상한이 있다. 그래서 키를 새로 넣어도 최대 30분을 기다려야 확인이 됐다.
     * 이 엔드포인트가 그 대기를 건너뛴다.</p>
     *
     * <p>🔴 <b>kiosk 키가 맞을 때만 부른다.</b> 누를 때마다 크레딧이 나가므로, 공개 URL 에서
     * 아무나 눌러 예산을 태우는 길을 열지 않는다 — 해역 이동과 같은 기준이다(api.md §1.1).
     * 키가 없으면 지금 가진 문장을 그대로 주고 `NO_KEY` 라고 밝힌다. 조용히 무시하지 않는다.</p>
     *
     * <p><b>좌표는 필수다.</b> 부른 자리 기준으로 만든다 — 기본 위치로 만들면 누른 사람이
     * 보고 있는 바다와 다른 문장이 온다.</p>
     *
     * @return `message` 가 `OK` 면 진짜 LLM 응답이다. 아니면 목으로 물러선 이유가 담긴다
     */
    @PostMapping("/summary/refresh")
    @Operation(summary = "해양 요약 즉시 재생성 (kiosk 키 필요 · 호출 좌표 기준 · 누를 때마다 크레딧 소모)")
    public ApiResponse<OceanSummary> refreshSummary(
            @RequestParam double lat, @RequestParam double lon,
            @RequestHeader(value = KioskKey.HEADER, required = false) String presented) {
        if (!kioskKey.matches(presented)) {
            return ApiResponse.ok("NO_KEY", summaries.current(lat, lon));
        }
        OceanSummaryService.Refreshed r = summaries.refreshNow(lat, lon);
        return r.note() == null ? ApiResponse.ok(r.summary()) : ApiResponse.ok(r.note(), r.summary());
    }

    /**
     * 본선 격자의 시각별 예측. 시계열 차트용.
     *
     * 8일치(178시각)를 다 주지 않는다 — 화면이 읽을 수 있는 창만 준다.
     * 48시간이면 조석 반일주기가 네 번 들어와 주기가 눈에 보인다.
     */
    @GetMapping("/series")
    @Operation(summary = "본선 격자의 시각별 예측 (기본 48시간) · 타일 수집 유발은 kiosk 키가 맞을 때만")
    public ApiResponse<RomsSeriesView> series(
            @RequestParam double lat, @RequestParam double lon,
            @RequestParam(defaultValue = "48") int hours,
            @RequestHeader(name = KioskKey.HEADER, required = false) String key) {
        Interest interest = noteInterest(lat, lon, key);
        if (!tiles.covers(lat, lon)) {
            return notCovered(interest);
        }
        int window = Math.max(6, Math.min(192, hours));
        var sample = romsStore.sample(lat, lon, Instant.now())
                .filter(s -> s.distanceKm() <= OceanRomsStore.NEIGHBOR_RADIUS_KM);
        if (sample.isEmpty()) {
            return notCovered(interest);
        }
        var grid = sample.get().grid();
        var points = romsStore.series(grid.lat(), grid.lon(), Instant.now(), window).stream()
                .map(g -> new RomsSeriesView.Point(g.predcDt(), g.crdirDeg(), g.crspMs(), g.wtemC()))
                .toList();
        if (points.isEmpty()) {
            return notCovered(interest);
        }
        return ApiResponse.ok(new RomsSeriesView(
                grid.lat(), grid.lon(), sample.get().distanceKm(), points));
    }

    /**
     * 본선 주변 격자. 지도 구역 표시용.
     *
     * /current 와 나눈 이유: 저쪽은 표류 추정 입력(점 하나)이고 이쪽은 화면이다.
     * 한 응답에 섞으면 표류 계산이 화면 사정에 끌려다닌다.
     */
    @GetMapping("/grid")
    @Operation(summary = "본선 칸 + 이웃 (rings=1 이면 3x3, 크게 주면 등치선용) · at 으로 예측 시각 선택 · 타일 수집 유발은 kiosk 키가 맞을 때만")
    public ApiResponse<RomsGridView> grid(
            @RequestParam double lat, @RequestParam double lon,
            @RequestParam(defaultValue = "1") int rings,
            @RequestParam(required = false) Instant at,
            @RequestHeader(name = KioskKey.HEADER, required = false) String key) {
        Interest interest = noteInterest(lat, lon, key);
        if (!tiles.covers(lat, lon)) {
            return notCovered(interest);
        }
        RomsLattice lattice = romsStore.lattice();
        // 상한 12 = 25x25 칸. 본선 타일(0.25° ≈ 9x8칸)과 이웃을 넘으면 받지 않은 빈 칸이다
        int r = Math.max(1, Math.min(12, rings));
        Instant now = Instant.now();
        List<Instant> times = romsStore.forecastTimes(now);
        var cells = romsStore.neighborhood(lat, lon, frameAt(at, now, times), lattice, r);
        if (lattice == null || cells.isEmpty()) {
            return notCovered(interest);
        }
        return ApiResponse.ok(new RomsGridView(
                cells.getFirst().predcDt(), lattice.latStep(), lattice.lonStep(),
                cells.stream().map(RomsCellView::of).toList(),
                times, romsStore.range(lat, lon, now, lattice, r)));
    }

    /**
     * 슬라이더가 고른 시각을 받을 수 있는 범위로 물린다.
     *
     * 과거는 지금으로 — 지난 예측을 "그 시각 값"으로 보여주지 않는다(/current 와 같은 규칙).
     * 마지막 예측보다 뒤면 마지막으로 — 그대로 두면 격자가 비어 "해역 밖"으로 잘못 답한다.
     */
    static Instant frameAt(Instant at, Instant now, List<Instant> times) {
        if (at == null || at.isBefore(now)) {
            return now;
        }
        return !times.isEmpty() && at.isAfter(times.getLast()) ? times.getLast() : at;
    }

    @GetMapping("/current")
    @Operation(summary = "좌표 최근접 ROMS 격자 + 이웃 산포 (at 이후 가장 이른 예측 · at 없으면 지금 · 보관 24시간 · 타일 수집 유발은 kiosk 키가 맞을 때만)")
    public ApiResponse<RomsPointView> current(@RequestParam double lat, @RequestParam double lon,
                                              @RequestParam(required = false) Instant at,
                                              @RequestHeader(name = KioskKey.HEADER, required = false) String key) {
        Instant now = Instant.now();
        if (at != null) {
            if (!OceanRetention.covers(at, now)) {
                throw new BusinessException(ErrorCode.OCEAN_OUT_OF_RETENTION);
            }
            // 지난 사고의 재계산이다. 수집을 부르지 않는다 — 지금 배 주변이 아니라 사고 지점 타일을 받게 된다.
            // 그때 받았던 타일이 지금과 다를 수 있어 타일 판정으로 자르지 않는다 — withinHistoryGap 이 대신 거른다
            return romsStore.sample(lat, lon, at)
                    // 🔴 거리 제한이 없으면 400km 떨어진 격자를 이 좌표의 값처럼 돌려준다.
                    //    nearest 는 "가장 가까운 것"이지 "가까운 것"이 아니다
                    .filter(sample -> sample.distanceKm() <= OceanRomsStore.NEIGHBOR_RADIUS_KM)
                    .filter(sample -> withinHistoryGap(sample.grid().predcDt(), at))
                    .map(sample -> ApiResponse.ok(RomsPointView.of(sample)))
                    .orElseGet(this::noHistory);
        }
        // 조회가 곧 관심 표명이다. 본선 주변 타일을 받게 넘기고, 이번 응답은 지금 가진 것으로 답한다
        Interest interest = noteInterest(lat, lon, key);
        if (!tiles.covers(lat, lon)) {
            return notCovered(interest);
        }
        return romsStore.sample(lat, lon, now)
                .filter(sample -> sample.distanceKm() <= OceanRomsStore.NEIGHBOR_RADIUS_KM)
                .map(sample -> ApiResponse.ok(RomsPointView.of(sample)))
                .orElseGet(() -> notCovered(interest));
    }

    /** 조회가 수집을 부를 수 있었나 — 값이 없을 때 이유를 가른다 */
    enum Interest {
        /** 키가 맞고 ROMS 수집이 켜져 있다 — 넘겼으니 곧 들어온다 */
        COLLECTING,
        /** 키가 없거나 틀리다 — 수집을 부르지 않았다 */
        NO_KEY,
        /** 키는 맞는데 ROMS 수집이 꺼져 있거나 인증키가 없다 — 기다려도 안 들어온다 */
        COLLECTION_OFF
    }

    /**
     * 조회가 곧 관심 표명 — 본선 주변 타일을 받게 한다. kiosk 키가 맞을 때만 (결정 2026-09-15, api.md §1.1 · §5.3).
     *
     * 키가 없어도 조회는 계속한다 — 막을 것은 수집 유발뿐이다(밖에서 먼 좌표를 돌려 부르면 쿼터를 태운다).
     */
    private Interest noteInterest(double lat, double lon, String presented) {
        if (!kioskKey.matches(presented)) {
            return Interest.NO_KEY;
        }
        return tiles.request(lat, lon) ? Interest.COLLECTING : Interest.COLLECTION_OFF;
    }

    /**
     * 본선 근처 값이 없을 때의 응답.
     *
     * 타일을 아직 못 받은 것은 **정상 상태**다 — 배가 새 바다로 들어갈 때 늘 지나가는 구간이다.
     * 그걸 503 으로 주면 브라우저 콘솔이 오류로 찍히고 화면도 장애와 구분하지 못한다.
     *
     * 이전에는 "예측이 하나도 없으면 503"이었다. 타일 캐시에서는 기동 직후·첫 배 전에 받은 타일이 0개인 게 정상이라
     * 그 판정이 키 설정 문제(NO_KEY)까지 "수집 장애"로 덮었다(2026-09-15 로컬 실측).
     */
    static <T> ApiResponse<T> notCovered(Interest interest) {
        return switch (interest) {
            case COLLECTING -> new ApiResponse<>(true, OUTSIDE_AREA, null);
            case NO_KEY -> new ApiResponse<>(true, OUTSIDE_AREA_NOT_MOVED, null);
            case COLLECTION_OFF -> throw new BusinessException(ErrorCode.OCEAN_SOURCE_UNAVAILABLE);
        };
    }

    /**
     * 과거 시각 조회에서 받은 예측 시각이 요청 시각에 붙어 있나.
     *
     * "at 이후 가장 이른 예측"을 고르므로, 그 시각에 그 타일을 안 받았으면 몇 시간 뒤 격자가 잡힌다 —
     * 그 값을 사고 시각의 유속으로 쓰면 틀린다. ROMS 가 1시간 간격이라 1시간을 넘으면 그 시각 값이 아니다.
     */
    static boolean withinHistoryGap(Instant predcDt, Instant at) {
        return !predcDt.isAfter(at.plus(HISTORY_GAP));
    }

    private static final Duration HISTORY_GAP = Duration.ofHours(1);

    /** 보관 기간 안이지만 그 시각·좌표에 격자가 없다 — 그때 그 타일을 받지 않았다. 오류가 아니라 "없음" */
    public static final String NO_HISTORY = "NO_HISTORY";

    private <T> ApiResponse<T> noHistory() {
        return new ApiResponse<>(true, NO_HISTORY, null);
    }

    /**
     * 기상청 해양 관측 지점 — 시각 at 기준 지점별 최근 관측(보관 24시간).
     *
     * 표류 추정의 바람 입력. 요청 좌표 반경으로 고른다 — 사고 지점이 기준이다.
     * 관측이 at 보다 최대 90분 이르다(SeaObsHistory.WINDOW) — observedAt 을 함께 싣는다.
     */
    @GetMapping("/observations")
    @Operation(summary = "기상청 해양 관측 지점 (at 기준 최근 관측 · 반경 radiusKm · 보관 24시간)")
    public ApiResponse<List<StationObsView>> observations(
            @RequestParam double lat, @RequestParam double lon,
            @RequestParam(required = false) Instant at,
            @RequestParam(defaultValue = "30") double radiusKm) {
        Instant now = Instant.now();
        if (at != null && !OceanRetention.covers(at, now)) {
            throw new BusinessException(ErrorCode.OCEAN_OUT_OF_RETENTION);
        }
        var latest = obsStore.latestAt(SeaObsCollector.SOURCE, at == null ? now : at, SeaObsHistory.WINDOW);
        return ApiResponse.ok(SeaObsHistory.near(latest, lat, lon, radiusKm).stream()
                .map(StationObsView::of).toList());
    }

    /**
     * 가장 가까운 조석예보 지점의 조위 곡선 + 만조·간조 (2026-09-16).
     *
     * `/sources` 의 tide-forecast payload 는 지점마다 **지금 값 한 줄**이라 곡선을 못 그린다.
     * 여기는 지점 하나의 시계열을 준다 — 용도가 "지금 조위"가 아니라 "언제 만조"다.
     *
     * 수집을 부르지 않는다 — 조석예보는 전국을 하루 한 번 받아 둔다(ROMS 타일과 다르다).
     * 근처에 지점이 없으면 NO_STATION 으로 null — 오류가 아니다. 먼바다에서는 늘 그렇다.
     */
    @GetMapping("/tide")
    @Operation(summary = "가장 가까운 조석예보 지점의 조위 곡선 + 만조·간조 (기본 48시간 · 반경 밖이면 NO_STATION)")
    public ApiResponse<TideSeriesView> tide(
            @RequestParam double lat, @RequestParam double lon,
            @RequestParam(defaultValue = "48") int hours,
            @RequestParam(required = false) Double radiusKm) {
        Instant now = Instant.now();
        // 48시간이면 반일주기가 네 번 — 만조·간조가 각 네 번 들어와 "다음"이 늘 있다.
        // 예보를 하루치(24행)씩 받으므로 72시간을 넘겨 물어도 그 이상은 없다
        Duration window = Duration.ofHours(Math.max(6, Math.min(72, hours)));
        var stations = obsStore.forecastFrom(TideForecastCollector.SOURCE, now, window);
        var near = SeaObsHistory.near(stations, lat, lon,
                radiusKm == null ? TIDE_STATION_RADIUS_KM : radiusKm);
        if (near.isEmpty()) {
            return new ApiResponse<>(true, NO_STATION, null);
        }
        var closest = near.getFirst();
        var series = obsStore.forecastSeries(TideForecastCollector.SOURCE, closest.station().stn(), now, window);
        if (series.isEmpty()) {
            return new ApiResponse<>(true, NO_STATION, null);
        }
        return ApiResponse.ok(TideSeriesView.of(closest, series));
    }

    /**
     * 조석예보 지점 반경 기본값.
     *
     * 지점 소스 기본 30km 보다 넓다 — 조석예보는 전국 166곳(연안)뿐이라 30km 로 자르면 먼바다에서 늘 빈다.
     * 멀면 값이 틀리지만(만마다 만조 시각이 30분씩 다르다) 화면이 지점명·거리를 함께 내 그 한계를 드러낸다.
     */
    private static final double TIDE_STATION_RADIUS_KM = 60;

    /** 반경 안에 조석예보 지점이 없다. 오류가 아니라 "없음" — 먼바다에서는 늘 그렇다 */
    public static final String NO_STATION = "NO_STATION";

    /**
     * 기상청 해구별 예측 한 프레임 — 해양포털 방식의 전국 층.
     *
     * level=large 전국 대해구(0.5°) · level=small 관심 선박 주변 소해구(1/6°, 수온·시정·너울 포함).
     * 조회가 수집을 부르지 않는다 — 수집기가 발표본(하루 2회)을 미리 받아 둔다.
     * 발표본이 하나도 없으면 503 — "해구가 없다"와 "수집이 안 돌고 있다"를 가른다.
     */
    @GetMapping("/zones")
    @Operation(summary = "기상청 해구별 예측 (level=large|small · at 으로 발효시각 선택)")
    public ApiResponse<ZoneGridView> zones(
            @RequestParam(defaultValue = "large") String level,
            @RequestParam(required = false) Instant at) {
        ZoneLevel zoneLevel = ZoneLevel.parse(level);
        if (zoneLevel == null) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        Instant now = Instant.now();
        if (at != null && !OceanRetention.covers(at, now)) {
            throw new BusinessException(ErrorCode.OCEAN_OUT_OF_RETENTION);
        }
        // 프레임은 24시간 보관분까지에서 고른다 — 사고 시각 재계산. 슬라이더 눈금·색 기준은 최신 발표본만
        List<Instant> history = zoneStore.allTimes(zoneLevel);
        if (history.isEmpty()) {
            throw new BusinessException(ErrorCode.OCEAN_SOURCE_UNAVAILABLE);
        }
        Instant validAt = zoneFrame(at, now, history);
        // 받는 중인 다음 발표본 — 화면이 "옛 값을 보고 있다"를 알 수 있게.
        // cells 는 여전히 완결된 직전 발표본이다(스테이징은 ocean_zone 에 올라오지 않는다)
        Instant nextIssuance = zoneStore.pendingIssuance(zoneLevel).orElse(null);
        return ApiResponse.ok(ZoneGridView.of(zoneLevel, validAt,
                zoneStore.cells(zoneLevel, validAt), zoneStore.times(zoneLevel), zoneStore.range(zoneLevel),
                nextIssuance));
    }

    /**
     * 3시간 간격 예측에서 고를 발효시각 — **그 시각을 덮는 구간의 시작**(그 시각 이하 가장 늦은 것).
     *
     * ROMS(/grid)는 "이후 가장 이른"을 고르는데 여기는 반대다. 1시간 간격 ROMS 는 차이가 작지만,
     * 3시간 간격에서 "이후"를 고르면 지금 11시에 14시 예측을 "지금"으로 보여준다.
     * 범위 밖이면 양끝으로 물린다.
     */
    static Instant zoneFrame(Instant at, Instant now, List<Instant> times) {
        Instant target = at == null ? now : at;
        Instant pick = times.getFirst();
        for (Instant t : times) {
            if (t.isAfter(target)) {
                break;
            }
            pick = t;
        }
        return pick;
    }

    /** 본선 주변 타일을 아직 못 받았다는 표식 — 수집을 넘겼다 */
    public static final String OUTSIDE_AREA = "OUTSIDE_AREA";

    /**
     * 못 받았는데 kiosk 키가 없어 수집을 부르지 않았다.
     *
     * OUTSIDE_AREA 로 주면 화면이 "받는 중"을 거짓으로 띄우고 10초마다 영원히 다시 묻는다.
     */
    public static final String OUTSIDE_AREA_NOT_MOVED = "OUTSIDE_AREA_NOT_MOVED";
}

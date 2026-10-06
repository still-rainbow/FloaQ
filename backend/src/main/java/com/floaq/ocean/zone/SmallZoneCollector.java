package com.floaq.ocean.zone;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Coverage;
import com.floaq.ocean.client.OceanApiClient;
import com.floaq.ocean.roms.RomsTile;
import com.floaq.ocean.roms.RomsTileStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * 소해구(1/6°). 수온·시정·강수·너울이 여기만 있다.
 *
 * <p><b>기본은 전국</b>(2026-09-17). {@code app.ocean.small-zone-nationwide=false} 면
 * 옛 방식(본선 주변 대해구 40개)으로 돌아간다 — 쿼터·시간 문제가 생겼을 때 한 줄로 되돌리기 위해서다.
 * 전국으로 바꾼 이유는 <b>배가 1° 칸을 옮길 때마다 26회를 다시 받던 것</b>이 사라지고,
 * 호출량이 배의 움직임·척수와 무관한 고정값(1,768회/일 · 한도의 9%)이 되기 때문이다.</p>
 *
 * 전국 소해구 기각 — 발표본당 884회 × 1.4초 ≈ 20분(2026-09-14 실측으로 환산). 수집 틱이 그동안 멈춘다.
 *
 * ⚠ <b>대해구처럼 {@code Lzone=0}(전체) 으로 한 번에 받는 길은 없다</b> — 2026-09-17 실호출로 확인.
 *   {@code marine_small_zone.php} 는 HTTP 200 에 "대해구번호를 입력하세요." 한 줄을 준다.
 *   즉 전국은 반드시 40개씩 34묶음으로 나눠야 하고, 위 884회는 줄일 수 없는 하한이다.
 *   (막는 것은 쿼터가 아니다 — 1,768회/일은 API허브 한도 20,000건의 9% 다. 시간이 막는다.)
 *
 * <b>묶음을 40보다 작게 쪼개면 더 나빠진다</b> — 2026-09-17 실측(부산 앞 기준):
 * <pre>
 *   Lzone 1개   0.75초   2.6KB    9행     전국 34,580회/발표본 → 한도 20,000 초과
 *   Lzone 10개  1.23초  21.9KB   90행     전국  3,458회/발표본
 *   Lzone 40개  3.69초  86.0KB  360행     전국    884회/발표본  ← 현재
 * </pre>
 * 호출당 고정 오버헤드가 0.7초쯤이라 <b>40배 데이터를 5배 시간에 받는다.</b>
 * 40은 명세 상한이자 실제로도 가장 싼 묶음이다.
 *
 * ⚠ 위 3.69초는 2026-09-14 측정치(1.38초)의 2.7배다. 전국 소요가 20분이 아니라 <b>약 54분</b>이라는 뜻 —
 *   한 틱에 몰아 받는 한 이 값은 신뢰 구간이 아니라 <b>변동하는 장애 시간</b>이다.
 *
 * 선박 여러 척 (2026-09-15) — 최근 24시간 조회된 ROMS 타일을 1° 칸으로 묶어, 칸 중심마다 가까운 대해구 40개의 합집합을 받는다.
 *   40개 ≈ 4°×4.5°(부산 중심 2026-09-14 실측)라 같은 1° 칸의 배는 중심 하나로 덮이고, 칸을 묶어 조회 수를 줄인다.
 *   합집합이 40개를 넘으면 ZoneCollector 가 나눠 묻는다 — 발표본당 26회 × 묶음 수.
 *   관심 선박이 없으면 기본 위치(app.ocean.coverage) — 화면·요약이 비지 않게.
 *
 * ⚠ 선단이 새 1° 칸으로 들어가 합집합이 바뀌면 같은 발표본도 다시 받는다.
 */
@Component
@Order(2)
public class SmallZoneCollector extends ZoneCollector {

    public static final String SOURCE = "marine-zone-small";

    /** 중심 하나에서 고를 대해구 수. Lzone 한 번의 상한과 같게 잡았다 — 한 척이면 한 묶음 */
    static final int NEAR_COUNT = 40;

    /** 관심 타일을 묶는 칸(도). 40개 범위(약 4°)보다 충분히 작아 칸 안 어느 배도 덮인다 */
    static final double GROUP_DEG = 1.0;

    private final RomsTileStore tiles;
    private final OceanApiProperties props;

    /**
     * 한 틱에 받을 묶음 수.
     *
     * <p><b>묶음 하나가 26회다</b>(발효시각 +0~75h, 3시간 간격). 전국은 34묶음 × 26 = 884회이고,
     * 한 틱에 몰면 약 54분 동안 뒤 소스가 멈춘다(수집 틱이 소스를 순서대로 돈다).</p>
     *
     * <p><b>1로 잡은 근거 — 2가 더 나쁘다.</b> 2묶음이면 52회 ≈ 78초라 <b>틱 간격(60초)을 넘긴다.</b>
     * 그러면 다음 틱이 리스에 막혀 건너뛰고 결국 2분에 2묶음 — 처리량은 1묶음/분으로 같은데
     * 블로킹만 2배가 된다. 실측으로 확인했다(2026-09-17: 4/34 → 6/34 가 114초).</p>
     *
     * <p>1묶음 = 26회 ≈ 39초. 34틱 ≈ <b>34분</b>에 전국이 찬다 — 발표 간격 12시간에 한참 못 미친다.</p>
     */
    static final int CHUNKS_PER_TICK = 1;

    private final boolean nationwide;

    public SmallZoneCollector(OceanApiClient client, OceanZoneStore store,
                              RomsTileStore tiles, OceanApiProperties props,
                              @Value("${app.ocean.small-zone-nationwide:true}") boolean nationwide) {
        super(client, store, ZoneLevel.SMALL);
        this.tiles = tiles;
        this.props = props;
        this.nationwide = nationwide;
    }

    /** 전국일 때만 나눠 받는다. 본선 주변(40개)은 한 묶음이라 나눌 것이 없다 */
    @Override
    protected int chunksPerTick() {
        return nationwide ? CHUNKS_PER_TICK : Integer.MAX_VALUE;
    }

    @Override
    public String source() {
        return SOURCE;
    }

    @Override
    protected List<Integer> targetZones() {
        if (nationwide) {
            // 대해구 발표본에 있는 번호 전부. Lzone=0(전체)은 소해구에서 거부된다 —
            // "대해구번호를 입력하세요."(2026-09-17 실호출). 그래서 번호를 다 적어 40개씩 나눠 묻는다
            return store.zones(ZoneLevel.LARGE);
        }
        Set<Integer> zones = new TreeSet<>();
        for (double[] center : centers(tiles.active(RomsTileStore.ACTIVE_WINDOW), props.coverage())) {
            zones.addAll(store.largeZonesNear(center[0], center[1], NEAR_COUNT));
        }
        return new ArrayList<>(zones);
    }

    /**
     * 1° 칸 중심 목록 [위도, 경도].
     *
     * @return 관심 타일이 없으면 기본 위치 하나, 기본 위치도 없으면 빈 목록
     */
    static List<double[]> centers(List<RomsTile> active, Coverage fallback) {
        Map<String, double[]> groups = new LinkedHashMap<>();
        for (RomsTile tile : active) {
            double lat = Math.floor(tile.centerLat() / GROUP_DEG) * GROUP_DEG + GROUP_DEG / 2;
            double lon = Math.floor(tile.centerLon() / GROUP_DEG) * GROUP_DEG + GROUP_DEG / 2;
            groups.putIfAbsent(lat + "," + lon, new double[]{lat, lon});
        }
        if (groups.isEmpty()) {
            return fallback == null ? List.of() : List.<double[]>of(new double[]{fallback.defaultLat(), fallback.defaultLon()});
        }
        return new ArrayList<>(groups.values());
    }
}

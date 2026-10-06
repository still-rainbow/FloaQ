package com.floaq.ocean.roms;

import com.floaq.ocean.OceanApiProperties;
import com.floaq.ocean.OceanApiProperties.Source;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 조회 쪽 타일 판단 — "본선 근처 값을 갖고 있나"와 "받게 하기".
 *
 * 조회가 곧 관심 표명이다. kiosk 키가 맞는 조회만 {@link #request} 를 부른다(OceanController).
 * 수집은 요청 스레드에서 하지 않는다 — 타일 하나가 약 24페이지(추정)라 응답이 그만큼 늦어진다.
 */
@Slf4j
@Service
public class RomsTileService {

    /**
     * 조회 한 번이 받게 하는 범위 — 본선 ±0.1° (위도 약 11km · 경도 약 9km, 격자 약 3칸).
     * 반폭이 타일 절반(0.125°)보다 작아 축마다 타일 1~2개 → 1~4개(약 24~96페이지, 추정).
     * 기각 ±0.15°(옛 0.3° 해역과 같은 문맥) — 폭 0.3° 가 타일보다 커 늘 4~9개(96~216페이지)
     */
    static final double DEMAND_HALF_DEG = 0.1;

    /** 격자 간격을 아직 모를 때(첫 수집 전) 이웃 한 칸 폭. 실측 위도 0.02864° · 경도 0.03197° 중 큰 값 */
    static final double FALLBACK_STEP_DEG = 0.032;

    private final RomsTileStore tiles;
    private final OceanRomsStore store;
    private final RomsCollector collector;
    private final OceanApiProperties props;
    private final TaskScheduler executor;

    /**
     * 이 인스턴스가 이미 넘긴 타일. 60초 폴링마다 같은 작업을 큐에 쌓지 않게 —
     * 중복 수집 방지 자체는 DB 리스(RomsTileStore.claim)가 한다. 이건 인스턴스 안의 절약일 뿐이다.
     */
    private final Set<RomsTile> queued = ConcurrentHashMap.newKeySet();

    // Lombok 생성자 기각 — @Qualifier 가 생성자 파라미터로 복사되지 않는다(lombok.config 없음)
    public RomsTileService(RomsTileStore tiles, OceanRomsStore store, RomsCollector collector,
                           OceanApiProperties props,
                           @Qualifier("collectTaskScheduler") TaskScheduler executor) {
        this.tiles = tiles;
        this.store = store;
        this.collector = collector;
        this.props = props;
        this.executor = executor;
    }

    /**
     * 본선의 최근접 격자와 이웃 한 칸이 걸치는 타일을 **전부** 받았나.
     *
     * 거리(최근접 5km)로 판정하지 않는다 — 해역 밖 본선에 옛 수집 가장자리 칸이 OK 로 나갔다(2026-09-15 실측).
     * 받은 타일 안의 육지 결측 칸은 통과하고 최근접 5km 가 메운다.
     */
    public boolean covers(double lat, double lon) {
        RomsLattice lattice = store.lattice();
        double halfLat = lattice == null ? FALLBACK_STEP_DEG : lattice.latStep();
        double halfLon = lattice == null ? FALLBACK_STEP_DEG : lattice.lonStep();
        List<RomsTile> needed = RomsTile.covering(lat, lon, halfLat, halfLon);
        return tiles.collectedAmong(needed).containsAll(needed);
    }

    /**
     * 본선 주변 타일에 관심을 찍고, 받을 필요가 있으면 수집 스레드로 넘긴다.
     *
     * @return ROMS 수집이 켜져 있고 인증키가 있어 받을 수 있나. false 면 기다려도 안 들어온다 — 호출부가 503 으로 드러낸다
     */
    public boolean request(double lat, double lon) {
        Source config = props.sources().get(RomsCollector.SOURCE);
        String key = config == null ? null : props.keyFor(config);
        if (config == null || !config.enabled() || key == null || key.isBlank()) {
            // 수집이 꺼져 있다. 관심만 찍어 두면 켜는 순간 하루치 활성 타일을 한꺼번에 받는다 — 찍지 않는다
            return false;
        }
        List<RomsTile> demand = RomsTile.covering(lat, lon, DEMAND_HALF_DEG, DEMAND_HALF_DEG);
        tiles.touch(demand);
        for (RomsTile tile : demand) {
            if (!queued.add(tile)) {
                continue;
            }
            executor.schedule(() -> {
                try {
                    collector.collectTile(config, key, tile);
                } catch (Exception e) {
                    log.error("[ocean] roms {} 수집 예외", tile, e);
                } finally {
                    queued.remove(tile);
                }
            }, Instant.now());
        }
        return true;
    }
}

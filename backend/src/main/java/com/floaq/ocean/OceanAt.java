package com.floaq.ocean;

import com.floaq.ocean.roms.OceanRomsStore;
import com.floaq.ocean.seaobs.SeaObsCollector;
import com.floaq.ocean.seaobs.SeaObsHistory;
import com.floaq.ocean.seaobs.SeaObsStore;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

/**
 * <b>그 좌표, 그 시각의 바다</b> 한 벌. 사고가 만들어질 때 사고 행에 박아 두는 값이다.
 *
 * <p>관측값은 24시간만 보관한다({@link OceanRetention#WINDOW}). 그래서 사고가 날 때 받아 두지
 * 않으면 하루 뒤에는 "그때 조류가 어땠나"에 아무도 답할 수 없다 — 표류가 왜 그만큼 흘렀는지,
 * 생존 예상이 왜 그렇게 짧았는지의 근거가 통째로 사라진다.</p>
 *
 * <p>조회 API({@code /api/ocean/current}·{@code /observations})와 <b>같은 자료를 같은 규칙으로</b>
 * 읽는다 — 거리 상한도 같다. 저장한 값과 화면이 그때그때 받는 값이 달라지면
 * 어느 쪽을 믿어야 할지 알 수 없게 된다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OceanAt {

    /** 바람을 찾을 반경. 웹이 쓰는 값과 맞춘다(lib/ocean.ts WIND_RADIUS_KM) */
    private static final double WIND_RADIUS_KM = 50;

    /** 정시 예보를 사고 시각으로 반올림하는 폭 */
    private static final long HALF_HOUR_SEC = 1800;
    /** 사고 시각과 예보 시각이 이보다 벌어지면 그 시각 값이 아니다(OceanController.HISTORY_GAP 과 같다) */
    private static final Duration MAX_GAP = Duration.ofHours(1);

    private final OceanRomsStore roms;
    private final SeaObsStore obs;

    /**
     * @param when 사고 시각. 이 시각 이후 가장 이른 예측·관측을 고른다
     * @return 유속·바람 중 <b>하나라도</b> 있으면 값. 둘 다 없으면 비어 있다 —
     *         빈 값을 0 으로 채우면 "잔잔한 바다"라는 다른 말이 된다
     */
    public Optional<Snap> at(double lat, double lon, Instant when) {
        /*
         * 🔴 <b>사고 시각에 가장 가까운 예보</b>를 고른다.
         *
         * <p>ROMS 는 정시 단위 예보라 10:38 사고에 딱 맞는 값이 없다. {@code sample} 은
         * "이 시각 <b>이후</b> 가장 이른 예보"를 주므로 그대로 넘기면 10:05 사고가 11:00 예보를
         * 받는다 — 55분 뒤 값인데 5분 전 값(10:00)이 있는데도 그렇다.</p>
         *
         * <p>30분을 당겨 물으면 그 규칙이 <b>반올림</b>이 된다: 10:38 → 10:08 이후 첫 예보 = 11:00(22분 차),
         * 10:05 → 09:35 이후 첫 예보 = 10:00(5분 차). 둘 다 가까운 쪽이다.</p>
         */
        var sample = roms.sample(lat, lon, when.minusSeconds(HALF_HOUR_SEC))
                .filter(s -> s.distanceKm() <= OceanRomsStore.NEIGHBOR_RADIUS_KM)
                /*
                 * 🔴 <b>너무 멀리 떨어진 예보는 버린다.</b> 그 시각 그 타일을 안 받았으면 몇 시간 뒤
                 * 격자가 잡히는데, 3시간 뒤 유속을 사고 시각 값이라고 적으면 틀린 말이다.
                 * 조회 API 와 같은 기준(1시간)이다 — OceanController.withinHistoryGap.
                 */
                .filter(s -> Duration.between(when, s.grid().predcDt()).abs().compareTo(MAX_GAP) <= 0);
        var wind = SeaObsHistory
                .near(obs.latestAt(SeaObsCollector.SOURCE, when, SeaObsHistory.WINDOW), lat, lon, WIND_RADIUS_KM)
                .stream()
                .filter(n -> n.station().windSpeedMs() != null && n.station().windDirDeg() != null)
                .findFirst();

        if (sample.isEmpty() && wind.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(new Snap(
                sample.map(s -> s.grid().crspMs()).orElse(null),
                sample.map(s -> s.grid().crdirDeg()).orElse(null),
                wind.map(n -> n.station().windSpeedMs()).orElse(null),
                wind.map(n -> n.station().windDirDeg()).orElse(null),
                sample.map(s -> s.neighborSpreadMs()).orElse(null),
                // 관측 시각은 둘이 다를 수 있다. 표류 계산을 이끄는 쪽(조류)을 적는다
                sample.map(s -> s.grid().predcDt()).orElseGet(() -> wind.get().station().observedAt())));
    }

    /**
     * @param currentDirDeg 흘러가는 쪽 (ROMS 관례)
     * @param windDirDeg    <b>불어오는 쪽</b> (기상 관례). 표류 계산은 여기서 180° 를 더해 쓴다
     * @param observedAt    이 값들이 관측·예측된 시각
     */
    public record Snap(Double currentSpeedMs, Double currentDirDeg,
                       Double windSpeedMs, Double windDirDeg,
                       Double spreadMs, Instant observedAt) {
    }
}

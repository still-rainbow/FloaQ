package com.floaq.ocean;

import com.floaq.ocean.collect.OceanCollector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 기동 시 공공데이터 설정을 훑어 문제를 로그로 드러낸다.
 *
 * 없으면 어떻게 되나 — 수집 스케줄러가 매번 401 을 받고 빈 값을 저장한다.
 * 화면에는 "데이터 없음"으로 보이고, 키가 없는 것인지 그 해역에 값이 없는 것인지 구분되지 않는다.
 * 조용한 실패보다 시끄러운 실패가 낫다(계획.md §2).
 *
 * 기동을 막지는 않는다. 해양 데이터는 부가 경로이고, 이것 때문에 사고 기록 수신까지
 * 못 뜨면 우선순위가 뒤집힌다(§9.13 — `/cloud` 가 끊겨도 핵심은 돈다).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OceanApiStartupCheck {

    private final OceanApiProperties props;
    private final List<OceanCollector> collectors;

    @EventListener(ApplicationReadyEvent.class)
    public void report() {
        Map<String, OceanApiProperties.Source> sources = props.sources();
        if (sources.isEmpty()) {
            log.warn("[ocean] 설정된 소스가 없다 — 해양 데이터가 수집되지 않는다");
            return;
        }

        Set<String> implemented = collectors.stream().map(OceanCollector::source).collect(Collectors.toSet());
        List<String> ready = new ArrayList<>();
        List<String> blocked = new ArrayList<>();

        sources.forEach((name, s) -> {
            if (!s.enabled()) {
                return; // 일부러 끈 것은 경고하지 않는다
            }
            if (!implemented.contains(name)) {
                // 🔴 스케줄러는 **수집기**를 훑으며 설정을 찾는다 — 설정만 켜면 조용히 아무 일도 안 한다.
                // 화면에는 "값 없음"으로만 보여 키 문제와 구분되지 않는다
                blocked.add("%s (수집기 없음 — 설정만 켜져 있다)".formatted(name));
                return;
            }
            String key = props.keyFor(s);
            if (key == null || key.isBlank()) {
                // 소스 전용 키를 쓰는 곳(NIFS)과 발급처 공용 키를 쓰는 곳을 구분해 말한다 —
                // 어느 환경변수를 채워야 하는지가 달라진다
                blocked.add(s.hasOwnKey() || props.keys().get(s.provider()) == null
                        ? "%s (%s 키 없음)".formatted(name, s.provider())
                        : "%s (%s 공용 키 없음)".formatted(name, s.provider()));
                return;
            }
            if (s.baseUrl() == null || s.baseUrl().isBlank()) {
                blocked.add("%s (엔드포인트 미확인)".formatted(name));
                return;
            }
            if (s.exceedsQuota()) {
                // 조용히 쿼터를 태우면 하루 중간에 수집이 멈추고, 그 시각 이후 값이 통째로 빈다
                log.warn("[ocean] {} — 주기 {}초면 하루 {}회인데 상한이 {}회다. 주기를 늘리거나 운영계정을 받을 것",
                        name, s.intervalSec(), s.callsPerDay(), s.dailyQuota());
            }
            ready.add(name);
        });

        var coverage = props.coverage();
        if (coverage == null || !coverage.isValid()) {
            // 수집은 돈다(ROMS 는 조회 좌표 타일). 좌표 없는 조회·요약·관심 선박 없는 소해구의 기준만 없다
            log.warn("[ocean] app.ocean.coverage 가 유효하지 않다 — 좌표 없는 조회·요약의 기준 위치가 없다");
        } else {
            log.info("[ocean] 기본 위치 {},{} · 지점 반경 {}km · ROMS {}° 타일 (조회된 곳만 수집)",
                    coverage.defaultLat(), coverage.defaultLon(), coverage.stationRadiusKm(),
                    com.floaq.ocean.roms.RomsTile.DEG);
        }
        log.info("[ocean] 수집 가능 {}종: {}", ready.size(), ready);
        if (!blocked.isEmpty()) {
            log.warn("[ocean] 막힌 소스 {}종: {} — infra/.env 를 확인할 것", blocked.size(), blocked);
        }
    }
}

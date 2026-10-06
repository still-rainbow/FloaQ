package com.floaq.pi;

import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Pi 수신 서비스가 공유하는 선행 조건 검사 (docs/api.md §4.1 · §4.3).
 *
 * <p>{@link PiIngestService} 안에 private 으로 있던 것을 꺼냈다(2026-09-18) —
 * {@link PiTelemetryService}·{@link PiEventService}·{@link PiFileService} 가 같은 검사를 한다.
 * 복사해 두면 "승인 선박만"·"자기 사고만" 규칙이 네 곳에서 따로 늙는다.</p>
 *
 * <p><b>배치 하나 = 트랜잭션 하나.</b> 여기서 던지는 예외는 배치 전체를 되돌린다 —
 * 일부만 들어가면 Pi 가 어디까지 성공했는지 알 수 없다.</p>
 */
@Component
@RequiredArgsConstructor
public class PiIngestSupport {

    private final JdbcTemplate jdbc;

    /**
     * 승인({@code ACTIVE})된 선박만 데이터를 올릴 수 있다.
     *
     * <p><b>데이터를 잃지 않는다.</b> §4.1 재시도 표대로 Pi 는 전송을 멈추고 큐를 쥐고 있다가
     * 승인된 뒤 밀린 것부터 보낸다. 승인 안 된 선박의 사고가 관제 목록에 올라오면
     * <b>실제 선박인지 누가 키를 들고 장난친 것인지 구분할 방법이 없다.</b></p>
     *
     * <p>{@code PI_SHIP_UNKNOWN}(404)과 코드를 가른 이유: Pi 가 할 일이 다르다.
     * 모르는 선박은 설정 문제라 사람이 풀어야 하지만 <b>승인 대기는 기다리면 풀린다.</b></p>
     */
    public void requireApprovedShip(UUID callerShipId) {
        if (callerShipId == null) {
            // 필터가 실어 주지 않았다 = 선박 키가 아니다(등록 키로 데이터를 올리려는 경우)
            throw new BusinessException(ErrorCode.PI_UNAUTHORIZED);
        }
        // queryForObject 가 아니다 — 행이 없으면 EmptyResultDataAccessException 이 나 500 으로 샌다.
        // 키를 발급받은 뒤 선박이 지워진 경우가 실제로 여기로 온다
        List<String> status = jdbc.queryForList(
                "SELECT status FROM ship WHERE ship_id = ? AND is_deleted = false",
                String.class, callerShipId);
        if (status.isEmpty()) {
            throw new BusinessException(ErrorCode.PI_SHIP_UNKNOWN);
        }
        if (!"ACTIVE".equals(status.getFirst())) {
            throw new BusinessException(ErrorCode.PI_SHIP_NOT_APPROVED);
        }
    }

    /**
     * 사고 행이 먼저 올라와 있어야 한다 — FK 위반은 배치 전체를 롤백시킨다.
     *
     * <p><b>영구 실패가 아니라 순서 문제다</b>: Pi 는 그 원소를 보류하고 사고를 먼저 보낸 뒤
     * 다시 보낸다(§4.1 재시도 표). 그래서 {@code failed} 에 index 를 반드시 싣는다.</p>
     *
     * <p>⚠ 사고가 <b>키의 선박 것</b>이어야 한다. 존재만 보면 남의 사고에 행을 끼워 넣을 수 있다.</p>
     */
    public void requireKnownAccidents(List<UUID> accidentIds, UUID callerShipId) {
        Set<UUID> known = selectIds(
                "SELECT accident_id FROM accident WHERE accident_id = ANY (?) AND ship_id = ?",
                accidentIds, callerShipId);

        List<PiFailure> failures = new ArrayList<>();
        for (int i = 0; i < accidentIds.size(); i++) {
            UUID id = accidentIds.get(i);
            if (id == null || !known.contains(id)) {
                failures.add(new PiFailure(i, String.valueOf(id),
                        ErrorCode.ACCIDENT_NOT_FOUND.getCode()));
            }
        }
        if (!failures.isEmpty()) {
            throw new PiBatchException(ErrorCode.ACCIDENT_NOT_FOUND, failures);
        }
    }

    /**
     * 사고 하나짜리 판. 파일 업로드처럼 배치가 아닌 자리에서 쓴다.
     *
     * @return 사고가 그 선박 것이면 true
     */
    public boolean ownsAccident(UUID accidentId, UUID callerShipId) {
        if (accidentId == null) {
            return false;
        }
        return !jdbc.queryForList(
                "SELECT 1 FROM accident WHERE accident_id = ? AND ship_id = ?",
                Integer.class, accidentId, callerShipId).isEmpty();
    }

    /** {@code ids} 가 첫 파라미터({@code ANY (?)}), {@code extra} 가 그 뒤를 잇는다. */
    public Set<UUID> selectIds(String sql, List<UUID> ids, Object... extra) {
        UUID[] param = new HashSet<>(ids).stream().filter(Objects::nonNull).toArray(UUID[]::new);
        if (param.length == 0) {
            return Set.of();
        }
        Object[] args = new Object[1 + extra.length];
        args[0] = param;
        System.arraycopy(extra, 0, args, 1, extra.length);
        return new HashSet<>(jdbc.queryForList(sql, UUID.class, args));
    }

    /**
     * {@code batchUpdate} 의 {@code int[][]}(청크별 배열)에서 실제로 반영된 행 수를 센다.
     *
     * <p>{@code ON CONFLICT DO NOTHING} 이면 0 이 곧 <b>재전송</b>이다 — 오류가 아니다.</p>
     */
    public static int countAffected(int[][] chunks) {
        int n = 0;
        for (int[] chunk : chunks) {
            for (int affected : chunk) {
                if (affected > 0) {
                    n++;
                }
            }
        }
        return n;
    }
}

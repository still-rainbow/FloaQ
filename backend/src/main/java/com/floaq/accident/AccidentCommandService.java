package com.floaq.accident;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentState;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.UUID;

/**
 * 관제 웹이 사고에 <b>쓰는</b> 것. 읽기는 {@link AccidentQueryService} 가 한다.
 *
 * <p>여기 있는 것은 <b>관제가 한 일</b>뿐이다 — 감지와 상태 전이의 권위는 Pi 에 있고 서버는
 * 받아 적을 뿐이다(계획.md §9.2). 접수·발견·종결은 관제 쪽에서 일어난 사실이라 Pi 가 알 수 없고,
 * 그래서 여기서 쓴다.</p>
 */
@Service
@RequiredArgsConstructor
@Transactional
public class AccidentCommandService {

    private final AccidentRepository accidents;
    private final AccidentStateRepository states;

    /**
     * 사고 접수 — 관제 화면이 이 사고를 받았다.
     *
     * <p>지금까지 이 시각은 브라우저 안에만 있었다. 새로고침하면 사라지고 다른 관제사 화면에는
     * 보이지 않았으며, 종료 리포트의 '해경 접수'도 한 사람 화면에서만 참인 값이었다(2026-09-18).</p>
     *
     * <p><b>멱등이다.</b> 화면이 목록을 5초마다 다시 받고 그때마다 접수를 부르므로 —
     * 두 번째부터는 아무것도 하지 않고 처음 시각을 그대로 둔다. 최초 시각이
     * "신고에서 접수까지 얼마나 걸렸나"의 원재료라 나중 값으로 덮으면 그 기록이 사라진다.</p>
     *
     * <p>범위 밖 사고는 {@link AccidentQueryService#scopeOf} 와 같은 이유로 <b>404</b> 다 —
     * 403 이면 "그런 사고가 있다"를 알려주는 셈이다.</p>
     *
     * @return 이번 호출이 처음이었나
     */
    public boolean ack(UUID accidentId) {
        return target(accidentId).webAck(currentUserId(), Instant.now());
    }

    /**
     * 사고자 발견 — 수색 화면에서 경비정이 찾았다고 찍는다(단계 ④).
     *
     * <p>지금까지 이 시각은 브라우저 안에만 있었다. 새로고침하면 사라지고 다른 관제사에게는
     * 보이지 않았다 — 접수와 같은 사연이다(2026-09-21).</p>
     *
     * <p><b>멱등이다.</b> 이미 찍혀 있으면 최초 시각을 그대로 둔다.</p>
     *
     * @return 이번 호출이 처음이었나
     */
    public boolean rescue(UUID accidentId) {
        return target(accidentId).rescue(Instant.now());
    }

    /**
     * 사고 종결 — <b>되돌릴 수 없다.</b>
     *
     * <p>지금까지 종결은 브라우저 안에서만 일어났다. 화면은 '완료'로 바뀌는데 새로고침하면
     * 사고가 되살아났고, 다른 관제사 화면에서는 처음부터 진행 중이었다(2026-09-21).</p>
     *
     * <p>🔴 <b>중복 종결 가드</b>는 {@code closed_at} 하나에 걸린다(계획.md §9.20) —
     * 키오스크와 관제 웹이 경합한다. 먼저 누른 쪽만 성립하고, 나중 호출은
     * 조용히 false 다. 오류로 만들면 이미 끝난 사고를 종결하려던 사람에게 "실패했다"고
     * 말하는 셈인데 사고는 분명히 끝나 있다.</p>
     *
     * <p>경위 한 줄({@code accident_state})도 같이 남긴다 — 없으면 표에는 끝났다고 적혀 있는데
     * 경위에는 그 일이 없다.</p>
     *
     * @return 이번 호출이 처음이었나
     */
    public boolean close(UUID accidentId) {
        Accident a = target(accidentId);
        AccidentStatus prev = a.getStatus();
        Instant at = Instant.now();
        if (!a.close(at)) {
            return false;
        }
        Long by = currentUserId();
        states.save(AccidentState.byControl(accidentId, AccidentStatus.CLOSE, prev, at,
                by == null ? "관제" : "관제 " + by));
        return true;
    }

    /**
     * 볼 수 있는 사고만 손댄다. 범위 밖은 <b>404</b> 다 — 403 이면 "그런 사고가 있다"를
     * 알려주는 셈이고, 사고 ID 를 바꿔 가며 찔러 보면 어느 선박에 사고가 있었는지가 새어 나간다.
     */
    private Accident target(UUID accidentId) {
        return accidents.findByAccidentIdAndStatusIn(accidentId, AccidentQueryService.scopeOf())
                .orElseThrow(() -> new BusinessException(ErrorCode.ACCIDENT_NOT_FOUND));
    }

    /**
     * 로그인한 계정. JWT {@code sub} 가 {@code users.user_id} 다(auth/TokenService).
     * 본문으로 받지 않는 이유는 보내는 쪽이 정하는 값이면 증명이 되지 않기 때문이다.
     */
    private Long currentUserId() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || auth.getName() == null) {
            return null;
        }
        try {
            return Long.valueOf(auth.getName());
        } catch (NumberFormatException e) {
            // 토큰이 우리가 발급한 모양이 아니다. 접수 자체는 남기고 누구인지만 비운다
            return null;
        }
    }
}

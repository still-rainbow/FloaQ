package com.floaq.ship;

import com.floaq.accident.AccidentRepository;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.PageView;
import com.floaq.ship.dto.AdminShipView;
import com.floaq.ship.entity.Ship;
import com.floaq.ship.entity.ShipStatus;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Set;
import java.util.UUID;

/**
 * 선박 등록 관리 — 신청 목록 · 승인 · 반려 (WEB-08 · docs/api.md §3.3). SUPER_ADMIN 만 부른다(SecurityConfig).
 *
 * <p>{@link com.floaq.auth.AdminUserService} 와 같은 모양으로 둔다. 관제 웹이 두 승인을 같은
 * 컴포넌트로 그리므로(SuperAdmin.tsx) 응답 모양과 오류가 어긋나면 화면이 분기를 두 벌 갖게 된다.</p>
 *
 * <p><b>신청(등록)은 여기 없다.</b> Pi 가 서명해 보내는 경로이고 서명 계약이 아직 없다(api.md §9 3-1).
 * 수정(PATCH)도 화면에 그 조작이 없어 두지 않는다.</p>
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AdminShipService {

    /** ⚠ 임시 상한 — AdminUserService 와 같은 값. api.md §9 #7 "페이지 상한" 미결 */
    static final int MAX_PAGE_SIZE = 100;

    /**
     * 아직 안 끝난 사고. 이 상태의 사고가 있는 배는 지울 수 없다.
     * {@code CLOSE}·{@code CANCEL} 은 끝난 것이라 지워도 관제가 곤란하지 않다.
     */
    private static final Set<AccidentStatus> LIVE =
            Set.of(AccidentStatus.DETECT, AccidentStatus.WAIT, AccidentStatus.REPORT);

    private final ShipRepository ships;
    private final AccidentRepository accidents;

    /**
     * {@code status} 가 없으면 논리 삭제만 뺀 전체. 최근 신청이 위.
     *
     * <p>계정 목록은 비활성화(DELETED)를 숨기지만 여기서는 반려까지 다 보여준다 —
     * 선박은 숨길 상태가 없고, 반려한 배가 목록에 남아야 "왜 안 올라오지"를 SA 가 확인할 수 있다.</p>
     */
    public PageView<AdminShipView> list(ShipStatus status, int page, int size) {
        Pageable pageable = PageRequest.of(Math.max(0, page), Math.clamp(size, 1, MAX_PAGE_SIZE),
                Sort.by(Sort.Direction.DESC, "createdAt", "shipId"));
        Page<Ship> found = status == null
                ? ships.findByDeletedFalse(pageable)
                : ships.findByStatusAndDeletedFalse(status, pageable);
        return PageView.of(found.map(AdminShipView::of));
    }

    @Transactional
    public AdminShipView approve(UUID shipId, long decidedByUserId) {
        Ship ship = target(shipId);
        ship.approve(decidedByUserId);
        return AdminShipView.of(saved(ship));
    }

    @Transactional
    public AdminShipView reject(UUID shipId, long decidedByUserId) {
        Ship ship = target(shipId);
        ship.reject(decidedByUserId);
        return AdminShipView.of(saved(ship));
    }

    /** 논리 삭제된 배는 없는 것으로 본다 — 지운 배를 되살리는 경로를 승인 버튼으로 만들지 않는다 */
    private Ship target(UUID shipId) {
        Ship ship = ships.findById(shipId)
                .orElseThrow(() -> new BusinessException(ErrorCode.SHIP_NOT_FOUND));
        if (ship.isDeleted()) {
            throw new BusinessException(ErrorCode.SHIP_NOT_FOUND);
        }
        return ship;
    }

    /** flush 해야 decidedAt·updatedAt 이 채워진다. 커밋 때 채워지면 응답에는 처리 전 값이 나간다 */
    private Ship saved(Ship ship) {
        return ships.saveAndFlush(ship);
    }

    /**
     * 선박 삭제 (api.md §3.3). <b>논리 삭제다</b> — {@code is_deleted} 만 찍고 행은 남긴다.
     *
     * <p>화면에는 삭제 버튼이 있는데 서버에 이 메서드가 없어, 운영에서 누르면 500 이 났다.
     * 경로가 매핑돼 있지 않으면 스프링이 404 를 주는데, 인증을 통과한 뒤라 오류 처리가
     * 그걸 500 으로 바꿔 내보냈다 — 화면에는 "서버 오류"로만 보였다(2026-09-20).</p>
     *
     * <p>⚠ <b>진행 중 사고가 있으면 409 다.</b> 그 배를 목록에서 지우면 관제가 사고를 못 찾는다.
     * 끝난 사고만 있으면 지워도 된다 — 기록은 배 이름을 이 행에서 읽으므로 그대로 남는다.</p>
     */
    @Transactional
    public void remove(UUID shipId) {
        Ship ship = ships.findById(shipId)
                .orElseThrow(() -> new BusinessException(ErrorCode.SHIP_NOT_FOUND));
        if (accidents.existsByShipIdAndStatusIn(shipId, LIVE)) {
            throw new BusinessException(ErrorCode.INVALID_STATE);
        }
        ship.delete();
    }
}

package com.floaq.auth;

import com.floaq.auth.dto.AdminUserView;
import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.PageView;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 계정 관리 — 가입 신청 목록 · 승인 · 반려 (WEB-07 · docs/api.md §3.2). SA 만 부른다(SecurityConfig).
 *
 * <p>비활성화({@code ACTIVE → DELETED})는 {@link #deactivate} 가 한다 — 행은 남기고 상태만 바꾼다.</p>
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AdminUserService {

    /** ⚠ 임시 상한 — api.md §9 #7 "페이지 상한" 미결. 화면은 hasNext 를 보고 다음 페이지를 부른다 */
    static final int MAX_PAGE_SIZE = 100;

    private final UserRepository users;

    /** {@code status} 가 없으면 비활성화(DELETED)만 뺀 전체. 최근 신청이 위 */
    public PageView<AdminUserView> list(UserStatus status, int page, int size) {
        Pageable pageable = PageRequest.of(Math.max(0, page), Math.clamp(size, 1, MAX_PAGE_SIZE),
                Sort.by(Sort.Direction.DESC, "createdAt", "userId"));
        Page<User> found = status == null
                ? users.findByStatusNot(UserStatus.DELETED, pageable)
                : users.findByStatus(status, pageable);
        return PageView.of(found.map(AdminUserView::of));
    }

    @Transactional
    public AdminUserView approve(long userId) {
        User user = target(userId);
        user.approve();
        return AdminUserView.of(saved(user));
    }

    @Transactional
    public AdminUserView reject(long userId) {
        User user = target(userId);
        user.reject();
        return AdminUserView.of(saved(user));
    }

    /**
     * 비활성화 (ACTIVE → DELETED). 관제 화면의 <b>계정 삭제</b> 버튼이 부른다.
     *
     * <p>화면에는 이 버튼이 있는데 서버에 경로가 없어, 누르면 500 이 났다 — 선박 삭제와 같은 일이다
     * (2026-09-20). 이 클래스 주석에 "화면에 그 조작이 없다"고 적어 뒀는데 그사이 생겼다.</p>
     *
     * <p>관리자(SA) 계정은 {@link #target} 이 막는다 — 마지막 관리자를 비활성화하면
     * 아무도 승인을 못 하게 된다.</p>
     */
    @Transactional
    public AdminUserView deactivate(long userId) {
        User user = target(userId);
        user.deactivate();
        return AdminUserView.of(saved(user));
    }

    /**
     * 처리 대상. 관리자 계정은 승인·반려·비활성화 대상이 아니다 — 자기 자신이나 다른 관리자를 반려해
     * 관리자가 한 명도 남지 않는 일을 막는다(api.md §3.2).
     */
    private User target(long userId) {
        User user = users.findById(userId)
                .orElseThrow(() -> new BusinessException(ErrorCode.USER_NOT_FOUND));
        if (user.getRole() == UserRole.SA) {
            throw new BusinessException(ErrorCode.FORBIDDEN);
        }
        return user;
    }

    /** flush 해야 updatedAt 이 채워진다. 커밋 때 채워지면 응답에는 처리 전 시각이 나간다 */
    private User saved(User user) {
        return users.saveAndFlush(user);
    }
}

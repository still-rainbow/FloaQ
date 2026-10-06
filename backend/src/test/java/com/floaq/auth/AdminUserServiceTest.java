package com.floaq.auth;

import com.floaq.auth.dto.AdminUserView;
import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.PageView;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 계정 관리 규칙 검증. DB 없이 저장소를 목으로 둔다. */
class AdminUserServiceTest {

    private final UserRepository users = mock(UserRepository.class);
    private final AdminUserService admin = new AdminUserService(users);

    private User stored(long id, UserRole role, UserStatus status) {
        User user = User.create("user" + id + "@kcg.example", "hash", "박서연", role, status);
        ReflectionTestUtils.setField(user, "userId", id);
        when(users.findById(id)).thenReturn(Optional.of(user));
        when(users.saveAndFlush(user)).thenReturn(user);
        return user;
    }

    private static void assertCode(ThrowingCallable call, ErrorCode expected) {
        assertThatThrownBy(call)
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getErrorCode()).isEqualTo(expected));
    }

    @Test
    void 승인하면_로그인할_수_있는_상태가_된다() {
        stored(3, UserRole.A, UserStatus.WAIT);

        AdminUserView res = admin.approve(3);

        assertThat(res.status()).isEqualTo(UserStatus.ACTIVE);
        verify(users).saveAndFlush(any());
    }

    @Test
    void 반려하면_REJECTED_가_되고_행은_남는다() {
        User user = stored(3, UserRole.A, UserStatus.WAIT);

        AdminUserView res = admin.reject(3);

        assertThat(res.status()).isEqualTo(UserStatus.REJECTED);
        // 반려는 비활성화(삭제)가 아니다 — 삭제 시각도 찍지 않는다
        assertThat(user.getDeletedAt()).isNull();
        assertThat(user.isDeleted()).isFalse();
        verify(users, never()).delete(any());
    }

    @Test
    void 대기_중이_아닌_신청은_다시_처리하지_않는다() {
        // 관리자 두 명이 거의 동시에 누른 경우 — 나중 사람은 409 를 받고 목록을 새로 본다
        stored(3, UserRole.A, UserStatus.ACTIVE);
        stored(4, UserRole.A, UserStatus.REJECTED);

        assertCode(() -> admin.approve(3), ErrorCode.INVALID_STATE);
        assertCode(() -> admin.reject(3), ErrorCode.INVALID_STATE);
        assertCode(() -> admin.approve(4), ErrorCode.INVALID_STATE);
        verify(users, never()).saveAndFlush(any());
    }

    @Test
    void 없는_계정은_계정_없음으로_알려준다() {
        when(users.findById(99L)).thenReturn(Optional.empty());

        assertCode(() -> admin.approve(99), ErrorCode.USER_NOT_FOUND);
    }

    @Test
    void 관리자_계정은_승인_반려_대상이_아니다() {
        // 자기 자신이나 다른 관리자를 반려해 관리자가 남지 않는 일을 막는다
        stored(1, UserRole.SA, UserStatus.WAIT);

        assertCode(() -> admin.reject(1), ErrorCode.FORBIDDEN);
        assertCode(() -> admin.approve(1), ErrorCode.FORBIDDEN);
    }

    @Test
    void 상태를_안_고르면_비활성화_계정만_빼고_모두_보여준다() {
        User wait = User.create("a@kcg.example", "hash", "박서연", UserRole.A, UserStatus.WAIT);
        when(users.findByStatusNot(eq(UserStatus.DELETED), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of(wait), PageRequest.of(0, 20), 1));

        PageView<AdminUserView> res = admin.list(null, 0, 20);

        assertThat(res.content()).extracting(AdminUserView::loginId).containsExactly("a@kcg.example");
        assertThat(res.totalElements()).isEqualTo(1);
        assertThat(res.hasNext()).isFalse();
        verify(users, never()).findByStatus(any(), any());
    }

    @Test
    void 페이지_번호와_크기는_허용_범위로_자른다() {
        when(users.findByStatus(eq(UserStatus.WAIT), any(Pageable.class)))
                .thenReturn(new PageImpl<>(List.of()));

        admin.list(UserStatus.WAIT, -3, 5000);

        ArgumentCaptor<Pageable> pageable = ArgumentCaptor.forClass(Pageable.class);
        verify(users).findByStatus(eq(UserStatus.WAIT), pageable.capture());
        assertThat(pageable.getValue().getPageNumber()).isZero();
        assertThat(pageable.getValue().getPageSize()).isEqualTo(AdminUserService.MAX_PAGE_SIZE);
    }
}

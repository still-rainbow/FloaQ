package com.floaq.auth;

import com.floaq.auth.dto.LoginRequest;
import com.floaq.auth.dto.LoginResponse;
import com.floaq.auth.dto.SignupRequest;
import com.floaq.auth.dto.SignupResponse;
import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 로그인 규칙 검증. DB 없이 저장소를 목으로 둔다.
 *
 * <p>bcrypt 라운드를 4 로 낮춘다 — 12 면 해시 한 번에 수백 ms 라 테스트가 느려진다.
 * 비교 결과는 라운드와 무관하다.</p>
 */
class AuthServiceTest {

    private static final String EMAIL = "kim@kcg.example";
    private static final String PASSWORD = "floaq1234!";

    private final UserRepository users = mock(UserRepository.class);
    private final TokenService tokens = mock(TokenService.class);
    private final PasswordEncoder encoder = new BCryptPasswordEncoder(4);
    private final AuthService auth = new AuthService(users, encoder, tokens);

    private User stored(UserStatus status) {
        User user = User.create(EMAIL, encoder.encode(PASSWORD), "김민준", UserRole.A, status);
        ReflectionTestUtils.setField(user, "userId", 3L);
        when(users.findByLoginId(EMAIL)).thenReturn(Optional.of(user));
        when(users.findById(3L)).thenReturn(Optional.of(user));
        return user;
    }

    private static void assertCode(ThrowingCallable call, ErrorCode expected) {
        assertThatThrownBy(call)
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getErrorCode()).isEqualTo(expected));
    }

    @Test
    void 승인된_계정은_토큰과_계정을_받는다() {
        stored(UserStatus.ACTIVE);
        Instant expiresAt = Instant.parse("2026-09-15T12:00:00Z");
        when(tokens.issue(any())).thenReturn(new TokenService.IssuedToken("token", expiresAt));

        LoginResponse res = auth.login(new LoginRequest(EMAIL, PASSWORD));

        assertThat(res.accessToken()).isEqualTo("token");
        assertThat(res.tokenType()).isEqualTo("Bearer");
        assertThat(res.expiresAt()).isEqualTo(expiresAt);
        assertThat(res.user().userId()).isEqualTo(3L);
        assertThat(res.user().role()).isEqualTo(UserRole.A);
    }

    @Test
    void 이메일은_대소문자와_앞뒤_공백을_가리지_않는다() {
        stored(UserStatus.ACTIVE);
        when(tokens.issue(any())).thenReturn(new TokenService.IssuedToken("token", Instant.now()));

        assertThat(auth.login(new LoginRequest("  Kim@KCG.example ", PASSWORD)).accessToken()).isEqualTo("token");
    }

    @Test
    void 없는_이메일과_틀린_비밀번호는_같은_오류다() {
        // 둘을 가르면 이메일만 넣어 보고 가입 여부를 알아낼 수 있다
        stored(UserStatus.ACTIVE);
        assertCode(() -> auth.login(new LoginRequest("nobody@kcg.example", PASSWORD)),
                ErrorCode.AUTH_INVALID_CREDENTIALS);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, "wrong-password")),
                ErrorCode.AUTH_INVALID_CREDENTIALS);
        verify(tokens, never()).issue(any());
    }

    @Test
    void 승인_대기는_비밀번호가_맞을_때만_알려준다() {
        stored(UserStatus.WAIT);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, PASSWORD)), ErrorCode.AUTH_ACCOUNT_PENDING);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, "wrong-password")), ErrorCode.AUTH_INVALID_CREDENTIALS);
    }

    @Test
    void 반려된_신청은_비밀번호가_맞을_때만_반려를_알려준다() {
        stored(UserStatus.REJECTED);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, PASSWORD)), ErrorCode.AUTH_ACCOUNT_REJECTED);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, "wrong-password")), ErrorCode.AUTH_INVALID_CREDENTIALS);
    }

    @Test
    void 반려된_이메일은_옛_신청을_지우고_다시_신청할_수_있다() {
        User rejected = stored(UserStatus.REJECTED);
        when(users.saveAndFlush(any())).thenAnswer(inv -> inv.getArgument(0));

        SignupResponse res = auth.signup(signup("  KIM@kcg.example", PASSWORD));

        // 지운 뒤 flush 해야 새 INSERT 가 같은 login_id 로 UNIQUE 에 걸리지 않는다
        InOrder order = inOrder(users);
        order.verify(users).delete(rejected);
        order.verify(users).flush();
        ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
        order.verify(users).saveAndFlush(saved.capture());
        assertThat(saved.getValue()).isNotSameAs(rejected);
        assertThat(saved.getValue().getStatus()).isEqualTo(UserStatus.WAIT);
        assertThat(res.status()).isEqualTo(UserStatus.WAIT);
    }

    @Test
    void 대기_중이거나_비활성화된_이메일은_다시_신청할_수_없다() {
        // 비활성화 행은 과거 기록의 처리자라 지우지 않는다
        for (UserStatus status : new UserStatus[]{UserStatus.WAIT, UserStatus.DELETED}) {
            stored(status);
            assertCode(() -> auth.signup(signup(EMAIL, PASSWORD)), ErrorCode.AUTH_ALREADY_REGISTERED);
        }
        verify(users, never()).delete(any());
        verify(users, never()).saveAndFlush(any());
    }

    @Test
    void 삭제된_계정은_로그인할_수_없다() {
        stored(UserStatus.DELETED);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, PASSWORD)), ErrorCode.AUTH_ACCOUNT_DELETED);
    }

    @Test
    void 상태가_활성이어도_삭제_시각이_있으면_막는다() {
        User user = stored(UserStatus.ACTIVE);
        ReflectionTestUtils.setField(user, "deletedAt", Instant.parse("2026-09-15T00:00:00Z"));
        assertCode(() -> auth.login(new LoginRequest(EMAIL, PASSWORD)), ErrorCode.AUTH_ACCOUNT_DELETED);
    }

    @Test
    void 비밀번호가_72바이트를_넘으면_예외_없이_틀린_비밀번호로_처리한다() {
        stored(UserStatus.ACTIVE);
        // 한글은 3바이트 — 25자면 75바이트다
        String longPassword = "가".repeat(25);
        assertCode(() -> auth.login(new LoginRequest(EMAIL, longPassword)), ErrorCode.AUTH_INVALID_CREDENTIALS);
    }

    // ── 가입 신청 ─────────────────────────────────────────────

    private static SignupRequest signup(String loginId, String password) {
        return new SignupRequest(loginId, password, "박서연");
    }

    @Test
    void 가입_신청은_해경_승인대기로_들어가고_비밀번호는_해시로만_남는다() {
        when(users.saveAndFlush(any())).thenAnswer(inv -> inv.getArgument(0));

        SignupResponse res = auth.signup(new SignupRequest("  Park@KCG.example ", PASSWORD, " 박서연 "));

        ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
        verify(users).saveAndFlush(saved.capture());
        User user = saved.getValue();
        assertThat(user.getLoginId()).isEqualTo("park@kcg.example");
        assertThat(user.getName()).isEqualTo("박서연");
        assertThat(user.getRole()).isEqualTo(UserRole.A);
        assertThat(user.getStatus()).isEqualTo(UserStatus.WAIT);
        assertThat(user.getPassword()).isNotEqualTo(PASSWORD);
        assertThat(encoder.matches(PASSWORD, user.getPassword())).isTrue();
        assertThat(res.status()).isEqualTo(UserStatus.WAIT);
    }

    @Test
    void 이미_있는_이메일은_대소문자가_달라도_막는다() {
        stored(UserStatus.ACTIVE);

        assertCode(() -> auth.signup(signup("KIM@kcg.example", PASSWORD)), ErrorCode.AUTH_ALREADY_REGISTERED);
        verify(users, never()).delete(any());
        verify(users, never()).saveAndFlush(any());
    }

    @Test
    void 거의_동시에_같은_이메일로_신청하면_나중_것은_중복으로_처리한다() {
        // exists 확인은 둘 다 통과하고 UNIQUE 제약이 막는다
        when(users.saveAndFlush(any())).thenThrow(new DataIntegrityViolationException("uq_users_login_id"));

        assertCode(() -> auth.signup(signup(EMAIL, PASSWORD)), ErrorCode.AUTH_ALREADY_REGISTERED);
    }

    @Test
    void 가입_비밀번호가_72바이트를_넘으면_형식_오류로_알려준다() {
        assertCode(() -> auth.signup(signup(EMAIL, "가".repeat(25))), ErrorCode.INVALID_INPUT);
        verify(users, never()).saveAndFlush(any());
    }

    @Test
    void 토큰이_살아_있어도_비활성화된_계정은_내_계정을_볼_수_없다() {
        stored(UserStatus.DELETED);
        assertCode(() -> auth.me(3L), ErrorCode.AUTH_ACCOUNT_DELETED);
    }
}

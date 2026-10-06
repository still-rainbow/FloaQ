package com.floaq.auth;

import com.floaq.auth.dto.LoginRequest;
import com.floaq.auth.dto.LoginResponse;
import com.floaq.auth.dto.SignupRequest;
import com.floaq.auth.dto.SignupResponse;
import com.floaq.auth.dto.UserView;
import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Optional;

/**
 * 로그인 (WEB-01 · docs/api.md §3.1).
 *
 * <p><b>확인 순서가 규칙이다 — 비밀번호가 먼저, 상태가 나중.</b> 상태를 먼저 보면
 * 비밀번호를 몰라도 "승인 대기"·"사용할 수 없음" 문구로 그 이메일이 가입돼 있는지 알아낼 수 있다.</p>
 */
@Service
@Transactional(readOnly = true)
public class AuthService {

    /** bcrypt 가 받아들이는 비밀번호 상한. 넘으면 뒤가 잘리거나 인코더가 예외를 던진다 */
    private static final int BCRYPT_MAX_BYTES = 72;

    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;
    private final TokenService tokens;

    /**
     * 없는 이메일에도 bcrypt 비교를 한 번 돌리기 위한 해시.
     * 바로 돌려보내면 응답이 수백 ms 빨라서, 시간만 재도 계정이 있는지 새어 나간다.
     */
    private final String dummyHash;

    public AuthService(UserRepository users, PasswordEncoder passwordEncoder, TokenService tokens) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
        this.tokens = tokens;
        this.dummyHash = passwordEncoder.encode("floaq-dummy-password");
    }

    public LoginResponse login(LoginRequest request) {
        Optional<User> found = users.findByLoginId(normalizeLoginId(request.loginId()));
        if (!passwordMatches(request.password(), found.map(User::getPassword).orElse(dummyHash))
                || found.isEmpty()) {
            throw new BusinessException(ErrorCode.AUTH_INVALID_CREDENTIALS);
        }

        User user = found.get();
        if (user.isDeleted()) {
            throw new BusinessException(ErrorCode.AUTH_ACCOUNT_DELETED);
        }
        if (user.getStatus() == UserStatus.WAIT) {
            throw new BusinessException(ErrorCode.AUTH_ACCOUNT_PENDING);
        }
        if (user.getStatus() == UserStatus.REJECTED) {
            throw new BusinessException(ErrorCode.AUTH_ACCOUNT_REJECTED);
        }

        TokenService.IssuedToken token = tokens.issue(user);
        return new LoginResponse(token.value(), "Bearer", token.expiresAt(), UserView.of(user));
    }

    /**
     * 가입 신청 (WEB-02 · docs/api.md §3.1). 역할·상태는 요청으로 받지 않는다 — 항상 A + WAIT.
     *
     * <p><b>반려된 이메일은 다시 신청할 수 있다.</b> 반려된 옛 행을 지우고 새 신청으로 넣는다 —
     * 옛 행을 고쳐 쓰면 {@code created_at}(신청 시각)을 바꿀 수 없어 관리 화면에 예전 날짜가 찍힌다.
     * 반려된 계정은 로그인한 적이 없어 이 행을 가리키는 기록이 없다. 대신 반려 이력은 남지 않는다.</p>
     *
     * <p>대기·승인·비활성화된 이메일은 409 다. 비활성화 행은 과거 기록의 처리자라 지우지 않는다.</p>
     */
    @Transactional
    public SignupResponse signup(SignupRequest request) {
        if (request.password().getBytes(StandardCharsets.UTF_8).length > BCRYPT_MAX_BYTES) {
            // 로그인은 틀린 비밀번호와 같게 떨구지만, 가입은 규칙을 알려 줘야 사용자가 고칠 수 있다
            throw new BusinessException(ErrorCode.INVALID_INPUT, "비밀번호가 너무 깁니다.");
        }
        String loginId = normalizeLoginId(request.loginId());
        Optional<User> existing = users.findByLoginId(loginId);
        if (existing.isPresent()) {
            if (existing.get().getStatus() != UserStatus.REJECTED) {
                throw new BusinessException(ErrorCode.AUTH_ALREADY_REGISTERED);
            }
            users.delete(existing.get());
            // 지운 것을 먼저 DB 에 보낸다. Hibernate 는 flush 때 INSERT 를 DELETE 보다 먼저 보내서,
            // 안 보내면 아래 새 행이 같은 login_id 로 UNIQUE 에 걸린다
            users.flush();
        }

        User user = User.create(loginId, passwordEncoder.encode(request.password()), request.name(),
                UserRole.A, UserStatus.WAIT);
        try {
            // flush 해야 UNIQUE 위반이 여기서 난다. 커밋 시점에 나면 이 catch 를 지나쳐 500 이 된다
            users.saveAndFlush(user);
        } catch (DataIntegrityViolationException e) {
            // 같은 이메일로 거의 동시에 두 번 누른 경우. 위 exists 확인을 둘 다 통과한다
            throw new BusinessException(ErrorCode.AUTH_ALREADY_REGISTERED);
        }
        return new SignupResponse(user.getUserId(), user.getStatus());
    }

    /**
     * 내 계정. 토큰이 유효해도 그사이 비활성화됐으면 막는다 —
     * 화면이 새로고침 때마다 이걸 부르므로, 해임된 계정은 늦어도 다음 새로고침에 끊긴다.
     */
    public UserView me(long userId) {
        User user = users.findById(userId)
                .filter(u -> !u.isDeleted())
                .orElseThrow(() -> new BusinessException(ErrorCode.AUTH_ACCOUNT_DELETED));
        return UserView.of(user);
    }

    /** 기관 이메일은 대소문자를 가리지 않는다. 저장도 조회도 이 모양으로 한다 */
    static String normalizeLoginId(String loginId) {
        return loginId.trim().toLowerCase(Locale.ROOT);
    }

    private boolean passwordMatches(String raw, String hash) {
        if (raw.getBytes(StandardCharsets.UTF_8).length > BCRYPT_MAX_BYTES) {
            // 비교는 그래도 돌린다 — 긴 비밀번호만 빨리 떨어지면 그것도 신호가 된다
            passwordEncoder.matches("", hash);
            return false;
        }
        return passwordEncoder.matches(raw, hash);
    }
}

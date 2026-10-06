package com.floaq.auth.entity;

import com.floaq.global.entity.BaseTimeEntity;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.Instant;

/**
 * 관제 웹 계정. 서버가 만드는 행이다.
 *
 * <p>소셜 로그인을 쓰지 않는다 — <b>셀프 가입을 열 수 없기 때문이다.</b>
 * 해경이 신청({@code WAIT})하고 SA 이 승인({@code ACTIVE})한다(계획.md §9.13 · WEB-02·07).</p>
 *
 * <p>⚠⚠ <b>ERD 에 로그인 식별자가 없다.</b> {@code password}·{@code name}·{@code role}·{@code status} 뿐이라
 * <b>WEB-01 로그인이 성립하지 않는다</b> — 무엇으로 계정을 찾을지가 없다.
 * 아래 {@code loginId} 는 ERD 에 추가해야 하는 컬럼이다.</p>
 */
@Entity
@Getter
@Table(name = "users")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class User extends BaseTimeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "user_id")
    private Long userId;

    /**
     * ⚠ <b>ERD 에 없다. 추가 필요.</b>
     * <b>기관 이메일이다</b>(2026-09-15 결정). 소문자·앞뒤 공백 없이 저장한다 —
     * 대소문자만 다른 두 계정이 생기면 UNIQUE 가 막지 못한다. 컬럼 이름은 api.md 대로 중립으로 둔다.
     */
    @Column(name = "login_id", nullable = false, unique = true, length = 64)
    private String loginId;

    /**
     * bcrypt(round 12) 해시. <b>길이 60 은 bcrypt 출력 길이다</b> — 알고리즘을 바꾸면 같이 늘려야 한다.
     * 원문은 어디에도 저장하지 않는다.
     */
    @Column(name = "password", nullable = false, length = 60)
    private String password;

    @Column(name = "name", nullable = false, length = 20)
    private String name;

    @Enumerated(EnumType.STRING)
    @Column(name = "role", nullable = false, length = 16)
    private UserRole role;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private UserStatus status;

    /** 논리 삭제. 과거 사고 기록의 처리자 추적이 끊기지 않게 행은 남긴다 */
    @Column(name = "deleted_at")
    private Instant deletedAt;

    /**
     * 서버가 만드는 계정. 가입 신청({@code AuthService#signup})과 시연 계정 시드({@code DemoAccountSeeder})가 쓴다.
     * {@code passwordHash} 는 이미 bcrypt 로 해시한 값이다 — 원문을 넘기지 않는다.
     *
     * <p>소속 · 부서 · 계급은 두지 않는다(2026-09-15 결정). 해경 쪽에서는 신고를 <b>받았는지</b>만 알 수 있고,
     * 누가 담당하는지·어느 곳에서 처리하는지는 알 수 없다.</p>
     */
    public static User create(String loginId, String passwordHash, String name, UserRole role, UserStatus status) {
        User user = new User();
        user.loginId = loginId;
        user.password = passwordHash;
        user.name = name;
        user.role = role;
        user.status = status;
        return user;
    }

    /** 승인. 대기 중인 신청만 — 이미 처리된 신청을 다시 누르면 409 (api.md §3.2) */
    public void approve() {
        requireWaiting();
        status = UserStatus.ACTIVE;
    }

    /** 반려. 대기 중인 신청만. 행은 지우지 않는다 — 과거 기록의 처리자 추적이 끊기지 않게 */
    public void reject() {
        requireWaiting();
        status = UserStatus.REJECTED;
    }

    /**
     * 비활성화. 쓰던 계정을 더 못 쓰게 한다 — 승인·반려와 달리 <b>이미 쓰고 있던 계정</b>이 대상이다.
     *
     * <p>행은 지우지 않는다. 지난 사고의 처리자·접수자가 이 계정을 가리키고 있어, 진짜로 지우면
     * 기록에서 "누가 받았나"가 사라진다. 로그인은 {@code AuthService} 가 이 상태를 보고 막는다.</p>
     *
     * <p>두 번 눌러도 그냥 둔다 — 화면이 폴링하다 겹쳐 불러도 같은 결과여야 한다.</p>
     *
     * <p><b>반려된 계정도 지울 수 있다</b>(2026-09-20). 반려는 "로그인 못 한다"까지만 정할 뿐
     * 목록에서 치우지는 않아서, 안 받기로 한 신청이 승인 화면에 계속 쌓였다. 지운 뒤에도 행은
     * 남으니 "언제 누가 반려했나"는 그대로 추적된다.</p>
     *
     * <p>⚠ <b>대기 중은 막는다.</b> 아직 승인도 반려도 안 한 신청을 지우면 신청한 사람은
     * 영영 답을 못 받는다 — 그 줄에서 할 일은 승인이나 반려이지 삭제가 아니다.</p>
     */
    public void deactivate() {
        if (status == UserStatus.DELETED) {
            return;
        }
        if (status != UserStatus.ACTIVE && status != UserStatus.REJECTED) {
            throw new BusinessException(ErrorCode.INVALID_STATE);
        }
        status = UserStatus.DELETED;
    }

    /** 관리자 두 명이 같은 신청을 거의 동시에 누르면 나중 사람이 여기서 막힌다 */
    private void requireWaiting() {
        if (status != UserStatus.WAIT) {
            throw new BusinessException(ErrorCode.INVALID_STATE);
        }
    }

    /** 논리 삭제된 행은 상태 값과 무관하게 막는다 — 둘 중 하나만 바뀐 행이 있어도 열리지 않게 */
    public boolean isDeleted() {
        return status == UserStatus.DELETED || deletedAt != null;
    }
}

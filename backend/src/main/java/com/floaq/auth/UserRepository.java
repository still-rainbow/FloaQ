package com.floaq.auth;

import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserStatus;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {

    /** {@code loginId} 는 소문자로 정규화한 값을 넘긴다({@link AuthService#normalizeLoginId}) */
    Optional<User> findByLoginId(String loginId);

    boolean existsByLoginId(String loginId);

    /** 계정 관리 목록 — 상태를 골랐을 때 */
    Page<User> findByStatus(UserStatus status, Pageable pageable);

    /** 계정 관리 목록 — 상태를 안 골랐을 때. 비활성화(DELETED)만 뺀다(api.md §3.2) */
    Page<User> findByStatusNot(UserStatus status, Pageable pageable);
}

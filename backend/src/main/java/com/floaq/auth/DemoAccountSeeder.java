package com.floaq.auth;

import com.floaq.auth.entity.User;
import com.floaq.auth.entity.UserRole;
import com.floaq.auth.entity.UserStatus;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 시연 계정. {@code app.auth.seed-demo-accounts=true} 일 때만 돈다(local 프로파일).
 *
 * <p>스키마가 아니라 데이터라 Flyway 에 넣지 않았다 — 마이그레이션에 넣으면 운영 DB 에도
 * 알려진 비밀번호의 관리자 계정이 생긴다. 운영의 SA 은 운영자가 DB 로 만든다(api.md §3.1).</p>
 *
 * <p>이미 있는 계정은 건드리지 않는다. 비밀번호를 바꿔 두었으면 그대로 남는다.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "app.auth.seed-demo-accounts", havingValue = "true")
public class DemoAccountSeeder implements ApplicationRunner {

    /** 웹 로그인 화면의 시연 버튼(apps/web/src/lib/auth.ts {@code DEMO})과 같은 값이다. 바꾸면 둘 다 바꾼다 */
    static final String DEMO_PASSWORD = "floaq1234!";

    private record Demo(String loginId, String name, UserRole role, UserStatus status) {
    }

    private static final List<Demo> DEMOS = List.of(
            new Demo("admin@floaq.example", "운영 관리자", UserRole.SA, UserStatus.ACTIVE),
            new Demo("kim@kcg.example", "김민준", UserRole.A, UserStatus.ACTIVE),
            // 승인 대기 문구를 화면에서 확인하는 용도
            new Demo("park@kcg.example", "박서연", UserRole.A, UserStatus.WAIT));

    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;

    @Override
    public void run(ApplicationArguments args) {
        for (Demo demo : DEMOS) {
            if (users.existsByLoginId(demo.loginId())) {
                continue;
            }
            users.save(User.create(demo.loginId(), passwordEncoder.encode(DEMO_PASSWORD),
                    demo.name(), demo.role(), demo.status()));
            log.info("시연 계정 생성 - {} ({}, {})", demo.loginId(), demo.role(), demo.status());
        }
    }
}

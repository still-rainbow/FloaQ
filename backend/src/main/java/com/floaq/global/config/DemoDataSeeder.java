package com.floaq.global.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;

/**
 * 시연 데이터를 <b>서버를 켤 때마다</b> 지금 기준으로 맞춘다.
 *
 * <p>🔴 {@code local} 프로필에서만 돈다. 운영에서는 이 빈 자체가 만들어지지 않는다.</p>
 *
 * <h3>왜 필요한가</h3>
 * <p>시연 데이터는 넣는 순간에만 최신이다. 하루가 지나면 하루 지난 사고가 되고, 저체온 생존
 * 상한의 두 배를 넘겨 전부 '장기 미종결'로 목록 맨 아래에 깔린다 — 그러면 사고 탭이 비어
 * 화면이 제대로 도는지 볼 수가 없다(2026-09-19).</p>
 *
 * <h3>왜 기동 시점인가</h3>
 * <p>화면을 보고 있는데 사고가 저절로 생기면 시연 중에 어색하다. 실제로 그 이유로
 * "몇 분마다 사고를 만드는 연출기"는 접었다. 반면 서버를 켜는 것은 <b>우리가 하는 일</b>이라
 * 시점이 예측 가능하고, 시연 도중에 재시작할 일은 없다.</p>
 *
 * <h3>안전장치</h3>
 * <ul>
 *   <li>프로필이 {@code local} 이 아니면 안 돈다 — EC2 는 {@code prod} 다</li>
 *   <li>스크립트가 <b>멱등</b>이다. 몇 번을 돌려도 사고가 늘지 않는다</li>
 *   <li>실패해도 <b>기동을 막지 않는다</b>. 시연 데이터가 없는 것보다 서버가 안 뜨는 쪽이 나쁘다</li>
 *   <li>스크립트가 건드리는 사고는 id 가 {@code 0000…0001%} 인 것뿐이다 —
 *       Pi 가 실제로 올린 행은 종결 대상이 될 뿐 지워지지 않는다</li>
 * </ul>
 */
@Slf4j
@Component
@Profile("local")
@RequiredArgsConstructor
public class DemoDataSeeder implements ApplicationRunner {

    private static final String SCRIPT = "db/demo/refresh_demo.sql";

    private final DataSource dataSource;

    @Override
    public void run(ApplicationArguments args) {
        try (Connection c = dataSource.getConnection()) {
            ScriptUtils.executeSqlScript(c, new ClassPathResource(SCRIPT));
            log.info("시연 데이터를 지금 기준으로 맞췄습니다 ({}). local 프로필에서만 돕니다.", SCRIPT);
        } catch (Exception e) {
            // 기동은 계속한다. 데이터가 낡은 채로 뜨는 편이 서버가 안 뜨는 것보다 낫다
            log.warn("시연 데이터 새로고침을 건너뜁니다 — {}", e.getMessage());
        }
    }
}

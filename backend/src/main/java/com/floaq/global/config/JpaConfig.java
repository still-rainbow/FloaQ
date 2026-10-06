package com.floaq.global.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

/** {@code @CreatedDate}·{@code @LastModifiedDate} 를 켠다 (BaseTimeEntity). */
@Configuration
@EnableJpaAuditing
public class JpaConfig {
}

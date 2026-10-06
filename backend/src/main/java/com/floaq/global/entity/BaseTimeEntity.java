package com.floaq.global.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.MappedSuperclass;
import lombok.Getter;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.Instant;

/**
 * 생성·수정 시각.
 *
 * <p><b>{@link Instant} 를 쓰고 {@code LocalDateTime} 을 쓰지 않는다.</b>
 * LocalDateTime 은 타임존 정보가 없어 사고 경위를 재구성할 때 어긋난다(계획.md §2).
 * UTC 로 저장하고 표시 시점에 Asia/Seoul 로 바꾼다.</p>
 *
 * <p><b>{@code updatedAt} 이 EC2 동기화의 워터마크다.</b> 이 컬럼이 없으면
 * "지난번 동기화 이후 바뀐 행"을 고를 수 없다 — ERD 검토에서 빠져 있다고 지적한 항목이다
 * ([[260910_mqtt-erd-review]] §3.4).</p>
 */
@Getter
@MappedSuperclass
@EntityListeners(AuditingEntityListener.class)
public abstract class BaseTimeEntity {

    @CreatedDate
    @Column(updatable = false)
    private Instant createdAt;

    @LastModifiedDate
    private Instant updatedAt;
}

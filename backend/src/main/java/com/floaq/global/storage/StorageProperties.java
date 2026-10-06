package com.floaq.global.storage;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

/**
 * 사고 영상·프레임 저장소 (계획.md §9.6 · api.md §3.6).
 *
 * <p><b>R2 전용이 아니라 S3 호환 저장소 설정이다.</b> 이름을 {@code app.r2} 로 두지 않은 이유 —
 * 계획.md 가 "로컬 MinIO / 운영 Cloudflare R2 로 하면 R2 키 없이 작업 가능하다. endpoint 만 갈아끼우면 된다" 고
 * 이미 정해 뒀다. 계정 ID 로 주소를 조립하면 그 갈아끼우기가 막힌다.</p>
 *
 * <p><b>Pi 는 이 키를 갖지 않는다.</b> 어선에 실린 물리 장비라 분해·도난을 전제한다 —
 * Pi 는 EC2 로 올리고 EC2 만 저장소에 넣는다(ref/mqtt-연동-웹_v2.md §11 · 계획.md §9.6).</p>
 *
 * <p>키는 저장소에 두지 않는다: infra/.env → compose environment → 환경변수 → application.yml 의 ${...}.</p>
 *
 * @param endpoint    S3 호환 엔드포인트. R2 는 {@code https://<account_id>.r2.cloudflarestorage.com}.
 *                    비면 저장소 기능이 꺼진다 — 주소를 지어내면 "키가 틀렸나 주소가 틀렸나"를 가를 수 없다
 * @param bucket      버킷 이름
 * @param presignTtl  재생용 presigned URL 수명. 기본 2시간 —
 *                    사고 영상 상한이 1시간(계획.md §9.6)이라 끝까지 재생하고도 탐색·재시청 여유가 남는 값이다.
 *                    ⚠ api.md §3.6 은 이 값을 "미정"으로 두고 있었다. 이 기본값이 그 제안이다
 */
@ConfigurationProperties(prefix = "app.storage")
public record StorageProperties(
        String endpoint,
        String accessKey,
        String secretKey,
        String bucket,
        @DefaultValue("2h") Duration presignTtl) {

    /** 넷이 다 있어야 쓸 수 있다. 하나라도 비면 저장소를 끈다 — 반만 설정된 상태로 뜨면 업로드 시점에야 터진다 */
    public boolean isConfigured() {
        return notBlank(endpoint) && notBlank(accessKey) && notBlank(secretKey) && notBlank(bucket);
    }

    private static boolean notBlank(String v) {
        return v != null && !v.isBlank();
    }
}

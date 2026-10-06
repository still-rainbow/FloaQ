package com.floaq.global.storage;

import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.checksums.RequestChecksumCalculation;
import software.amazon.awssdk.core.checksums.ResponseChecksumValidation;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.S3Exception;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;

/**
 * S3 호환 저장소 접근 (Cloudflare R2 · 로컬 MinIO).
 *
 * <p>DB 에는 {@code object_key} 만 둔다 — 바이너리를 넣지 않는다(계획.md §2 · V1 {@code video.object_key}).
 * 재생은 presigned GET URL 로 내준다(api.md §3.6) — 영상 바이트가 EC2 를 거치지 않는다.</p>
 *
 * <h2>🔴 R2 에서 반드시 꺼야 하는 둘</h2>
 * 이 둘을 모르면 업로드가 <b>전부</b> 실패하고, 원인 메시지가 그 이유를 말해 주지 않는다.
 * <ol>
 *   <li><b>checksum</b> — SDK 가 기본({@code WHEN_SUPPORTED})으로 CRC32 를 붙이는데 R2 가 거부한다.
 *       {@code WHEN_REQUIRED} 로 낮춘다. 응답 검증도 같이 낮춘다</li>
 *   <li><b>chunked encoding</b> — SDK 는 {@code putObject} 에 chunked transfer encoding 을 쓰는데
 *       R2 에서 <b>서명 불일치 403</b> 이 난다. {@code chunkedEncodingEnabled(false)}</li>
 * </ol>
 * (확인 2026-09-16 — aws/aws-sdk-java-v2 #6518 · Cloudflare R2 S3 호환 문서)
 *
 * <p>R2 에는 리전 개념이 없다. SDK 가 region 을 요구하므로 {@code auto} 를 넣는다.</p>
 *
 * <p><b>키가 없으면 빈을 만들지 않고 기동 경고만 남긴다</b>(KioskKey · PiApiKeyFilter 와 같은 방식).
 * 저장소가 없다고 앱이 안 뜨면 해양 데이터·사고 경보까지 같이 멈춘다 — 영상만 막히는 편이 낫다.</p>
 */
@Slf4j
@Component
public class ObjectStorage {

    /** R2 는 리전이 없다. SDK 필수 값이라 넣는 자리표시자 */
    private static final Region REGION = Region.of("auto");

    private final StorageProperties props;
    private final S3Client client;
    private final S3Presigner presigner;

    public ObjectStorage(StorageProperties props) {
        this.props = props;
        if (!props.isConfigured()) {
            // 조용히 꺼지면 "업로드가 왜 안 되지"를 원인 없이 겪는다
            log.warn("app.storage 미설정 — 사고 영상 업로드·재생이 막힙니다 (STORAGE_ENDPOINT·ACCESS_KEY·SECRET_KEY·BUCKET)");
            this.client = null;
            this.presigner = null;
            return;
        }
        var credentials = StaticCredentialsProvider.create(
                AwsBasicCredentials.create(props.accessKey(), props.secretKey()));
        URI endpoint = URI.create(props.endpoint());

        this.client = S3Client.builder()
                .endpointOverride(endpoint)
                .region(REGION)
                .credentialsProvider(credentials)
                // 🔴 위 클래스 주석 참고 — 이 셋 중 하나라도 빠지면 R2 업로드가 실패한다
                .requestChecksumCalculation(RequestChecksumCalculation.WHEN_REQUIRED)
                .responseChecksumValidation(ResponseChecksumValidation.WHEN_REQUIRED)
                .serviceConfiguration(S3Configuration.builder()
                        .chunkedEncodingEnabled(false)
                        .build())
                .build();
        this.presigner = S3Presigner.builder()
                .endpointOverride(endpoint)
                .region(REGION)
                .credentialsProvider(credentials)
                .build();
        log.info("저장소 준비됨 — {} · 버킷 {} · presign {}분",
                props.endpoint(), props.bucket(), props.presignTtl().toMinutes());
    }

    /** 설정이 없으면 false. 호출부가 503 을 내기 전에 이걸로 가른다 */
    public boolean isReady() {
        return client != null;
    }

    /**
     * 올린다. 같은 키면 덮어쓴다 — 재전송 멱등이 그 위에 선다(api.md §4.2).
     *
     * @throws BusinessException 저장소 미설정이거나 호출 실패 — {@code STORAGE_UNAVAILABLE} 503
     */
    public void put(String key, byte[] body, String contentType) {
        requireReady();
        try {
            client.putObject(PutObjectRequest.builder()
                            .bucket(props.bucket())
                            .key(key)
                            .contentType(contentType)
                            .build(),
                    RequestBody.fromBytes(body));
        } catch (S3Exception e) {
            // 메시지에 키·서명이 섞여 나올 수 있어 클라이언트에는 내보내지 않는다. 로그가 단서다
            log.error("저장소 업로드 실패 - key={} status={}", key, e.statusCode(), e);
            throw new BusinessException(ErrorCode.STORAGE_UNAVAILABLE);
        }
    }

    /**
     * 재생용 서명 URL. {@code <video src>} 에 그대로 쓴다(api.md §3.6).
     *
     * <p>바이트가 EC2 를 거치지 않는 것이 핵심이다 — 1시간 영상이 3.6GB 까지 간다(계획.md §9.6).</p>
     */
    public Presigned presignGet(String key) {
        requireReady();
        Duration ttl = props.presignTtl();
        var signed = presigner.presignGetObject(GetObjectPresignRequest.builder()
                .signatureDuration(ttl)
                .getObjectRequest(GetObjectRequest.builder().bucket(props.bucket()).key(key).build())
                .build());
        return new Presigned(signed.url().toString(), Instant.now().plus(ttl));
    }

    /** 있나. 인코딩 완료 판정처럼 "키만 있고 실제로 올라갔는지 모르는" 자리에서 쓴다 */
    public boolean exists(String key) {
        requireReady();
        try {
            client.headObject(HeadObjectRequest.builder().bucket(props.bucket()).key(key).build());
            return true;
        } catch (NoSuchKeyException e) {
            return false;
        } catch (S3Exception e) {
            log.error("저장소 조회 실패 - key={} status={}", key, e.statusCode(), e);
            throw new BusinessException(ErrorCode.STORAGE_UNAVAILABLE);
        }
    }

    private void requireReady() {
        if (!isReady()) {
            throw new BusinessException(ErrorCode.STORAGE_UNAVAILABLE);
        }
    }

    /** @param expiresAt api.md §3.6 의 {@code urlExpiresAt} */
    public record Presigned(String url, Instant expiresAt) {
    }

    @PreDestroy
    void close() {
        if (client != null) {
            client.close();
        }
        if (presigner != null) {
            presigner.close();
        }
    }
}

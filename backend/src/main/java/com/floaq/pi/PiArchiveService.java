package com.floaq.pi;

import com.floaq.global.Uuid7;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.storage.ObjectStorage;
import com.floaq.pi.dto.PiArchiveResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.zip.GZIPInputStream;

/**
 * 사고 산출물 묶음 수신 — {@code POST /api/pi/archives} (dev-iot {@code iot/pi/floaq/archive.py}).
 *
 * <h2>왜 장당 업로드와 따로 있나</h2>
 * <p>{@link PiFileService} 는 <b>장당 1요청</b>이고 이 서비스는 <b>사고 1건 = 묶음 1개</b>다.
 * 둘 다 살려 둔다 — Pi 가 <b>이미 묶음 쪽을 구현해 돌리고 있고</b>(별도 스레드로
 * {@code object_key IS NULL} 인 사고를 골라 부친다), 장당 경로는 Jetson→Pi 구간과 모양이 같아
 * 소규모 재전송에 쓰기 좋다. 우리가 한쪽을 막으면 <b>Pi 의 대기열이 영영 안 줄어든다.</b></p>
 *
 * <h2>tar 인가 mp4 인가 — 두 번 본다</h2>
 * <p>1차는 파트의 {@code Content-Type} 이다. Pi 가 이미 정확히 싣는다({@code application/gzip}).
 * <b>그러나 그것만으로 가르지 않는다</b> — 본문 타입은 보내는 쪽이 쓰는 값이라 증명이 아니다
 * ({@link PiController} 의 {@code callerShipId} 주석과 같은 원칙). 그래서 2차로
 * <b>매직 바이트</b>를 본다. 둘이 어긋나면 받지 않는다.</p>
 *
 * <pre>
 *   gzip  1f 8b        (0바이트)     → 풀고 나서 다시 tar 인지 본다
 *   tar   ustar        (257바이트)
 *   mp4   ftyp         (4바이트)
 * </pre>
 *
 * <p>⚠ Pi 주석이 <i>api.json 이 압축 여부를 안 적어서 gzip 을 건다 · 무압축 tar 도 받는지
 * 웹 팀 확인 필요</i> 로 남아 있다. <b>둘 다 받는다.</b> 그러면 그 미정이 사라진다.</p>
 *
 * <h2>객체 키는 묶음 안 이름을 쓰지 않는다</h2>
 * <p>🔴 멤버 이름은 <b>보내는 쪽이 쓰는 문자열</b>이다. 키를 만들 때는 manifest 의
 * {@code (file_type, sequence_no)} 로 {@link PiFileService} 와 <b>같은 규칙</b>을 다시 계산한다 —
 * 그래야 선내 로컬 경로·R2 키·웹 URL 이 계속 같은 문자열로 남는다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiArchiveService {

    /** {@code accident_file.file_type} CHECK 와 같은 값이어야 한다 */
    private static final Set<String> FILE_TYPES = Set.of("DETECT_SNAPSHOT", "BEFORE", "AFTER");

    /** 확장자가 객체 키에 그대로 들어간다. 화이트리스트로 둔다 */
    private static final Map<String, String> IMAGE_EXT =
            Map.of("jpg", "jpg", "jpeg", "jpg", "png", "png");

    /**
     * 한 묶음에서 꺼낼 최대 파일 수. Pi 의 {@code MAX_FILES = 200} 의 두 배로 둔다 —
     * 상대가 늘려도 바로 막히지 않되, <b>묶음 폭탄이 무한히 돌지는 않게</b> 상한은 둔다.
     */
    private static final int MAX_ENTRIES = 400;

    /**
     * 풀었을 때 허용할 총 바이트. gzip 은 <b>작은 본문이 거대하게 풀릴 수 있다</b>(폭탄).
     * multipart 상한(32MB)과 별개로 여기서 한 번 더 끊는다. 사고 하나가 126장 × 200KB 로
     * 약 25MB 라, 96MB 면 정상 묶음은 절대 안 걸린다.
     */
    private static final long MAX_INFLATED_BYTES = 96L * 1024 * 1024;

    /** 한 장 최대. 프레임 하나가 이보다 크면 형식이 잘못된 것이다 */
    private static final int MAX_MEMBER_BYTES = 8 * 1024 * 1024;

    private static final String MANIFEST = "manifest.json";

    private static final String UPSERT_FILE = """
            INSERT INTO accident_file (file_id, accident_id, file_type, sequence_no,
                                       object_key, content_type, camera, bytes, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (accident_id, file_type, sequence_no) DO UPDATE
               SET object_key   = EXCLUDED.object_key,
                   content_type = EXCLUDED.content_type,
                   camera       = EXCLUDED.camera,
                   bytes        = EXCLUDED.bytes,
                   captured_at  = EXCLUDED.captured_at,
                   updated_at   = now()
            """;

    private final ObjectStorage storage;
    private final JdbcTemplate jdbc;
    private final PiIngestSupport support;

    /**
     * 묶음 하나를 받는다.
     *
     * @param sha256 Pi 가 계산한 묶음 해시. <b>맞춰 본다</b> — 전송 중 잘린 묶음을 풀면
     *               앞부분만 저장되고, Pi 는 키를 받은 장을 완료로 표시하므로
     *               <b>나머지를 영영 다시 안 보낸다.</b>
     */
    public PiArchiveResponse receive(UUID accidentId, UUID callerShipId, MultipartFile archive,
                                     String sha256, Long createdAt) {
        support.requireApprovedShip(callerShipId);
        // 남의 사고에 끼워 넣을 수 없다. 존재만 보면 그게 열린다
        if (!support.ownsAccident(accidentId, callerShipId)) {
            throw new BusinessException(ErrorCode.ACCIDENT_NOT_FOUND);
        }
        byte[] body = readBytes(archive);
        requireDigest(body, sha256);

        Kind kind = sniff(archive.getContentType(), body);
        return switch (kind) {
            case MP4 -> storeVideo(accidentId, body, createdAt);
            case TAR -> storeTar(accidentId, body);
            case GZIP -> storeTar(accidentId, gunzip(body));
        };
    }

    private enum Kind { GZIP, TAR, MP4 }

    /**
     * MIME 으로 고르고 매직으로 확인한다. 어긋나면 받지 않는다.
     *
     * <p>MIME 이 비어 있거나 {@code application/octet-stream} 이어도 매직만 맞으면 받는다 —
     * 중계 한 단만 거쳐도 타입이 뭉개지는데, 그 때문에 사진을 잃을 이유가 없다.</p>
     */
    private Kind sniff(String contentType, byte[] body) {
        String mime = contentType == null ? ""
                : contentType.split(";")[0].trim().toLowerCase(Locale.ROOT);
        Kind byMagic = magic(body);
        if (byMagic == null) {
            log.warn("[pi] 묶음 형식을 알 수 없다 (content-type={}, {}바이트)", mime, body.length);
            throw new BusinessException(ErrorCode.MEDIA_UNSUPPORTED_TYPE);
        }
        Kind byMime = switch (mime) {
            case "application/gzip", "application/x-gzip" -> Kind.GZIP;
            case "application/x-tar", "application/tar" -> Kind.TAR;
            case "video/mp4" -> Kind.MP4;
            default -> null;
        };
        if (byMime != null && byMime != byMagic) {
            // 🔴 조용히 매직을 따르지 않는다. 둘이 다르면 보내는 쪽이 뭔가 잘못 알고 있는 것이고,
            //    그대로 저장하면 그 오해가 R2 에 굳는다
            log.warn("[pi] 묶음 형식 불일치 — content-type={} 인데 내용은 {}", mime, byMagic);
            throw new BusinessException(ErrorCode.MEDIA_UNSUPPORTED_TYPE);
        }
        return byMagic;
    }

    /**
     * 매직 바이트. 문자 리터럴 대신 16진수로 적는다 — ustar·ftyp 을 눈으로 세는 것보다
     * 바이트 값이 명세와 바로 대조된다.
     *
     * @return 모르는 형식이면 null
     */
    private Kind magic(byte[] b) {
        if (b.length >= 2 && u(b, 0) == 0x1F && u(b, 1) == 0x8B) {
            return Kind.GZIP;                       // gzip
        }
        // mp4: 4바이트째부터 ftyp (ISO base media)
        if (b.length >= 12 && u(b, 4) == 0x66 && u(b, 5) == 0x74
                && u(b, 6) == 0x79 && u(b, 7) == 0x70) {
            return Kind.MP4;
        }
        // tar: 257바이트째부터 ustar. 빈 묶음도 512바이트는 있다
        if (b.length >= 262 && u(b, 257) == 0x75 && u(b, 258) == 0x73 && u(b, 259) == 0x74
                && u(b, 260) == 0x61 && u(b, 261) == 0x72) {
            return Kind.TAR;
        }
        return null;
    }

    private static int u(byte[] b, int i) {
        return b[i] & 0xFF;
    }

    /**
     * 받은 mp4 를 손대지 않고 R2 에 넣는다.
     *
     * <p>키에 {@code created_at} 을 쓰는 이유: <b>같은 묶음을 다시 보내면 같은 키여야 한다.</b>
     * 해시를 쓰면 재인코딩으로 바이트가 1비트만 달라져도 새 객체가 쌓인다.</p>
     *
     * <p>⚠ 지금 이 경로로 보내는 쪽이 없다 — Pi 의 manifest 에 videos 자리는 있으나 주석이
     * <i>pi_video 는 아직 생성하는 코드가 없다</i> 로 되어 있다. 계약을 먼저 열어 둔다.</p>
     */
    private PiArchiveResponse storeVideo(UUID accidentId, byte[] body, Long createdAt) {
        long stamp = createdAt == null ? System.currentTimeMillis() / 1000 : createdAt;
        String objectKey = "accidents/%s/video/%d.mp4".formatted(accidentId, stamp);
        boolean duplicated = !jdbc.queryForList(
                "SELECT 1 FROM video WHERE accident_id = ? AND object_key = ?",
                Integer.class, accidentId, objectKey).isEmpty();

        storage.put(objectKey, body, "video/mp4");
        if (!duplicated) {
            jdbc.update("INSERT INTO video (accident_id, object_key, created_at) VALUES (?, ?, now())",
                    accidentId, objectKey);
        }
        log.info("[pi] 사고 {} mp4 {}바이트 저장 — {}", accidentId, body.length, objectKey);
        return new PiArchiveResponse(1, duplicated ? 0 : 1, duplicated ? 1 : 0, 0,
                List.of(new PiArchiveResponse.Stored(objectKey, "VIDEO", null, null, duplicated)));
    }

    private PiArchiveResponse storeTar(UUID accidentId, byte[] tar) {
        Map<String, JsonNode> manifest = new LinkedHashMap<>();
        Map<String, byte[]> members = new LinkedHashMap<>();
        readTar(tar, manifest, members);

        List<PiArchiveResponse.Stored> stored = new ArrayList<>();
        int duplicated = 0;
        int failed = 0;

        for (Map.Entry<String, JsonNode> e : manifest.entrySet()) {
            byte[] data = members.get(e.getKey());
            if (data == null) {
                // manifest 에는 있는데 묶음에 없다. Pi 가 크기 상한에 걸려 자른 자리일 수 있다
                log.warn("[pi] 사고 {}: manifest 의 {} 가 묶음에 없다 — 건너뛴다", accidentId, e.getKey());
                failed++;
                continue;
            }
            try {
                PiArchiveResponse.Stored one = putOne(accidentId, e.getValue(), data);
                stored.add(one);
                if (one.duplicated()) {
                    duplicated++;
                }
            } catch (RuntimeException ex) {
                // 한 장이 깨져도 나머지는 올린다. Pi 는 키를 못 받은 장만 다음 회차에 다시 보낸다
                log.error("[pi] 사고 {}: {} 저장 실패 — {}", accidentId, e.getKey(), ex.toString());
                failed++;
            }
        }
        log.info("[pi] 사고 {} 묶음 {}장 중 {}장 저장 (중복 {} · 실패 {})",
                accidentId, manifest.size(), stored.size(), duplicated, failed);
        return new PiArchiveResponse(manifest.size(), stored.size(), duplicated, failed, stored);
    }

    private PiArchiveResponse.Stored putOne(UUID accidentId, JsonNode entry, byte[] data) {
        String fileType = text(entry, "file_type");
        if (!FILE_TYPES.contains(fileType)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        Integer sequenceNo = entry.path("sequence_no").isIntegralNumber()
                ? entry.path("sequence_no").asInt() : null;
        if (sequenceNo != null && (sequenceNo < 0 || sequenceNo > 99_999)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        String camera = text(entry, "camera");
        if (camera != null && !"L".equals(camera) && !"R".equals(camera)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        // 🔴 묶음 안 이름이 아니라 manifest 의 (type, seq) 로 키를 다시 만든다
        String ext = extensionOf(text(entry, "name"));
        String seq = sequenceNo == null ? "snapshot" : String.format(Locale.ROOT, "%04d", sequenceNo);
        String objectKey = "accidents/%s/%s/%s.%s".formatted(accidentId, fileType, seq, ext);
        boolean duplicated = alreadyStored(accidentId, fileType, sequenceNo);
        String contentType = "png".equals(ext) ? "image/png" : "image/jpeg";
        Long capturedAt = entry.path("created_at").isIntegralNumber()
                ? entry.path("created_at").asLong() : null;

        // R2 먼저, DB 나중. 그 사이 죽으면 R2 엔 있고 DB 가 모르는 고아가 남는데,
        // 반대(DB 먼저)는 관제 화면이 없는 사진을 가리켜 깨진 이미지가 뜬다 (PiFileService 와 같은 판단)
        storage.put(objectKey, data, contentType);
        jdbc.update(UPSERT_FILE, ps -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, accidentId);
            ps.setString(3, fileType);
            PiBind.setInt(ps, 4, sequenceNo);
            ps.setString(5, objectKey);
            ps.setString(6, contentType);
            PiBind.setText(ps, 7, camera);
            ps.setInt(8, data.length);
            PiBind.setEpoch(ps, 9, capturedAt);
        });
        return new PiArchiveResponse.Stored(objectKey, fileType, sequenceNo, camera, duplicated);
    }

    /**
     * 묶음을 한 번만 훑어 manifest 와 멤버를 동시에 모은다.
     *
     * <p>🔴 <b>디스크에 쓰지 않는다.</b> 경로 탈출을 막는 가장 확실한 방법은 파일 시스템을
     * 안 쓰는 것이다 — 멤버 이름은 <b>manifest 와 맞춰 보는 열쇠로만</b> 쓰고
     * 경로로는 절대 쓰지 않는다.</p>
     */
    private void readTar(byte[] tar, Map<String, JsonNode> manifest, Map<String, byte[]> members) {
        long total = 0;
        int count = 0;
        try (TarArchiveInputStream in = new TarArchiveInputStream(new ByteArrayInputStream(tar))) {
            TarArchiveEntry entry;
            while ((entry = in.getNextEntry()) != null) {
                if (!entry.isFile()) {
                    continue;                       // 디렉터리·링크는 무시한다. 우리가 쓰는 건 파일뿐이다
                }
                if (++count > MAX_ENTRIES) {
                    log.warn("[pi] 묶음 항목이 {}개를 넘는다 — 거부", MAX_ENTRIES);
                    throw new BusinessException(ErrorCode.MEDIA_TOO_LARGE);
                }
                byte[] data = in.readAllBytes();
                total += data.length;
                if (data.length > MAX_MEMBER_BYTES || total > MAX_INFLATED_BYTES) {
                    log.warn("[pi] 묶음이 풀었을 때 너무 크다 ({}바이트) — 거부", total);
                    throw new BusinessException(ErrorCode.MEDIA_TOO_LARGE);
                }
                if (MANIFEST.equals(entry.getName())) {
                    readManifest(data, manifest);
                } else {
                    members.put(entry.getName(), data);
                }
            }
        } catch (IOException e) {
            log.warn("[pi] 묶음을 풀지 못했다: {}", e.toString());
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        if (manifest.isEmpty()) {
            // manifest 가 없으면 무엇이 무엇인지 알 수 없다. 이름으로 유추하지 않는다
            log.warn("[pi] 묶음에 {} 가 없다 — 거부", MANIFEST);
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

    private void readManifest(byte[] data, Map<String, JsonNode> out) {
        JsonNode doc = JsonMapper.builder().build().readTree(data);
        for (JsonNode f : doc.path("files")) {
            String name = text(f, "name");
            if (name != null) {
                out.put(name, f);
            }
        }
    }

    /**
     * 해시가 안 맞으면 <b>하나도 저장하지 않는다.</b> 잘린 묶음을 풀면 앞부분만 들어가는데,
     * Pi 는 키를 받은 장을 완료로 표시하므로 <b>나머지를 영영 다시 안 보낸다.</b>
     */
    private void requireDigest(byte[] body, String sha256) {
        if (sha256 == null || sha256.isBlank()) {
            return;                                 // 안 보내는 클라이언트도 받는다 — 있으면 확인할 뿐이다
        }
        try {
            String actual = HexFormat.of()
                    .formatHex(MessageDigest.getInstance("SHA-256").digest(body));
            if (!actual.equalsIgnoreCase(sha256.trim())) {
                log.warn("[pi] 묶음 해시 불일치 — 보낸 값 {} · 실제 {}", sha256, actual);
                throw new BusinessException(ErrorCode.INVALID_INPUT);
            }
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 이 없는 JVM", e);
        }
    }

    private byte[] readBytes(MultipartFile file) {
        try (InputStream in = file.getInputStream()) {
            return in.readAllBytes();
        } catch (IOException e) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

    private byte[] gunzip(byte[] body) {
        try (GZIPInputStream in = new GZIPInputStream(new ByteArrayInputStream(body))) {
            // 풀린 크기를 여기서도 끊는다. readTar 는 이미 푼 바이트를 받으므로 그 전에 막아야 한다
            byte[] out = in.readNBytes((int) MAX_INFLATED_BYTES + 1);
            if (out.length > MAX_INFLATED_BYTES) {
                log.warn("[pi] gzip 이 {}바이트를 넘게 풀린다 — 거부", MAX_INFLATED_BYTES);
                throw new BusinessException(ErrorCode.MEDIA_TOO_LARGE);
            }
            return out;
        } catch (IOException e) {
            log.warn("[pi] gzip 을 풀지 못했다: {}", e.toString());
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

    private String extensionOf(String memberName) {
        int dot = memberName == null ? -1 : memberName.lastIndexOf(".");
        String raw = dot < 0 ? "" : memberName.substring(dot + 1).toLowerCase(Locale.ROOT);
        String ext = IMAGE_EXT.get(raw);
        if (ext == null) {
            throw new BusinessException(ErrorCode.MEDIA_UNSUPPORTED_TYPE);
        }
        return ext;
    }

    private boolean alreadyStored(UUID accidentId, String fileType, Integer sequenceNo) {
        // ⚠ IS NOT DISTINCT FROM 이다. sequence_no 가 NULL 인 DETECT_SNAPSHOT 은 등호로 안 잡힌다
        return !jdbc.queryForList(
                "SELECT 1 FROM accident_file WHERE accident_id = ? AND file_type = ?"
                        + " AND sequence_no IS NOT DISTINCT FROM ?",
                Integer.class, accidentId, fileType, sequenceNo).isEmpty();
    }

    private static String text(JsonNode node, String field) {
        JsonNode v = node.path(field);
        return v.isString() ? v.asString() : null;
    }
}

package com.floaq.pi;

import com.floaq.global.Uuid7;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.storage.ObjectStorage;
import com.floaq.pi.dto.PiFileResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 사고 파일 업로드 — Pi → EC2 → R2 (ref/mqtt-연동-웹_v2 §11 · 계획.md §9.6).
 *
 * <p><b>Pi 는 R2 자격증명을 갖지 않는다.</b> 어선에 실린 물리 장비라 분해·도난을 전제한다 —
 * Pi 가 EC2 로 올리고 <b>EC2 만</b> 저장소에 넣는다. 그래서 바이트가 여기를 한 번 거친다.</p>
 *
 * <p><b>이 경로는 파일 하나당 요청 하나다.</b> 묶으면 부분 실패가 지저분해지고, 150장 중 3장이
 * 깨졌을 때 무엇을 다시 보낼지 알기 어렵다 — Jetson→Pi 구간이 장당 1요청인 이유도 같다.</p>
 *
 * <p>🔴 ~~tar 묶음은 기각했다~~ — <b>뒤집혔다 (2026-09-18).</b> dev-iot 를 읽어 보니
 * {@code iot/pi/floaq/archive.py} 가 {@code POST /api/pi/archives} 를 <b>이미 구현해 돌리고 있었다</b>
 * (별도 스레드로 {@code object_key IS NULL} 인 사고를 골라 부친다). 우리가 안 받는 동안
 * 그 요청은 404 였다. {@link PiArchiveService} 가 그 자리를 메운다 — <b>둘 다 산다.</b>
 * 부분 실패 문제는 묶음 쪽에서 장별 {@code failed} 카운트와 장별 {@code object_key} 응답으로 푼다.</p>
 *
 * <h2>객체 키가 Pi 로컬 경로와 같은 문자열인 이유</h2>
 * dev-iot {@code iot/pi/floaq/web/files.py} 가 {@code accidents/{accident_id}/{file_type}/{seq:04d}.{ext}}
 * 로 맞춰 뒀다. <b>선내 화면은 Pi 로컬 HTTP 에서, 육상 웹은 R2 에서</b> 같은 키로 같은 장을 가리킨다 —
 * 키오스크가 R2 를 보면 선내 화면이 인터넷에 의존하게 되고, 사고 상황에서 인터넷이 가장 먼저 끊긴다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiFileService {

    /** {@code pi_accident_file.file_type} CHECK 와 같은 값이어야 한다 */
    private static final Set<String> FILE_TYPES = Set.of("DETECT_SNAPSHOT", "BEFORE", "AFTER");

    /**
     * 받아들일 형식. <b>화이트리스트로 둔다</b> — 확장자가 객체 키에 그대로 들어가므로
     * 입력에서 온 문자열을 경로에 붙이면 안 된다(Pi {@code files.py} 와 같은 규칙).
     */
    private static final Map<String, String> EXTENSIONS =
            Map.of("image/jpeg", "jpg", "image/png", "png");

    /** Pi {@code files.py} 와 같은 범위. 0~99999 밖이면 {@code %04d} 가 자릿수를 넘긴다 */
    private static final int MAX_SEQUENCE_NO = 99_999;

    private final ObjectStorage storage;
    private final JdbcTemplate jdbc;
    private final PiIngestSupport support;

    /**
     * 멱등키는 {@code (accident_id, file_type, sequence_no)} 다(§11).
     *
     * <p>🔴 {@code DETECT_SNAPSHOT} 은 {@code sequence_no} 가 NULL 이라
     * 대응 제약이 {@code NULLS NOT DISTINCT} 여야 한다 — 평범한 UNIQUE 면 재전송이 그대로 중복된다.</p>
     */
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

    /**
     * 한 장 올린다.
     *
     * <p><b>트랜잭션 안에서 R2 를 부르지 않는다.</b> 업로드가 수 초 걸릴 수 있어
     * DB 커넥션을 그동안 잡고 있으면 초당 들어오는 시계열 수신이 커넥션 풀에서 굶는다.
     * 그래서 R2 먼저, DB 나중이다 — 그 사이 죽으면 <b>R2 에는 있고 DB 가 모르는 객체</b>가 남는다.
     * 반대(DB 먼저)보다 낫다: 그쪽은 관제 화면이 없는 사진을 가리켜 깨진 이미지가 뜬다.
     * 고아 객체는 같은 키로 재전송되면 덮어써져 저절로 회수된다.</p>
     *
     * @return 저장된 객체 키. <b>Pi 는 이 값을 받아야 그 장을 업로드 완료로 표시한다</b>
     */
    public PiFileResponse upload(UUID accidentId, UUID callerShipId, MultipartFile file,
                                 String fileType, Integer sequenceNo, String camera,
                                 Long capturedAt) {
        support.requireApprovedShip(callerShipId);
        // 남의 사고에 사진을 끼워 넣을 수 없다. 존재만 보면 그게 열린다
        if (!support.ownsAccident(accidentId, callerShipId)) {
            throw new BusinessException(ErrorCode.ACCIDENT_NOT_FOUND);
        }

        String type = normalizeFileType(fileType);
        String ext = extensionOf(file);
        requireSequence(type, sequenceNo);
        requireCamera(camera);
        byte[] body = readBytes(file);

        String objectKey = objectKey(accidentId, type, sequenceNo, ext);
        boolean duplicated = alreadyStored(accidentId, type, sequenceNo);

        // 같은 키면 덮어쓴다. 재전송이라도 내용이 바뀌었을 수 있어 새로 올리는 쪽이 맞다 —
        // Pi 의 test_reupload_clears_object_key 가 같은 판단이다
        storage.put(objectKey, body, file.getContentType());
        record(accidentId, type, sequenceNo, objectKey, file.getContentType(), camera,
                body.length, capturedAt);

        return new PiFileResponse(objectKey, duplicated);
    }

    /**
     * ⚠ {@code @Transactional} 을 붙이지 않는다. 두 가지 이유 —
     * ① statement 하나라 그 자체로 원자적이다. ② 이 메서드는 같은 클래스 안에서 불리므로
     * 프록시를 타지 않아 애초에 적용되지도 않는다(self-invocation).
     * 트랜잭션이 필요해지면 호출부를 별 빈으로 빼야 한다.
     */
    private void record(UUID accidentId, String fileType, Integer sequenceNo, String objectKey,
                        String contentType, String camera, int bytes, Long capturedAt) {
        jdbc.update(UPSERT_FILE, ps -> {
            ps.setObject(1, Uuid7.next());
            ps.setObject(2, accidentId);
            ps.setString(3, fileType);
            PiBind.setInt(ps, 4, sequenceNo);
            ps.setString(5, objectKey);
            ps.setString(6, contentType);
            PiBind.setText(ps, 7, camera);
            ps.setInt(8, bytes);
            PiBind.setEpoch(ps, 9, capturedAt);
        });
    }

    /**
     * {@code accidents/{accident_id}/{file_type}/{0001|snapshot}.{ext}}.
     *
     * <p>조립에 들어가는 셋이 전부 형태가 강제된 값이다 — {@code accidentId} 는 {@link UUID},
     * {@code fileType} 은 화이트리스트, {@code sequenceNo} 는 범위 검사를 통과한 정수.
     * <b>문자열을 그대로 붙이는 자리가 없다</b>(Pi {@code files.py} 의 {@code BadPath} 와 같은 방어).</p>
     */
    private String objectKey(UUID accidentId, String fileType, Integer sequenceNo, String ext) {
        String name = sequenceNo == null ? "snapshot" : String.format(Locale.ROOT, "%04d", sequenceNo);
        return "accidents/%s/%s/%s.%s".formatted(accidentId, fileType, name, ext);
    }

    private boolean alreadyStored(UUID accidentId, String fileType, Integer sequenceNo) {
        // ⚠ IS NOT DISTINCT FROM 이다. sequence_no 가 NULL 인 DETECT_SNAPSHOT 은 `= ?` 로 안 잡힌다
        List<Integer> hit = jdbc.queryForList(
                "SELECT 1 FROM accident_file WHERE accident_id = ? AND file_type = ?"
                        + " AND sequence_no IS NOT DISTINCT FROM ?",
                Integer.class, accidentId, fileType, sequenceNo);
        return !hit.isEmpty();
    }

    private String normalizeFileType(String fileType) {
        String type = fileType == null ? "" : fileType.trim().toUpperCase(Locale.ROOT);
        if (!FILE_TYPES.contains(type)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        return type;
    }

    /**
     * {@code Content-Type} 으로 확장자를 정한다. 파일 이름은 보지 않는다 —
     * 이름은 보내는 쪽이 쓰는 값이고 경로 조립에 들어가면 안 된다.
     */
    private String extensionOf(MultipartFile file) {
        String contentType = file.getContentType();
        String base = contentType == null ? "" : contentType.split(";")[0].trim().toLowerCase(Locale.ROOT);
        String ext = EXTENSIONS.get(base);
        if (ext == null) {
            throw new BusinessException(ErrorCode.MEDIA_UNSUPPORTED_TYPE);
        }
        return ext;
    }

    /**
     * 프레임은 순번이 있어야 한다 — 사고 전 30초가 150장이라 <b>순서 없이는 재생이 안 된다</b>
     * (상세기획 §6.1). 스냅샷은 한 장뿐이라 없어도 된다.
     */
    private void requireSequence(String fileType, Integer sequenceNo) {
        if (sequenceNo == null) {
            if (!"DETECT_SNAPSHOT".equals(fileType)) {
                throw new BusinessException(ErrorCode.INVALID_INPUT);
            }
            return;
        }
        if (sequenceNo < 0 || sequenceNo > MAX_SEQUENCE_NO) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

    private void requireCamera(String camera) {
        if (camera != null && !"L".equals(camera) && !"R".equals(camera)) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

    /**
     * 빈 본문을 막는다. 0바이트도 R2 는 받아 주기 때문에,
     * 여기서 안 막으면 <b>관제 화면에 깨진 이미지가 뜨고 원인이 안 보인다</b>.
     */
    private byte[] readBytes(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
        try {
            return file.getBytes();
        } catch (IOException e) {
            log.error("업로드 본문을 읽지 못했다 - size={}", file.getSize(), e);
            throw new BusinessException(ErrorCode.INVALID_INPUT);
        }
    }

}

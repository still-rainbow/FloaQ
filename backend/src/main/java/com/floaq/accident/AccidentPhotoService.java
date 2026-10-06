package com.floaq.accident;

import com.floaq.accident.dto.PhotosView;
import com.floaq.accident.dto.PhotosView.Photo;
import com.floaq.global.storage.ObjectStorage;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.List;
import java.util.UUID;

/**
 * 사고 사진 — 관제 화면이 <b>읽는</b> 쪽. 쓰는 쪽은 Pi 수신({@code PiFileService}·{@code PiArchiveService})이다.
 *
 * <p>🔴 전에는 이 경로가 없었다. Pi 는 사진을 R2 에 올리고 {@code accident_file} 에 적고 있었는데
 * <b>관제 웹이 읽을 길이 없어</b> 화면은 늘 "받지 못했습니다"였다(2026-09-21).</p>
 *
 * <p>JPA 엔티티를 두지 않고 JDBC 로 읽는다 — 쓰는 쪽(Pi 수신)이 이미 JDBC 로 쓰고 있고,
 * 여기서 필요한 건 두 줄뿐이라 엔티티를 새로 만들 이유가 없다.</p>
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AccidentPhotoService {

    /** 감지 순간 한 장. {@code sequence_no} 가 NULL 인 유일한 종류다 */
    private static final String DETECT = """
            SELECT object_key, captured_at, camera, sequence_no FROM accident_file
             WHERE accident_id = ? AND file_type = 'DETECT_SNAPSHOT'
             ORDER BY created_at DESC LIMIT 1
            """;

    /**
     * 사고 뒤 가장 최근 한 장. 찍힌 시각이 먼저고, 같으면 순번으로 가른다 —
     * 두 카메라(L·R)가 같은 초에 찍을 수 있다.
     */
    private static final String LATEST = """
            SELECT object_key, captured_at, camera, sequence_no FROM accident_file
             WHERE accident_id = ? AND file_type = 'AFTER'
             ORDER BY captured_at DESC NULLS LAST, sequence_no DESC NULLS LAST LIMIT 1
            """;

    private final AccidentQueryService query;
    private final JdbcTemplate jdbc;
    private final ObjectStorage storage;

    /**
     * 볼 수 있는 사고만 답한다 — 범위 밖은 {@link AccidentQueryService} 가 404 로 막는다.
     *
     * <p>저장소가 꺼져 있으면(로컬은 대개 R2 열쇠가 없다) 행이 있어도 주소를 못 만든다.
     * 그때는 빈 값이다 — 오류로 만들면 화면이 사고 상세 전체를 실패로 그린다.</p>
     */
    public PhotosView photos(UUID accidentId) {
        query.requireVisible(accidentId);
        if (!storage.isReady()) {
            return PhotosView.empty();
        }
        return new PhotosView(one(DETECT, accidentId), one(LATEST, accidentId));
    }

    private Photo one(String sql, UUID accidentId) {
        List<Photo> rows = jdbc.query(sql, (rs, i) -> toPhoto(rs), accidentId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Photo toPhoto(ResultSet rs) throws SQLException {
        var signed = storage.presignGet(rs.getString("object_key"));
        Timestamp at = rs.getTimestamp("captured_at");
        int seq = rs.getInt("sequence_no");
        return new Photo(signed.url(), signed.expiresAt(),
                at == null ? null : at.toInstant(),
                rs.getString("camera"),
                rs.wasNull() ? null : seq);
    }
}

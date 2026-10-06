package com.floaq.pi;

import com.floaq.global.error.BusinessException;
import com.floaq.global.storage.ObjectStorage;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.zip.GZIPOutputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Pi 계약 검증. <b>여기서 깨지면 Pi 의 업로드 대기열이 영영 안 줄어든다</b> —
 * dev-iot {@code archive.py} 의 {@code _apply()} 가 응답을 못 읽으면 재시도가 아니라
 * 그 사고를 포기하기 때문이다.
 */
class PiArchiveServiceTest {

    private static final UUID ACCIDENT = UUID.fromString("01a0b234-0493-7b94-ba10-9a8f080326ee");
    private static final UUID SHIP = UUID.fromString("01a0b232-5568-7188-996d-b7fa311d04a5");

    private ObjectStorage storage;
    private JdbcTemplate jdbc;
    private PiArchiveService service;
    private List<String> putKeys;

    @BeforeEach
    void setUp() {
        storage = mock(ObjectStorage.class);
        jdbc = mock(JdbcTemplate.class);
        PiIngestSupport support = mock(PiIngestSupport.class);
        when(support.ownsAccident(any(), any())).thenReturn(true);
        // 중복 판정: 기본은 "없던 것"
        when(jdbc.queryForList(anyString(), any(Class.class), any(Object[].class)))
                .thenReturn(List.of());
        putKeys = new ArrayList<>();
        service = new PiArchiveService(storage, jdbc, support);
    }

    /** Pi 가 실제로 보내는 모양 그대로 만든다 (archive.py build_tarball) */
    private static byte[] tarball(boolean gzip) throws IOException {
        ByteArrayOutputStream raw = new ByteArrayOutputStream();
        try (TarArchiveOutputStream tar = new TarArchiveOutputStream(raw)) {
            add(tar, "accidents/x/BEFORE/0001.jpg", new byte[]{1, 2, 3});
            add(tar, "accidents/x/DETECT_SNAPSHOT/snapshot.jpg", new byte[]{4, 5});
            String manifest = """
                    {"version":1,"accident_id":"%s","created_at":1789700000,
                     "files":[
                       {"name":"accidents/x/BEFORE/0001.jpg","file_type":"BEFORE","sequence_no":1,
                        "camera":"L","bytes":3,"created_at":1789700001},
                       {"name":"accidents/x/DETECT_SNAPSHOT/snapshot.jpg","file_type":"DETECT_SNAPSHOT",
                        "sequence_no":null,"camera":null,"bytes":2,"created_at":1789700002}
                     ],"videos":[]}
                    """.formatted(ACCIDENT);
            add(tar, "manifest.json", manifest.getBytes(StandardCharsets.UTF_8));
        }
        if (!gzip) {
            return raw.toByteArray();
        }
        ByteArrayOutputStream gz = new ByteArrayOutputStream();
        try (GZIPOutputStream out = new GZIPOutputStream(gz)) {
            out.write(raw.toByteArray());
        }
        return gz.toByteArray();
    }

    private static void add(TarArchiveOutputStream tar, String name, byte[] body) throws IOException {
        TarArchiveEntry e = new TarArchiveEntry(name);
        e.setSize(body.length);
        tar.putArchiveEntry(e);
        tar.write(body);
        tar.closeArchiveEntry();
    }

    private MockMultipartFile part(byte[] body, String contentType) {
        return new MockMultipartFile("archive", "x.tar.gz", contentType, body);
    }

    @Test
    void gzip_묶음을_풀어_장마다_객체키를_돌려준다() throws IOException {
        var res = service.receive(ACCIDENT, SHIP, part(tarball(true), "application/gzip"), null, 1L);

        assertThat(res.received()).isEqualTo(2);
        assertThat(res.stored()).isEqualTo(2);
        assertThat(res.failed()).isZero();
        // 🔴 키는 묶음 안 이름이 아니라 (file_type, sequence_no) 에서 다시 만든다
        assertThat(res.files()).extracting("objectKey").containsExactly(
                "accidents/%s/BEFORE/0001.jpg".formatted(ACCIDENT),
                "accidents/%s/DETECT_SNAPSHOT/snapshot.jpg".formatted(ACCIDENT));
        assertThat(res.files()).extracting("fileType").containsExactly("BEFORE", "DETECT_SNAPSHOT");
        assertThat(res.files()).extracting("sequenceNo").containsExactly(1, null);
    }

    @Test
    void 무압축_tar_도_받는다() throws IOException {
        // Pi 주석의 "무압축 tar 도 받는지 웹 팀 확인 필요" 에 대한 답이 이 시험이다
        var res = service.receive(ACCIDENT, SHIP, part(tarball(false), "application/x-tar"), null, 1L);

        assertThat(res.stored()).isEqualTo(2);
    }

    @Test
    void 타입을_모르면_매직을_따른다() throws IOException {
        // 중계 한 단만 거쳐도 타입이 뭉개진다. 그것 때문에 사진을 잃지 않는다
        var res = service.receive(ACCIDENT, SHIP,
                part(tarball(true), "application/octet-stream"), null, 1L);

        assertThat(res.stored()).isEqualTo(2);
    }

    @Test
    void 타입과_내용이_어긋나면_거부한다() throws IOException {
        assertThatThrownBy(() -> service.receive(ACCIDENT, SHIP,
                part(tarball(true), "video/mp4"), null, 1L))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    void mp4_는_그대로_올린다() {
        // ftyp 박스가 있는 최소 mp4 머리
        byte[] mp4 = new byte[32];
        mp4[4] = 0x66; mp4[5] = 0x74; mp4[6] = 0x79; mp4[7] = 0x70;

        var res = service.receive(ACCIDENT, SHIP,
                new MockMultipartFile("archive", "a.mp4", "video/mp4", mp4), null, 1789700000L);

        assertThat(res.stored()).isEqualTo(1);
        assertThat(res.files()).hasSize(1);
        assertThat(res.files().getFirst().objectKey())
                .isEqualTo("accidents/%s/video/1789700000.mp4".formatted(ACCIDENT));
    }

    @Test
    void 해시가_다르면_하나도_저장하지_않는다() throws IOException {
        assertThatThrownBy(() -> service.receive(ACCIDENT, SHIP,
                part(tarball(true), "application/gzip"), "deadbeef", 1L))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    void 빈_묶음은_형식을_알_수_없다고_거부한다() {
        // dev-iot probe_archive.py 판별 세트의 "빈 타르볼". 4xx 여야 한다 —
        // 여기서 500 이 나가면 IoT 가 우리 핸들러가 터진 줄로 읽는다
        assertThatThrownBy(() -> service.receive(ACCIDENT, SHIP,
                part(new byte[0], "application/gzip"), null, 1L))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    void 남의_사고에는_끼워_넣을_수_없다() throws IOException {
        // 판별 세트의 "없는 사고". 존재만 보면 남의 사고에 사진을 넣는 길이 열린다
        PiIngestSupport denies = mock(PiIngestSupport.class);
        when(denies.ownsAccident(any(), any())).thenReturn(false);
        var blocked = new PiArchiveService(storage, jdbc, denies);

        assertThatThrownBy(() -> blocked.receive(ACCIDENT, SHIP,
                part(tarball(true), "application/gzip"), null, 1L))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    void manifest_가_없으면_이름으로_유추하지_않는다() throws IOException {
        ByteArrayOutputStream raw = new ByteArrayOutputStream();
        try (TarArchiveOutputStream tar = new TarArchiveOutputStream(raw)) {
            add(tar, "accidents/x/BEFORE/0001.jpg", new byte[]{1});
        }
        assertThatThrownBy(() -> service.receive(ACCIDENT, SHIP,
                part(raw.toByteArray(), "application/x-tar"), null, 1L))
                .isInstanceOf(BusinessException.class);
    }
}

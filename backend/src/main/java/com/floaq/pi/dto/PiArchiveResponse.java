package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * {@code POST /api/pi/archives} 응답.
 *
 * <p>🔴 <b>필드 이름을 바꾸면 Pi 가 멈춘다.</b> dev-iot {@code iot/pi/floaq/archive.py} 의
 * {@code _apply()} 가 {@code data.files[].object_key} 를 읽어 로컬 행에 박고,
 * 하나도 못 읽으면 <b>"응답 모양이 바뀌었다"로 보고 그 사고를 건너뛴다</b> —
 * 재시도가 아니라 포기라서, 그 사고의 사진이 R2 에 영영 안 올라간다.</p>
 *
 * <p>Pi 는 {@code (file_type, sequence_no)} 로 로컬 행을 찾는다({@code file_by_slot}).
 * {@code camera} 는 매칭에 쓰지 않으므로 없어도 되지만, 사람이 로그로 볼 때 필요해 같이 싣는다.</p>
 *
 * @param received   타르볼에서 꺼낸 파일 수 (manifest 기준)
 * @param stored     R2 에 넣고 행까지 채운 수
 * @param duplicated 이미 같은 자연키가 있던 수. <b>오류가 아니다</b> — 응답 유실 뒤 재전송이 여기다
 * @param failed     꺼냈지만 저장하지 못한 수. 0 이 아니면 Pi 가 다음 회차에 다시 보낸다
 */
public record PiArchiveResponse(
        @JsonProperty("received") int received,
        @JsonProperty("stored") int stored,
        @JsonProperty("duplicated") int duplicated,
        @JsonProperty("failed") int failed,
        @JsonProperty("files") List<Stored> files) {

    /** 저장된 파일 하나. Pi 가 이 셋으로 로컬 행을 찾아 키를 박는다 */
    public record Stored(
            @JsonProperty("object_key") String objectKey,
            @JsonProperty("file_type") String fileType,
            @JsonProperty("sequence_no") Integer sequenceNo,
            @JsonProperty("camera") String camera,
            @JsonProperty("duplicated") boolean duplicated) {
    }
}

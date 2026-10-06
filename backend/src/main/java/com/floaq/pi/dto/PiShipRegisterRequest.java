package com.floaq.pi.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;

/**
 * {@code POST /api/pi/ships} 요청 (docs/api.md §4.3).
 *
 * <p><b>{@code registration_no} 가 필수인 이유</b>: 이 값이 멱등키다. DB 에 부분 UNIQUE 가 걸려 있어
 * (`uq_ship_registration_no`) 응답이 유실돼 Pi 가 다시 보내도 <b>같은 선박을 돌려줄 수 있다.</b>
 * 없으면 재시도마다 선박이 늘고 그중 어느 것이 진짜인지 아무도 모른다.
 * (SA 직접 등록 §3.3 에서는 선택이었다 — 거기선 사람이 보고 있다.)</p>
 *
 * <p>{@code camera_height_m}·{@code launcher_offset_m} 은 <b>현장 값</b>이다. 추락 위치 계산 입력이고,
 * 관제(SA)가 먼저 알 방법이 없어서 등록 방향을 "선내 신청"으로 뒤집은 근거이기도 하다.</p>
 */
public record PiShipRegisterRequest(
        @JsonProperty("name") @NotBlank @Size(max = 64) String name,
        @JsonProperty("registration_no") @NotBlank @Size(max = 20) String registrationNo,
        @JsonProperty("mmsi") @Pattern(regexp = "^[0-9]{9}$") String mmsi,
        @JsonProperty("has_buoy") Boolean hasBuoy,
        /**
         * 수면 기준. 0 보다 커야 한다 — DB CHECK 가 막는다.
         *
         * <p>⚠ <b>계약(docs/api.json)에서 빠졌다</b>(2026-09-17). Pi 가 자기 {@code env} 로 갖고 있고
         * 추락 위치 계산도 Pi 가 한다. 필드를 지우지 않고 받아만 두는 이유:
         * Pi 가 나중에 보내기로 해도 서버를 고칠 것이 없다 — 봉투의 {@code request_id} 와 같은 처리다.</p>
         */
        @JsonProperty("camera_height_m") BigDecimal cameraHeightM,
        /** 카메라 기준. <b>음수 가능</b> — 발사장치가 카메라보다 뒤에 있으면 그렇다 */
        @JsonProperty("launcher_offset_m") BigDecimal launcherOffsetM) {

    public boolean hasBuoyOrFalse() {
        return Boolean.TRUE.equals(hasBuoy);
    }
}

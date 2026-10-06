package com.floaq.ship.dto;

import com.floaq.ship.entity.Ship;
import com.floaq.ship.entity.ShipStatus;

import java.time.Instant;
import java.util.UUID;

/**
 * 선박 등록 승인 목록의 한 줄 (docs/api.md §3.3).
 *
 * <p><b>설치 캘리브레이션(카메라 높이·발사장치 거리)은 넣지 않는다.</b> 승인 판단에 쓰는 값이 아니라
 * 장비 설정이고, 화면에 늘어놓으면 SA 가 무엇을 보고 판단해야 하는지가 흐려진다
 * (apps/web {@code lib/shipRequests.ts} 주석과 같은 결정).</p>
 *
 * <p>⚠ 총톤수·승선 인원도 뺐다 (2026-09-16) — ERD 의 ship 에 없는 컬럼이라 V8 에서 함께 제거했다.
 * apps/web {@code shipRequests.ts} 의 {@code ApiAdminShip} 에서도 두 필드를 빼야 한다.</p>
 *
 * <p>{@code decidedAt} 이 null 이면 아직 처리 전이거나 V8 이전에 들어온 행이다 — 둘을 {@code status} 로 가른다.</p>
 */
public record AdminShipView(UUID shipId, String name, String registrationNo,
                            ShipStatus status, Instant createdAt, Instant decidedAt) {

    public static AdminShipView of(Ship ship) {
        return new AdminShipView(ship.getShipId(), ship.getName(), ship.getRegistrationNo(),
                ship.getStatus(), ship.getCreatedAt(), ship.getDecidedAt());
    }
}

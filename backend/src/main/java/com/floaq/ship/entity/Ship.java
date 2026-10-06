package com.floaq.ship.entity;

import com.floaq.global.entity.BaseTimeEntity;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.Uuid7;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * 선박. <b>{@code ship_id} 는 서버(EC2)가 만든다</b> (결정 2026-09-17) —
 * 선내 kiosk 에서 신청하면 {@code WAIT} 로 들어오고 SUPER_ADMIN 이 승인한다
 * (WEB-08 · W-05 · docs/api.md §3.3).
 *
 * <p><b>등록 방향을 뒤집었다</b>(2026-09-16). 상세기획 부록 C 는 "SA 가 먼저 등록 → 등록 코드 →
 * kiosk 가 코드 입력"을 제안했지만, 설치 현장에 있는 사람은 선주고 SA 는 선박 제원을 먼저 알 방법이 없다.
 * 승인 화면이 계정 승인(W-04)과 같은 모양이라 화면·API·상태값이 한 벌로 재사용되는 것도 근거다.</p>
 *
 * <p><b>왜 Pi 가 아니라 서버인가</b>(2026-09-17 개정. 이전 안은 "Pi 가 만들어 서명해 보낸다"였다).
 * {@code ship_id} 는 <b>사고 데이터와 성격이 다르다</b> —
 * 사고({@code accident_id})는 인터넷이 끊긴 바다에서도 만들어져야 해서 Pi 가 채번한다.
 * 선박 등록은 그렇지 않다: 등록 자체가 온라인 행위이고, 승인 주체가 SUPER_ADMIN 이며,
 * 서버가 채번하면 <b>미등록 id 로 데이터가 올라올 일이 아예 없어진다</b>
 * (지금 IoT 쪽은 "실행할 때마다 새로 발급"이라 그 값으로 올리면 전부 404 다).
 * Pi 가 만들면 필요했던 요청 서명 계약(알고리즘·헤더·시각 창)도 이 결정으로 사라진다.</p>
 *
 * <p>{@code ship_id} 가 MQTT 토픽 접두어 {@code ship/{ship_id}/...} 라 이 값이 정해져야 선내 통신이
 * 성립한다({@code docs/edge/mqtt.md} §7 #7) — <b>서버가 발급한 값을 Pi 설정에 넣는 절차</b>가 된다.
 * ⚠ 값이 틀리면 브로커가 아무 에러도 주지 않고 조용히 아무것도 오지 않는다.</p>
 *
 * <p>⚠ <b>신청 경로({@code POST /api/ships})는 아직 없다.</b> 지금은 승인·조회만 있다 —
 * 만들 때 {@link com.floaq.global.Uuid7#next()} 로 채번한다({@code UUID.randomUUID()} 는 v4 라
 * 시간순 정렬이 안 된다).</p>
 */
@Entity
@Getter
@Table(name = "ship")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Ship extends BaseTimeEntity {

    /**
     * UUID v7. <b>서버가 {@link com.floaq.global.Uuid7} 로 채번한다</b> (결정 2026-09-17).
     *
     * <p>{@code @GeneratedValue} 를 쓰지 않는 이유: Hibernate 의 UUID 생성은 <b>v4</b> 라
     * 시간순 정렬이 안 된다. 이 값은 MQTT 토픽 접두어이자 등록 순서를 보는 키라 v7 이어야 한다.</p>
     *
     * <p>⚠ Pi 기원 테이블({@code accident}·{@code buoy}·{@code imu} …)과 규칙이 다르다.
     * 그쪽은 <b>Pi 가 발급한 PK 를 그대로 쓰지만</b>(오프라인 채번이 필요해서),
     * 선박은 서버가 만든다 — 등록은 온라인 행위이고 승인 주체도 서버 쪽이다.</p>
     */
    @Id
    @Column(name = "ship_id", nullable = false, updatable = false)
    private UUID shipId;

    /**
     * 선박 Pi 키의 SHA-256. <b>평문은 발급 응답에만 실리고 서버에 남지 않는다</b> (V10).
     *
     * <p>이 값이 <b>키 → 선박</b> 조회의 키다. 요청마다 타므로 부분 UNIQUE 인덱스가 붙어 있다.</p>
     */
    // ⚠ 코드는 pi, DB 는 edge 다. 2026-09-17 개명에서 **DB 만 제외**했다 —
    //   RENAME 마이그레이션은 되돌리기 어렵고 팀원·EC2 가 각자 적용해야 하는데,
    //   컬럼·테이블 이름은 IoT 계약(경로·헤더·오류코드)에 드러나지 않아 얻는 게 없다.
    @Column(name = "edge_key_hash", length = 64)
    private String piKeyHash;

    @Column(name = "name", nullable = false, length = 64)
    private String name;

    /** 어선 등록번호. `0` 이나 `-` 가 섞여 들어와 숫자로 두지 않는다 (ERD 주석). */
    @Column(name = "registration_no", length = 20)
    private String registrationNo;

    /** 자동 식별 시스템(AIS) 식별번호. 9자리. DSC·AIS 메시지에 실린다 */
    @Column(name = "mmsi", length = 9)
    private String mmsi;

    /** 부표 탑재 여부 */
    @Column(name = "has_buoy", nullable = false)
    private boolean hasBuoy;

    /** 등록 상태 (V8). 논리 삭제는 {@link #deleted} 가 따로 본다 */
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private ShipStatus status;

    /*
     * ⚠ 총톤수·승선 인원은 두지 않는다 (2026-09-16 결정). ERD(docs/erd-actual.md)의 ship 에 없는 컬럼이라,
     *   등록 화면이 받는다는 이유로 넣으면 ERD 와 실제 스키마가 갈라진다. kiosk 등록 화면에서도 함께 뺐다.
     *   승인 판단은 선박명·등록번호로 한다.
     */

    /**
     * 설치 캘리브레이션. 선박마다 다른 값은 이 둘뿐이다(계획.md §6).
     *
     * <p>승인 판단에는 쓰지 않는다 — 장비 설정이라 SA 목록에도 내보내지 않는다.
     * 투하 위치 계산이 쓴다. {@code launcherOffsetM} 은 카메라 기준 거리라 뒤쪽이면 음수다.</p>
     */
    @Column(name = "camera_height_m", precision = 4, scale = 2)
    private BigDecimal cameraHeightM;

    @Column(name = "launcher_offset_m", precision = 4, scale = 2)
    private BigDecimal launcherOffsetM;

    /**
     * 승인·반려 시각과 처리자.
     *
     * <p>계정에는 이 둘이 없어 {@code updatedAt} 으로 때우고 있는데(AdminUserView 주석),
     * 선박은 나중에 정보 수정(PATCH)이 생기므로 따로 둔다 — 수정할 때마다 처리 시각이 밀린다.</p>
     *
     * <p>⚠ V8 이전 행은 둘 다 null 이다. 승인 절차를 거친 적이 없어서다(V8 마이그레이션 주석).</p>
     */
    @Column(name = "decided_at")
    private Instant decidedAt;

    @Column(name = "decided_by")
    private Long decidedBy;

    /**
     * 논리 삭제. <b>물리 삭제하지 않는다</b> — 과거 사고 기록이 이 선박을 참조하고 있어
     * 지우면 사고 경위에서 배 정보가 사라진다.
     */
    @Column(name = "is_deleted", nullable = false)
    private boolean deleted;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    /**
     * 승인. 대기 중인 신청만 — 이미 처리된 신청을 다시 누르면 409 (api.md §3.3).
     *
     * <p>{@code decidedBy} 를 인자로 받는다. 종결·승인의 <b>주체</b>는 지워지면 안 되는 기록이다
     * (계획.md §9.20 과 같은 이유).</p>
     */
    /**
     * 선내 단말에서 등록 신청 (docs/api.md §4.3 {@code POST /api/pi/ships}).
     *
     * <p>{@code shipId} 는 <b>서버가 uuid v7 로 채번한다</b> — 사고({@code accident_id})와 달리
     * 등록은 온라인 행위이고, 서버가 만들면 <b>미등록 id 로 데이터가 올라올 일이 없어진다.</b></p>
     *
     * <p>{@code WAIT} 로 들어간다. 승인 전에는 Pi 수신이 거절된다 —
     * 다만 데이터를 잃지는 않는다. Pi 가 큐를 쥐고 있다가 승인 뒤 밀린 것부터 보낸다.</p>
     *
     * @param piKeyHash 선박 키의 SHA-256. <b>평문은 응답에만 실린다</b>
     */
    public static Ship register(String name, String registrationNo, String mmsi, boolean hasBuoy,
                                BigDecimal cameraHeightM, BigDecimal launcherOffsetM,
                                String piKeyHash) {
        Ship ship = new Ship();
        ship.shipId = Uuid7.next();
        ship.name = name;
        ship.registrationNo = registrationNo;
        ship.mmsi = mmsi;
        ship.hasBuoy = hasBuoy;
        ship.cameraHeightM = cameraHeightM;
        ship.launcherOffsetM = launcherOffsetM;
        ship.piKeyHash = piKeyHash;
        ship.status = ShipStatus.WAIT;
        ship.deleted = false;
        return ship;
    }

    public void approve(long decidedByUserId) {
        requireWaiting();
        status = ShipStatus.ACTIVE;
        stamp(decidedByUserId);
    }

    /** 반려. 행은 지우지 않는다 — 같은 배가 고쳐서 다시 신청할 수 있어야 한다 */
    public void reject(long decidedByUserId) {
        requireWaiting();
        status = ShipStatus.REJECTED;
        stamp(decidedByUserId);
    }

    /**
     * 논리 삭제. <b>행은 남긴다</b> — 지난 사고가 이 배를 참조하고 있어, 진짜로 지우면
     * 기록 탭에서 그 사고의 배 이름이 사라진다.
     *
     * <p>이미 지워진 배를 또 지워도 그냥 둔다. 화면이 두 번 눌러도 같은 결과여야 한다 —
     * 여기서 막으면 "이미 지웠다"는 오류가 떠 지운 사람이 실패한 줄 안다.</p>
     */
    public void delete() {
        if (deleted) {
            return;
        }
        deleted = true;
        deletedAt = Instant.now();
    }

    private void stamp(long decidedByUserId) {
        decidedAt = Instant.now();
        decidedBy = decidedByUserId;
    }

    /** 관리자 둘이 같은 신청을 거의 동시에 누르면 나중 사람이 여기서 막힌다 */
    private void requireWaiting() {
        if (status != ShipStatus.WAIT) {
            throw new BusinessException(ErrorCode.INVALID_STATE);
        }
    }
}

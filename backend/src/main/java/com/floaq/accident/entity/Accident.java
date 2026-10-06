package com.floaq.accident.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.domain.Persistable;

import java.time.Instant;
import java.util.UUID;

/**
 * 사고. <b>Pi(Raspberry Pi)가 만들고 서버는 받아 적는다.</b>
 *
 * <p>ERD {@code accident} 기준. PK 가 uuid v7 인 것이 이 설계의 핵심이다 —
 * Pi 가 <b>인터넷 없이도 ID 를 발급</b>할 수 있어야 재전송이 멱등해진다.
 * 서버가 ID 를 새로 발급하면 두절 복귀 때 같은 사고가 여러 행이 된다.</p>
 */
@Entity
@Getter
@Table(name = "accident", indexes = {
        // 사고 목록 (상세기획 §6.5)
        @Index(name = "ix_accident_ship_created", columnList = "ship_id, created_at DESC"),
        // 진행 중 사고 조회 · 자동 신고 스케줄러
        @Index(name = "ix_accident_status", columnList = "status"),
})
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Accident implements Persistable<UUID> {

    /**
     * Pi 가 발급한 UUID v7.
     *
     * <p>{@code @GeneratedValue} 를 쓰지 않는다 — 서버가 만들면 안 되는 값이다.</p>
     */
    @Id
    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    @Column(name = "ship_id", nullable = false, updatable = false)
    private UUID shipId;

    /**
     * 사고 좌표. <b>NULL 을 허용한다</b> — GPS 미수신 상황을 담기 위한 설계로 보인다.
     *
     * <p>⚠ 신고 시점에 NULL 이면 어떻게 하는지가 아직 어디에도 없다.
     * 조난 좌표를 0,0 으로 채우면 그 자리가 거짓말이 된다 — 팀 확인 대기.</p>
     */
    @Column(name = "accident_lat")
    private Double lat;

    @Column(name = "accident_lon")
    private Double lon;

    /**
     * {@code EnumType.STRING} 고정. <b>{@code ORDINAL} 을 쓰면 enum 순서를 바꾸는 순간
     * 과거 사고의 유형이 통째로 뒤바뀐다</b> — 되돌릴 방법이 없다.
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "report_type", nullable = false, length = 16)
    private ReportType reportType;

    /**
     * ITU-R M.493 nature of distress (100~111). {@code URGENCY} 는 해당 코드가 없어 null.
     *
     * <p><b>서버는 이 값을 계산하지 않는다.</b> 유형 → 코드 매핑은 Pi 가 한 곳에서만 한다
     * ({@code ACCIDENT_ROUTING}). 두 벌이면 언젠가 갈리고, 갈린 것을 알아챌 방법이 없다.</p>
     */
    @Column(name = "report_dsc")
    private Integer reportDsc;

    /** 사고 유형 8종 (V9). ⚠ {@code triggerSource == AI} 면 {@code MOB} 이어야 한다 — DB CHECK 가 막는다. */
    @Enumerated(EnumType.STRING)
    @Column(name = "accident_type", length = 20)
    private AccidentType accidentType;

    @Enumerated(EnumType.STRING)
    @Column(name = "trigger_source", length = 8)
    private TriggerSource triggerSource;

    /**
     * 카운트다운 길이(초). 30초가 정책값인데도 <b>사고마다 박아 둔다</b> —
     * 나중에 기준이 바뀌어도 과거 사고 기록이 흔들리지 않게(database/pi.sql 과 같은 판단).
     */
    @Column(name = "wait_sec")
    private Integer waitSec;

    /**
     * 첫 {@code REPORT} 시각. 서버가 {@code accident-states} 를 받을 때 채우는 <b>비정규화</b>다 —
     * 사고 목록 조회마다 {@code accident_state} 를 join 하지 않으려는 것(docs/api.md §3.4).
     */
    @Column(name = "reported_at")
    private Instant reportedAt;

    /**
     * 구조 확정 시각. <b>{@code CLOSE} 가 구조인지 종료인지 가르는 유일한 값</b>이다 —
     * 이게 없으면 "구조했다"와 "포기했다"가 화면에서 같은 모습이 된다.
     */
    @Column(name = "rescued_at")
    private Instant rescuedAt;

    /** 오탐 분석용. 어떤 모델이 이 사고를 만들었나. */
    @Column(name = "model_version", length = 64)
    private String modelVersion;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private AccidentStatus status;

    /**
     * <b>Pi 가 사고를 만든 시각이다. 서버 수신 시각이 아니다.</b>
     *
     * <p>{@code @CreatedDate} 를 붙이지 않는 이유가 여기 있다 — 붙이면 두절 복귀 때
     * 몇 시간 전 사고가 "방금 일어난 것"으로 기록된다. 사고 경위 재구성이 무의미해진다.
     * Pi 의 GPS 시계가 기준이다(계획.md §9.5).</p>
     */
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    /**
     * 서버 반영 시각. <b>EC2 동기화 워터마크</b>로 쓴다.
     *
     * <p>⚠ <b>ERD 에 없다.</b> 없으면 "지난번 동기화 이후 바뀐 행"을 고를 수 없어
     * 계획.md §9.9 의 준실시간 동기화가 성립하지 않는다([[260910_mqtt-erd-review]] §3.4).</p>
     */
    @Column(name = "updated_at")
    private Instant updatedAt;

    /**
     * 자동 신고 예정 시각. {@code WAIT} 일 때만 값이 있다.
     *
     * <p>⚠ <b>ERD 에 없다. 없으면 30초 카운트다운을 그릴 수 없다.</b>
     * mqtt.md §5.1 이 <i>"report_due_at 을 반드시 쓰세요 — 키오스크가 자체 타이머를 돌리면 안 됩니다"</i>
     * 라고 한 그 컬럼이고, 재접속 시 남은 시간을 복구하는 유일한 근거다.</p>
     */
    @Column(name = "report_due_at")
    private Instant reportDueAt;

    /**
     * 종결 시각. <b>중복 종결 가드가 이 컬럼 하나에 걸린다</b>(계획.md §9.20) —
     * {@code where closedAt is null} 로 한 번만 성립시킨다.
     *
     * <p>⚠ ERD 에 없다. 상세기획 §6.1 이 "🔴 최우선"으로 꼽은 항목이다.</p>
     */
    @Column(name = "closed_at")
    private Instant closedAt;

    /**
     * 사고가 나던 때의 바다 (V20260921_1210). 수온과 <b>같은 이유로</b> 여기 둔다 —
     * 원본인 {@code ocean_roms}·{@code ocean_station_obs} 는 24시간치만 두고 지워서,
     * 남겨 두지 않으면 하루 지난 사고의 조류·바람은 영영 못 구한다.
     *
     * <p>비어 있을 수 있다. 이 칸이 생기기 전 사고이거나, 격자·관측 지점이 너무 먼 사고다.
     * <b>0 으로 채우지 않는다</b> — 0 은 "잔잔하다"이지 "모른다"가 아니다.</p>
     */
    @Column(name = "ocean_current_speed_ms")
    private Float oceanCurrentSpeedMs;

    @Column(name = "ocean_current_dir_deg")
    private Float oceanCurrentDirDeg;

    @Column(name = "ocean_wind_speed_ms")
    private Float oceanWindSpeedMs;

    /** <b>불어오는 쪽</b>이다(기상 관례). 표류 계산은 여기에 180° 를 더해 쓴다 */
    @Column(name = "ocean_wind_dir_deg")
    private Float oceanWindDirDeg;

    @Column(name = "ocean_spread_ms")
    private Float oceanSpreadMs;

    /** 위 값들이 관측·예측된 시각. 사고 시각과 한 시간까지 벌어질 수 있다 */
    @Column(name = "ocean_observed_at")
    private Instant oceanObservedAt;

    /**
     * 사고 시각·좌표의 해수 온도 (V11). 생존 잔여시간 계산의 입력이다.
     *
     * <p>해양 관측값에서 복사해 박아 둔 <b>스냅샷</b>이다. 원본인 {@code ocean_station_obs} 는
     * 24시간치만 두고 지워서, 여기 남기지 않으면 <b>하루 지난 사고의 수온은 영영 못 구한다.</b></p>
     */
    /**
     * 관제 웹이 이 사고를 접수한 시각.
     *
     * <p>{@code report.acked_at} 과 <b>다른 값이다</b> — 그쪽은 DSC 조난호출에 대한 해안국의
     * 무선 ACK 이고({@code acked_by} 가 MMSI 다), 이 값은 관제 화면이 사고를 받았다는 사실이다.</p>
     *
     * <p>한 번만 찍는다. 최초 시각이 "대응이 얼마나 빨랐나"의 원재료라 나중 값으로 덮지 않는다.</p>
     */
    @Column(name = "web_acked_at")
    private Instant webAckedAt;

    /** 접수한 관제 계정. FK 를 걸지 않는다 — 계정을 지워도 접수 기록은 남아야 한다 */
    @Column(name = "web_acked_by")
    private Long webAckedBy;

    /**
     * 접수를 찍는다. <b>이미 찍혀 있으면 아무것도 하지 않는다</b>(멱등).
     *
     * @return 이번 호출이 처음이었나. 화면이 "이미 접수됨"을 구별할 수 있게 돌려준다
     */
    public boolean webAck(Long userId, Instant at) {
        if (webAckedAt != null) {
            return false;
        }
        webAckedAt = at;
        webAckedBy = userId;
        return true;
    }

    /**
     * 사고자를 <b>찾은 시각</b>. 관제가 수색 화면에서 찍는다(단계 ④).
     *
     * <p><b>멱등이다.</b> 이미 찍혀 있으면 덮지 않는다 — 부표 버튼이 먼저 눌려 찍혔을 수 있고,
     * <b>최초 시각</b>이 "신고에서 발견까지 얼마나 걸렸나"의 원재료다. 나중 값으로 덮으면
     * 그 기록이 사라진다.</p>
     *
     * @return 이번 호출이 처음이었나
     */
    public boolean rescue(Instant at) {
        if (rescuedAt != null) {
            return false;
        }
        rescuedAt = at;
        return true;
    }

    /**
     * 사고 종결. <b>되돌릴 수 없다.</b>
     *
     * <p>🔴 <b>중복 종결 가드가 {@code closedAt} 하나에 걸린다</b>(계획.md §9.20).
     * 키오스크와 관제 웹이 동시에 종결할 수 있어, 먼저 찍은 쪽만 성립시킨다.
     * (자동 종결은 없다 — 사고는 사람이 끝낼 때까지 간다. 수색이 몇 시간 이어질 수 있다)
     * 두 번째 호출은 조용히 false 다 — 오류로 만들면 이미 끝난 사고를 종결하려던 사람에게
     * "실패했다"고 말하는 셈인데, 사고는 분명히 끝나 있다.</p>
     *
     * <p>취소({@code CANCEL})는 신고 전에 선내에서 거두는 것이라 여기서 하지 않는다 —
     * 관제는 신고받은 사고만 본다.</p>
     *
     * @return 이번 호출이 처음이었나
     */
    public boolean close(Instant at) {
        if (closedAt != null) {
            return false;
        }
        closedAt = at;
        status = AccidentStatus.CLOSE;
        return true;
    }

    @Column(name = "water_temp_c")
    private Float waterTempC;

    // ── Persistable ─────────────────────────────────────────

    /**
     * <b>Spring Data 의 {@code save()} 가 {@code merge()} 로 빠지는 것을 막는다.</b>
     *
     * <p>ID 가 이미 채워져 있으면 기본 {@code isNew()} 는 false 를 돌려주고,
     * {@code save()} 는 SELECT 후 INSERT 하는 {@code merge()} 를 부른다 —
     * 쿼리가 두 배가 되고 돌아오는 인스턴스도 내가 넘긴 것이 아니다.
     * Pi 가 PK 를 발급하는 구조라 <b>모든 삽입이 이 경로를 탄다.</b></p>
     */
    @Override
    public UUID getId() {
        return accidentId;
    }

    @Override
    public boolean isNew() {
        // 서버가 채우는 값이라, 아직 비어 있으면 저장된 적이 없는 행이다
        return updatedAt == null;
    }
}

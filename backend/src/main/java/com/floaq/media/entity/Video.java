package com.floaq.media.entity;

import com.floaq.global.entity.BaseTimeEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.UUID;

/**
 * 사고 영상. <b>서버가 만드는 행이다</b> — Pi 가 tar 로 프레임을 올리면 EC2 가
 * 종결 시점에 mp4 로 인코딩해 R2 에 넣고 키만 여기 남긴다(계획.md §9.6).
 *
 * <p><b>Pi 는 R2 자격증명을 갖지 않는다.</b> Pi에 스토리지 키를 두지 않는 편이 안전하고,
 * 인코딩을 Pi 에서 하면 사고 진행 중에 추론·신고가 쓸 CPU 를 뺏는다.</p>
 *
 * <p>서버가 만드는 행이라 {@link BaseTimeEntity} 의 auditing 을 그대로 쓴다 —
 * Pi 기원 엔티티들이 {@code created_at} 을 직접 받는 것과 다른 이유가 여기 있다.</p>
 *
 * <p>⚠ ERD 컬럼명은 {@code accident_id22} 다. ERDCloud 개명 흔적 — {@code accident_id} 로 매핑했다.</p>
 */
@Entity
@Getter
@Table(name = "video",
        indexes = @Index(name = "ix_video_accident", columnList = "accident_id"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Video extends BaseTimeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "video_id")
    private Long videoId;

    @Column(name = "accident_id", nullable = false, updatable = false)
    private UUID accidentId;

    /**
     * R2 오브젝트 키. <b>바이너리를 DB 에 넣지 않는다</b> — 키만 둔다(계획.md §2).
     * 사고 1건이 최대 18,000 프레임이라 행 하나가 통째로 커지면 동기화가 못 돈다.
     */
    @Column(name = "object_key", nullable = false, length = 200)
    private String objectKey;

    /**
     * 영상 시작부터 익수 확정(t=0)까지의 초 (V11).
     *
     * <p>사고 시각은 {@code accident.created_at} 으로 이미 안다. 여기 모자라는 것은
     * <b>그 시각이 영상의 몇 초 지점인가</b> 하나다. 그러면 촬영 시작 시각도
     * {@code accident.created_at - triggerSec} 으로 나온다 — 칸을 둘 둘 이유가 없다.</p>
     *
     * <p>⚠ {@code createdAt}(BaseTimeEntity)은 <b>서버가 행을 만든 시각</b>이다.
     * 영상은 종결 뒤에 인코딩해 등록하므로 촬영 시작과 몇 분에서 몇십 분까지 벌어진다.</p>
     */
    @Column(name = "trigger_sec")
    private Float triggerSec;
}

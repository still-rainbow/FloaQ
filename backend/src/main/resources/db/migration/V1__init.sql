-- FloaQ 초기 스키마
--
-- 근거: p-shim/ref/schema_260911.sql (ERDCloud 내보내기) + 엔티티 매핑
-- 검토 내역과 ERD 와의 차이는 report/260911_schema-review.md 참고.
--
-- ⚠ 이 파일은 **첫 운영 배포 전까지만** 고칠 수 있다.
--    배포 후에는 절대 수정하지 않는다 — 체크섬이 바뀌면 이미 마이그레이션된 서버가 기동을 거부한다.
--    그때부터는 V2, V3 을 새로 추가한다.
--
-- ⚠ ERD 원본을 그대로 쓰지 않은 곳이 다섯이다. 각각 주석으로 이유를 남겼다.
--    ① enum 타입 → varchar + CHECK   ② PK 기본값 추가
--    ③ accident_id2/22 → accident_id  ④ 기능상 필수 컬럼 4개
--    ⑤ Pi 가 만드는 테이블의 PK = (uuid, created_at) 복합키 (2026-09-11)

-- ─────────────────────────────────────────────────────────────
-- ⑤ PK 설계 (2026-09-11 확정)
--
-- Pi 가 만드는 행은 **Pi 가 PK 를 발급한다.** accident 가 이미 그렇게 돼 있었고
-- buoy·imu·accident_state·report 만 서버 발급 bigint identity 로 남아 있었다.
--
-- 왜 복합키인가 — 두 제약이 같은 답으로 모인다.
--   ① **Pi 의 SQLite 는 복합 PK 와 AUTOINCREMENT 를 같이 못 쓴다.**
--      AUTOINCREMENT 는 단일 INTEGER PRIMARY KEY(rowid 별칭)에서만 동작한다.
--      → Pi 가 채번하려면 uuid 여야 한다.
--   ② **TimescaleDB 하이퍼테이블은 모든 PK·UNIQUE 에 파티셔닝 컬럼을 요구한다.**
--      단일 PK 는 거부된다 — 유일성을 청크 단위로 검사하기 때문이다.
--   → (uuid v7, created_at) 하나로 둘 다 만족한다.
--
-- 얻는 것: **재전송 멱등이 PK 자체로 보장된다.** 자연키 UNIQUE 3개를 지웠다
--   (uq_buoy_accident_measured · uq_imu_accident_measured · uq_state_accident_status_at).
--   IDENTITY 가 사라져 **배치 INSERT 도 묶인다** — 두절 복귀 시 밀린 행이 한꺼번에 오는 경로다.
--
-- 🔴 **전제: Pi 가 uuid 를 자기 SQLite 에 저장하고 재전송 때 그대로 다시 보내야 한다.**
--    재전송마다 uuid 를 새로 만들면 PK 가 달라져 **중복 행을 막을 방법이 하나도 없다** —
--    자연키 UNIQUE 를 지웠기 때문이다. IoT 팀과의 계약 사항이다.
-- ─────────────────────────────────────────────────────────────

-- TimescaleDB. 이미지(timescale/timescaledb:*-pg17-oss)에 미리 적재돼 있다.
-- ⚠ 하이퍼테이블은 buoy·imu 뿐이다. **accident 는 만들면 안 된다** —
--   하이퍼테이블 → 하이퍼테이블 FK 가 미지원이라 accident 를 참조하는 6개 테이블이 전부 깨진다.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────────────────────────
-- ship — 서버가 만든다 (SUPER_ADMIN 이 관제 웹에서 등록, 상세기획 부록 C)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ship (
    ship_id         uuid         NOT NULL,
    name            varchar(64)  NOT NULL,
    registration_no varchar(20),
    mmsi            varchar(9),
    has_buoy        boolean      NOT NULL DEFAULT false,
    is_deleted      boolean      NOT NULL DEFAULT false,
    created_at      timestamptz  NOT NULL,
    updated_at      timestamptz,
    deleted_at      timestamptz,
    CONSTRAINT pk_ship PRIMARY KEY (ship_id)
);

COMMENT ON COLUMN ship.ship_id         IS 'uuid v7. MQTT 토픽 접두어 ship/{ship_id}/... 가 된다';
COMMENT ON COLUMN ship.registration_no IS '어선 등록번호. 0 이나 - 가 섞여 들어와 문자열로 둔다';
COMMENT ON COLUMN ship.mmsi            IS 'AIS 식별번호 9자리. DSC·AIS 메시지에 실린다';
COMMENT ON COLUMN ship.is_deleted      IS '논리 삭제. 과거 사고가 참조하므로 행은 남긴다';

-- ─────────────────────────────────────────────────────────────
-- accident — Edge(Pi)가 만들고 서버는 받아 적는다
-- ─────────────────────────────────────────────────────────────
CREATE TABLE accident (
    accident_id   uuid         NOT NULL,
    ship_id       uuid         NOT NULL,
    accident_lat  float8,
    accident_lon  float8,
    report_type   varchar(16)  NOT NULL,
    report_dsc    integer,
    status        varchar(16)  NOT NULL,
    created_at    timestamptz  NOT NULL,
    updated_at    timestamptz,
    report_due_at timestamptz,
    closed_at     timestamptz,
    CONSTRAINT pk_accident PRIMARY KEY (accident_id),
    CONSTRAINT fk_accident_ship FOREIGN KEY (ship_id) REFERENCES ship (ship_id),

    -- ① ERD 는 enum 타입이었다. PostgreSQL enum 은 값 삭제·순서 변경이 사실상 불가능한데
    --    사고 유형이 아직 5개냐 10개냐로 흔들린다(ref/mqtt.md §7 #2). 바꾸기 쉬운 쪽을 골랐다.
    CONSTRAINT ck_accident_report_type CHECK (report_type IN ('DISTRESS', 'URGENCY', 'SAFETY')),
    CONSTRAINT ck_accident_status      CHECK (status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE')),
    -- ITU-R M.493 nature of distress. URGENCY·SAFETY 는 해당 코드가 없어 NULL
    CONSTRAINT ck_accident_dsc         CHECK (report_dsc IS NULL OR report_dsc BETWEEN 100 AND 111),
    CONSTRAINT ck_accident_lat         CHECK (accident_lat IS NULL OR accident_lat BETWEEN -90 AND 90),
    CONSTRAINT ck_accident_lon         CHECK (accident_lon IS NULL OR accident_lon BETWEEN -180 AND 180),
    -- WAIT 이면 자동 신고 예정 시각이 반드시 있어야 한다. 없으면 카운트다운을 못 그린다
    CONSTRAINT ck_accident_due         CHECK (status <> 'WAIT' OR report_due_at IS NOT NULL)
);

-- ④ ERD 에 없어 추가한 컬럼 셋. 근거는 report/260911_schema-review.md §2
COMMENT ON COLUMN accident.accident_id   IS 'uuid v7. Edge 가 인터넷 없이 발급한다 — 재전송 멱등의 근거';
COMMENT ON COLUMN accident.created_at    IS 'Edge 의 사고 발생 시각(GPS 기준). 서버 수신 시각이 아니다';
COMMENT ON COLUMN accident.updated_at    IS '서버 반영 시각. EC2 동기화 워터마크 (ERD 에 없어 추가)';
COMMENT ON COLUMN accident.report_due_at IS '자동 신고 예정 시각. WAIT 일 때만. 30초 카운트다운의 유일한 근거 (ERD 에 없어 추가)';
COMMENT ON COLUMN accident.closed_at     IS '종결 시각. 중복 종결 가드가 이 컬럼에 걸린다 (ERD 에 없어 추가)';
COMMENT ON COLUMN accident.accident_lat  IS 'GPS 미수신 시 NULL. ⚠ 신고 시점에 NULL 이면 어떻게 할지 미정';

CREATE INDEX ix_accident_ship_created ON accident (ship_id, created_at DESC);
CREATE INDEX ix_accident_status       ON accident (status);
-- 자동 신고 스케줄러 (상세기획 §6.5)
CREATE INDEX ix_accident_due          ON accident (report_due_at) WHERE status = 'WAIT';

-- 동시 사고 1건 (상세기획 E1). 앱이 놓쳐도 두 번째 INSERT 가 실패한다 —
-- ref/mqtt.md §5.1 의 uq_pi_accident_active 와 같은 역할을 서버 쪽에 둔 것이다.
CREATE UNIQUE INDEX uq_accident_active ON accident (ship_id)
    WHERE status IN ('DETECT', 'WAIT', 'REPORT');

-- ─────────────────────────────────────────────────────────────
-- accident_state — 사고 상태 이력 (관제 사고 상세 타임라인, WEB-04)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE accident_state (
    accident_state_id uuid         NOT NULL,
    accident_id       uuid         NOT NULL,
    status            varchar(16)  NOT NULL,
    created_at        timestamptz  NOT NULL,
    -- ⑤ 하이퍼테이블이 아니라 created_at 이 PK 에 들어갈 이유는 없다.
    --   그래도 넣는다 — Pi 의 SQLite 스키마와 패턴을 하나로 두기 위해서다.
    --   테이블마다 PK 모양이 다르면 Pi 쪽 저장·재전송 코드가 테이블별로 갈린다.
    CONSTRAINT pk_accident_state PRIMARY KEY (accident_state_id, created_at),
    CONSTRAINT fk_state_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_state_status CHECK (status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE'))
);

COMMENT ON COLUMN accident_state.accident_state_id IS 'uuid v7. Pi 발급 — 재전송 멱등의 근거 (⑤)';
COMMENT ON COLUMN accident_state.created_at IS '상태가 변경된 시각. 행이 만들어진 시각이 아니다';

CREATE INDEX ix_state_accident_created ON accident_state (accident_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- launch — 부표 투하. 사고당 1회, 재투하 없음(E5)이라 PK 가 곧 FK 다
-- ─────────────────────────────────────────────────────────────
CREATE TABLE launch (
    -- ③ ERD 컬럼명은 accident_id2 였다. ERDCloud 가 FK 를 자동 개명한 흔적이라 바로잡았다
    accident_id      uuid        NOT NULL,
    launch_lat       float8      NOT NULL,
    launch_lon       float8      NOT NULL,
    horizontal_angle real        NOT NULL,
    vertical_angle   real        NOT NULL,
    confidence_score real,
    created_at       timestamptz,
    CONSTRAINT pk_launch PRIMARY KEY (accident_id),
    CONSTRAINT fk_launch_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_launch_confidence CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1)
);

COMMENT ON COLUMN launch.horizontal_angle IS 'deg';
COMMENT ON COLUMN launch.vertical_angle   IS 'deg';

-- ─────────────────────────────────────────────────────────────
-- buoy — 부표 위치 이력. 1초마다 한 행 (IOT-05)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE buoy (
    buoy_id     uuid         NOT NULL,
    accident_id uuid         NOT NULL,
    buoy_lat    float8       NOT NULL,
    buoy_lon    float8       NOT NULL,
    is_pressed  boolean      NOT NULL DEFAULT false,
    created_at  timestamptz  NOT NULL,
    CONSTRAINT pk_buoy PRIMARY KEY (buoy_id, created_at),
    CONSTRAINT fk_buoy_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_buoy_lat CHECK (buoy_lat BETWEEN -90 AND 90),
    CONSTRAINT ck_buoy_lon CHECK (buoy_lon BETWEEN -180 AND 180)
);

-- 하이퍼테이블. 청크 간격은 기본값(7일)을 쓴다 —
-- 1행/초 × 사고 최대 1시간(§9.6)이면 사고 하나가 3,600행이라 청크 하나에 다 들어간다.
SELECT create_hypertable('buoy', by_range('created_at'), if_not_exists => TRUE);

COMMENT ON COLUMN buoy.buoy_id    IS 'uuid v7. Pi 발급. ⚠ 재전송 때 새로 만들면 중복을 막을 방법이 없다 (⑤)';
COMMENT ON COLUMN buoy.created_at IS '부표 GPS 가 위치를 측정한 시각. LoRa 수신 시각도 서버 수신 시각도 아니다';
COMMENT ON COLUMN buoy.is_pressed IS '사람이 부표를 잡음(APP-08). ⚠ false 가 "사람이 없다"는 뜻은 아니다(E9)';

-- 최신 부표 위치는 초당 조회된다 (상세기획 §6.5). 없으면 풀스캔이다
CREATE INDEX ix_buoy_accident_created ON buoy (accident_id, created_at DESC);

-- ─────────────────────────────────────────────────────────────
-- imu — 사고 구간 자세·가속도 (IOT-20, 30초 단위 업로드)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE imu (
    imu_id      uuid         NOT NULL,
    accident_id uuid         NOT NULL,
    accel_x     real,
    accel_y     real,
    accel_z     real,
    roll        real         NOT NULL,
    pitch       real         NOT NULL,
    yaw         real         NOT NULL,
    created_at  timestamptz  NOT NULL,
    CONSTRAINT pk_imu PRIMARY KEY (imu_id, created_at),
    CONSTRAINT fk_imu_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE
);

SELECT create_hypertable('imu', by_range('created_at'), if_not_exists => TRUE);

COMMENT ON COLUMN imu.imu_id  IS 'uuid v7. Pi 발급 (⑤)';
COMMENT ON COLUMN imu.accel_x IS 'm/s^2';
COMMENT ON COLUMN imu.accel_y IS 'm/s^2';
COMMENT ON COLUMN imu.accel_z IS 'm/s^2';
-- ⚠ ERD 주석은 deg/s 였다. ref/mqtt.md §5.6 이 스스로 "각도(deg)가 맞다"고 정정한 항목이다.
--   각속도로 읽으면 전복 판정 임계 롤 각(침수 101 / 전복 104)이 무의미해진다.
COMMENT ON COLUMN imu.roll  IS '자세각 deg (deg/s 아님)';
COMMENT ON COLUMN imu.pitch IS '자세각 deg';
COMMENT ON COLUMN imu.yaw   IS '방위 deg. MPU-6050 은 6축이라 드리프트가 누적된다 — GPS 로 보정';

CREATE INDEX ix_imu_accident_created ON imu (accident_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- report — 신고 발신 '기록'. 서버는 쏘지 않는다 (확정 2026-09-11, 계획.md §9.4)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE report (
    report_id   uuid         NOT NULL,
    accident_id uuid         NOT NULL,
    report_lat  float8       NOT NULL,
    report_lon  float8       NOT NULL,
    created_at  timestamptz  NOT NULL,
    CONSTRAINT pk_report PRIMARY KEY (report_id, created_at),
    CONSTRAINT fk_report_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_report_lat CHECK (report_lat BETWEEN -90 AND 90),
    CONSTRAINT ck_report_lon CHECK (report_lon BETWEEN -180 AND 180)
);

COMMENT ON COLUMN report.report_id  IS 'uuid v7. Pi 발급 (⑤)';
COMMENT ON TABLE  report            IS 'Pi 가 UDP 로 발신한 사실의 기록. 발신 주체는 Pi 다';
COMMENT ON COLUMN report.report_lat IS '전송 좌표. 불변 스냅샷 — 사고 좌표가 갱신돼도 바뀌지 않는다';

CREATE INDEX ix_report_accident_created ON report (accident_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- video — EC2 가 mp4 로 인코딩해 R2 에 넣고 키만 남긴다 (계획.md §9.6)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE video (
    video_id    bigint        GENERATED BY DEFAULT AS IDENTITY,
    accident_id uuid          NOT NULL,
    object_key  varchar(200)  NOT NULL,
    created_at  timestamptz   NOT NULL,
    updated_at  timestamptz,
    CONSTRAINT pk_video PRIMARY KEY (video_id),
    CONSTRAINT fk_video_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE
);

COMMENT ON COLUMN video.object_key IS 'R2 오브젝트 키. 바이너리는 DB 에 넣지 않는다';

CREATE INDEX ix_video_accident ON video (accident_id);

-- ─────────────────────────────────────────────────────────────
-- users — 관제 웹 계정. 셀프 가입 없음 (WAIT → SUPER_ADMIN 승인 → ACTIVE)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE users (
    user_id    bigint       GENERATED BY DEFAULT AS IDENTITY,
    -- ④ ERD 에 로그인 식별자가 없어 추가했다. 없으면 무엇으로 계정을 찾을지가 없다(WEB-01).
    --   ⚠ 이메일인지 아이디인지는 미정 — 상세기획 §10.2 "해경 가입 신청 입력 항목"
    login_id   varchar(64)  NOT NULL,
    password   varchar(60)  NOT NULL,
    name       varchar(20)  NOT NULL,
    role       varchar(16)  NOT NULL,
    status     varchar(16)  NOT NULL,
    created_at timestamptz  NOT NULL,
    updated_at timestamptz,
    deleted_at timestamptz,
    CONSTRAINT pk_users PRIMARY KEY (user_id),
    CONSTRAINT uq_users_login_id UNIQUE (login_id),
    CONSTRAINT ck_users_role   CHECK (role IN ('ADMIN', 'SUPER_ADMIN')),
    CONSTRAINT ck_users_status CHECK (status IN ('WAIT', 'ACTIVE', 'DELETED'))
);

COMMENT ON COLUMN users.password IS 'bcrypt(round 12). 길이 60 은 bcrypt 출력 길이다';
COMMENT ON COLUMN users.role     IS 'ADMIN 이 상세기획의 A(해경). 신고받은 사고만 본다';

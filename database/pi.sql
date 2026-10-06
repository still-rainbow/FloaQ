-- FloaQ Edge(Raspberry Pi) 스키마 — SQLite STRICT
--
-- 근거: database/schema_pi_260911.sql (ERDCloud 내보내기) + docs/edge/mqtt.md §5 페이로드
--       + 2026-09-11 팀 결정 4건. web.sql 과 같은 서술 방식을 따른다.
--
-- ⚠ 원본 ERDCloud 내보내기는 MySQL 문법(백틱, 인라인 COMMENT)이라 SQLite 에서 실행되지 않았다.
--    타입도 `uuid` 처럼 SQLite 에 없는 것을 쓰고 있었다. 이 파일이 실행 가능한 정본이다.
--
-- ⚠ 원본과 다르게 간 곳이 다섯이다. 각각 주석으로 이유를 남겼다.
--    ① 복합 PK → 단일 INTEGER PK + FK    ② 전 테이블 updated_at 추가
--    ③ uuid → TEXT, 시각 → INTEGER(초)   ④ CHECK·인덱스 추가 (원본은 0개)
--    ⑤ 테이블 5개 신설
--
-- ⚠ 런타임에 반드시 켤 것. SQLite 는 기본이 OFF 라 FK 가 조용히 무시된다.
--      PRAGMA foreign_keys = ON;
--      PRAGMA journal_mode = WAL;    -- 1Hz 쓰기 중에도 키오스크 조회가 막히지 않는다
--      PRAGMA synchronous  = NORMAL; -- WAL 과 조합. microSD 쓰기 감소

-- ─────────────────────────────────────────────────────────────
-- 규약
--   시각   : INTEGER, Unix epoch **초**. mqtt.md §0 의 `Unix` 와 같다
--   UUID   : TEXT 36자 (UUID v7). 문자열 정렬이 곧 시간 순서다
--   불린   : INTEGER 0/1. SQLite STRICT 에 BOOLEAN 타입이 없다
--   좌표   : REAL. 8바이트 부동소수 — 상세기획 §6.4 가 요구한 float8 에 해당한다
--
-- ③ STRICT 허용 타입은 INT / INTEGER / REAL / TEXT / BLOB / ANY 뿐이다.
--    `uuid`·`varchar`·`timestamptz`·`boolean` 은 전부 쓸 수 없다.
--    PK 는 반드시 `INTEGER` 로 적는다 — `INT` 로 적으면 STRICT 는 통과하지만
--    rowid 별칭이 안 돼서 자동 채번이 조용히 멈춘다.
-- ─────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────
-- pi_ship — 서버가 발급한 선박 정보를 내려받아 보관한다 (상세기획 부록 C)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_ship (
    ship_id         TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    registration_no TEXT,
    mmsi            TEXT,
    has_buoy        INTEGER NOT NULL DEFAULT 0,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    deleted_at      INTEGER,
    PRIMARY KEY (ship_id),
    CHECK (has_buoy   IN (0, 1)),
    CHECK (is_deleted IN (0, 1)),
    -- MMSI 9자리. TEXT 인 이유는 선행 0 이 유효하기 때문이다 — INTEGER 면 날아간다
    CHECK (mmsi IS NULL OR mmsi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')
) STRICT;

-- ─────────────────────────────────────────────────────────────
-- pi_accident — Pi 가 만든다. 인터넷 없이 발급하므로 UUID v7 이어야 한다
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_accident (
    accident_id    TEXT    NOT NULL,
    ship_id        TEXT    NOT NULL,
    accident_lat   REAL,
    accident_lon   REAL,
    accident_type  TEXT    NOT NULL,
    trigger_source TEXT    NOT NULL,
    report_type    TEXT    NOT NULL,
    report_dsc     INTEGER,
    status         TEXT    NOT NULL,
    wait_sec       INTEGER NOT NULL DEFAULT 30,
    report_due_at  INTEGER,
    model_version  TEXT,
    rescued_at     INTEGER,
    closed_at      INTEGER,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    PRIMARY KEY (accident_id),
    FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id),

    CHECK (status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE')),
    -- ⚠ SAFETY 를 뺐다 `확정` 2026-09-17. 항행경보 수준이라 익수자 구조 시스템에
    --    쓸 일이 없다. api.md §1.7 서버 CHECK 와 글자까지 같다.
    CHECK (report_type IN ('DISTRESS', 'URGENCY')),
    CHECK (trigger_source IN ('AI', 'MANUAL')),
    -- ⚠ 8종 `확정` 2026-09-17. HAZARD(위험물 발견)·ABANDON_SHIP(퇴함)을 1차 범위에서 뺐다.
    --   ABANDON_SHIP 을 되살린다면 (DISTRESS, 108) 이다 — 퇴선은 조난이고,
    --   DSC 의 category 108(safety)과 nature of distress 108(abandoning ship)은 다른 표다.
    CHECK (accident_type IN (
        'MOB', 'FIRE', 'FLOODING', 'COLLISION', 'GROUNDING',
        'ENGINE_FAILURE', 'OTHER_DISTRESS', 'MEDICAL')),
    -- ITU-R M.493 nature of distress. URGENCY 는 해당 코드가 없어 NULL
    CHECK (report_dsc IS NULL OR report_dsc BETWEEN 100 AND 111),
    CHECK (accident_lat IS NULL OR accident_lat BETWEEN -90 AND 90),
    CHECK (accident_lon IS NULL OR accident_lon BETWEEN -180 AND 180),

    -- WAIT 이면 자동 신고 예정 시각이 반드시 있어야 한다.
    -- 없으면 카운트다운을 그릴 수 없고, Pi 가 언제 쏠지도 모른다 (mqtt.md §5.1)
    CHECK (status <> 'WAIT' OR report_due_at IS NOT NULL),
    -- CLOSE 가 아니면 종료 시각이 없다
    CHECK (status = 'CLOSE' OR closed_at IS NULL),
    -- AI 감지는 MOB 만 만든다. 나머지 유형은 사람이 S-07 에서 고른다 (상세기획 §3.3)
    CHECK (trigger_source <> 'AI' OR accident_type = 'MOB')
) STRICT;

-- 동시 사고 1건 (상세기획 E1). 앱이 AI-05 를 놓쳐도 두 번째 INSERT 가 실패한다.
-- mqtt.md §5.1 이 이름으로 참조하는 그 인덱스다.
CREATE UNIQUE INDEX uq_pi_accident_active ON pi_accident (ship_id)
    WHERE status IN ('DETECT', 'WAIT', 'REPORT');

CREATE INDEX ix_pi_accident_ship_created ON pi_accident (ship_id, created_at DESC);
-- 자동 신고 스케줄러가 초당 훑는다 (상세기획 §6.5)
CREATE INDEX ix_pi_accident_due  ON pi_accident (report_due_at) WHERE status = 'WAIT';
CREATE INDEX ix_pi_accident_sync ON pi_accident (updated_at, accident_id);

-- ─────────────────────────────────────────────────────────────
-- pi_accident_state — 상태 전이 이력 (S-05 타임라인)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_accident_state (
    accident_state_id INTEGER NOT NULL,
    accident_id       TEXT    NOT NULL,
    status            TEXT    NOT NULL,
    prev_status       TEXT,
    reason            TEXT    NOT NULL,
    caused_by         TEXT,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    -- ① 원본은 PK (accident_state_id, accident_id) 복합이었다.
    --    Pi 는 배가 한 척이라 단독으로 이미 유일하고, 복합 PK 로 두면
    --    rowid 별칭이 안 돼 자동 채번이 막힌다. 사고 스코핑은 FK + 인덱스가 받는다.
    PRIMARY KEY (accident_state_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (status      IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE')),
    CHECK (prev_status IS NULL OR prev_status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE')),
    CHECK (reason IN ('AI_DETECT', 'COUNTDOWN_START', 'TIMEOUT',
                      'TABLET_CANCEL', 'TABLET_REPORT_NOW', 'TABLET_MANUAL',
                      'TABLET_RESCUE', 'TABLET_CLOSE')),
    -- 서버 uq_state_accident_status_at 과 같은 멱등키. 재전송해도 행이 늘지 않는다
    UNIQUE (accident_id, status, created_at)
) STRICT;

CREATE INDEX ix_pi_state_accident ON pi_accident_state (accident_id, created_at);
CREATE INDEX ix_pi_state_sync     ON pi_accident_state (updated_at, accident_state_id);

-- ─────────────────────────────────────────────────────────────
-- pi_launch — 부표 투하. 사고당 1회, 재투하 없음(E5)이라 PK 가 곧 FK 다
--
-- 조준 해는 Jetson 이 계산해 보낸다 `확정` 2026-09-11 (mqtt.md §5.1, DES-38 §5).
-- Pi 는 범위·만료·프로파일을 검증만 하고, 거부하면 result='FAILED' 로 남긴다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_launch (
    accident_id      TEXT    NOT NULL,
    detection_id     TEXT,
    result           TEXT    NOT NULL,
    fail_reason      TEXT,
    launch_lat       REAL    NOT NULL,
    launch_lon       REAL    NOT NULL,
    target_lat       REAL,
    target_lon       REAL,
    horizontal_angle REAL    NOT NULL,
    vertical_angle   REAL    NOT NULL,
    confidence_score REAL,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    PRIMARY KEY (accident_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (result IN ('SUCCESS', 'FAILED')),
    CHECK (fail_reason IS NULL OR fail_reason IN
           ('NOT_LOADED', 'DEVICE_ERROR', 'OUT_OF_RANGE', 'NO_SOLUTION')),
    -- 성공이면 실패 사유가 없고, 실패면 반드시 있다
    CHECK ((result = 'SUCCESS' AND fail_reason IS NULL)
        OR (result = 'FAILED'  AND fail_reason IS NOT NULL)),
    CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
    -- 명령한 각도. 소프트 리밋에 걸리면 Jetson 이 보낸 target_* 과 다를 수 있다 (DES-38 §8)
    CHECK (horizontal_angle BETWEEN -180 AND 180),
    CHECK (vertical_angle   BETWEEN  -90 AND 90)
) STRICT;

CREATE INDEX ix_pi_launch_sync ON pi_launch (updated_at, accident_id);

-- ─────────────────────────────────────────────────────────────
-- pi_buoy — 부표 LoRa 수신 이력. 1초마다 한 행 (IOT-05)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_buoy (
    buoy_log_id INTEGER NOT NULL,
    accident_id TEXT    NOT NULL,
    seq         INTEGER NOT NULL,
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    is_pressed  INTEGER NOT NULL DEFAULT 0,
    rssi        REAL,
    created_at  INTEGER NOT NULL,
    received_at INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (buoy_log_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (is_pressed IN (0, 1)),
    CHECK (lat BETWEEN -90 AND 90),
    CHECK (lon BETWEEN -180 AND 180),
    -- 서버 uq_buoy_accident_measured 와 같은 멱등키. LoRa 중복 수신도 여기서 막힌다.
    -- ⚠ created_at 이 초 단위라 같은 초에 2건이 오면 두 번째가 거부된다.
    --    1Hz 전제(상세기획 §8)에서는 의도한 dedup 이다.
    UNIQUE (accident_id, created_at)
) STRICT;

-- created_at 은 부표 GPS 가 위치를 측정한 시각이다. LoRa 수신 시각은 received_at 이다.
-- 둘은 LoRa 지연만큼 벌어지므로 지도에는 created_at 을 쓴다 (mqtt.md §3.4).
-- is_pressed = 0 이 "사람이 없다"는 뜻은 아니다 (E9).
CREATE INDEX ix_pi_buoy_accident ON pi_buoy (accident_id, created_at DESC);
CREATE INDEX ix_pi_buoy_sync     ON pi_buoy (updated_at, buoy_log_id);

-- ─────────────────────────────────────────────────────────────
-- pi_imu — 사고 구간 자세. 상시 기록은 RAM 링버퍼(IOT-09)에 있고
--          DB 에는 사고 전후 10분만 남긴다 (상세기획 §8) — 그래서 accident_id 가 NOT NULL 이다
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_imu (
    imu_id       INTEGER NOT NULL,
    accident_id  TEXT    NOT NULL,
    imu_position TEXT    NOT NULL,
    accel_x      REAL,
    accel_y      REAL,
    accel_z      REAL,
    roll         REAL    NOT NULL,
    pitch        REAL    NOT NULL,
    yaw          REAL    NOT NULL,
    heading_deg  REAL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    PRIMARY KEY (imu_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (imu_position IN ('HULL', 'CAMERA_L', 'CAMERA_R')),
    CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360),
    -- imu_position 을 멱등키에 넣은 이유: IMU 를 2개 이상 동시에 쓰면
    -- (accident_id, created_at) 만으로는 같은 초에 온 둘째가 거부된다.
    -- 상세기획 §2.2 는 "3개 중 하나"지만 스키마가 그 결정을 막지 않게 둔다.
    UNIQUE (accident_id, created_at, imu_position)
) STRICT;

-- ⚠ roll/pitch/yaw 는 **각도(deg)** 다. ERD 주석의 deg/s 는 오기이며
--   mqtt.md §5.6 이 스스로 정정한 항목이다. 각속도로 읽으면 전복 판정
--   임계 롤 각(침수 101 / 전복 104)이 무의미해진다.
-- yaw 는 MPU-6050 이 6축이라 드리프트가 누적된다 — GPS 로 보정한다.
CREATE INDEX ix_pi_imu_accident ON pi_imu (accident_id, created_at);
CREATE INDEX ix_pi_imu_sync     ON pi_imu (updated_at, imu_id);

-- ─────────────────────────────────────────────────────────────
-- pi_report — 신고 발신 기록. **발신 주체는 Pi 다** `확정` 2026-09-11
--
--   상세기획 §3.2⑥·§7.1 은 [Backend] 라고 적혀 있으나 §4.2 IOT-11/12/13 은 IoT 였다.
--   Pi 가 쏴야 인터넷 두절을 Pi 가 직접 알고 화면에 띄울 수 있다 (mqtt.md §5.10).
--   ⚠ 상세기획 §3.2⑥·§7.1 수정 필요.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_report (
    report_id     INTEGER NOT NULL,
    accident_id   TEXT    NOT NULL,
    channel       TEXT    NOT NULL,
    -- ⚠ 원본 ERD 의 pi_report.report_type(AUTO/MANUAL/RESCUE)은
    --    pi_accident.report_type(DISTRESS/URGENCY)과 이름은 같고 의미가 달랐다.
    --    필드명이 곧 컬럼명인 규약(mqtt.md §3.5) 아래에서는 반드시 사고가 나므로 개명했다.
    trigger_kind  TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    sent_count    INTEGER NOT NULL DEFAULT 0,
    report_lat    REAL    NOT NULL,
    report_lon    REAL    NOT NULL,
    first_sent_at INTEGER,
    last_sent_at  INTEGER,
    acked_at      INTEGER,
    acked_by      TEXT,
    fail_reason   TEXT,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (report_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (channel      IN ('AIS_MOB', 'AIS_SART', 'DSC')),
    CHECK (trigger_kind IN ('AUTO', 'MANUAL', 'RESCUE')),
    CHECK (status       IN ('SENDING', 'ACKED', 'STOPPED', 'FAILED')),
    CHECK (fail_reason IS NULL OR fail_reason IN ('NO_INTERNET', 'NO_RECEIVER', 'TIMEOUT')),
    CHECK (report_lat BETWEEN -90 AND 90),
    CHECK (report_lon BETWEEN -180 AND 180),
    CHECK (sent_count >= 0),
    -- AIS 는 단방향 브로드캐스트라 ACK 이 올 수 없다. DSC 만 가능하다 (mqtt.md §5.11)
    CHECK (acked_at IS NULL OR channel = 'DSC'),
    CHECK ((status = 'ACKED') = (acked_at IS NOT NULL)),
    CHECK (acked_by IS NULL OR acked_by GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    -- 채널당 한 행. 재전송해도 행이 늘지 않고 sent_count 만 오른다
    UNIQUE (accident_id, channel)
) STRICT;

-- report_lat/lon 은 전송 시점의 좌표를 박제한 값이다. 사고 좌표가 갱신돼도 바뀌지 않는다.
CREATE INDEX ix_pi_report_accident ON pi_report (accident_id);
CREATE INDEX ix_pi_report_sync     ON pi_report (updated_at, report_id);

-- ─────────────────────────────────────────────────────────────
-- pi_imu_log — 상시 IMU 기록 (사고와 무관)
--
--   🔴 `pi_imu` 는 accident_id 가 NOT NULL 이라 **사고 전 데이터를 담을 수 없다.**
--      그런데 필요한 것이 바로 그 구간이다 — 사고 10분 전부터 무슨 일이 있었나.
--      그래서 사고와 무관한 롤링 로그를 따로 두고, 사고가 나면 그 창을 pi_imu 로
--      옮긴다 (`copy_imu_window`). pi_ship_position 과 같은 모양이다.
--
--   ⚠ 1Hz 다. 프룬이 없으면 microSD 가 하루 8.6만 행씩 찬다 — ImuPump 가
--     IMU_LOG_KEEP_SEC 보다 오래된 행을 매 회차 지운다.
--
--   ⚠ **sync 대상이 아니다.** 관제로 가는 것은 사고에 붙은 pi_imu 뿐이다.
--     여기까지 올리면 1Hz × 상시라 좁은 어선 상향 대역이 죽는다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_imu_log (
    imu_log_id   INTEGER NOT NULL,
    ship_id      TEXT    NOT NULL,
    imu_position TEXT    NOT NULL,
    accel_x      REAL,
    accel_y      REAL,
    accel_z      REAL,
    -- 🔴 NULL 을 허용한다. 설치 영점이 없으면 각도를 **모르는 것**이고,
    --    0 을 넣으면 화면이 "수평" 으로 읽는다 (adapters/imu.py 참고).
    roll         REAL,
    pitch        REAL,
    heading_deg  REAL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    PRIMARY KEY (imu_log_id),
    FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id),

    CHECK (imu_position IN ('HULL', 'CAMERA_L', 'CAMERA_R')),
    CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360),
    UNIQUE (ship_id, created_at, imu_position)
) STRICT;

-- 사고가 나면 [사고시각 - 10분, 지금] 을 이 인덱스로 긁어 pi_imu 로 옮긴다
CREATE INDEX ix_pi_imu_log_time ON pi_imu_log (ship_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_ship_position — 선박 위치 이력. 상시 1Hz (APP-01 항적·ETA)
--
--   GPS 를 Pi 에 단다 `확정` 2026-09-11. 상세기획 §2.2 는 "태블릿 GPS" 였으나
--   ① 폐쇄망이라 NTP 가 없어 시각 기준이 필요하고(GPS UTC)
--   ② 태블릿이 꺼지면 위치가 끊기며
--   ③ 조타실 실내 수신 약화(§9.2-3)도 함께 해결된다.
--   ⚠ 상세기획 §2.2 수정 필요. mqtt.md 토픽도 kiosk/sensor/gps → pi/sensor/gps.
--
--   기록 주기 `제안`⚠️ — 평상시 **5초**, 사고 중(DETECT/WAIT/REPORT)엔 **1초**.
--     ⚠ MQTT `pi/sensor/gps` 발행은 **항상 1Hz** 다. 둘을 혼동하지 말 것 —
--       speed_kn·heading_deg 는 Jetson 의 조준 해 입력이라(DES-38 §5) 5초 전 값을 쓰면 안 된다.
--       10노트면 5초에 26m 이동하고, 그 사이 선회하면 침로가 크게 틀어진다.
--       DB 는 항적(APP-01)·ETA 용이라 5초면 충분하다 — 지도에선 26m 간격이 부드럽다.
--   ⚠ 이 테이블만 상시 기록되어 Pi 저장량의 거의 전부를 차지한다.
--     5초 주기면 17,280 행/일 (1Hz 대비 1/5). 보관 정책은 여전히 미정 (mqtt.md §8).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_ship_position (
    position_id INTEGER NOT NULL,
    ship_id     TEXT    NOT NULL,
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    speed_kn    REAL,
    heading_deg REAL,
    accuracy_m  REAL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (position_id),
    FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id),

    CHECK (lat BETWEEN -90 AND 90),
    CHECK (lon BETWEEN -180 AND 180),
    CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360),
    CHECK (speed_kn IS NULL OR speed_kn >= 0),
    UNIQUE (ship_id, created_at)
) STRICT;

-- speed_kn·heading_deg 는 Jetson 의 조준 해 입력이기도 하다 —
-- 발사대가 움직이는 배 위에 있어서 목표점이 "착수 예상 시점의 위치"여야 한다 (DES-38 §5).
CREATE INDEX ix_pi_position_ship ON pi_ship_position (ship_id, created_at DESC);
CREATE INDEX ix_pi_position_sync ON pi_ship_position (updated_at, position_id);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_accident_file — 감지 스틸컷 + 사고 전후 프레임
--    바이너리는 넣지 않는다. 사고당 125장 × 200KB = 25MB 를 BLOB 로 넣으면
--    microSD 수명에 불리하고 동기화 한 행이 통째로 커진다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_accident_file (
    file_id     INTEGER NOT NULL,
    accident_id TEXT    NOT NULL,
    file_type   TEXT    NOT NULL,
    sequence_no INTEGER,
    file_path   TEXT    NOT NULL,
    object_key  TEXT,
    width       INTEGER,
    height      INTEGER,
    bytes       INTEGER,
    camera      TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (file_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (file_type IN ('DETECT_SNAPSHOT', 'BEFORE', 'AFTER')),
    CHECK (camera IS NULL OR camera IN ('L', 'R')),
    CHECK (bytes IS NULL OR bytes > 0),
    -- 앞 15초·뒤 10초가 125장이라 순서 없이는 재생이 안 된다 (상세기획 §6.1)
    UNIQUE (accident_id, file_type, sequence_no)
) STRICT;

-- object_key 는 R2 업로드 확정 후에 채운다. NULL 이면 아직 안 올라간 것이고,
-- 로컬 파일은 저장 확정 응답을 받은 뒤에만 지운다 (DES-31 C-8).
CREATE INDEX ix_pi_file_accident ON pi_accident_file (accident_id, file_type, sequence_no);
CREATE INDEX ix_pi_file_sync     ON pi_accident_file (updated_at, file_id);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_comm_loss — LoRa 두절 구간. 1분 미수신이면 두절 판정 (상세기획 §8)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_comm_loss (
    comm_loss_id     INTEGER NOT NULL,
    accident_id      TEXT    NOT NULL,
    detected_at      INTEGER NOT NULL,
    last_buoy_log_id INTEGER,
    last_lat         REAL    NOT NULL,
    last_lon         REAL    NOT NULL,
    last_received_at INTEGER NOT NULL,
    threshold_sec    INTEGER NOT NULL,
    recovered_at     INTEGER,
    updated_at       INTEGER NOT NULL,
    PRIMARY KEY (comm_loss_id),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (last_lat BETWEEN -90 AND 90),
    CHECK (last_lon BETWEEN -180 AND 180),
    CHECK (threshold_sec > 0),
    CHECK (recovered_at IS NULL OR recovered_at >= detected_at)
) STRICT;

-- last_lat/lon 은 조인 없이 지도에 찍으려고 값을 복사해 둔 것이다.
-- threshold_sec 도 판정 당시 기준을 박제한다 — 나중에 기준이 바뀌어도 기록은 안 흔들린다.
CREATE INDEX ix_pi_comm_loss_accident ON pi_comm_loss (accident_id, detected_at);
CREATE INDEX ix_pi_comm_loss_sync     ON pi_comm_loss (updated_at, comm_loss_id);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_drift_estimate — 표류 예상 범위 (APP-09, 상세기획 §11 우선순위 5위)
--
--   계산 주체는 Pi 다 `확정` 2026-09-11. 상세기획 §1.1 은 "웹" 담당이었으나
--   두절·표류는 인터넷 없이도 동작해야 하고(§9.1), Pi 에 없으면 오프라인 사고의
--   수색 범위 이력이 사라진다.  ⚠ 상세기획 §1.1 수정 필요.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_drift_estimate (
    estimate_id         INTEGER NOT NULL,
    accident_id         TEXT    NOT NULL,
    comm_loss_id        INTEGER,
    base_lat            REAL    NOT NULL,
    base_lon            REAL    NOT NULL,
    last_received_at    INTEGER NOT NULL,
    elapsed_sec         INTEGER NOT NULL,
    center_lat          REAL    NOT NULL,
    center_lon          REAL    NOT NULL,
    -- ⚠ 하위 호환. 타원이 생기기 전 화면이 원으로 그리던 값이다.
    --   95% 장축을 넣는다 — 과소평가보다 과대평가가 낫다(수색 범위다).
    radius_m            REAL    NOT NULL,
    -- 표류 타원. 🔴 **1σ 값이다** (50/75/95 배율 적용 **전**).
    --   같은 공분산에 배율만 바꿔 세 범위를 그리므로(공통 명세 §6), 배율을 미리
    --   먹여 저장하면 화면이 어느 배율인지 모르고 또 곱한다.
    axis_major_m        REAL,
    axis_minor_m        REAL,
    -- 장축 방위. 북 0°, 시계방향 (공통 명세 §2)
    axis_bearing_deg    REAL,
    input_current_speed REAL,
    input_current_dir   REAL,
    input_wind_speed    REAL,
    input_wind_dir      REAL,
    input_observed_at   INTEGER,
    -- 무엇의 표류인가. 부표와 사람은 leeway 계수가 3배 넘게 달라(3.00% vs 0.96%)
    -- 같은 사고에서도 타원이 따로 나온다 (공통 명세 §3).
    --
    -- 🔴 나중에 넣으면 uq_pi_drift_current 를 갈아야 한다 — 그 인덱스가
    --   accident_id 하나로 잡혀 있어서 두 대상을 동시에 못 담는다.
    target              TEXT    NOT NULL DEFAULT 'BUOY',
    is_current          INTEGER NOT NULL DEFAULT 1,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    PRIMARY KEY (estimate_id),
    FOREIGN KEY (accident_id)  REFERENCES pi_accident  (accident_id) ON DELETE CASCADE,
    FOREIGN KEY (comm_loss_id) REFERENCES pi_comm_loss (comm_loss_id),

    CHECK (is_current IN (0, 1)),
    CHECK (target IN ('BUOY', 'PERSON')),
    CHECK (axis_major_m IS NULL OR axis_major_m > 0),
    CHECK (axis_minor_m IS NULL OR axis_minor_m > 0),
    -- 장축이 단축보다 짧으면 둘을 바꿔 넣은 것이다. 조용히 지나가면 타원이 90도 돌아간다
    CHECK (axis_major_m IS NULL OR axis_minor_m IS NULL OR axis_major_m >= axis_minor_m),
    -- 🔴 방위가 아니라 **축**이다. 0~180 이다 — 타원은 180° 대칭이라 90° 와 270°
    --   가 같은 축이고, 360 까지 받으면 같은 타원을 두 가지로 적을 수 있다.
    --   그러면 Pi 와 관제의 추정을 비교할 수가 없다. 180 은 0 과 같으므로 뺀다
    CHECK (axis_bearing_deg IS NULL OR (axis_bearing_deg >= 0 AND axis_bearing_deg < 180)),
    CHECK (base_lat   BETWEEN -90 AND 90),
    CHECK (base_lon   BETWEEN -180 AND 180),
    CHECK (center_lat BETWEEN -90 AND 90),
    CHECK (center_lon BETWEEN -180 AND 180),
    CHECK (radius_m > 0),
    CHECK (elapsed_sec >= 0),
    CHECK (input_current_dir IS NULL OR input_current_dir BETWEEN 0 AND 360),
    CHECK (input_wind_dir    IS NULL OR input_wind_dir    BETWEEN 0 AND 360)
) STRICT;

-- 갱신될 때마다 새 행을 쌓고 이전 건은 is_current = 0 으로 내린다.
-- 덮어쓰면 "그때 어디를 수색 범위로 봤는지"가 사라진다 (상세기획 §6.2).
--
-- ⚠ input_* 은 계산에 쓴 해양 데이터의 스냅샷이다. 전부 NULL 이면 해양 데이터 없이
--   추정한 것이다(§9.1). input_observed_at 을 반드시 화면에 같이 띄워야 한다 —
--   3시간 전 조류로 그린 원과 3분 전 조류로 그린 원은 화면에서 똑같이 생겼다.
CREATE INDEX ix_pi_drift_accident ON pi_drift_estimate (accident_id, created_at DESC);
-- 🔴 `target` 이 들어간다. 부표와 사람의 현재 추정이 **동시에** 있어야 한다 —
--   accident_id 하나로 잡으면 둘 중 하나만 남고, 그게 어느 쪽인지도 모른다.
CREATE UNIQUE INDEX uq_pi_drift_current ON pi_drift_estimate (accident_id, target)
    WHERE is_current = 1;
CREATE INDEX ix_pi_drift_sync ON pi_drift_estimate (updated_at, estimate_id);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_ocean_data — 해양 공공데이터 캐시 (EC2 → Pi pull)
--
--   표류 계산을 Pi 가 하려면 조류·풍속이 오프라인에도 있어야 한다.
--   인터넷이 있을 때 받아 두고, 끊기면 마지막 값으로 계산한다.
--   ⚠ 수집 주체 미정 — EC2 가 받아 Pi 가 pull 하는 쪽을 권한다 (API 키를 배에 두지 않아도 된다).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_ocean_data (
    ocean_data_id INTEGER NOT NULL,
    ship_id       TEXT    NOT NULL,
    observed_at   INTEGER NOT NULL,
    source        TEXT    NOT NULL,
    -- 값을 잰 **그 지점**이다. 본선 위치가 아니다.
    -- 🔴 ROMS 격자는 약 3km 간격이고 관측소는 수십 km 떨어져 있다. 어디 값인지
    --    모르면 "이 자리 조류"인 척하게 되고, 표류 타원이 실제보다 확실해 보인다.
    lat           REAL,
    lon           REAL,
    -- 조회 지점에서 거기까지(km). 화면이 "30km 밖 관측소 값"이라고 말할 수 있어야 한다
    distance_km   REAL,
    wind_speed    REAL,
    wind_dir      REAL,
    current_speed REAL,
    current_dir   REAL,
    -- 한 칸(약 3km) 이내 이웃 격자와의 유속 최대 차이. 표류 명세 §5 의 불확실성 입력이다.
    -- ⚠ NULL 과 0 이 다르다. 이웃이 없어서 못 재면 NULL 이고, 0 으로 두면 "확실하다"로 읽힌다
    current_spread REAL,
    wave_height   REAL,
    water_temp    REAL,
    fetched_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (ocean_data_id),
    FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id),

    CHECK (source IN ('KHOA', 'KMA', 'MOF')),
    CHECK (wind_dir    IS NULL OR wind_dir    BETWEEN 0 AND 360),
    CHECK (current_dir IS NULL OR current_dir BETWEEN 0 AND 360),
    CHECK (wind_speed    IS NULL OR wind_speed    >= 0),
    CHECK (current_speed IS NULL OR current_speed >= 0),
    CHECK (current_spread IS NULL OR current_spread >= 0),
    CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
    CHECK (distance_km IS NULL OR distance_km >= 0),
    UNIQUE (ship_id, source, observed_at)
) STRICT;

-- ⚠ 상세기획 §6.2 의 raw_payload(jsonb)는 넣지 않았다. SQLite STRICT 에 jsonb 가 없고,
--   원본 응답 보관은 EC2 의 몫이다. Pi 는 계산에 쓰는 값만 갖는다.
-- observed_at 은 관측 시각, fetched_at 은 Pi 가 받은 시각이다.
-- 표류 계산은 observed_at 을 pi_drift_estimate.input_observed_at 에 복사한다.
CREATE INDEX ix_pi_ocean_ship ON pi_ocean_data (ship_id, observed_at DESC);

-- ─────────────────────────────────────────────────────────────
-- pi_video — 사고 영상 청크. 30초 단위 (IOT-19)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_video (
    video_name  TEXT    NOT NULL,
    accident_id TEXT    NOT NULL,
    object_key  TEXT,
    duration    INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (video_name),
    FOREIGN KEY (accident_id) REFERENCES pi_accident (accident_id) ON DELETE CASCADE,

    CHECK (duration > 0)
) STRICT;

CREATE INDEX ix_pi_video_accident ON pi_video (accident_id, created_at);
CREATE INDEX ix_pi_video_sync     ON pi_video (updated_at, video_name);

-- ─────────────────────────────────────────────────────────────
-- ⑤ pi_command_log — 키오스크 명령 중복 제거
--
--   QoS 1 은 at-least-once 라 같은 명령이 두 번 온다. 중복되면 신고가 두 번 나가고
--   사고가 두 개 생긴다.
--
--   ⚠ **메모리에 두면 안 된다.** 재부팅 후 replay 된 명령이 그대로 통과한다.
--     키오스크의 재시도 정책(같은 request_id 로 1회 재발행)과 짝이 되려면 디스크여야 한다.
--   ⚠ 명령 토픽에만 적용한다. QoS 0 텔레메트리는 애초에 중복이 안 생기므로
--     1초마다 UUID 를 기억하는 건 낭비다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_command_log (
    request_id  TEXT    NOT NULL,
    command     TEXT    NOT NULL,
    accident_id TEXT,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (request_id),
    CHECK (command IN ('cancel', 'report_now', 'report_manual', 'rescue', 'close'))
) STRICT;

-- 오래된 항목은 지워도 된다 — 키오스크 재시도는 2초 안에 끝난다.
CREATE INDEX ix_pi_command_log_created ON pi_command_log (created_at);

-- ─────────────────────────────────────────────────────────────
-- pi_credential — 서버가 선박 등록 때 **한 번만** 준 선박 키
--
--   POST /api/pi/ships 가 (ship_id, ship_key, status)를 돌려준다 (api.json).
--   그 뒤 모든 /api/pi/** 요청은 X-Ship-Secret-Key 로 이 값을 싣는다.
--   등록 키(X-Ship-Register-Key)는 공용이고 등록 한 번에만 쓴다.
--
--   🔴 **ship_key 는 다시 안 내려온다.** 서버가 해시로만 보관한다. 받는 즉시
--     여기 쓰지 않으면 그 배는 영영 못 붙는다 — 그래서 pi_ship INSERT 와
--     **같은 트랜잭션**이다 (floaq/provision.py register_ship).
--   🔴 **pi_ship 의 컬럼으로 넣지 않는다.** pi_ship 은 sync PUSH 대상이라
--     "행을 그대로 보낸다"가 전제다. 컬럼이면 키가 매 요청 본문에 실려 되돌아간다.
--   🔴 **sync 에 넣지 않는다.** 올릴 이유가 없다.
--   🔴 **floaq/contracts/ 에 모델로 만들지 않는다.** 거기 들어가면 Pi 가 공개로
--     서빙하는 /contract.json 에 스키마가 나간다.
--
--   status 는 서버의 승인 상태다. WAIT 동안에는 등록 말고 아무것도 못 올린다 —
--   사람이 관제 웹에서 POST /api/admin/ships/{shipId}/approve 를 눌러야 한다.
--   REJECTED 는 자동 재시도로 안 풀린다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE pi_credential (
    ship_id    TEXT    NOT NULL,
    ship_key   TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'WAIT',
    issued_at  INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (ship_id),
    FOREIGN KEY (ship_id) REFERENCES pi_ship (ship_id) ON DELETE CASCADE,
    CHECK (length(ship_key) > 0),
    CHECK (status IN ('WAIT', 'ACTIVE', 'REJECTED'))
) STRICT;

-- ─────────────────────────────────────────────────────────────
-- sync — EC2 동기화 커서
--
-- ② 원본은 synced_at 한 컬럼짜리 단일 행이었다. 전 테이블이 워터마크 하나를
--    공유하면, 한 테이블이 실패했을 때 올리면 유실이고 안 올리면 전체 재전송이다.
--    테이블별로 나눈다.
--
--    그리고 워터마크가 시각만이면 경계에서 깨진다. created_at/updated_at 이
--    **초 단위**인데 1Hz 테이블이 있어서 같은 초에 여러 행이 흔하다.
--      >  로 자르면 아직 안 읽은 같은 초 행을 건너뛰고 (유실)
--      >= 로 자르면 매번 같은 초를 다시 보낸다 (중복)
--    그래서 (updated_at, pk) 복합 커서를 쓴다.
--
--      SELECT * FROM pi_buoy
--      WHERE (updated_at, buoy_log_id) > (:synced_at, :synced_pk)
--      ORDER BY updated_at, buoy_log_id
--      LIMIT :batch;
--
--    PK 타입이 테이블마다 달라(TEXT/INTEGER) synced_pk 는 ANY 로 둔다.
--    rowid 는 인덱스에 넣을 수 없으므로 각 테이블의 실제 PK 컬럼으로 인덱스를 걸었다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE sync (
    table_name TEXT    NOT NULL,
    direction  TEXT    NOT NULL,
    synced_at  INTEGER NOT NULL DEFAULT 0,
    synced_pk  ANY,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (table_name, direction),
    CHECK (direction IN ('PUSH', 'PULL'))
) STRICT;

-- PUSH = Pi → EC2 (사고·부표·IMU·영상).  PULL = EC2 → Pi (해양 데이터).
--
-- ⚠ 워터마크는 **저장 확정 응답을 받은 뒤에만** 전진시킨다.
--   영상에 대해 DES-31 C-8 이 정한 원칙과 같다.
-- ⚠ 업로드 순서는 FK 를 따른다:
--     pi_ship → pi_accident → pi_accident_state·pi_launch
--             → pi_buoy·pi_imu·pi_comm_loss·pi_drift_estimate·pi_accident_file·pi_video
--             → pi_report
--   pi_accident 없이 자식을 올리면 서버에서 FK 위반으로 배치가 통째로 롤백된다.
-- ⚠ 삭제 정책은 워터마크 위쪽 행을 절대 건드리지 않는다:
--     DELETE FROM pi_ship_position
--     WHERE (updated_at, position_id) <= (SELECT synced_at, synced_pk
--                                         FROM sync WHERE table_name='pi_ship_position'
--                                                     AND direction='PUSH')
--       AND created_at < :cutoff;

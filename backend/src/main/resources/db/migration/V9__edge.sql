-- V9 — Pi(edge) 데이터 수신용 스키마 확장
--
-- 조건이었던 "IoT 팀 Pi 스키마 원본과 컬럼명 대조"가 끝나 초안(docs/edge_draft.sql)에서 옮겼다
-- (2026-09-17 · database/pi.sql 14테이블 대조 · docs/api.md §4 · §8 · §9 3).
--
-- ⚠ 이 파일은 이제 체크섬이 걸린다. 고치면 이미 적용한 DB 가 기동을 거부한다 —
--   바꿀 일이 생기면 V10 을 새로 만든다. 로컬은 볼륨 재생성(`down -v`)이 절차다.
--
-- 전부 NULL 허용으로 추가한다 — 기존 행이 있는 DB 에서 NOT NULL 추가가 실패하지 않게.
-- NOT NULL 로 조일 컬럼은 "옮길 때 결정" 주석으로 표시했다. 그건 Edge 수신이 실제로
-- 돌기 시작하고 값이 항상 오는 것이 확인된 뒤에 V10 에서 조인다.

-- ─────────────────────────────────────────────────────────────
-- ⓪ 자연키 UNIQUE 복원 — 재전송 멱등의 실제 장치 (결정 2026-09-17)
-- ─────────────────────────────────────────────────────────────
-- V1 ⑤ 는 "재전송 멱등이 PK 자체로 보장된다"며 자연키 UNIQUE 3개를 지우고,
-- **Pi 가 uuid v7 을 채번해 재전송 때 같은 값을 보낸다**를 계약으로 적었다.
--
-- 🔴 Pi 는 그 계약을 안 지킨다 — 그리고 그쪽이 옳다.
--   ref/pi.sql 의 PK 는 전부 INTEGER 자동 채번이다. SQLite STRICT 에서 rowid 별칭이 되려면
--   `INTEGER` 여야 하고, `INT` 로 적으면 통과는 하되 자동 채번이 조용히 멈춘다.
--   대신 Pi 는 테이블마다 자연키 UNIQUE 를 걸고 주석에 "서버 uq_buoy_accident_measured 와 같은
--   멱등키" 라고 적었다 — **서버에 그게 있다고 믿고 있다. 서버는 지웠다.**
--   양쪽이 서로 상대방이 멱등을 해줄 거라 믿는 상태였다.
--
-- 되살린다. Pi 쪽 변경이 0 이고, Pi 가 PK 를 보낼 필요조차 없어진다 —
-- 서버가 uuid 를 채번하고 중복은 자연키가 막는다.
--
-- ✅ 하이퍼테이블에서 되는 것을 확인했다 (2026-09-17 실행).
--    하이퍼테이블은 모든 UNIQUE 에 파티셔닝 컬럼을 요구하는데 셋 다 created_at 을 포함한다.
--    ON CONFLICT (accident_id, created_at) DO NOTHING 으로 2회 INSERT → 1행.
ALTER TABLE buoy ADD CONSTRAINT uq_buoy_accident_measured UNIQUE (accident_id, created_at);
-- imu 의 자연키는 imu_position 을 쓰므로 그 컬럼을 추가한 뒤인 ⑥ 에 있다 (순서 의존).
-- accident_state 는 하이퍼테이블이 아니라 파티셔닝 컬럼 제약이 없다
ALTER TABLE accident_state ADD CONSTRAINT uq_state_accident_status_at UNIQUE (accident_id, status, created_at);
-- report 는 ④ 의 uq_report_accident_channel 이 이미 같은 역할을 한다 (Pi UNIQUE (accident_id, channel) 과 일치)

-- ⚠ 이걸 넣으면 edge 수신 코드는 ON CONFLICT 대상을 **PK 가 아니라 자연키**로 적어야 한다.
--   PK 로 적으면 서버가 매번 새 uuid 를 채번하므로 충돌이 영원히 안 난다 — 조용히 중복이 쌓인다.

-- ─────────────────────────────────────────────────────────────
-- ① accident — Pi pi_accident 에만 있던 컬럼 (api.md §8 #5·#13)
-- ─────────────────────────────────────────────────────────────
ALTER TABLE accident
    ADD COLUMN accident_type  varchar(20),
    ADD COLUMN trigger_source varchar(8),
    ADD COLUMN wait_sec       integer,
    ADD COLUMN reported_at    timestamptz,
    ADD COLUMN rescued_at     timestamptz,
    ADD COLUMN model_version  varchar(64),
    -- varchar + CHECK — 8종 확정(2026-09-17, api.md §8 #16). enum 이 아니라 varchar 인 이유:
    -- SAFETY 를 되살리면 값이 다시 늘고, enum 은 값 삭제가 사실상 불가하다
    ADD CONSTRAINT ck_accident_type CHECK (accident_type IS NULL OR accident_type IN (
        'MOB', 'FIRE', 'FLOODING', 'COLLISION', 'GROUNDING', 'ENGINE_FAILURE',
        'OTHER_DISTRESS', 'MEDICAL')),
    ADD CONSTRAINT ck_accident_trigger CHECK (trigger_source IS NULL OR trigger_source IN ('AI', 'MANUAL')),
    -- Pi ck_pi_accident_ai_type 과 같은 규칙. AI 감지는 익수만 만든다(계획.md §9.21)
    ADD CONSTRAINT ck_accident_ai_mob CHECK (trigger_source IS DISTINCT FROM 'AI' OR accident_type = 'MOB'),
    ADD CONSTRAINT ck_accident_wait_sec CHECK (wait_sec IS NULL OR wait_sec >= 0);

COMMENT ON COLUMN accident.accident_type  IS '옮길 때 NOT NULL 결정. 8종 전부 사고를 여는 유형이다 — SAFETY 2종(HAZARD·ABANDON_SHIP)은 1차 범위에서 뺐다(2026-09-17). ⚠ Pi enums.py 는 아직 10종';
COMMENT ON COLUMN accident.wait_sec       IS '카운트다운 길이. 30초가 정책값이라 사고마다 기록';
COMMENT ON COLUMN accident.reported_at    IS '첫 REPORT 시각. 서버가 accident-states 수신 때 채움 — 목록 조회마다 accident_state join 을 피하려는 비정규화(api.md §3.4)';
COMMENT ON COLUMN accident.rescued_at     IS '구조 확정 시각. CLOSE 가 구조인지 종료인지 가르는 유일한 값(api.md §3.4)';
COMMENT ON COLUMN accident.model_version  IS '오탐 분석용';

-- ─────────────────────────────────────────────────────────────
-- ② accident_state — 이전 상태 · 사유 (api.md §4.3 · mqtt.md §5.3)
-- ─────────────────────────────────────────────────────────────
ALTER TABLE accident_state
    ADD COLUMN prev_status varchar(16),
    ADD COLUMN reason      varchar(24),
    -- 무엇이 이 전이를 일으켰나. 키오스크 명령이면 그 request_id 가 들어온다(database/pi.sql pi_accident_state)
    ADD COLUMN caused_by   varchar(64),
    ADD CONSTRAINT ck_state_prev_status CHECK (prev_status IS NULL OR prev_status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE')),
    -- mqtt.md §5.3 의 8종. 모르는 사유는 400 으로 거절 — 조용히 null 로 두면 종결 주체 기록이 사라짐
    ADD CONSTRAINT ck_state_reason CHECK (reason IS NULL OR reason IN (
        'AI_DETECT', 'COUNTDOWN_START', 'TIMEOUT', 'TABLET_CANCEL', 'TABLET_REPORT_NOW',
        'TABLET_MANUAL', 'TABLET_RESCUE', 'TABLET_CLOSE'));

-- 🔴 사유 목록에 관제 웹 종료·1시간 자동 종결이 없다. 계획.md §9.20 "종결 주체를 남긴다"가 여기 걸림.
--    후보 WEB_CLOSE · AUTO_CLOSE — IoT 팀 합의 후 CHECK 에 추가.
COMMENT ON COLUMN accident_state.reason IS '종결 주체도 이 값으로 가름(api.md §8 #5). ⚠ WEB_CLOSE·AUTO_CLOSE 미합의';

-- ─────────────────────────────────────────────────────────────
-- ③ launch — 투하 결과 · 목표 위치 (api.md §8 #14 · mqtt.md §5.4)
-- ─────────────────────────────────────────────────────────────
ALTER TABLE launch
    ADD COLUMN detection_id varchar(64),
    ADD COLUMN result      varchar(8),
    ADD COLUMN fail_reason varchar(16),
    ADD COLUMN target_lat  float8,
    ADD COLUMN target_lon  float8,
    ADD CONSTRAINT ck_launch_result      CHECK (result IS NULL OR result IN ('SUCCESS', 'FAILED')),
    -- NO_SOLUTION 추가 (2026-09-17, ref/pi.sql 대조) — Jetson 이 조준 해를 못 낸 경우.
    -- varchar(16) 에 들어간다(12자)
    ADD CONSTRAINT ck_launch_fail_reason CHECK (fail_reason IS NULL OR fail_reason IN ('NOT_LOADED', 'DEVICE_ERROR', 'OUT_OF_RANGE', 'NO_SOLUTION')),
    -- Pi ck_pi_launch_fail_reason 과 같은 규칙
    ADD CONSTRAINT ck_launch_success_reason CHECK (result IS DISTINCT FROM 'SUCCESS' OR fail_reason IS NULL),
    ADD CONSTRAINT ck_launch_target_lat CHECK (target_lat IS NULL OR target_lat BETWEEN -90 AND 90),
    ADD CONSTRAINT ck_launch_target_lon CHECK (target_lon IS NULL OR target_lon BETWEEN -180 AND 180);

COMMENT ON COLUMN launch.detection_id IS 'Jetson 탐지 건 식별자. 조준 해의 출처 추적용 (database/pi.sql pi_launch)';
COMMENT ON COLUMN launch.result IS '옮길 때 NOT NULL 결정. FAILED 도 저장 — 발사 정확도 피드백 근거';

-- ─────────────────────────────────────────────────────────────
-- ④ report — append-only → 채널별 upsert (api.md §8 #8 · mqtt.md §5.10)
-- ─────────────────────────────────────────────────────────────
-- created_at = first_sent_at (불변). V1 PK (report_id, created_at) 가 upsert 키로 성립하려면 이 매핑이 필요
ALTER TABLE report
    ADD COLUMN channel       varchar(8),
    ADD COLUMN trigger_kind  varchar(8),
    -- 🔴 created_at 과 나눈 이유는 아래 주석. Pi 는 이 값이 NULL 일 수 있다
    ADD COLUMN first_sent_at timestamptz,
    ADD COLUMN status       varchar(8),
    ADD COLUMN sent_count   integer,
    ADD COLUMN last_sent_at timestamptz,
    ADD COLUMN acked_at     timestamptz,
    ADD COLUMN acked_by     varchar(9),
    ADD COLUMN fail_reason  varchar(16),
    ADD CONSTRAINT ck_report_channel     CHECK (channel IS NULL OR channel IN ('AIS_MOB', 'AIS_SART', 'DSC')),
    ADD CONSTRAINT ck_report_trigger_kind CHECK (trigger_kind IS NULL OR trigger_kind IN ('AUTO', 'MANUAL', 'RESCUE')),
    ADD CONSTRAINT ck_report_status      CHECK (status IS NULL OR status IN ('SENDING', 'ACKED', 'STOPPED', 'FAILED')),
    ADD CONSTRAINT ck_report_sent_count  CHECK (sent_count IS NULL OR sent_count >= 0),
    ADD CONSTRAINT ck_report_fail_reason CHECK (fail_reason IS NULL OR fail_reason IN ('NO_INTERNET', 'NO_RECEIVER', 'TIMEOUT')),
    -- 아래 셋은 Pi ck_pi_report_ack_channel · ack_status · acked_by 와 같은 규칙
    ADD CONSTRAINT ck_report_ack_channel CHECK (acked_at IS NULL OR channel = 'DSC'),
    ADD CONSTRAINT ck_report_ack_status  CHECK ((status = 'ACKED') = (acked_at IS NOT NULL)),
    ADD CONSTRAINT ck_report_acked_by    CHECK (acked_by IS NULL OR acked_by ~ '^[0-9]{9}$');

-- 사고당 채널 1행. 같은 채널이 두 행이면 "몇 번 보냈나"가 둘로 쪼개짐
CREATE UNIQUE INDEX uq_report_accident_channel ON report (accident_id, channel) WHERE channel IS NOT NULL;

COMMENT ON COLUMN report.sent_count IS '누적. 줄어들면 옛 행(stale) — api.md §4.3';

-- 🔴 report.created_at = first_sent_at 매핑이 깨진다 (2026-09-17, ref/pi.sql 대조).
--   Pi 의 first_sent_at 은 **NULL 허용**이다 — 아직 한 번도 못 쏜 채널의 행이 먼저 생긴다
--   (예: internet 두절로 SENDING 도 못 간 DSC). 서버 PK 는 (report_id, created_at) 이라
--   created_at 이 NULL 이면 행 자체가 못 들어간다.
--   후보 ① created_at = Pi created_at(행 생성 시각), first_sent_at 을 별도 컬럼으로 추가
--        ② first_sent_at 이 NULL 인 행은 Pi 가 안 보낸다
--   ①이 낫다 — ②는 "못 쏜 채널"이 관제에 안 보인다. 그게 봐야 하는 정보다.
-- ⚠ Report 엔티티가 isNew() 항상 true(append-only). 이 스키마로 옮기면 엔티티도 upsert 로 바꿔야 함
-- ⚠ Pi pi_report.report_type(AUTO/MANUAL/RESCUE)은 받지 않음 — accident.report_type 과 이름만 같고 뜻이 다름(mqtt.md §8)

-- ─────────────────────────────────────────────────────────────
-- ⑤ buoy (하이퍼테이블) — 순번 · 수신 시각 · 신호 세기
-- ─────────────────────────────────────────────────────────────
-- 하이퍼테이블 ADD COLUMN 은 청크 전체에 전파됨. 기본값 없는 NULL 컬럼이라 재작성 없음
ALTER TABLE buoy
    ADD COLUMN seq         integer,
    ADD COLUMN received_at timestamptz,
    ADD COLUMN rssi        real;

COMMENT ON COLUMN buoy.seq         IS '부표가 매긴 순번. 유실 감지용';
COMMENT ON COLUMN buoy.received_at IS 'Pi LoRa 수신 시각. created_at(부표 GPS 측정 시각)과 다름';
-- 🔴 좌표 컬럼명: 서버 buoy_lat/buoy_lon vs Pi lat/lon(mqtt.md §6·§8 "lng → lon"). 대조 전 확정 불가
-- 🔴 PK: 서버 uuid vs mqtt.md buoy_log_id Int (api.md §8 #9)

-- ─────────────────────────────────────────────────────────────
-- ⑥ imu (하이퍼테이블) — 장착 위치 · 방위
-- ─────────────────────────────────────────────────────────────
ALTER TABLE imu
    ADD COLUMN imu_position varchar(8),
    ADD COLUMN heading_deg  real,
    ADD CONSTRAINT ck_imu_position CHECK (imu_position IS NULL OR imu_position IN ('HULL', 'CAMERA_L', 'CAMERA_R')),
    -- Pi 는 BETWEEN 0 AND 360 이라 360 을 허용한다. 서버만 막으면 배치 전체가 롤백된다
    ADD CONSTRAINT ck_imu_heading  CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360);

-- ⓪ 의 자연키 복원 중 imu 것. imu_position 을 쓰므로 여기여야 한다.
-- ⚠ NULLS NOT DISTINCT 가 필요하다 — PG 기본은 NULL 끼리 서로 다르다고 봐서,
--   imu_position 이 NULL 인 행은 UNIQUE 가 있어도 재전송이 그대로 중복된다.
--   이걸 쓰면 imu_position 을 NULL 허용으로 둔 채(이 파일의 원칙) 멱등이 성립한다.
-- imu_position 을 키에 넣는 이유: IMU 2개를 동시에 쓰면 (accident_id, created_at) 만으로는
--   같은 초에 온 둘째가 거부된다. 상세기획 §2.2 는 "3개 중 하나"지만 스키마가 그 결정을 막지 않게 둔다.
-- ✅ 하이퍼테이블에서 되는 것 확인 (2026-09-17 실행).
ALTER TABLE imu ADD CONSTRAINT uq_imu_accident_measured
    UNIQUE NULLS NOT DISTINCT (accident_id, created_at, imu_position);

-- ─────────────────────────────────────────────────────────────
-- ⑦ edge_command — 관제 → Pi 하행 명령 (api.md §3.5 · §4.4 · §4.5)
-- ─────────────────────────────────────────────────────────────
-- 서버가 만드는 행이라 단일 PK. Pi 기원 테이블의 (uuid, created_at) 규칙(V1 ⑤) 대상 아님
CREATE TABLE edge_command (
    command_id      uuid         NOT NULL,
    ship_id         uuid         NOT NULL,
    accident_id     uuid         NOT NULL,
    type            varchar(16)  NOT NULL,
    state           varchar(12)  NOT NULL,
    issued_by       bigint       NOT NULL,
    issued_at       timestamptz  NOT NULL,
    delivered_at    timestamptz,
    handled_at      timestamptz,
    expired_at      timestamptz,
    error_code      varchar(32),
    accident_status varchar(16),
    CONSTRAINT pk_edge_command PRIMARY KEY (command_id),
    CONSTRAINT fk_command_ship     FOREIGN KEY (ship_id)     REFERENCES ship (ship_id),
    CONSTRAINT fk_command_accident FOREIGN KEY (accident_id) REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT fk_command_user     FOREIGN KEY (issued_by)   REFERENCES users (user_id),
    CONSTRAINT ck_command_type  CHECK (type IN ('CLOSE_ACCIDENT', 'STOP_MEDIA')),
    CONSTRAINT ck_command_state CHECK (state IN ('ISSUED', 'DELIVERED', 'DONE', 'REJECTED', 'EXPIRED')),
    CONSTRAINT ck_command_error CHECK (error_code IS NULL OR state = 'REJECTED'),
    CONSTRAINT ck_command_accident_status CHECK (accident_status IS NULL OR accident_status IN ('DETECT', 'WAIT', 'REPORT', 'CANCEL', 'CLOSE'))
);

COMMENT ON COLUMN edge_command.command_id IS 'uuid v7 = 시간순. Pi 폴링이 이 순서로 받음';
COMMENT ON COLUMN edge_command.expired_at IS '만료 시각. 만료 뒤 늦게 온 ack 도 받아 state 를 DONE/REJECTED 로 덮음(api.md §3.5)';
COMMENT ON COLUMN edge_command.accident_status IS 'ack 때 Pi 가 아는 사고 상태. 화면을 실제 상태로 돌리는 근거';

-- 같은 사고·유형에 처리 전 명령 1건 — 연타로 명령이 쌓이지 않게(api.md §3.5 INVALID_STATE)
CREATE UNIQUE INDEX uq_edge_command_pending ON edge_command (accident_id, type)
    WHERE state IN ('ISSUED', 'DELIVERED');
-- Pi 폴링 GET /api/edge/commands?ship_id= — 미처리만
CREATE INDEX ix_edge_command_poll ON edge_command (ship_id, command_id)
    WHERE state IN ('ISSUED', 'DELIVERED');

-- ─────────────────────────────────────────────────────────────
-- ⑧ ship_position (하이퍼테이블) — 선박 위치. 평시 + 사고 구간
-- ─────────────────────────────────────────────────────────────
-- 2026-09-17 결정: 평시 항적을 받는다. 계획.md §9.13 의 "웹이 위치를 받는 계기는 사고뿐" 을 뒤집은 것.
--   보관 24시간 · 원천은 pi/sensor/gps (Pi 자체 GPS, mqtt-연동-웹_v2 §2).
--
--   주기 — **평시 5초 · 사고 중(DETECT/WAIT/REPORT) 1초** (ref/pi.sql 제안 채택, 2026-09-17).
--     ⚠ MQTT 발행은 항상 1Hz 지만 **DB 에 적는 주기는 다르다.** 서버로 올라오는 건 DB 쪽이다.
--     근거(ref/pi.sql): 10노트면 5초에 26m — 항적·ETA 용으로는 지도에서 충분히 부드럽다.
--     조준 해 입력(speed_kn·heading_deg)은 5초 전 값을 쓰면 안 되지만 그건 MQTT 1Hz 가 받는다.
--     하루 17,280행(1Hz 대비 1/5). 사고 구간만 1초라 거기서만 조밀해진다.
--   기각: Redis Stream — 재전송 멱등(api.md §4.2)이 XADD 로는 성립하지 않고,
--        noeviction 한도에서 평시 항적이 incident:{id}:reported SETNX 가드 쓰기를 밀어낸다(계획.md §2).
CREATE TABLE ship_position (
    ship_position_id uuid        NOT NULL,
    ship_id          uuid        NOT NULL,
    accident_id      uuid,
    -- 컬럼명은 Pi(ref/pi.sql pi_ship_position)를 그대로 따른다 — 매핑 한 겹을 없앤다.
    -- ⚠ buoy 는 V1 이 buoy_lat/buoy_lon 으로 이미 배포돼 그대로 두고 DTO 에서 매핑한다(미결).
    lat              float8      NOT NULL,
    lon              float8      NOT NULL,
    speed_kn         real,
    heading_deg      real,
    accuracy_m       real,
    created_at       timestamptz NOT NULL,
    CONSTRAINT pk_ship_position PRIMARY KEY (ship_position_id, created_at),
    CONSTRAINT fk_ship_position_ship     FOREIGN KEY (ship_id)     REFERENCES ship (ship_id),
    CONSTRAINT fk_ship_position_accident FOREIGN KEY (accident_id) REFERENCES accident (accident_id) ON DELETE SET NULL,
    CONSTRAINT ck_ship_position_lat     CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT ck_ship_position_lon     CHECK (lon BETWEEN -180 AND 180),
    CONSTRAINT ck_ship_position_speed   CHECK (speed_kn IS NULL OR speed_kn >= 0),
    -- Pi 는 BETWEEN 0 AND 360 이라 360 을 허용한다. 서버도 맞춘다 — 경계에서만 거절하면
    -- Pi 가 보낸 행이 서버에서만 튕겨 배치 전체가 롤백된다
    CONSTRAINT ck_ship_position_heading CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 360),
    -- 재전송 멱등. Pi UNIQUE (ship_id, created_at) 과 같은 키 (⓪ 와 같은 방식)
    CONSTRAINT uq_ship_position_measured UNIQUE (ship_id, created_at)
);

-- 조각 1시간. 기본값(7일)이면 drop_chunks(older_than => 24h) 가 거의 아무것도 못 버린다 —
-- 조각은 "전체 범위가 기준보다 오래됐을 때만" 버려지므로 7일 조각에 24시간 보관은 최대 8일치가 남는다.
-- 평시 5초면 720행/조각, 사고 중 1초 구간은 3,600행/조각. 상시 24~25조각.
-- 간격은 by_range 의 2번째 인자다. chunk_time_interval => 을 따로 넘기면
-- "function create_hypertable(...) does not exist" 다 (2026-09-17 실행 확인).
SELECT create_hypertable('ship_position', by_range('created_at', INTERVAL '1 hour'),
                         if_not_exists => TRUE);

COMMENT ON TABLE  ship_position            IS '선박 위치. 평시 5초 · 사고 중 1초. 보관 24시간(계획.md §9.13, 2026-09-17)';
COMMENT ON COLUMN ship_position.ship_position_id IS 'uuid v7. Pi 발급. ⚠ 재전송 때 같은 값이어야 멱등이 성립한다 (V1 ⑤)';
COMMENT ON COLUMN ship_position.accident_id      IS '평시 NULL. 사고 구간이면 그 사고. 이 컬럼의 유무가 평시/사고를 가른다';
COMMENT ON COLUMN ship_position.created_at       IS 'GPS 측정 시각(measured_at). Pi 수신 시각도 서버 수신 시각도 아니다';
COMMENT ON COLUMN ship_position.speed_kn         IS 'knot. ETA 계산 입력(계획.md §9.14)';
COMMENT ON COLUMN ship_position.heading_deg      IS '진북 기준 0~360';
COMMENT ON COLUMN ship_position.accuracy_m       IS 'GPS 오차 반경(m). null 이면 Pi 가 모르는 것이지 오차가 0 인 것이 아니다';

-- "이 배 지금 어디" — 선박당 최신 1건. 86,400행에서 풀스캔하지 않게
CREATE INDEX ix_ship_position_ship_created ON ship_position (ship_id, created_at DESC);
-- 사고 구간 항적만. 평시 행이 대부분이라 부분 인덱스로 크기를 줄인다
CREATE INDEX ix_ship_position_accident ON ship_position (accident_id, created_at)
    WHERE accident_id IS NOT NULL;

-- 보관 24시간 — 🔴 add_retention_policy 는 못 쓴다.
--   timescaledb 2.21.3 apache 라이선스에서 "not supported under the current apache license" (2026-09-17 실호출 확인).
--   drop_chunks 는 apache 에서 된다 → 스케줄러가 부른다. OceanRetention 과 같은 줄기(정책 없이 직접 지운다).
--   SELECT drop_chunks('ship_position', older_than => INTERVAL '24 hours');
--   ⚠ 조각 단위라 실제 보관은 24~25시간이다. 정확히 24시간이 필요하면 DELETE 를 써야 하고, 그러면 bloat 가 온다.

-- 🔴 Pi 스키마 대조 항목
--   ✅ 컬럼명 — Pi 이름(lat/lon)을 따랐다 (2026-09-17, ref/pi.sql 대조 완료)
--   ✅ PK      — Pi 는 position_id INTEGER 자동 채번. 서버가 uuid 를 채번하고 멱등은 자연키가 한다(⓪)
--   Pi 의 updated_at 은 받지 않는다 — 그쪽 동기화 워터마크용이고 서버는 자기 수신 시각을 쓴다

-- ─────────────────────────────────────────────────────────────
-- ⑨ 제안 테이블 — DDL 쓰지 않음. Pi 스키마는 받았고(2026-09-17) 서버 화면 요구가 정해지면 쓴다
-- ─────────────────────────────────────────────────────────────
-- comm_loss       pi_comm_loss 10컬럼 — LoRa 두절 구간.
--                 ✅ 판정 주체는 Pi 로 확정(threshold_sec 로 판정 당시 기준을 박제). api.md §9 4 해소
-- drift_estimate  pi_drift_estimate 18컬럼 — 표류 추정 이력. is_current 부분 UNIQUE 로 현재 1건.
--                 input_* 는 계산에 쓴 해양 데이터 스냅샷 — 전부 NULL 이면 해양 데이터 없이 추정한 것이다.
--                 ⚠ input_observed_at 을 화면에 반드시 같이 띄운다 (3시간 전 조류로 그린 원과 3분 전 것이 똑같이 생겼다)
-- accident_file   pi_accident_file 12컬럼 — 감지 스틸컷 + 사고 전후 프레임. camera L|R 있음(서버에 없는 구분).
--                 🔴 업로드 규약이 둘이다 — api.md §4.3 tar 묶음 vs mqtt-연동-웹_v2 §11 장당 1요청 (§8 #20)
-- video           pi_video — Pi 가 30초 청크를 만든다(IOT-19).
--                 🔴 계획.md §9.6 은 "진행 중엔 최신 프레임, 종결 시 EC2 가 mp4 한 번"이고
--                    청크 이어붙이기를 명시적으로 기각했다. Pi 가 청크를 만들면 그 기각이 무효가 된다
--
-- 🔴 서버에 아예 없는 경로: **하행 해양 데이터** (pi_ocean_data · sync.direction = 'PULL')
--    Pi 가 표류를 오프라인에서 계산하려면 조류·풍속이 Pi 에 있어야 한다.
--    api.md §4.4 에는 GET /api/edge/commands 뿐이다 — GET /api/edge/ocean?ship_id= 가 필요하다.
--    Pi 주석도 "EC2 가 받아 Pi 가 pull 하는 쪽을 권한다(API 키를 배에 두지 않아도 된다)"로 같은 방향.

-- ─────────────────────────────────────────────────────────────
-- 옮기기 전 확인 목록
-- ─────────────────────────────────────────────────────────────
-- 1. Pi schema.sql 원본과 컬럼명·타입 대조 (buoy 좌표명, PK 타입)
-- 2. accident_state.reason 에 WEB_CLOSE · AUTO_CLOSE 합의
-- 3. NOT NULL 로 조일 컬럼: accident.accident_type · trigger_source, launch.result, report.channel · status · sent_count
-- 4. Report 엔티티 upsert 전환 · edge DTO @JsonNaming(SnakeCase)
-- 5. 이 초안은 전부 추가(ADD COLUMN · CREATE TABLE)라, 옮길 때 볼륨 재생성이 필요 없다

-- Pi 가 이미 POST 하고 있는데 서버에 표가 없던 셋 (dev-iot `iot/pi/floaq/sync.py` TABLES 대조, 2026-09-18)
--
-- V9__edge.sql ⑨ 가 "제안 테이블 — DDL 쓰지 않음" 으로 남겨 둔 자리다. 그 사이 Pi 는
-- 9개 경로를 순서대로 밀고 있고 **그 순서가 곧 FK 순서**라, 앞 테이블에서 404 가 나면
-- 뒤가 통째로 멈춘다(sync.py "첫 테이블에서 끊는다"). 그래서 남은 셋을 여기서 만든다.
--
-- 공통 원칙 (V9 ⓪ 와 같다)
--   · Pi 의 PK(INTEGER)는 받지 않는다 — Pi 안에서만 뜻이 있다. 서버가 uuid v7 을 채번하고
--     멱등은 **자연키 UNIQUE** 가 보장한다. PK 로 걸면 매번 새 값이라 충돌이 영영 안 난다.
--   · Pi 의 updated_at 은 받지 않는다 — 그쪽 동기화 워터마크다.
--   · 좌표·각도 CHECK 범위는 Pi 와 같게 둔다. 서버만 좁히면 Pi 가 보낸 행이 여기서만 튕겨
--     배치 전체가 롤백된다(V9 ck_ship_position_heading 과 같은 이유).

-- ─────────────────────────────────────────────────────────────
-- ① comm_loss — LoRa 두절 구간 (상세기획 §8 · ref/pi.sql pi_comm_loss)
-- ─────────────────────────────────────────────────────────────
-- 판정 주체는 Pi 다. threshold_sec 로 **판정 당시 기준을 박제**한다 —
-- 나중에 임계를 바꿔도 지난 기록의 뜻이 흔들리지 않는다.
-- last_lat/lon 은 조인 없이 지도에 찍으려고 복사해 둔 값이다.
CREATE TABLE comm_loss (
    comm_loss_id     uuid        NOT NULL,
    accident_id      uuid        NOT NULL,
    detected_at      timestamptz NOT NULL,
    last_lat         float8      NOT NULL,
    last_lon         float8      NOT NULL,
    last_received_at timestamptz NOT NULL,
    threshold_sec    integer     NOT NULL,
    recovered_at     timestamptz,
    -- ⚠ Pi 는 이 표에 created_at 을 보내지 않는다(sync.py comm-losses 컬럼 7개).
    --    그래서 이건 **서버 수신 시각**이다. 두절 시각은 detected_at 을 봐야 한다
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz,
    CONSTRAINT pk_comm_loss PRIMARY KEY (comm_loss_id),
    CONSTRAINT fk_comm_loss_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_comm_loss_lat       CHECK (last_lat BETWEEN -90 AND 90),
    CONSTRAINT ck_comm_loss_lon       CHECK (last_lon BETWEEN -180 AND 180),
    CONSTRAINT ck_comm_loss_threshold CHECK (threshold_sec > 0),
    CONSTRAINT ck_comm_loss_recovered CHECK (recovered_at IS NULL OR recovered_at >= detected_at),
    -- 재전송 멱등. 두절 복귀 뒤 recovered_at 만 채워 다시 오므로 UPDATE 로 받는다
    CONSTRAINT uq_comm_loss_detected  UNIQUE (accident_id, detected_at)
);

COMMENT ON COLUMN comm_loss.threshold_sec IS '판정 당시 임계(초). 기준이 바뀌어도 기록은 안 흔들린다';
COMMENT ON COLUMN comm_loss.created_at    IS 'Pi 가 안 보내는 값 — 서버 수신 시각이다. 두절 시각은 detected_at';

CREATE INDEX ix_comm_loss_accident ON comm_loss (accident_id, detected_at);

-- ─────────────────────────────────────────────────────────────
-- ② drift_estimate — 표류 추정 이력 (ref/pi.sql pi_drift_estimate)
-- ─────────────────────────────────────────────────────────────
-- input_* 는 계산에 쓴 해양 데이터 스냅샷이다. 전부 NULL 이면 해양 데이터 없이 추정한 것.
-- ⚠ input_observed_at 을 화면에 반드시 같이 띄운다 —
--   3시간 전 조류로 그린 원과 3분 전 것이 똑같이 생겼다(V9 ⑨ 주석).
--
-- ⚠ Pi 의 comm_loss_id 는 받지 않는다. Pi 안의 INTEGER 라 서버에서 뜻이 없고(api.md §4.3),
--   sync.py 도 그 컬럼을 보내지 않는다. 두절과의 연결이 필요해지면
--   comm_loss_detected_at 을 추가하는 쪽으로 간다 — 그때 IoT 팀 합의가 먼저다.
CREATE TABLE drift_estimate (
    estimate_id         uuid        NOT NULL,
    accident_id         uuid        NOT NULL,
    base_lat            float8      NOT NULL,
    base_lon            float8      NOT NULL,
    last_received_at    timestamptz NOT NULL,
    elapsed_sec         integer     NOT NULL,
    center_lat          float8      NOT NULL,
    center_lon          float8      NOT NULL,
    radius_m            real        NOT NULL,
    input_current_speed real,
    input_current_dir   real,
    input_wind_speed    real,
    input_wind_dir      real,
    input_observed_at   timestamptz,
    is_current          boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz,
    CONSTRAINT pk_drift_estimate PRIMARY KEY (estimate_id),
    CONSTRAINT fk_drift_estimate_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_drift_base_lat    CHECK (base_lat   BETWEEN -90 AND 90),
    CONSTRAINT ck_drift_base_lon    CHECK (base_lon   BETWEEN -180 AND 180),
    CONSTRAINT ck_drift_center_lat  CHECK (center_lat BETWEEN -90 AND 90),
    CONSTRAINT ck_drift_center_lon  CHECK (center_lon BETWEEN -180 AND 180),
    CONSTRAINT ck_drift_radius      CHECK (radius_m > 0),
    CONSTRAINT ck_drift_elapsed     CHECK (elapsed_sec >= 0),
    CONSTRAINT ck_drift_current_dir CHECK (input_current_dir IS NULL OR input_current_dir BETWEEN 0 AND 360),
    CONSTRAINT ck_drift_wind_dir    CHECK (input_wind_dir    IS NULL OR input_wind_dir    BETWEEN 0 AND 360),
    -- 재전송 멱등. Pi PK(estimate_id INTEGER)는 서버에서 뜻이 없다
    CONSTRAINT uq_drift_estimate_created UNIQUE (accident_id, created_at)
);

-- 사고당 현재 추정 1건 (Pi 부분 UNIQUE 와 같은 규칙).
-- 🔴 이 인덱스가 있으면 **서비스가 먼저 옛 행을 내려야** 한다 — 안 내리고 INSERT 하면
--    배치 전체가 롤백된다. PiEventService.acceptDriftEstimates 가 그 순서를 지킨다.
--    인덱스를 빼는 쪽도 검토했으나 기각 — 현재 추정이 둘이면 지도에 어느 원을 그릴지 알 수 없다.
CREATE UNIQUE INDEX uq_drift_estimate_current ON drift_estimate (accident_id) WHERE is_current;

COMMENT ON COLUMN drift_estimate.input_observed_at IS '입력 해양 데이터 관측 시각. 화면에 반드시 같이 띄운다 — 3시간 전 조류로 그린 원과 3분 전 것이 똑같이 생겼다';
COMMENT ON COLUMN drift_estimate.is_current        IS '현재 추정. 사고당 1건(부분 UNIQUE)';

CREATE INDEX ix_drift_estimate_accident ON drift_estimate (accident_id, created_at);

-- ─────────────────────────────────────────────────────────────
-- ③ accident_file — 감지 스틸컷 + 사고 전후 프레임 (ref/pi.sql pi_accident_file)
-- ─────────────────────────────────────────────────────────────
-- 바이너리는 R2 에 있고 여기엔 **키만** 둔다 (계획.md §2 · video 와 같은 방식).
-- object_key 는 Pi 로컬 상대경로와 **같은 문자열**이다 — dev-iot `web/files.py` 가
-- `accidents/{accident_id}/{file_type}/{seq:04d}.{ext}` 로 맞춰 뒀다.
-- 그래서 선내(Pi 로컬 HTTP)와 육상(R2)이 같은 키로 같은 장을 가리킨다.
--
-- ⚠ Pi 는 R2 자격증명을 갖지 않는다. 어선에 실린 물리 장비라 분해·도난을 전제한다 —
--   Pi 가 EC2 로 올리고 EC2 만 저장소에 넣는다(계획.md §9.6 · ref/mqtt-연동-웹_v2 §11).
CREATE TABLE accident_file (
    file_id      uuid         NOT NULL,
    accident_id  uuid         NOT NULL,
    file_type    varchar(16)  NOT NULL,
    -- DETECT_SNAPSHOT 은 장이 하나라 순번이 없다(NULL). 아래 NULLS NOT DISTINCT 가 그걸 받친다
    sequence_no  integer,
    object_key   varchar(200) NOT NULL,
    content_type varchar(32)  NOT NULL,
    camera       varchar(1),
    bytes        integer,
    captured_at  timestamptz,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz,
    CONSTRAINT pk_accident_file PRIMARY KEY (file_id),
    CONSTRAINT fk_accident_file_accident FOREIGN KEY (accident_id)
        REFERENCES accident (accident_id) ON DELETE CASCADE,
    CONSTRAINT ck_accident_file_type   CHECK (file_type IN ('DETECT_SNAPSHOT', 'BEFORE', 'AFTER')),
    CONSTRAINT ck_accident_file_camera CHECK (camera IS NULL OR camera IN ('L', 'R')),
    CONSTRAINT ck_accident_file_bytes  CHECK (bytes IS NULL OR bytes > 0),
    CONSTRAINT ck_accident_file_seq    CHECK (sequence_no IS NULL OR sequence_no BETWEEN 0 AND 99999),
    -- 🔴 NULLS NOT DISTINCT 가 **필수**다. PG 기본은 NULL 끼리 서로 다르다고 보므로,
    --    sequence_no 가 NULL 인 DETECT_SNAPSHOT 은 평범한 UNIQUE 로는 재전송이 그대로 중복된다.
    --    imu 에서 이미 겪은 함정이다(V9 ⑥). PG15+ 문법이고 운영은 pg17 이다(infra 이미지 확인)
    CONSTRAINT uq_accident_file UNIQUE NULLS NOT DISTINCT (accident_id, file_type, sequence_no)
);

COMMENT ON TABLE  accident_file             IS 'R2 오브젝트 키만 둔다. 바이너리는 DB 에 넣지 않는다';
COMMENT ON COLUMN accident_file.object_key  IS 'Pi 로컬 상대경로와 같은 문자열 — 선내·육상이 같은 키로 같은 장을 가리킨다';
COMMENT ON COLUMN accident_file.camera      IS 'L|R. 서버 다른 표에는 없는 구분이라 여기서만 보존한다';
COMMENT ON COLUMN accident_file.captured_at IS 'Pi 가 찍은 시각. created_at(서버 수신)과 다르다';

CREATE INDEX ix_accident_file_accident ON accident_file (accident_id, file_type, sequence_no);

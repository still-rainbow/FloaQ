-- 해양 수집 — 선박 여러 척 · 백엔드 여러 대 (2026-09-15)
--
-- 이전: 서버 메모리의 수집 해역 하나(OceanAreaService)가 마지막으로 조회한 배를 따라갔다.
--   배 두 척이면 해역을 서로 빼앗아 둘 다 대부분 "해역 밖"이 되고, 60초마다 ROMS 35페이지를 헛불렀다.
--   진행 상태(마지막 수집 · 호출 예산)도 메모리라 인스턴스를 늘리면 호출이 인스턴스 수만큼 곱해졌다.
--
-- 이후: ROMS 는 0.25° 고정 타일 단위 캐시(RomsTile). 진행 상태 · 리스 · 예산을 이 DB 에 둔다.
--   기각 — 전국 일괄 수집: 한국 연안이 0.3° 해역의 약 530배라 1.8만 페이지(추정, 일일 한도 확인 전)
--   기각 — 선박별 해역: 같은 바다에 모인 배들이 같은 격자를 중복 수집
--   기각 — Redis 락: 락(Redis)과 데이터(PostgreSQL)가 달라 둘 사이 불일치를 따로 다뤄야 하고, 로컬에 Redis 가 없으면 수집이 멈춘다

-- ─────────────────────────────────────────────────────────────
-- ocean_roms_tile — 타일별 수집 상태
--
-- 조회(kiosk 키가 맞는 것)가 requested_at 을 찍고, 수집이 collected_at · generation 을 찍는다.
-- lease_* 는 "누가 받는 중인가". 인스턴스가 받다가 죽으면 lease_until 이 지나 다른 인스턴스가 잡는다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_roms_tile (
    tile_row     integer     NOT NULL,
    tile_col     integer     NOT NULL,
    requested_at timestamptz NOT NULL,
    collected_at timestamptz,
    generation   bigint      NOT NULL DEFAULT 0,
    attempted_at timestamptz,
    result_code  varchar(16),
    result_msg   varchar(200),
    lease_owner  varchar(64),
    lease_until  timestamptz,
    CONSTRAINT pk_ocean_roms_tile PRIMARY KEY (tile_row, tile_col)
);

COMMENT ON TABLE  ocean_roms_tile              IS 'ROMS 0.25° 타일 수집 상태. 격자 값은 ocean_roms';
COMMENT ON COLUMN ocean_roms_tile.tile_row     IS 'floor(위도 / 0.25). 타일 남쪽 끝 = tile_row × 0.25';
COMMENT ON COLUMN ocean_roms_tile.tile_col     IS 'floor(경도 / 0.25)';
COMMENT ON COLUMN ocean_roms_tile.requested_at IS '마지막 관심 조회. 24시간 안이면 새 예측본 때 다시 받는다';
COMMENT ON COLUMN ocean_roms_tile.collected_at IS '마지막 수집 성공. null 이면 한 번도 못 받았다 — 조회는 해역 밖으로 답한다';
COMMENT ON COLUMN ocean_roms_tile.generation   IS '받았을 때의 예측본 세대 (ocean_roms_generation). 현재보다 작으면 옛 예측본';
COMMENT ON COLUMN ocean_roms_tile.attempted_at IS '마지막 수집 시도. 실패 타일을 매 조회가 다시 부르지 않게';

-- 활성 타일(최근 조회) 선별
CREATE INDEX ix_ocean_roms_tile_requested ON ocean_roms_tile (requested_at);

-- ─────────────────────────────────────────────────────────────
-- ocean_roms_generation — 예측본 세대. 한 행
--
-- API 가 발표 시각을 주지 않아 "새 예측본"은 매시 1페이지를 저장값과 비교해 감지한다(RomsCollector).
-- 감지하면 +1 — 옛 세대로 받은 활성 타일이 다시 받을 대상이 된다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_roms_generation (
    id          smallint    NOT NULL,
    generation  bigint      NOT NULL,
    detected_at timestamptz NOT NULL,
    CONSTRAINT pk_ocean_roms_generation PRIMARY KEY (id),
    CONSTRAINT ck_ocean_roms_generation_single CHECK (id = 1)
);

INSERT INTO ocean_roms_generation (id, generation, detected_at) VALUES (1, 1, now());

-- ─────────────────────────────────────────────────────────────
-- ocean_job — 소스별 수집 작업의 주기 · 리스 (OceanCollectScheduler)
--
-- 틱은 인스턴스마다 돌지만 소스 하나는 한 인스턴스만 잡는다.
-- last_started_at 이 DB 에 있어 재기동해도 주기가 이어진다(메모리일 때는 재기동마다 전 소스가 즉시 불렸다).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_job (
    name             varchar(64) NOT NULL,
    last_started_at  timestamptz,
    last_finished_at timestamptz,
    lease_owner      varchar(64),
    lease_until      timestamptz,
    CONSTRAINT pk_ocean_job PRIMARY KEY (name)
);

COMMENT ON TABLE ocean_job IS '해양 수집 작업 주기·리스. name 은 app.ocean.sources 키';

-- ─────────────────────────────────────────────────────────────
-- ocean_call_budget — 소스별 하루 호출 수 (OceanCallBudget)
--
-- 발급처 한도는 계정 단위라 인스턴스 합계로 세야 한다. 메모리일 때는 인스턴스마다 따로 세어 합계가 예산의 배수였다.
-- day 는 한국 날짜 — 발급처가 KST 자정에 리셋한다.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_call_budget (
    day    date        NOT NULL,
    source varchar(32) NOT NULL,
    used   integer     NOT NULL,
    CONSTRAINT pk_ocean_call_budget PRIMARY KEY (day, source)
);

COMMENT ON TABLE ocean_call_budget IS '소스별 하루 호출 수(페이지 단위). 7일 지난 행은 수집 때 지운다';

-- 옛 단일 해역의 미래 격자는 어느 타일에도 "수집됨"이 아니라 조회 판정 밖인데, 최근접 조회(5km)에 섞일 수 있다 — 지운다.
-- 지난 24시간 보관분(사고 시각 재계산 입력, OceanRetention)은 남긴다
DELETE FROM ocean_roms WHERE predc_dt >= now();

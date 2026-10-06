-- V20260917_1731 — 소해구 전국 수집용 스테이징 (결정 2026-09-17)
--
-- 전국 소해구는 발표본당 884회(26 발효시각 × 34 묶음) · 약 54분이다. 한 틱에 몰면 그동안
-- 같은 인스턴스의 ROMS·sea-obs·특보가 전부 멈춘다. 그래서 **틱마다 몇 묶음씩** 나눠 받는다.
--
-- ⚠ 그런데 `ocean_zone` 에 바로 쓰면 안 된다. 읽기가 `tma_fc = max(tma_fc)` 로 최신 발표본을
--   고르므로, 받는 도중에 새 발표본이 "최신"이 되어 **반쪽짜리가 화면에 뜬다.**
--   슬라이더 중간이 비면 사람은 그 시각을 "값 없음"이 아니라 **잔잔한 바다**로 읽는다.
--
-- 그래서 다 받을 때까지 여기 쌓고, 완료되면 한 트랜잭션에 ocean_zone 으로 옮긴다.
-- 읽기 경로는 한 줄도 바뀌지 않는다 — 기존 원자성이 그대로 유지된다.

CREATE TABLE ocean_zone_pending (
    tma_fc            timestamptz NOT NULL,
    tma_ef            timestamptz NOT NULL,
    lzone             integer     NOT NULL,
    szone             smallint    NOT NULL,
    lat_min           float8      NOT NULL,
    lat_max           float8      NOT NULL,
    lon_min           float8      NOT NULL,
    lon_max           float8      NOT NULL,
    wave_height_m     real,
    wave_period_max_s real,
    wave_dir_deg      real,
    wind_speed_ms     real,
    wind_dir_deg      real,
    visibility_m      real,
    rain_mm           real,
    water_temp_c      real,
    swell_level       smallint,
    -- 몇 번째 묶음에서 왔나. 다음 틱이 "어디부터"를 이 값으로 정한다.
    -- 별도 커서 테이블을 두지 않는 이유: 커서와 실제 저장분이 어긋나면
    -- 빠진 묶음을 영영 모른 채 "완료"로 올린다. 진행 상태를 데이터에서 유도한다
    chunk_idx         smallint    NOT NULL,
    fetched_at        timestamptz NOT NULL,
    CONSTRAINT pk_ocean_zone_pending PRIMARY KEY (tma_ef, lzone, szone),
    CONSTRAINT ck_ozp_szone CHECK (szone BETWEEN 0 AND 9),
    CONSTRAINT ck_ozp_swell CHECK (swell_level IS NULL OR swell_level BETWEEN 1 AND 4)
);

COMMENT ON TABLE ocean_zone_pending IS
    '소해구 전국 수집 중간 적재. 완료되면 ocean_zone 으로 옮기고 비운다 — 반쪽 발표본이 화면에 뜨지 않게';
COMMENT ON COLUMN ocean_zone_pending.chunk_idx IS
    '묶음 번호(0부터). 다음 틱이 이어받을 지점. 커서 테이블 대신 데이터에서 진행을 유도한다';

-- 진행 판정("이 발표본을 어디까지 받았나")이 매 틱 돈다
CREATE INDEX ix_ozp_progress ON ocean_zone_pending (szone, tma_fc, chunk_idx);

-- ⚠ CHECK 를 ocean_zone 만큼 걸지 않았다(lat/lon 범위). 여기 들어온 값은 같은 파서를 지나
--   결국 ocean_zone 의 CHECK 를 통과해야 하므로, 두 벌을 두면 고칠 곳만 둘이 된다.

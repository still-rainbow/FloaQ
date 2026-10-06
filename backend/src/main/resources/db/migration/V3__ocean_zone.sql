-- 기상청 해구별 예측 (API허브 marine_large_zone · marine_small_zone)
--
-- 원자료: KIM 지역파랑모델(RWW3). 발표 하루 2회(00·12UTC), 발효 +0~75시간 3시간 간격(26시각).
-- 해양포털 "해구별 해양기상정보" 와 같은 원자료다 — 전국 층의 입력.
--
-- ocean_roms 와 같은 성질: 발표본 캐시라 부분 갱신이 아니라 층(대해구·소해구)별 전량 교체.
-- 하이퍼테이블 아님 — 매 발표본마다 통째로 지우고 넣는다.
--
-- 대해구·소해구를 한 테이블에 둔다. szone = 0 이 대해구 행이다.
--   기각: 테이블 둘 — 요소가 같고(소해구가 4개 더 많을 뿐) 조회·교체 코드가 두 벌이 된다.
--
-- ⚠ 결측은 원자료 -999.0 → NULL. 0 으로 두면 파고 0m·풍속 0m/s 로 읽힌다(육지 칸).

CREATE TABLE ocean_zone (
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
    -- 아래 넷은 소해구만. 대해구 행은 항상 NULL. 소해구도 2026-07-01 00UTC 발표본부터 제공
    visibility_m      real,
    rain_mm           real,
    water_temp_c      real,
    swell_level       smallint,
    fetched_at        timestamptz NOT NULL,
    CONSTRAINT pk_ocean_zone PRIMARY KEY (tma_ef, lzone, szone),
    CONSTRAINT ck_ocean_zone_szone CHECK (szone BETWEEN 0 AND 9),
    CONSTRAINT ck_ocean_zone_lat CHECK (lat_min < lat_max AND lat_min BETWEEN -90 AND 90 AND lat_max BETWEEN -90 AND 90),
    CONSTRAINT ck_ocean_zone_lon CHECK (lon_min < lon_max AND lon_min BETWEEN -180 AND 180 AND lon_max BETWEEN -180 AND 180),
    CONSTRAINT ck_ocean_zone_swell CHECK (swell_level IS NULL OR swell_level BETWEEN 1 AND 4)
);

COMMENT ON TABLE  ocean_zone               IS '기상청 해구별 예측. 층(szone=0 대해구 / >0 소해구)별 발표본 전량 교체';
COMMENT ON COLUMN ocean_zone.tma_fc        IS '발표시각 (원자료 UTC yyyymmddhh)';
COMMENT ON COLUMN ocean_zone.tma_ef        IS '발효시각. 발표 +0~75시간 3시간 간격';
COMMENT ON COLUMN ocean_zone.lzone         IS '대해구 번호. 연속 번호가 아니다 (1~8304 중 1,330개, 2026-09-14 실측)';
COMMENT ON COLUMN ocean_zone.szone         IS '0 = 대해구 행 · 1~9 = 소해구 (대해구를 3x3, 북서가 1)';
COMMENT ON COLUMN ocean_zone.wave_dir_deg  IS '파향 deg. ⚠ 오는 쪽/가는 쪽 관례가 명세에 없다';
COMMENT ON COLUMN ocean_zone.wind_dir_deg  IS '풍향 deg. 기상 관례상 불어오는 쪽';
COMMENT ON COLUMN ocean_zone.visibility_m  IS '시정 m. 원자료 상한 20000';
COMMENT ON COLUMN ocean_zone.swell_level   IS '너울 위험 1 관심 · 2 주의 · 3 경계 · 4 위험';

-- 한 프레임(층 + 발효시각) 조회. 슬라이더를 넘길 때마다 탄다
CREATE INDEX ix_ocean_zone_frame ON ocean_zone (szone, tma_ef);

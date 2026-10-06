-- 해양 관측 지점 24시간 이력 (OceanRetention)
--
-- 스냅샷(ocean_snapshot)은 최신 1건뿐이라 사고 기록이 늦게 동기화되면 사고 시각의 바람·파고를 답하지 못한다.
-- 표류 추정 입력(유속 + 풍속 × leeway)에서 바람이 여기서 나온다.
--
-- 전국 지점을 넣는다 — 해역 반경으로 거르면 해역이 옮겨진 뒤 옛 사고 지점 근처 관측이 없다.
-- sea_obs 전국 약 200지점 × 24시간 ≈ 5천 행이라 거를 이유가 없다.
--
-- source 를 두는 이유: 지금은 기상청 sea-obs 뿐이지만 수과원 실시간어장(수온)도 같은 모양이다.
-- 하이퍼테이블 아님 — 24시간 창을 수집 때 지우는 캐시다.

CREATE TABLE ocean_station_obs (
    source        varchar(32) NOT NULL,
    stn           varchar(16) NOT NULL,
    observed_at   timestamptz NOT NULL,
    network       varchar(8),
    name          varchar(64),
    lat           float8      NOT NULL,
    lon           float8      NOT NULL,
    wave_height_m real,
    wind_dir_deg  real,
    wind_speed_ms real,
    wind_gust_ms  real,
    water_temp_c  real,
    air_temp_c    real,
    pressure_hpa  real,
    humidity_pct  real,
    fetched_at    timestamptz NOT NULL,
    CONSTRAINT pk_ocean_station_obs PRIMARY KEY (source, stn, observed_at),
    CONSTRAINT ck_ocean_station_obs_lat CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT ck_ocean_station_obs_lon CHECK (lon BETWEEN -180 AND 180)
);

COMMENT ON TABLE  ocean_station_obs             IS '해양 관측 지점 24시간 이력. 수집 때 24시간 지난 행을 지운다';
COMMENT ON COLUMN ocean_station_obs.source      IS 'app.ocean.sources 키 (sea-obs)';
COMMENT ON COLUMN ocean_station_obs.observed_at IS '관측 시각. 수신 시각이 아니다';
COMMENT ON COLUMN ocean_station_obs.network     IS 'B 해양기상부이 · C 파고부이 · L 등표 · N 방재기상';
COMMENT ON COLUMN ocean_station_obs.wind_dir_deg IS '풍향 deg. 기상 관례상 불어오는 쪽';

-- "시각 T 이전 가장 최근 관측" 조회
CREATE INDEX ix_ocean_station_obs_time ON ocean_station_obs (source, observed_at);

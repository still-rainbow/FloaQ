-- 지점 관측·예보에 유향·유속·조위 (2026-09-16)
--
-- KHOA 조류예보(crntFcstTime) · 조석예보(tideFcstTime) 를 붙이면서 추가한다.
-- 둘 다 **지점 기반**이라 ocean_station_obs 의 행 모양을 그대로 쓴다 — 소스만 다르다(source 컬럼).
-- 새 테이블 기각: 조회가 "좌표 근처 지점"으로 같고(SeaObsStore.latestAt), 컬럼 셋만 다르면 테이블을 나눌 이유가 없다.
--
-- ⚠ 이 둘은 **예보**라 observed_at 이 미래다(예측 시각). 보관 삭제는 "24시간 지난 과거" 기준이라 미래 행은 남는다.
--    조회는 "그 시각 이후 가장 이른 예측"을 고른다 — ROMS 와 같은 규칙(OceanController /current).

ALTER TABLE ocean_station_obs
    ADD COLUMN current_dir_deg  real,
    ADD COLUMN current_speed_ms real,
    ADD COLUMN tide_level_m     real;

COMMENT ON COLUMN ocean_station_obs.current_dir_deg  IS '유향 deg (북 0, 시계방향). 조류예보 원본은 16방위 한글 — OceanUnits.degreesOfKorean16 으로 변환';
COMMENT ON COLUMN ocean_station_obs.current_speed_ms IS '유속 m/s. 조류예보 원본은 cm/s — OceanUnits.fromCmPerSec';
COMMENT ON COLUMN ocean_station_obs.tide_level_m     IS '조위 m. 조석예보 원본은 cm';

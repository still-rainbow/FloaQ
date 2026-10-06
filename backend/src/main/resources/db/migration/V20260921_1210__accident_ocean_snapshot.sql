-- 사고가 나던 때의 바다를 사고 행에 박아 둔다.
--
-- 왜: 해양 관측값은 24시간만 보관한다(OceanRetention.WINDOW). 그래서 하루가 지난 사고를 열면
--     "그때 조류가 어땠나"를 아무도 답할 수 없었고, 화면은 <b>오늘 바다</b>를 그 사고의 바다인 양
--     보여 주고 있었다. 표류 추정 타원도 같은 값으로 그려져 과거 사고의 지도가 매일 달라졌다.
--
-- 왜 사고 행인가: 이 값은 사고의 일부다. 수온(water_temp_c)을 이미 같은 이유로 여기 두고 있다 —
--     공공데이터에서 받지만 "그 사고의 수온"이라 사고와 함께 남는다. 유속·바람도 같다.
--
-- 채우는 시점: 사고가 만들어질 때 한 번(PiIngestService). 그 뒤로는 바뀌지 않는다 —
--     사고 시각은 고정이고, 그 시각의 관측값도 고정이다.
--
-- ⚠ 이 칸들이 비어 있는 사고가 있을 수 있다. 이 마이그레이션 이전에 난 사고, 그 좌표에 격자가
--    없는 사고, 관측 지점이 너무 먼 사고다. 그때 화면은 24시간 안쪽이면 조회로 메우고
--    아니면 "기록이 남아 있지 않다"고 말한다 — 0 으로 채우지 않는다. 0 은 "잔잔하다"는 뜻이라
--    모른다는 것과 전혀 다른 말이 된다.

ALTER TABLE accident
    ADD COLUMN ocean_current_speed_ms real,
    ADD COLUMN ocean_current_dir_deg  real,
    ADD COLUMN ocean_wind_speed_ms    real,
    ADD COLUMN ocean_wind_dir_deg     real,
    ADD COLUMN ocean_spread_ms        real,
    ADD COLUMN ocean_observed_at      timestamptz;

COMMENT ON COLUMN accident.ocean_current_speed_ms IS '사고 시각 유속 m/s (ROMS 최근접 격자)';
COMMENT ON COLUMN accident.ocean_current_dir_deg  IS '사고 시각 유향 0~360, 흘러가는 쪽';
COMMENT ON COLUMN accident.ocean_wind_speed_ms    IS '사고 시각 풍속 m/s (기상청 최근접 관측 지점)';
COMMENT ON COLUMN accident.ocean_wind_dir_deg     IS '사고 시각 풍향 0~360, 관측 관례대로 불어오는 쪽';
COMMENT ON COLUMN accident.ocean_spread_ms        IS '이웃 격자와의 유속 차이. 표류 추정 범위를 넓히는 근거';
COMMENT ON COLUMN accident.ocean_observed_at      IS '위 값들이 관측·예측된 시각. 사고 시각과 다를 수 있다';

ALTER TABLE accident
    ADD CONSTRAINT ck_accident_ocean_dir CHECK (
        (ocean_current_dir_deg IS NULL OR ocean_current_dir_deg BETWEEN 0 AND 360)
        AND (ocean_wind_dir_deg IS NULL OR ocean_wind_dir_deg BETWEEN 0 AND 360)),
    ADD CONSTRAINT ck_accident_ocean_speed CHECK (
        (ocean_current_speed_ms IS NULL OR ocean_current_speed_ms >= 0)
        AND (ocean_wind_speed_ms IS NULL OR ocean_wind_speed_ms >= 0)
        AND (ocean_spread_ms IS NULL OR ocean_spread_ms >= 0));

-- 해양 공공데이터 수집 결과 (계획.md §6 · §9.18)
--
-- 표시용 jsonb 한 곳 + 계산용 ROMS 타입 테이블. 소스별 테이블 6개 기각 —
-- 6종 구성이 미결(§10)이라 V3·V4 가 곧 따라붙는다.
-- 공통 컬럼 추출도 기각 — 응답 모양이 격자/문자열/중첩배열/고정폭텍스트로 갈려 전부 nullable.

-- ─────────────────────────────────────────────────────────────
-- ocean_snapshot — 소스별 최신 1행. 대시보드·LLM 요약 입력
--
-- 🔴 시각이 두 종류. 이 분리가 이 테이블의 전부다.
--    observed_at · payload      마지막 **성공** 값
--    fetched_at · result_code   마지막 **시도** 결과
--    실패 시 payload 유지 (§9.10 — 빈 화면보다 오래된 값)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_snapshot (
    source      varchar(32)  NOT NULL,
    observed_at timestamptz,
    payload     jsonb,
    fetched_at  timestamptz  NOT NULL,
    result_code varchar(16)  NOT NULL,
    result_msg  varchar(200),
    CONSTRAINT pk_ocean_snapshot PRIMARY KEY (source)
);

-- created_at 없음. 소스당 1행 upsert 라 생성 시각에 용처 없음 — 누락 아님
COMMENT ON TABLE  ocean_snapshot             IS '소스별 최신 수집 결과. 이력 아닌 캐시';
COMMENT ON COLUMN ocean_snapshot.source      IS 'app.ocean.sources 키 (roms · sea-obs · ...)';
COMMENT ON COLUMN ocean_snapshot.observed_at IS '원본 기준 시각. 관측=관측 시각, 예보=모델 기준 시각, 발표=발표 시각. 예보는 경과 시간이 신선도가 아니다 (payload.validAt 참조)';
COMMENT ON COLUMN ocean_snapshot.payload     IS '단위 정규화(SI) 값. ⚠ 실패 시 덮지 않음';
COMMENT ON COLUMN ocean_snapshot.result_code IS '00 성공 · 03 데이터없음 · 22 쿼터초과 · 30 미등록키 · 31 기한만료 · HTTP_* 게이트웨이';

-- ─────────────────────────────────────────────────────────────
-- ocean_roms — 표류 범위 추정의 유일한 입력 (§6)
--   HF-RADAR 기각: 최신이 7시간 전 (2026-09-11 실측)
--   하이퍼테이블 아님: 매 수집마다 전량 교체되는 예측본이라 청크 대상 아님
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ocean_roms (
    predc_dt   timestamptz NOT NULL,
    lat        float8      NOT NULL,
    lon        float8      NOT NULL,   -- ⚠ 응답 필드명은 lot
    crdir_deg  real,
    crsp_ms    real,
    wtem_c     real,
    fetched_at timestamptz NOT NULL,
    CONSTRAINT pk_ocean_roms PRIMARY KEY (predc_dt, lat, lon),
    CONSTRAINT ck_ocean_roms_lat CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT ck_ocean_roms_lon CHECK (lon BETWEEN -180 AND 180)
);

COMMENT ON TABLE  ocean_roms            IS '매 수집마다 DELETE 후 전량 INSERT. 부분 갱신 아님';
COMMENT ON COLUMN ocean_roms.predc_dt   IS '예측 시각. 원본에 타임존 표기 없으나 KST 확정 (2026-09-13, 수온 일주기 위상). 당일 00시부터라 과거 시각이 섞여 옴';
COMMENT ON COLUMN ocean_roms.crsp_ms    IS '유속 m/s. ROMS 만 원본이 m/s (HF-RADAR·부이 cm/s, 선박운항지수 kn)';
COMMENT ON COLUMN ocean_roms.crdir_deg  IS '유향 deg (북 0, 시계방향)';
COMMENT ON COLUMN ocean_roms.fetched_at IS '예측본 수신 시각. stale 표시 근거';

-- "at 이후 가장 이른 예측" 선별용. 없으면 격자 전체 스캔
CREATE INDEX ix_ocean_roms_predc ON ocean_roms (predc_dt);

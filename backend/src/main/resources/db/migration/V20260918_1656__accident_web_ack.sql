-- 관제 웹이 사고를 접수한 시각.
--
-- report.acked_at 과 다른 값이다. 그쪽은 DSC 조난호출에 대한 **해안국의 무선 ACK** 이고
-- (acked_by 가 9자리 MMSI 다), 이 값은 **관제 화면이 그 사고를 받았다**는 사실이다.
-- 한 칸에 둘을 담으면 "해경 무선국이 응답했다"와 "웹 운영자가 열어 봤다"를 구별할 수 없다.
--
-- 지금까지 이 시각은 브라우저 안에만 있었다 — 새로고침하면 사라지고 다른 관제사 화면에는
-- 보이지 않았다. 종료 리포트의 '해경 접수'도 그래서 한 사람 화면에서만 참인 값이었다(2026-09-18).
--
-- ⚠ 한 번만 찍는다. 두 번째 접수는 무시한다(AccidentCommandService) — 최초 시각이
--   대응이 얼마나 빨랐나의 원재료이고, 나중 값으로 덮으면 그 기록이 사라진다.

ALTER TABLE accident
    ADD COLUMN IF NOT EXISTS web_acked_at timestamptz,
    ADD COLUMN IF NOT EXISTS web_acked_by bigint;

COMMENT ON COLUMN accident.web_acked_at IS '관제 웹이 이 사고를 접수한 시각 (report.acked_at 과 다름)';
COMMENT ON COLUMN accident.web_acked_by IS '접수한 관제 계정 users.user_id';

-- FK 를 걸지 않는다. 계정을 지워도 "누가 언제 받았다"는 기록은 남아야 한다 —
-- 지우면 접수 사실까지 같이 사라지거나(CASCADE) 계정 삭제가 막힌다(RESTRICT).
CREATE INDEX IF NOT EXISTS ix_accident_web_acked ON accident (web_acked_at) WHERE web_acked_at IS NULL;

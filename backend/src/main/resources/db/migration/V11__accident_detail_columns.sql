-- 사고 상세 화면이 쓰는 값의 자리 (WEB-04 · docs/api.md §3.4)
--
-- 2026-09-16 검토에서 대부분 잘라냈다. 남긴 둘의 공통점은 **원본이 사라진다**는 것이다 —
-- 다시 계산하거나 다시 읽을 방법이 없어서 사고 기록과 같이 남겨야 하는 값만 남겼다.
--
-- 뺀 것과 이유:
--   ship.home_port        선적항. 화면 표시용이고 사고 기록과 무관
--   launch.distance_m     발사 거리 · 사출 속도. 지금 화면에 꼭 필요하지 않다
--   launch.muzzle_speed_ms
--   video.duration_sec    영상 길이 · fps 는 mp4 파일 자체에서 읽힌다 — DB 에 두면 두 곳이 어긋난다
--   video.fps
--   video.started_at      accident.created_at - trigger_sec 으로 나온다
--   video.stopped_at      영상이 왜 끝났는지는 지금 쓰는 데가 없다
--   ship_position         선박 위치. 저장할지 말지 미결(아래)
--
-- ⚠ 번호: V8(팀원 edge) · V9(부표 FK)가 아직 db/migration 밖에 있어 번호가 비어 있다.
--   V8 이 들어오는 날 Flyway 가 순서 위반으로 막는다 — 그때 볼륨을 다시 만든다.
--
-- ⚠ 팀원 V8 초안이 넣는 칸은 건드리지 않는다:
--   accident.accident_type · trigger_source · reported_at · rescued_at, accident_state.reason,
--   launch.result · fail_reason · target_lat/lon, report.channel · status · sent_count,
--   buoy.seq · received_at · rssi, imu.heading_deg, accident_file(탐지 사진).

-- ─────────────────────────────────────────────────────────────
-- ① accident — 사고 시점 수온
-- ─────────────────────────────────────────────────────────────
-- 🔴 스냅샷이어야 하는 이유: 수온은 ocean_station_obs 에서 오는데 그 표는 24시간치만 두고 지운다
--    (V4 주석). 사고 행에 박아 두지 않으면 하루 지난 사고의 수온을 영영 다시 구할 수 없다.
--    생존 잔여시간 계산의 입력이라 사고 기록과 같이 남아야 한다.
ALTER TABLE accident ADD COLUMN water_temp_c real;

COMMENT ON COLUMN accident.water_temp_c IS '사고 시각·좌표의 해수 온도. ocean_station_obs 에서 복사한 스냅샷 — 그 표는 24시간 뒤 지워진다';

-- ─────────────────────────────────────────────────────────────
-- ② video — 감지 시점이 영상의 몇 초인가
-- ─────────────────────────────────────────────────────────────
-- 칸 하나면 된다. 사고 시각은 accident.created_at 으로 이미 알고,
-- 촬영 시작 시각은 accident.created_at - trigger_sec 으로 나온다.
-- ⚠ video.created_at 을 촬영 시작으로 쓸 수 없다 — 그 행은 종결 뒤 인코딩해서 만들기 때문에
--   서버가 행을 만든 시각이고, 촬영 시작과 몇 분에서 몇십 분까지 벌어진다.

ALTER TABLE video
    ADD COLUMN trigger_sec real,
    ADD CONSTRAINT ck_video_trigger CHECK (trigger_sec IS NULL OR trigger_sec >= 0);

COMMENT ON COLUMN video.trigger_sec IS '영상 시작부터 익수 확정(t=0)까지의 초. 타임라인의 "감지" 표시가 여기 찍힌다';

-- ─────────────────────────────────────────────────────────────
-- ③ ship_position — 여기서 만들지 않는다
-- ─────────────────────────────────────────────────────────────
-- 이 파일 초안은 `ship_position` 을 직접 만들었다. V9__edge.sql 이 같은 이름으로
-- 먼저 만들고 있어 그대로 두면 Flyway 가 `relation already exists` 로 기동을 막는다(2026-09-17).
--
-- V9 쪽이 상위 호환이라 그쪽에 맞춘다 — PK 는 (ship_position_id, created_at) 로 같고
-- accident_id 가 nullable 이라 평시 항적까지 담으며 ship_id·speed_kn·heading_deg·accuracy_m 가 더 있다.
-- 우리 엔티티가 읽는 다섯 칸은 전부 V9 에 있어 조회 코드는 그대로 돈다.
--
-- ⚠ 다만 이 절을 만든 목적("종결된 사고를 다시 열면 지도에 배가 있게")은 아직 안 풀렸다.
--    V9 의 ship_position 은 24시간 보관 하이퍼테이블이라 하루 뒤 그 행이 사라진다.
--    api.md §9 3-2 에 미결로 올라가 있다 — drop_chunks 가 accident_id 를 안 보기 때문이다.

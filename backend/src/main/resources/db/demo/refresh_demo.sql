-- ══════════════════════════════════════════════════════════
--  시연 데이터 — 서버를 켤 때마다 "지금" 기준으로 맞춘다
-- ══════════════════════════════════════════════════════════
--
-- 🔴 local 프로필에서만 돈다(global/config/DemoDataSeeder.java). 운영에서는 실행되지 않는다.
--
-- <b>왜 필요한가.</b> 시연 데이터는 넣는 순간에만 최신이다. 하루 지나면 하루 지난 사고가 되고,
-- 저체온 생존 상한의 두 배를 넘겨 전부 '장기 미종결'로 목록 맨 아래에 깔린다 —
-- 그러면 사고 탭이 비어 화면이 제대로 도는지 볼 수가 없다(2026-09-19).
--
-- <b>왜 서버 기동 시점인가.</b> 화면을 보고 있는데 사고가 저절로 생기면 시연 중에 어색하다.
-- 서버를 켜는 것은 우리가 하는 일이라 <b>시점이 예측 가능하다</b>. 시연 중에 재시작할 일은 없다.
--
--   ① 30분이 넘은 진행 중 사고 → 그럴듯한 소요 시간(6~25분)을 먹여 종결
--   ② 진행 중 사고 4건을 지금 기준으로 다시 심는다 (부표 상태 네 가지 전부)
--
-- 멱등이다. 몇 번을 돌려도 사고가 늘지 않는다.

-- ── ① 오래 남은 진행 중 사고를 닫는다 ──────────────────
-- 순서가 중요하다. accident 를 먼저 닫으면 아래 두 문장의 WHERE 가 아무것도 못 고른다.

-- 경위에 종결 줄을 남긴다. 없으면 상세의 경위 표에 끝난 흔적이 안 보인다
INSERT INTO accident_state (accident_state_id, accident_id, status, prev_status, reason, created_at)
SELECT gen_random_uuid(), a.accident_id, 'CLOSE', a.status, 'TABLET_CLOSE',
       a.created_at + make_interval(secs => 420 + (hashtext(a.accident_id::text) & 1023))
FROM accident a
WHERE a.status IN ('DETECT', 'WAIT', 'REPORT') AND a.created_at < now() - interval '30 min'
ON CONFLICT DO NOTHING;

-- 신고는 멈춘 것으로. 종결된 사고가 '발신 중'이면 화면이 지금도 쏘는 줄 안다
UPDATE report r SET status = 'STOPPED'
FROM accident a
WHERE r.accident_id = a.accident_id AND r.status = 'SENDING'
  AND a.status IN ('DETECT', 'WAIT', 'REPORT') AND a.created_at < now() - interval '30 min';

-- 종결 시각은 사고마다 다르게. accident_id 해시를 써서 돌릴 때마다 같은 값이 나온다
UPDATE accident a
SET status = 'CLOSE',
    -- MOB 만 구조 확정이 있다. 화재·기관고장은 구조가 아니라 진화·예인이다
    rescued_at = CASE WHEN a.accident_type = 'MOB' OR a.accident_type IS NULL
                      THEN a.created_at + make_interval(secs => 360 + (hashtext(a.accident_id::text) & 1023)) END,
    closed_at  = a.created_at + make_interval(secs => 420 + (hashtext(a.accident_id::text) & 1023)),
    updated_at = now()
WHERE a.status IN ('DETECT', 'WAIT', 'REPORT') AND a.created_at < now() - interval '30 min';

-- ── ② 진행 중 사고를 지금 기준으로 다시 심는다 ──────────
-- 좌표는 전부 바다인 것을 확인한 자리다(apps/web lib/land.ts 판정 통과). 부산 앞바다.

INSERT INTO ship (ship_id, name, registration_no, mmsi, has_buoy, is_deleted, created_at, status)
VALUES
  ('00000000-0000-7000-8000-000000000003','성진호','0301-2020-0418','440123401',true,false,now() - interval '200 day','ACTIVE'),
  ('00000000-0000-7000-8000-000000000004','대원호','0405-2022-0091','440123402',true,false,now() - interval '180 day','ACTIVE'),
  ('00000000-0000-7000-8000-000000000005','삼양호','0502-2021-0233','440123403',true,false,now() - interval '160 day','ACTIVE'),
  ('00000000-0000-7000-8000-000000000006','금호호','0607-2019-0512','440123404',true,false,now() - interval '140 day','ACTIVE'),
  ('00000000-0000-7000-8000-000000000007','태성호','0711-2023-0064','440123405',true,false,now() - interval '120 day','ACTIVE')
ON CONFLICT (ship_id) DO NOTHING;

-- 이 스크립트가 만든 사고만 지운다. 팀원이 Pi 로 넣은 행은 건드리지 않는다
DELETE FROM accident WHERE accident_id::text LIKE '00000000-0000-7000-8000-0000000001%';

-- 전에 들어와 있던 사고 중 좌표가 육지인 것을 바다로 옮긴다.
-- 동해수산호 35.1659, 129.1051 은 부산 연산동 한복판이다 — 배가 있을 수 없는 자리였다.
-- 옮긴 곳은 해운대 동쪽 3km 바다(해안 0.65km), 육지 판정 통과한 좌표다.
UPDATE accident SET accident_lat = 35.1500, accident_lon = 129.1850
WHERE accident_id = '00000000-0000-7000-8000-00000000000b';

-- 사고 -------------------------------------------------------------
INSERT INTO accident (accident_id, ship_id, accident_lat, accident_lon, report_type, report_dsc,
                      status, created_at, reported_at, rescued_at, closed_at,
                      water_temp_c, accident_type, trigger_source, wait_sec)
VALUES
  -- 1) 3분 전 · 부표 발사 실패 — 바다에 찾을 주황색이 없다
  ('00000000-0000-7000-8000-000000000101','00000000-0000-7000-8000-000000000003',
   35.136, 129.128,'DISTRESS',110,'REPORT', now() - interval '3 min', now() - interval '150 sec',
   NULL, NULL, 14.6,'MOB','AI',30),

  -- 2) 18분 전 · 신호 오는 중 + 사람이 잡고 있음 (가장 확실한 경우)
  ('00000000-0000-7000-8000-000000000102','00000000-0000-7000-8000-000000000004',
   35.101, 129.128,'DISTRESS',110,'REPORT', now() - interval '18 min', now() - interval '17 min',
   NULL, NULL, 14.2,'MOB','AI',30),

  -- 3) 42분 전 · 신호 오는 중인데 버튼이 안 눌렸다 — 사람과 부표가 갈라진다
  ('00000000-0000-7000-8000-000000000103','00000000-0000-7000-8000-000000000005',
   35.076, 129.143,'DISTRESS',110,'REPORT', now() - interval '42 min', now() - interval '41 min',
   NULL, NULL, 13.8,'MOB','AI',30),

  -- 4) 70분 전 · 9분 전부터 끊김. 끊길 때까지 눌려 있었다
  ('00000000-0000-7000-8000-000000000104','00000000-0000-7000-8000-000000000006',
   35.169, 129.215,'DISTRESS',110,'REPORT', now() - interval '70 min', now() - interval '69 min',
   NULL, NULL, 13.5,'MOB','AI',30),

  -- 5) 2시간 전 종결 · 비-MOB(화재). 부표를 쏘지 않는다
  ('00000000-0000-7000-8000-000000000105','00000000-0000-7000-8000-000000000007',
   35.024, 129.087,'DISTRESS',100,'CLOSE', now() - interval '2 hour', now() - interval '119 min',
   NULL, now() - interval '86 min', 14.0,'FIRE','MANUAL',NULL),

  -- 6) 5시간 전 종결 · 구조 확정까지 남은 건
  ('00000000-0000-7000-8000-000000000106','00000000-0000-7000-8000-000000000002',
   35.018, 128.950,'DISTRESS',110,'CLOSE', now() - interval '5 hour', now() - interval '299 min',
   now() - interval '292 min', now() - interval '290 min', 14.4,'MOB','AI',30),

  -- 7) 20분 전 취소 · 관리자에게만 보인다
  ('00000000-0000-7000-8000-000000000107','00000000-0000-7000-8000-000000000001',
   35.101, 129.128,'DISTRESS',110,'CANCEL', now() - interval '20 min', NULL,
   NULL, now() - interval '19 min', 14.2,'MOB','AI',30);

-- 상태 이력 (경위에 뜬다) -------------------------------------------
INSERT INTO accident_state (accident_state_id, accident_id, status, prev_status, reason, created_at)
SELECT gen_random_uuid(), a.accident_id, v.status, v.prev, v.reason, a.created_at + v.dt
FROM accident a
JOIN (VALUES
  ('DETECT', NULL,     'AI_DETECT',       interval '0 sec'),
  ('WAIT',   'DETECT', 'COUNTDOWN_START', interval '2 sec'),
  ('REPORT', 'WAIT',   'TIMEOUT',         interval '32 sec')
) AS v(status, prev, reason, dt) ON true
WHERE a.accident_id::text LIKE '00000000-0000-7000-8000-0000000001%'
  AND a.status <> 'CANCEL';

INSERT INTO accident_state (accident_state_id, accident_id, status, prev_status, reason, created_at)
VALUES (gen_random_uuid(),'00000000-0000-7000-8000-000000000107','DETECT',NULL,'AI_DETECT', now() - interval '20 min'),
       (gen_random_uuid(),'00000000-0000-7000-8000-000000000107','CANCEL','WAIT','TABLET_CANCEL', now() - interval '19 min'),
       (gen_random_uuid(),'00000000-0000-7000-8000-000000000105','CLOSE','REPORT','TABLET_CLOSE', now() - interval '86 min'),
       (gen_random_uuid(),'00000000-0000-7000-8000-000000000106','CLOSE','REPORT','TABLET_RESCUE', now() - interval '290 min');

-- 신고 발신 ---------------------------------------------------------
INSERT INTO report (report_id, accident_id, report_lat, report_lon, created_at,
                    channel, first_sent_at, status, sent_count, last_sent_at)
SELECT gen_random_uuid(), a.accident_id, a.accident_lat, a.accident_lon, a.reported_at,
       -- 상태는 SENDING · ACKED · STOPPED · FAILED 넷뿐이다(ck_report_status).
       -- 종결된 사고는 STOPPED — 보내다 멈춘 것이지 '보냄'이라는 값은 없다
       'DSC', a.reported_at, CASE WHEN a.status = 'REPORT' THEN 'SENDING' ELSE 'STOPPED' END,
       4, a.reported_at + interval '30 sec'
FROM accident a
WHERE a.accident_id::text LIKE '00000000-0000-7000-8000-0000000001%' AND a.reported_at IS NOT NULL;

-- 부표 투하 ---------------------------------------------------------
INSERT INTO launch (accident_id, launch_lat, launch_lon, horizontal_angle, vertical_angle,
                    confidence_score, created_at, result, fail_reason, target_lat, target_lon)
VALUES
  ('00000000-0000-7000-8000-000000000101',35.136,129.128,41.2,38.0,0.88, now() - interval '3 min','FAILED','NO_SOLUTION',NULL,NULL),
  ('00000000-0000-7000-8000-000000000102',35.101,129.128,39.5,36.4,0.92, now() - interval '18 min','SUCCESS',NULL,35.1012,129.1284),
  ('00000000-0000-7000-8000-000000000103',35.076,129.143,44.0,40.1,0.85, now() - interval '42 min','SUCCESS',NULL,35.0763,129.1434),
  ('00000000-0000-7000-8000-000000000104',35.169,129.215,37.8,35.2,0.90, now() - interval '70 min','SUCCESS',NULL,35.1693,129.2154),
  ('00000000-0000-7000-8000-000000000106',35.018,128.950,42.6,39.0,0.87, now() - interval '5 hour','SUCCESS',NULL,35.0183,128.9504);

-- 부표 위치 이력 -----------------------------------------------------
-- 2) 지금도 받는 중 + 눌림. 마지막 행이 몇 초 전이라 실측으로 뜬다
INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed, created_at, seq)
SELECT gen_random_uuid(),'00000000-0000-7000-8000-000000000102',
       35.1012 + g * 0.00008, 129.1284 + g * 0.00011,
       g > 3, now() - interval '18 min' + (g * interval '60 sec'), g
FROM generate_series(0, 17) AS g;

-- 3) 지금도 받는 중인데 한 번도 안 눌렸다
INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed, created_at, seq)
SELECT gen_random_uuid(),'00000000-0000-7000-8000-000000000103',
       35.0763 - g * 0.00010, 129.1434 + g * 0.00014,
       false, now() - interval '42 min' + (g * interval '60 sec'), g
FROM generate_series(0, 41) AS g;

-- 4) 9분 전이 마지막. 그때까지 눌려 있었다 → 잡았는지 놓았는지 모르는 경우
INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed, created_at, seq)
SELECT gen_random_uuid(),'00000000-0000-7000-8000-000000000104',
       35.1693 + g * 0.00012, 129.2154 + g * 0.00009,
       g > 2, now() - interval '70 min' + (g * interval '60 sec'), g
FROM generate_series(0, 60) AS g;

-- 6) 종결된 건 — 구조 시점까지
INSERT INTO buoy (buoy_id, accident_id, buoy_lat, buoy_lon, is_pressed, created_at, seq)
SELECT gen_random_uuid(),'00000000-0000-7000-8000-000000000106',
       35.0183 + g * 0.00009, 128.9504 + g * 0.00013,
       g > 2, now() - interval '5 hour' + (g * interval '60 sec'), g
FROM generate_series(0, 8) AS g;



-- ══════════════════════════════════════════════════════════
--  ③ 종결·취소된 사고의 단계 시각을 앞뒤가 맞게 정리한다
--
-- 🔴 <b>시연 사고(00000000-0000-7000-8000-…)만 건드린다</b>(2026-09-21).
--    전에는 id 조건이 없어 <b>끝난 사고 전부</b>를 다시 계산했다 — 진짜 Pi 나 가짜 Pi 가 보낸
--    종료 시각이 서버를 켤 때마다 지어낸 시각으로 바뀌었고, 경위의 caused_by 도 'DEMO' 로
--    덮여 ⑦ 이 가짜 Pi 사고를 못 찾았다. 받은 값은 받은 그대로 둔다.
-- ══════════════════════════════════════════════════════════
--
-- 기록 탭의 단계 바는 다섯 시각을 그대로 그린다. 그런데 그 값들이 이랬다(2026-09-20):
--   · 유형·수온이 비어 '조난'·'—' 으로만 뜨는 사고
--   · 접수가 감지보다 7시간 뒤 (어제까지 화면이 '사고 자기 시계'로 찍던 흔적)
--   · 접수가 발견보다 늦음 — 받기도 전에 찾은 셈
--
-- 끝난 사고는 시각이 더 변하지 않으므로, 여기서 <b>감지 시각 기준으로 다시 계산</b>한다.
-- 사고마다 다른 값이 나오되 돌릴 때마다 같도록 accident_id 해시를 쓴다.
--
--   신고 = 감지 + 30~45초   (자동 신고는 30초 대기 뒤 나간다)
--   접수 = 신고 + 40초~3분  (해경이 목록에서 받는다)
--   발견 = 감지 + 6~23분    (MOB 만. 화재·기관고장은 '구조'가 아니다)
--   종결 = MOB   → 발견 + 1~3분
--          그 외 → 감지 + 20~37분 (진화·예인에 걸리는 시간)
--
-- ⚠ 진행 중 사고는 건드리지 않는다. 그쪽 접수는 해경이 화면에서 찍는 진짜 기록이다.
-- ⚠ 취소는 신고 전에 선내에서 거둔 것이라 신고·접수·발견이 전부 없는 것이 맞다.

-- 비어 있던 유형·수온을 채운다. 유형이 없으면 카드가 '조난'으로만 뜨고 수온이 없으면 생존 시계가 안 돈다
UPDATE accident SET accident_type =
       CASE
         -- 취소는 곧 오탐이다. 투하 전에 선내에서 거둔 것이라 부표 기록이 없는 게 정상이므로
         -- 아래 '부표가 없으면 화재' 규칙에 걸리면 안 된다
         WHEN status = 'CANCEL' THEN 'MOB'
         WHEN EXISTS (SELECT 1 FROM buoy b WHERE b.accident_id = accident.accident_id)
           OR EXISTS (SELECT 1 FROM launch l WHERE l.accident_id = accident.accident_id)
           THEN 'MOB'
         ELSE 'FIRE' END
WHERE accident_type IS NULL AND accident_id::text LIKE '00000000-0000-7000-8000-%';

-- 이미 엉뚱한 유형이 굳은 취소 건을 되돌린다. 자동 취소는 사람 감지 흐름에만 있다
UPDATE accident SET accident_type = 'MOB' WHERE status = 'CANCEL' AND accident_type <> 'MOB'
   AND accident_id::text LIKE '00000000-0000-7000-8000-%';

UPDATE accident SET water_temp_c = 14.2 WHERE water_temp_c IS NULL AND accident_id::text LIKE '00000000-0000-7000-8000-%';

UPDATE accident a SET
    reported_at = CASE WHEN a.status = 'CANCEL' THEN NULL
                       ELSE a.created_at + make_interval(secs => 30 + (hashtext(a.accident_id::text) & 15)) END,
    web_acked_at = CASE WHEN a.status = 'CANCEL' THEN NULL
                        ELSE a.created_at + make_interval(secs => 70 + (hashtext(a.accident_id::text) & 15)
                                                                     + ((hashtext(a.accident_id::text) >> 4) & 127)) END,
    rescued_at = CASE WHEN a.status = 'CLOSE' AND a.accident_type = 'MOB'
                      THEN a.created_at + make_interval(secs => 360 + ((hashtext(a.accident_id::text) >> 8) & 1023)) END,
    closed_at = CASE
        WHEN a.status = 'CANCEL'
             THEN a.created_at + make_interval(secs => 60 + (hashtext(a.accident_id::text) & 63))
        WHEN a.accident_type = 'MOB'
             THEN a.created_at + make_interval(secs => 360 + ((hashtext(a.accident_id::text) >> 8) & 1023)
                                                           + 60 + ((hashtext(a.accident_id::text) >> 12) & 127))
        ELSE a.created_at + make_interval(secs => 1200 + ((hashtext(a.accident_id::text) >> 12) & 1023)) END,
    updated_at = now()
WHERE a.status IN ('CLOSE', 'CANCEL') AND a.accident_id::text LIKE '00000000-0000-7000-8000-%';

-- 경위(상태 이력)를 위 시각에 맞춰 다시 깐다.
--
-- 고치는 게 아니라 지우고 새로 넣는다. 남아 있던 줄들이 이랬기 때문이다:
--   · 감지 줄이 종결 줄보다 <b>나중</b> (09-16 제7금양호: 감지 12:06, 종결 10:45)
--   · 신고 줄이 종결 뒤 (09-16 동해수산호: 종결 13:47, 신고 14:56)
--   · 취소된 사고인데 줄이 한 줄도 없음
-- 한 줄씩 맞추려면 어느 줄이 맞는지부터 정해야 하는데, 기준이 될 만한 줄이 없다.
--
-- 끝난 사고의 경위는 네 줄로 정해져 있다:
--   감지 → 대기(투하 전 되돌릴 시간) → 신고 → 종결
--   취소면 신고 없이  감지 → 대기 → 취소
DELETE FROM accident_state st USING accident a
WHERE st.accident_id = a.accident_id AND a.status IN ('CLOSE', 'CANCEL')
  AND a.accident_id::text LIKE '00000000-0000-7000-8000-%';

INSERT INTO accident_state (accident_state_id, accident_id, status, created_at, prev_status, reason, caused_by)
SELECT gen_random_uuid(), a.accident_id, v.status, v.at, v.prev, v.reason, 'DEMO'
FROM accident a
CROSS JOIN LATERAL (VALUES
    ('DETECT', a.created_at,                            NULL,     'AI_DETECT'),
    -- 대기는 부표를 쏘기 전 되돌릴 시간이다. 화재·기관고장은 쏘지 않으므로 이 줄이 없다
    ('WAIT',   CASE WHEN a.accident_type = 'MOB' THEN a.created_at + interval '2 sec' END,
                                                        'DETECT', 'COUNTDOWN_START'),
    ('REPORT', a.reported_at,
               CASE WHEN a.accident_type = 'MOB' THEN 'WAIT' ELSE 'DETECT' END, 'TIMEOUT'),
    (CASE WHEN a.status = 'CANCEL' THEN 'CANCEL' ELSE 'CLOSE' END,
               a.closed_at,
               CASE WHEN a.status = 'CANCEL' THEN 'WAIT' ELSE 'REPORT' END,  -- 취소는 신고 전에 멈춘 것
               CASE WHEN a.status = 'CANCEL' THEN 'TABLET_CANCEL' ELSE 'TABLET_CLOSE' END)
) AS v(status, at, prev, reason)
WHERE a.status IN ('CLOSE', 'CANCEL') AND a.accident_id::text LIKE '00000000-0000-7000-8000-%'
  AND v.at IS NOT NULL;   -- 취소 건에는 신고 줄이 없다

-- 신고 기록도 같은 시각으로
UPDATE report r SET first_sent_at = a.reported_at,
                    last_sent_at = a.reported_at + interval '30 sec'
FROM accident a
WHERE r.accident_id = a.accident_id AND a.reported_at IS NOT NULL
  AND a.status IN ('CLOSE', 'CANCEL') AND a.accident_id::text LIKE '00000000-0000-7000-8000-%';

-- ══════════════════════════════════════════════════════════
--  ④ 시연 사고의 배 항적
-- ══════════════════════════════════════════════════════════
--
-- 배 위치는 원래 Pi 가 보낸다. 시연 사고는 우리가 SQL 로 만든 것이라 항적이 한 점도 없어,
-- 지도에서 배가 사고 난 자리에 붙박여 있었다 — 부표만 흘러가고 배는 가만히 있으니
-- 배가 사고자를 버리고 간 것도, 찾고 있는 것도 아닌 이상한 그림이 됐다(2026-09-20).
--
-- 사고가 난 배는 그 자리를 뜨지 않는다. 사람이 빠진 지점 주변을 <b>천천히 돈다</b> —
-- 그래서 직선으로 밀지 않고 뱃머리를 조금씩 틀어 원을 그리게 한다.
-- 1.2~2.5노트에 초당 0.25~0.45도씩 돌면 반경 60~250m 가 되어 사고 지점을 벗어나지 않는다.
-- (직선으로 20분을 가면 2km 를 나가 육지에 올라앉는 일이 생긴다)
--
-- ⚠ accident_id 는 NULL 로 둔다. Pi 가 보내는 모양 그대로다 — 조회는 배와 사고 기간으로 고른다
--    (AccidentQueryService.shipPositions). 여기서만 채워 두면 실제와 다른 조건으로 시험하는 셈이다.

-- 다시 깔기 전에 지운다. 조회와 같은 조건(배 + 사고 기간)이라 시연 사고 구간만 지워진다 —
-- Pi 시뮬레이터로 넣은 행은 그 사고가 시연 id 가 아니라서 남는다
DELETE FROM ship_position p USING accident a
WHERE p.ship_id = a.ship_id
  AND a.accident_id::text LIKE '00000000-0000-7000-8000-%'
  AND p.created_at BETWEEN a.created_at AND coalesce(a.closed_at, now());

WITH src AS (
    SELECT a.accident_id, a.ship_id, a.accident_lat AS lat0, a.accident_lon AS lon0, a.created_at,
           1.2 + (hashtext(a.accident_id::text) & 7) * 0.19          AS spd,   -- 1.2~2.5 kn
           (hashtext(a.accident_id::text) >> 3 & 511) * 0.703        AS hdg0,  -- 0~360°
           0.25 + ((hashtext(a.accident_id::text) >> 12) & 3) * 0.07 AS rot,   -- 초당 0.25~0.46°
           -- 끝나는 시각. 진행 중이면 지금까지 보낸다.
           -- 단, 셋 중 하나꼴로 15분 전에 끊는다 — '소식 두절' 이 어떻게 보이는지 시연에서 보여야 한다
           GREATEST(
               a.created_at + interval '2 min',   -- 갓 난 사고도 자취가 보이게 최소 몇 점은 남긴다
               LEAST(
                   coalesce(a.closed_at, now()),
                   CASE WHEN a.closed_at IS NULL AND (hashtext(a.accident_id::text) & 3) = 0
                        THEN now() - interval '15 min' ELSE now() END
               )
           ) AS until
    FROM accident a
    -- 손으로 깔아 둔 사고 전부. 우리가 만드는 것(…0001xx)과 팀원이 넣어 둔 기록(…00000x)을 함께 본다.
    -- Pi 시뮬레이터가 만든 사고는 uuid v7 이라 여기 안 걸린다 — 거기엔 진짜 받은 항적이 있다
    WHERE a.accident_id::text LIKE '00000000-0000-7000-8000-%'
      AND a.accident_lat IS NOT NULL AND a.accident_lon IS NOT NULL
),
step AS (
    -- 30초 간격. 1초마다 넣으면 행이 수만 개가 되는데 화면은 그 차이를 못 그린다
    SELECT s.*, t AS sec, ((s.hdg0 + s.rot * t)::numeric % 360 + 360) % 360 AS hdg
    FROM src s
    CROSS JOIN LATERAL generate_series(0, GREATEST(0, EXTRACT(epoch FROM s.until - s.created_at)::int), 30) AS t
),
walked AS (
    -- 30초 동안 간 거리를 남북·동서로 쪼개 누적한다. 뱃머리가 계속 틀어져 자취가 원이 된다
    SELECT step.*,
           sum(spd * 0.514444 * 30 * cosd(hdg::double precision)) OVER w AS north_m,
           sum(spd * 0.514444 * 30 * sind(hdg::double precision)) OVER w AS east_m
    FROM step
    WINDOW w AS (PARTITION BY accident_id ORDER BY sec)
)
INSERT INTO ship_position (ship_position_id, ship_id, accident_id,
                           lat, lon, speed_kn, heading_deg, accuracy_m, created_at)
SELECT gen_random_uuid(), ship_id, NULL,
       lat0 + north_m / 110574.0,
       lon0 + east_m / (111320.0 * cosd(lat0)),
       spd, hdg, 4.5,
       created_at + make_interval(secs => sec)
FROM walked
ON CONFLICT (ship_id, created_at) DO NOTHING;

-- ══════════════════════════════════════════════════════════
--  ⑤ 시연 사고에 그때의 바다를 박는다
-- ══════════════════════════════════════════════════════════
--
-- 진짜 사고는 Pi 수신이 받아 넣는다(PiIngestService.stampOcean). 시연 사고는 우리가 SQL 로
-- 만들어서 그 경로를 안 타므로 여기서 같은 값을 같은 규칙으로 채운다.
--
-- ⚠ 채울 수 없는 사고가 있다. 관측값은 24시간만 보관해서, 며칠 전 사고는 원본이 이미 지워졌다.
--    그때는 비워 둔다 — 화면이 "기록이 남아 있지 않다"고 말한다. 0 으로 채우면 "잔잔했다"가 된다.

-- ⚠ UPDATE ... FROM LATERAL 안에서는 대상 표(a)를 못 참조한다. LATERAL 을 CTE 의 FROM 으로
--    옮기면 같은 뜻이 된다 — 거기서는 a 가 같은 FROM 절의 앞선 항목이라 보인다.
WITH pick_current AS (
    SELECT a.accident_id, g.crsp_ms, g.crdir_deg, g.predc_dt
    FROM accident a
    CROSS JOIN LATERAL (
        -- 사고 시각에 가장 가까운 예보, 그중 가장 가까운 격자. OceanAt 과 같은 규칙이다 —
        -- ROMS 는 정시 예보라 30분을 당겨 물어 "이후 첫 예보"를 반올림으로 만든다
        SELECT r.crsp_ms, r.crdir_deg, r.predc_dt
        FROM ocean_roms r
        WHERE r.predc_dt >= a.created_at - interval '30 min'
          -- 사고 시각과 1시간 넘게 벌어진 예보는 그 시각 값이 아니다(OceanAt.MAX_GAP 과 같은 기준).
          -- 그날 그 타일을 안 받은 사고는 여기서 걸러져 비워진다 — 3시간 뒤 유속을 적느니 비우는 게 낫다
          AND r.predc_dt <= a.created_at + interval '1 hour'
          AND r.crsp_ms IS NOT NULL AND r.crdir_deg IS NOT NULL
          -- 5km 상한. 없으면 400km 떨어진 격자를 이 좌표의 값처럼 쓰게 된다
          AND sqrt(((r.lat - a.accident_lat) * 110574)^2
                 + ((r.lon - a.accident_lon) * 111320 * cosd(a.accident_lat))^2) <= 5000
        ORDER BY r.predc_dt,
                 sqrt(((r.lat - a.accident_lat) * 110574)^2
                    + ((r.lon - a.accident_lon) * 111320 * cosd(a.accident_lat))^2)
        LIMIT 1
    ) g
    WHERE a.accident_id::text LIKE '00000000-0000-7000-8000-%'
      AND a.accident_lat IS NOT NULL AND a.accident_lon IS NOT NULL
      AND a.ocean_observed_at IS NULL
)
UPDATE accident a SET
    ocean_current_speed_ms = p.crsp_ms,
    ocean_current_dir_deg  = p.crdir_deg,
    ocean_observed_at      = p.predc_dt
FROM pick_current p
WHERE p.accident_id = a.accident_id;

-- 바람은 따로 고른다. 조류 격자가 없어도 바람은 있을 수 있고 그 반대도 있다
WITH pick_wind AS (
    SELECT a.accident_id, w.wind_speed_ms, w.wind_dir_deg, w.observed_at
    FROM accident a
    CROSS JOIN LATERAL (
        SELECT o.wind_speed_ms, o.wind_dir_deg, o.observed_at
        FROM ocean_station_obs o
        WHERE o.observed_at BETWEEN a.created_at - interval '90 min' AND a.created_at + interval '90 min'
          AND o.wind_speed_ms IS NOT NULL AND o.wind_dir_deg IS NOT NULL
          AND sqrt(((o.lat - a.accident_lat) * 110574)^2
                 + ((o.lon - a.accident_lon) * 111320 * cosd(a.accident_lat))^2) <= 50000
        ORDER BY sqrt(((o.lat - a.accident_lat) * 110574)^2
                    + ((o.lon - a.accident_lon) * 111320 * cosd(a.accident_lat))^2)
        LIMIT 1
    ) w
    WHERE a.accident_id::text LIKE '00000000-0000-7000-8000-%'
      AND a.accident_lat IS NOT NULL AND a.accident_lon IS NOT NULL
      AND a.ocean_wind_speed_ms IS NULL
)
UPDATE accident a SET
    ocean_wind_speed_ms = p.wind_speed_ms,
    ocean_wind_dir_deg  = p.wind_dir_deg,
    ocean_observed_at   = COALESCE(a.ocean_observed_at, p.observed_at)
FROM pick_wind p
WHERE p.accident_id = a.accident_id;

-- ══════════════════════════════════════════════════════════
--  ⑥ 시연 배의 개발용 열쇠 — tools/pi-sim.mjs 가 쓴다
-- ══════════════════════════════════════════════════════════
--
-- 가짜 Pi(tools/pi-sim.mjs)는 진짜 Pi 와 <b>똑같은 경로</b>(/api/pi/*)로 보낸다. 그러려면 선박 열쇠가
-- 있어야 하는데, 진짜 등록은 신청 → 관리자 승인을 거쳐야 하고 열쇠는 그때 한 번만 보여 준다.
-- 로컬에서 매번 그 절차를 밟을 수는 없으니 <b>규칙으로 정해진 열쇠</b>를 박는다:
--
--     열쇠 = 'floaq-dev-' || ship_id          (스크립트가 같은 규칙으로 만든다)
--     저장 = SHA-256 hex                      (서버 PiKeys.hash 와 같은 방식)
--
-- ⚠ 이 파일은 local 프로필에서만 돈다(DemoDataSeeder). 운영 DB 의 열쇠는 건드리지 않는다.
--    규칙이 공개돼 있어 누구나 만들 수 있는 열쇠라, 운영에 들어가면 안 되는 값이다.
UPDATE ship
   SET edge_key_hash = encode(sha256(convert_to('floaq-dev-' || ship_id::text, 'UTF8')), 'hex')
 WHERE ship_id::text LIKE '00000000-0000-7000-8000-%';

-- ══════════════════════════════════════════════════════════
--  ⑦ 가짜 Pi(tools/pi-sim.mjs)가 남긴 시험 사고를 치운다
-- ══════════════════════════════════════════════════════════
--
-- 가짜 Pi 는 진짜 경로로 보내므로 사고가 진짜로 쌓인다 — 돌릴 때마다 기록 탭에 한 건씩 늘어,
-- 며칠 쓰면 시험 사고가 시연 사고를 덮는다. 서버를 켤 때 한 번 치운다.
--
-- 가짜 Pi 가 보낸 사고는 경위에 caused_by = 'pi-sim' 을 남긴다. 그것으로만 고른다 —
-- 진짜 Pi 나 시연 사고는 그 값을 쓰지 않으니 건드리지 않는다.
--
-- 부표·신고·경위·발사는 사고를 지우면 같이 지워진다(FK ON DELETE CASCADE).
-- 배 위치만 사고에 안 붙어 있어(accident_id 가 비어 있다) 사고 기간으로 골라 따로 지운다.
WITH sim AS (
    SELECT DISTINCT a.accident_id, a.ship_id, a.created_at, coalesce(a.closed_at, now()) AS until
    FROM accident a
    JOIN accident_state s ON s.accident_id = a.accident_id
    WHERE s.caused_by = 'pi-sim'
)
DELETE FROM ship_position p USING sim
WHERE p.ship_id = sim.ship_id AND p.created_at BETWEEN sim.created_at AND sim.until;

DELETE FROM accident a USING accident_state s
WHERE s.accident_id = a.accident_id AND s.caused_by = 'pi-sim';

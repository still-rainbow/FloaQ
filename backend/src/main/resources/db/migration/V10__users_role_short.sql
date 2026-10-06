-- 역할 값을 짧게 — ADMIN → A · SUPER_ADMIN → SA (2026-09-16)
--
-- 상세기획이 해경을 A 로 부른다. V1 도 그 사실을 주석으로만 달아 뒀다
-- ("ADMIN 이 상세기획의 A(해경)"). 문서와 DB 가 다른 이름을 쓰면 읽는 쪽이 매번 옮겨 적어야 한다.
--
-- ⚠ ERD 의 users.role 은 아직 'ADMIN / SUPER_ADMIN' 이다. ERD 도 같이 고쳐야 한다.
--
-- ⚠ 번호: V8(팀원 edge) · V9(부표 FK)가 아직 db/migration 밖(docs/)에 있어 번호가 비어 있다.
--   이 파일이 먼저 적용된 로컬 DB 는 V8 이 들어오는 날 Flyway 가 순서 위반으로 막는다.
--   그때 볼륨을 다시 만들면 된다 — 지금 로컬에는 시연 계정뿐이라 잃을 것이 없다.
--
-- 값을 바꾸는 마이그레이션이라 순서가 있다. CHECK 를 먼저 풀지 않으면 UPDATE 가 거부된다.

ALTER TABLE users DROP CONSTRAINT ck_users_role;

UPDATE users SET role = 'SA' WHERE role = 'SUPER_ADMIN';
UPDATE users SET role = 'A'  WHERE role = 'ADMIN';

ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('A', 'SA'));

COMMENT ON COLUMN users.role IS 'A = 해경(상세기획의 A). 신고받은 사고만 본다 · SA = 운영 관리자';

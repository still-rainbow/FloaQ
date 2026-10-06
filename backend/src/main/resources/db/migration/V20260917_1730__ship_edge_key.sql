-- V20260917_1730 — 선박별 Pi 키
--
-- 결정 2026-09-17 (docs/api.md §1.1). 키를 둘로 나눈다:
--   등록 키  공용. POST /api/edge/ships 한 곳에만 쓴다 (부트스트랩 — 그 시점엔 선박이 없다)
--   선박 키  등록 응답으로 발급. 그 뒤 모든 Edge 요청이 이 키다
--
-- 하나로 두면 **그 키를 가진 쪽이 아무 ship_id 로나 데이터를 올릴 수 있다**(옛 api.md §9 6).
-- 선박 키는 **키가 곧 선박 증명**이라, 서버가 페이로드의 ship_id 를 키의 선박과 대조할 수 있다.

-- char(64) 가 아니라 varchar(64) 다. char 는 PostgreSQL 에서 공백을 채워 저장해
-- 길이·연결 연산이 기대와 어긋나고, 이 저장소의 다른 컬럼도 전부 varchar 다.
ALTER TABLE ship
    ADD COLUMN edge_key_hash varchar(64);

-- 평문을 두지 않는다. DB 덤프·백업으로 새어도 그것만으로는 쓸 수 없다
-- (리프레시 토큰과 같은 방식, 계획.md §2).
--
-- ⚠ bcrypt 가 아니라 SHA-256 인 이유: **조회에 써야 한다.** bcrypt 는 salt 가 행마다 달라
--   "이 키의 주인이 누구인가"를 인덱스로 찾을 수 없다. 키가 32바이트 난수(고엔트로피)라
--   비밀번호와 달리 사전 공격 대상이 아니므로 salt·stretching 이 필요 없다.
COMMENT ON COLUMN ship.edge_key_hash IS
    '선박 Edge 키의 SHA-256 hex 64자. 평문은 발급 응답에만 실리고 서버에 남지 않는다';

-- 키로 선박을 찾는다. 요청마다 타므로 인덱스가 없으면 풀스캔이다.
-- 부분 인덱스인 이유: 아직 키를 발급받지 않은 행(V10 이전 데이터)이 NULL 로 남는데,
-- 그것들이 서로 충돌하면 안 된다.
CREATE UNIQUE INDEX uq_ship_edge_key_hash ON ship (edge_key_hash)
    WHERE edge_key_hash IS NOT NULL;

-- ⚠ 재발급 절차는 아직 없다 (api.md §9 6). 키는 발급 시 한 번만 내려가므로
--   Pi 가 잃으면 다시 받을 길이 없다 — 지금은 이 컬럼을 NULL 로 되돌리고 재등록하는 수밖에 없다.

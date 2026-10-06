-- 가입 신청 반려 상태 (WEB-07 계정 승인)
--
-- 반려와 비활성화가 둘 다 DELETED 라 나중에 구분되지 않았다(docs/api.md §9 #12).
-- 반려는 계정이 된 적이 없는 신청이고, 비활성화는 쓰던 계정을 막은 것이다 — 로그인 문구와 관리 화면이 다르다.
-- 반려된 행도 지우지 않는다. login_id 가 UNIQUE 라 같은 이메일로 다시 신청할 수는 없다.
--
-- 번호: V5 다(2026-09-16 팀원과 교환). Pi 수신용 edge 스키마는 V8 이다(docs/V8__edge_draft.sql)
--   — V6 ocean_tiles · V7 ocean_station_current 가 먼저 들어와 있다.
--   처음엔 V6 으로 만들었다가 바꿨다. 순서 위반 위험이 사라진다 — V5 가 먼저, edge 가 뒤다.

ALTER TABLE users DROP CONSTRAINT ck_users_status;
ALTER TABLE users ADD CONSTRAINT ck_users_status
    CHECK (status IN ('WAIT', 'ACTIVE', 'REJECTED', 'DELETED'));

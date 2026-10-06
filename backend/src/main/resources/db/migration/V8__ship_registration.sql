-- 선박 등록 신청과 승인 (WEB-08 · W-05 · docs/api.md §3.3)
--
-- ⚠ 등록 방향을 뒤집었다 (2026-09-16 결정).
--   상세기획 부록 C 제안: SA 가 먼저 등록 → 등록 코드 발급 → kiosk 가 코드 입력
--   확정:                kiosk 에서 신청 → SA 가 승인
--   근거: 설치 현장에 있는 사람은 선주고, SA 는 선박 제원(총톤수·승선 인원·설치 값)을 먼저 알 방법이 없다.
--         승인 화면이 계정 승인(W-04)과 같은 모양이라 화면·API·상태값이 한 벌로 재사용된다.
--   ⚠ 부록 C 와 api.md §5.3 "선박 승인·거절은 두지 않는다"가 이 결정으로 뒤집힌다. 둘 다 갱신할 것.
--
-- ⚠ ship_id 는 **서버가 채번하지 않는다.** Pi 가 UUID v7 을 만들어 서명해 보내고 서버는 받아 적는다
--   (api.md §1 "Edge 가 발급한 PK 를 그대로 쓴다" — 재전송 멱등. 서버가 채번하면 두절 복귀 때 행이 둘이 된다).
--   신청 경로(POST /api/edge/ships + HMAC 검증)는 IoT 팀 서명 계약 수령 후 붙인다(api.md §9 3-1).
--   이 마이그레이션은 그 전에 **승인 쪽만** 먼저 세운다 — SA 화면이 실제 DB 로 돌아가게.

ALTER TABLE ship
    -- 승인 상태. 값 이름을 users.status 와 맞춘다. 화면이 같은 컴포넌트를 쓴다.
    -- DELETED 는 두지 않는다 — ship 은 is_deleted 컬럼이 따로 있고 둘을 겹치면 어느 쪽이 진실인지 모른다.
    ADD COLUMN status            varchar(16),

    -- ⚠ 총톤수·승선 인원은 두지 않는다 (2026-09-16 결정). ERD(docs/erd-actual.md)의 ship 에 없는 컬럼이다 —
    --   등록 화면이 받는다는 이유로 스키마를 늘리면 ERD 와 실제가 갈라진다. kiosk 등록 화면에서도 함께 뺐다.
    --   승인 판단은 선박명·등록번호로 한다. 제원이 필요해지면 그때 ERD 부터 고친다.

    -- 설치 캘리브레이션. 선박마다 다른 값은 이 둘뿐이다(계획.md §6 · 질문.md Q0-2).
    -- 승인 판단에는 안 쓴다(장비 설정). 투하 위치 계산이 쓴다.
    ADD COLUMN camera_height_m   numeric(4,2),
    ADD COLUMN launcher_offset_m numeric(4,2),

    -- 승인·반려 시각과 처리자. users 에는 이 둘이 없어 updatedAt 으로 때우고 있는데(AdminUserView 주석),
    -- 선박은 나중에 정보 수정이 생기므로 처리 시각을 따로 둔다 — updated_at 이 수정 때마다 밀린다.
    ADD COLUMN decided_at        timestamptz,
    ADD COLUMN decided_by        bigint;

-- 기존 행은 ACTIVE 로 본다. V8 이전에는 SA 가 관제 웹에서 직접 등록하는 것만 있었고(옛 api.md §5.3),
-- 그렇게 들어온 배는 이미 승인된 것과 같다. decided_at 이 null 로 남는 이유가 이것이다 —
-- 승인 절차를 거친 적이 없어서다. 없는 시각을 지어내지 않는다.
UPDATE ship SET status = 'ACTIVE' WHERE status IS NULL;

ALTER TABLE ship
    ALTER COLUMN status SET NOT NULL;

-- DEFAULT 를 두지 않는다. 기본값이 있으면 상태를 안 넣은 INSERT 가 조용히 WAIT 로 들어가고,
-- "신청이 왜 승인 목록에 없지"를 코드가 아니라 DB 에서 찾게 된다(계획.md — 조용한 손실보다 시끄러운 실패).
ALTER TABLE ship
    ADD CONSTRAINT ck_ship_status  CHECK (status IN ('WAIT', 'ACTIVE', 'REJECTED')),
    ADD CONSTRAINT ck_ship_camera_height CHECK (camera_height_m IS NULL OR camera_height_m > 0),
    -- launcher_offset_m 은 부호를 막지 않는다. 카메라 기준 거리라 발사장치가 뒤에 있으면 음수다
    ADD CONSTRAINT fk_ship_decided_by FOREIGN KEY (decided_by) REFERENCES users (user_id);

COMMENT ON COLUMN ship.status            IS 'WAIT 신청 · ACTIVE 승인 · REJECTED 반려. 논리 삭제는 is_deleted 가 따로 본다';
COMMENT ON COLUMN ship.decided_at        IS '승인·반려 시각. V8 이전 행은 null — 승인 절차를 거친 적이 없다';
COMMENT ON COLUMN ship.decided_by        IS '처리한 SUPER_ADMIN. 계정 행은 논리 삭제라 FK 가 끊기지 않는다';
COMMENT ON COLUMN ship.camera_height_m   IS '수면 기준 카메라 높이(m). 설치할 때 한 번 잰다';
COMMENT ON COLUMN ship.launcher_offset_m IS '카메라 기준 발사장치 거리(m). 뒤쪽이면 음수';

-- 같은 배가 두 번 등록되는 것을 막는다(ErrorCode.SHIP_ALREADY_REGISTERED).
-- 반려된 신청과 논리 삭제된 배는 제외한다 — 반려당한 배는 고쳐서 다시 신청할 수 있어야 한다.
-- ⚠ 등록번호가 null 인 행(SA 직접 등록)은 이 인덱스가 막지 못한다. 등록번호를 NOT NULL 로 조이는 것은
--   기존 행 때문에 지금 못 한다 — 신청 경로가 붙어 전부 채워진 뒤에 결정한다.
CREATE UNIQUE INDEX uq_ship_registration_no ON ship (registration_no)
    WHERE registration_no IS NOT NULL AND is_deleted = false AND status <> 'REJECTED';

-- 승인 대기 목록 인덱스는 두지 않는다. 선박 수가 세 자리를 넘지 않는 동안은 순차 스캔이 더 싸다.
-- 지금 없는 문제를 위해 인덱스를 만들지 않는다(계획.md 설계 원칙).

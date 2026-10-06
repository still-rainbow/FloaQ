# FloaQ backend

Spring Boot 4.1 · Java 21 · JPA/Hibernate · PostgreSQL · Redis

## 패키지 — 도메인 수직 분할

```
com.floaq
├── global/     config · security · web(필터) · error · response · entity
├── ship/       선박 등록 · 승인 · 조회
├── accident/   사고 상태 기계 · 상태 이력 · 투하 기록
├── buoy/       부표 위치 · 두절 판정
├── drift/      표류 범위 추정
├── report/     신고 발신 '기록' (발신 주체는 Pi)
├── media/      프레임 tar 수신 · R2 · 재생
├── ocean/      해양 공공데이터 수집 · LLM 요약
├── pi/       Pi 동기화 수신 · 하행 명령 큐
├── device/     장비 상태 (IMU 등)
└── auth/       JWT · role(ADMIN / SUPER_ADMIN)
```

계층(controller/service/repository)이 아니라 **도메인**으로 먼저 나눈다. 한 기능을 고칠 때 한 디렉토리만 열면 된다.

> `accident`·`ship` 이다 (`incident`·`vessel` 아님). DB 컬럼이 `accident_id`·`ship_id` 이고
> MQTT 페이로드도 그렇다. 프론트는 `incident` 를 쓰고 `apps/kiosk/src/pi/decode.ts` 가 변환한다.

## 실행

```bash
cd ../infra && docker compose up -d postgres redis
cd ../backend && ./gradlew bootRun --args='--spring.profiles.active=local'
```

기동 시 Flyway 가 먼저 돌고, 그다음 Hibernate 가 엔티티와 스키마가 맞는지 검증한다(`validate`).

---

## 스키마 형상관리 — Flyway 가 단독 주체다

```
src/main/resources/db/migration/V1__init.sql
```

### 규칙

| | |
|---|---|
| **스키마를 바꾸는 것은 Flyway 뿐** | 앱은 `ddl-auto: validate` 로 **검증만** 한다. local 도 prod 도 같다 |
| **적용된 마이그레이션은 수정 금지** | 체크섬이 바뀌면 이미 마이그레이션된 서버가 기동을 거부한다. 고치려면 `V2` 를 새로 만든다 |
| **첫 운영 배포 전까지는 예외** | `V1` 을 자유롭게 고치되 로컬 DB 를 지우고 다시 만든다. **지금이 그 구간이다** |
| 파일명 | `V{번호}__{설명}.sql` — 밑줄 **두 개**. 하나면 Flyway 가 인식하지 않는다 |
| `baseline-on-migrate` | **`false`**. 아래 참조 |

### ⚠ `ddl-auto: update` 를 쓰지 않는 이유

Hibernate 가 스키마를 고치면 **Flyway 는 그 변경을 모른다.** 로컬에만 있는 컬럼이 생기고,
운영에서 `validate` 가 *"로컬에선 됐는데"* 하며 터진다.

엔티티를 고쳤는데 마이그레이션을 안 썼으면 **기동이 실패해야 한다.** 그게 안전망이다 —
조용히 맞춰 주는 편이 편하지만, 그 편함이 곧 로컬과 운영이 갈라지는 경로다.

### ⚠ `baseline-on-migrate: true` 가 함정인 이유

비어 있지 않은 DB 를 만나면 **현재 상태를 baseline 으로 찍고 그 이전 버전을 전부 건너뛴다.**
예전에 `ddl-auto: update` 로 만들어진 로컬 DB 가 남아 있으면, `V1` 을 추가해도
**적용되지 않고 조용히 통과한다** — "마이그레이션을 넣었는데 테이블이 안 생긴다"를 원인 없이 겪는다.

기존 DB 를 처음 채택할 때만 일회성으로 켠다.

### 스키마를 갈아엎을 때 (첫 배포 전 한정)

```bash
cd ../infra
docker compose down -v        # -v 가 볼륨까지 지운다. 이게 없으면 옛 스키마가 남는다
docker compose up -d postgres redis
```

### 새 마이그레이션 추가

**`V<YYYYMMDD>_<HHmm>__설명.sql`** — 파일을 만드는 시각을 그대로 쓴다.

```bash
# 예: V20260918_0627__add_drift_estimate.sql
./gradlew bootRun --args='--spring.profiles.active=local'   # 기동 시 자동 적용
```

일련번호(V12·V13…)를 쓰지 않는 이유는 **브랜치마다 다음 번호가 같기 때문**이다.
둘이 동시에 V12 를 만들면 나중에 머지하는 쪽이 이름을 바꿔야 하고, 먼저 적용한
사람의 DB 에서는 그 순간 체크섬이 어긋난다. 2026-09-17 에 V8·V9 가 V10·V11 뒤에
들어와 `ship.status` 가 없는 채로 `/api/admin/ships` 가 500 을 냈다. 시각은 겹치지 않는다.

⚠ `-` 는 쓸 수 없다. Flyway 버전은 숫자와 `.` `_` 만 받고 `_` 는 `.` 로 치환된다 —
`V20260918_0627` 의 버전은 `20260918.0627` 이다. `-` 를 넣으면 기동할 때
`Invalid version containing non-numeric characters` 로 죽는다.

⚠ **V1~V11 은 그대로 둔다.** 이미 모두의 DB 에 적용돼 있어서, 이름을 바꾸면
`flyway_schema_history` 와 어긋나 `Detected applied migration not resolved locally` 로
기동이 막힌다. 새 규칙은 **다음에 만드는 것부터** 적용한다 —
숫자 버전(11)보다 시각 버전(20260918.0627)이 항상 크므로 순서도 자연히 맞는다.

`clean` 은 설정에서 막아 뒀다(`clean-disabled: true`). 운영에서 한 번 실행되면
스키마가 통째로 사라지고 복구 수단이 백업뿐이다.

### Pi(Pi) 스키마는 별개다

Pi 는 SQLite 를 쓰고 Flyway 를 쓰지 않는다. **두 스키마의 컬럼명을 사람이 맞춰야 한다** —
상세기획 §6.4 가 *"컬럼명을 서버와 완전히 동일하게"* 라고 못 박은 이유다.

---

## 확정된 규칙

| 항목 | 값 | 이유 |
|---|---|---|
| `ddl-auto` | **local·prod 모두 `validate`** | 스키마 주체는 Flyway 하나. 위 참조 |
| PK | `accident`·`ship` 은 **Pi/서버가 발급한 uuid v7** | Pi 가 인터넷 없이 ID 를 만들 수 있어야 재전송이 멱등해진다 |
| `save()` | Pi 기원 엔티티는 `Persistable` 구현 | ID 가 채워져 있으면 Spring Data 가 `merge()` 로 빠져 SELECT 를 한 번 더 친다 |
| 시각 컬럼 | `Instant` (UTC 저장) | `LocalDateTime` 은 타임존 정보가 없어 사고 경위 재구성에서 어긋난다 |
| `@CreatedDate` | **Pi 기원 엔티티에는 붙이지 않는다** | 두절 복귀 시 몇 시간 전 데이터가 "방금"으로 기록된다 |
| enum 컬럼 | `varchar` + `@Enumerated(STRING)` | `ORDINAL` 은 enum 순서를 바꾸는 순간 과거 기록이 뒤바뀐다 |
| 연관관계 | 전부 `LAZY` | `EAGER` 는 사고 목록 조회에서 N+1 |
| 관리 포트 | **9090** (127.0.0.1 바인딩) | 톰캣 스레드가 전부 잠겼을 때 actuator 가 응답해야 한다 |
| 헬스체크 | `/actuator/health/liveness` | 종합 health 는 외부 API 하나만 죽어도 503 |
| Tomcat keep-alive | **120s** | nginx(30s)가 항상 먼저 닫아야 간헐 502 가 안 난다 |

`heapdump`·`env` 엔드포인트는 절대 열지 않는다. heapdump 는 호출 한 번으로 서버를 멈추고,
env 는 시크릿을 통째로 뱉는다.

## API 문서

```
/swagger-ui.html      그룹 2개 — web(/api/**) · pi(/api/pi/**)
```

운영 프로파일에서는 닫는다. 엔드포인트 목록은 공격자에게도 지도다.

인증 스킴이 둘이다 — 관제 웹은 JWT, Raspberry Pi 는 `X-Floaq-Pi-Key` 공유 시크릿.
Pi 쪽 키가 비면 `/api/pi/**` 가 전부 401 로 닫힌다(안전한 쪽). 기동 로그에 경고가 찍힌다.

package com.floaq;

import org.hibernate.boot.Metadata;
import org.hibernate.boot.MetadataSources;
import org.hibernate.boot.registry.StandardServiceRegistry;
import org.hibernate.boot.registry.StandardServiceRegistryBuilder;
import org.hibernate.mapping.Column;
import org.hibernate.mapping.PersistentClass;
import org.hibernate.mapping.Table;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 엔티티 매핑 검증.
 *
 * <p><b>DB 도 H2 도 쓰지 않는다.</b> Hibernate 메타데이터만 만들어 들여다본다 —
 * 커넥션이 필요 없어 인프라에 묶이지 않고, H2 를 넣는 쪽은 방언이 달라
 * {@code uuid}·{@code float8} 에서 가짜 통과를 만든다.</p>
 *
 * <p>DDL 문자열을 비교하지 않는 이유도 같다. Hibernate 7.4 에서 {@code SchemaExport} 가 사라졌고,
 * 문자열 매칭은 방언 표기(예: {@code float(53)} vs {@code float8})에 묶인다.
 * <b>매핑 모델을 직접 보는 쪽이 정확하다.</b></p>
 */
class EntityMappingTest {

    private static Metadata metadata;

    @BeforeAll
    static void buildMetadata() {
        StandardServiceRegistry registry = new StandardServiceRegistryBuilder()
                // 방언을 박아 둔다. 없으면 Hibernate 가 커넥션으로 알아내려 한다
                .applySettings(Map.of("hibernate.dialect", "org.hibernate.dialect.PostgreSQLDialect"))
                .build();
        metadata = new MetadataSources(registry)
                .addAnnotatedClass(com.floaq.ship.entity.Ship.class)
                .addAnnotatedClass(com.floaq.accident.entity.Accident.class)
                .addAnnotatedClass(com.floaq.accident.entity.AccidentState.class)
                .addAnnotatedClass(com.floaq.accident.entity.Launch.class)
                .addAnnotatedClass(com.floaq.buoy.entity.Buoy.class)
                .addAnnotatedClass(com.floaq.device.entity.Imu.class)
                .addAnnotatedClass(com.floaq.report.entity.Report.class)
                .addAnnotatedClass(com.floaq.media.entity.Video.class)
                .addAnnotatedClass(com.floaq.auth.entity.User.class)
                .buildMetadata();
        // buildMetadata() 자체가 가장 큰 검증이다 — 잘못된 애노테이션은 여기서 던진다
    }

    private Table table(Class<?> entity) {
        PersistentClass pc = metadata.getEntityBinding(entity.getName());
        assertThat(pc).withFailMessage("엔티티로 인식되지 않음: %s", entity.getName()).isNotNull();
        return pc.getTable();
    }

    private Set<String> columns(Class<?> entity) {
        return table(entity).getColumns().stream()
                .map(Column::getName).collect(Collectors.toSet());
    }

    /** PK 를 이루는 컬럼 이름들 (순서 무시) */
    private Set<String> pkColumns(Class<?> entity) {
        return metadata.getEntityBinding(entity.getName()).getIdentifier().getColumns().stream()
                .map(Column::getName).collect(Collectors.toSet());
    }

    // ── 테이블 이름이 ERD 와 같은가 ──────────────────────────

    @Test
    void 테이블_이름이_ERD_와_같다() {
        assertThat(table(com.floaq.ship.entity.Ship.class).getName()).isEqualTo("ship");
        assertThat(table(com.floaq.accident.entity.Accident.class).getName()).isEqualTo("accident");
        assertThat(table(com.floaq.accident.entity.AccidentState.class).getName()).isEqualTo("accident_state");
        assertThat(table(com.floaq.accident.entity.Launch.class).getName()).isEqualTo("launch");
        assertThat(table(com.floaq.buoy.entity.Buoy.class).getName()).isEqualTo("buoy");
        assertThat(table(com.floaq.device.entity.Imu.class).getName()).isEqualTo("imu");
        assertThat(table(com.floaq.report.entity.Report.class).getName()).isEqualTo("report");
        assertThat(table(com.floaq.media.entity.Video.class).getName()).isEqualTo("video");
        assertThat(table(com.floaq.auth.entity.User.class).getName()).isEqualTo("users");
    }

    // ── ERDCloud 개명 흔적 ──────────────────────────────────

    @Test
    void accident_id2_같은_자동개명_컬럼이_없다() {
        // ERD 의 launch·buoy·video 가 accident_id2 / accident_id22 다.
        // ERDCloud 가 같은 테이블로 가는 FK 를 자동 개명한 흔적이고, 그대로 두면 실제 컬럼명이 된다.
        for (Class<?> e : new Class<?>[]{
                com.floaq.accident.entity.Launch.class,
                com.floaq.buoy.entity.Buoy.class,
                com.floaq.media.entity.Video.class}) {
            assertThat(columns(e))
                    .withFailMessage("%s 에 자동개명 컬럼이 남아 있다: %s", e.getSimpleName(), columns(e))
                    .contains("accident_id")
                    .doesNotContain("accident_id2", "accident_id22");
        }
    }

    // ── Pi 가 PK 를 발급하는 구조 ─────────────────────────

    @Test
    void Pi_기원_엔티티는_PK_를_서버가_만들지_않는다() {
        // accident_id 를 서버가 발급하면 두절 복귀 때 같은 사고가 여러 행이 된다.
        // Pi 가 인터넷 없이 UUID v7 을 발급할 수 있어야 재전송이 멱등해진다.
        // Hibernate 7 에서 KeyValue#isIdentityColumn(Dialect) 이 사라져 애노테이션을 직접 본다.
        // 보려는 성질은 같다 — "이 PK 를 DB 가 만드는가".
        assertThat(hasGeneratedId(com.floaq.accident.entity.Accident.class))
                .withFailMessage("accident PK 가 DB 생성값이면 Pi 가 인터넷 없이 ID 를 못 만든다")
                .isFalse();
        assertThat(hasGeneratedId(com.floaq.accident.entity.Launch.class)).isFalse();

        // 2026-09-11: buoy·imu·accident_state·report 도 Pi 채번으로 바꿨다.
        // ERD 는 이 넷이 서버 발급 integer 였는데, Pi 의 SQLite 가 복합 PK + AUTOINCREMENT 를
        // 같이 못 쓰는 것이 계기가 됐다. 결과로 배치 INSERT 와 멱등이 함께 풀렸다.
        assertThat(hasGeneratedId(com.floaq.buoy.entity.Buoy.class)).isFalse();
        assertThat(hasGeneratedId(com.floaq.device.entity.Imu.class)).isFalse();
        assertThat(hasGeneratedId(com.floaq.accident.entity.AccidentState.class)).isFalse();
        assertThat(hasGeneratedId(com.floaq.report.entity.Report.class)).isFalse();

        // 반대로 서버가 만드는 행은 DB 가 채워도 된다
        assertThat(hasGeneratedId(com.floaq.auth.entity.User.class)).isTrue();
        assertThat(hasGeneratedId(com.floaq.media.entity.Video.class)).isTrue();
    }

    private boolean hasGeneratedId(Class<?> entity) {
        return java.util.Arrays.stream(entity.getDeclaredFields())
                .filter(f -> f.isAnnotationPresent(jakarta.persistence.Id.class))
                .anyMatch(f -> f.isAnnotationPresent(jakarta.persistence.GeneratedValue.class));
    }

    @Test
    void Pi_기원_엔티티는_save_가_merge_로_빠지지_않는다() {
        // Spring Data 의 save() 는 isNew() 로 갈린다. ID 가 이미 채워져 있으면
        // 새 엔티티가 아니라고 보고 merge() 를 부른다 — SELECT 후 INSERT 라 쿼리가 두 배다.
        // Pi 가 PK 를 발급하는 구조라 모든 삽입이 이 경로를 탄다.
        assertThat(org.springframework.data.domain.Persistable.class)
                .isAssignableFrom(com.floaq.accident.entity.Accident.class);
        for (Class<?> e : new Class<?>[]{
                com.floaq.accident.entity.Launch.class,
                com.floaq.buoy.entity.Buoy.class,
                com.floaq.device.entity.Imu.class,
                com.floaq.accident.entity.AccidentState.class,
                com.floaq.report.entity.Report.class}) {
            assertThat(org.springframework.data.domain.Persistable.class)
                    .withFailMessage("%s 가 Persistable 이 아니면 삽입마다 SELECT 가 한 번씩 더 나간다",
                            e.getSimpleName())
                    .isAssignableFrom(e);
        }
    }

    // ── 멱등성 가드 ─────────────────────────────────────────

    @Test
    void Pi_가_만드는_시계열_테이블의_PK_는_uuid_와_created_at_복합키다() {
        // 자연키 UNIQUE 를 지우고 PK 가 그 역할을 가져갔다 (V1__init.sql ⑤).
        // 이 모양이 깨지면 두 가지가 동시에 무너진다 —
        //   ① 재전송 멱등 (막을 것이 아무것도 남지 않는다. UNIQUE 를 지웠기 때문이다)
        //   ② TimescaleDB 하이퍼테이블 (PK 에 파티셔닝 컬럼이 없으면 create_hypertable 이 거부한다)
        assertThat(pkColumns(com.floaq.buoy.entity.Buoy.class))
                .containsExactlyInAnyOrder("buoy_id", "created_at");
        assertThat(pkColumns(com.floaq.device.entity.Imu.class))
                .containsExactlyInAnyOrder("imu_id", "created_at");
        assertThat(pkColumns(com.floaq.accident.entity.AccidentState.class))
                .containsExactlyInAnyOrder("accident_state_id", "created_at");
        assertThat(pkColumns(com.floaq.report.entity.Report.class))
                .containsExactlyInAnyOrder("report_id", "created_at");
    }

    @Test
    void accident_는_단일_PK_를_유지한다() {
        // 🔴 accident 를 복합키로 만들면 이 테이블을 참조하는 FK 6개가 전부 복합키가 된다.
        //   하이퍼테이블로 만들어도 안 된다 — 하이퍼테이블 → 하이퍼테이블 FK 가 미지원이라
        //   buoy·imu 가 accident 를 참조할 수 없게 된다.
        assertThat(pkColumns(com.floaq.accident.entity.Accident.class))
                .containsExactly("accident_id");
    }

    // ── 시각 의미 ───────────────────────────────────────────

    @Test
    void Pi_기원_시각은_auditing_이_덮지_않는다() {
        // created_at 의 의미가 테이블마다 다르다 —
        //   buoy·imu·accident_state·accident : Pi 의 측정·변경 시각
        //   ship·users·video                 : 행 생성 시각 (서버가 만든다)
        // 전자에 @CreatedDate 를 붙이면 두절 복귀 시 몇 시간 전 데이터가 "방금"으로 기록되고,
        // 사고 경위 재구성이 무의미해진다 (계획.md §9.5 GPS 기준 시계).
        for (Class<?> e : new Class<?>[]{
                com.floaq.buoy.entity.Buoy.class,
                com.floaq.device.entity.Imu.class,
                com.floaq.accident.entity.AccidentState.class,
                com.floaq.accident.entity.Accident.class}) {
            assertThat(e.getSuperclass())
                    .withFailMessage("%s 가 BaseTimeEntity 를 상속하면 Pi 시각을 서버 시각이 덮는다",
                            e.getSimpleName())
                    .isEqualTo(Object.class);
        }

        for (Class<?> e : new Class<?>[]{
                com.floaq.ship.entity.Ship.class,
                com.floaq.auth.entity.User.class,
                com.floaq.media.entity.Video.class}) {
            assertThat(e.getSuperclass()).isEqualTo(com.floaq.global.entity.BaseTimeEntity.class);
        }
    }

    // ── 좌표 정밀도 ─────────────────────────────────────────

    @Test
    void 좌표는_float8_이다() {
        // real 은 미터 단위 오차가 난다 (상세기획 §6.4 "반드시 float8").
        // 조난자 위치에서 미터 오차는 수색 범위를 바꾼다.
        for (String col : new String[]{"accident_lat", "accident_lon"}) {
            assertThat(precision(com.floaq.accident.entity.Accident.class, col))
                    .withFailMessage("%s 가 double 이 아니다", col).isEqualTo(53);
        }
        for (String col : new String[]{"buoy_lat", "buoy_lon"}) {
            assertThat(precision(com.floaq.buoy.entity.Buoy.class, col)).isEqualTo(53);
        }
    }

    private int precision(Class<?> entity, String columnName) {
        Column c = table(entity).getColumns().stream()
                .filter(x -> x.getName().equals(columnName)).findFirst().orElseThrow();
        return c.getSqlType(metadata).toLowerCase().contains("float(53)")
                || c.getSqlType(metadata).toLowerCase().contains("double") ? 53 : 24;
    }

    // ── ERD 에 없어서 추가한 컬럼 ───────────────────────────

    @Test
    void ERD_에_없지만_기능상_필수인_컬럼이_들어가_있다() {
        Set<String> accident = columns(com.floaq.accident.entity.Accident.class);
        // 30초 카운트다운의 유일한 근거 (ref/mqtt.md §5.1 "반드시 쓰세요")
        assertThat(accident).contains("report_due_at");
        // 중복 종결 가드가 이 컬럼 하나에 걸린다 (계획.md §9.20)
        assertThat(accident).contains("closed_at");
        // EC2 동기화 워터마크. 없으면 "지난번 이후 바뀐 행"을 고를 수 없다
        assertThat(accident).contains("updated_at");

        // 로그인 식별자. ERD 의 users 에는 password·name·role·status 뿐이라 로그인이 성립하지 않는다
        assertThat(columns(com.floaq.auth.entity.User.class)).contains("login_id");
    }
}

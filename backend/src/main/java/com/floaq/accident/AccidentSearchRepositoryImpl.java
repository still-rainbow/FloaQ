package com.floaq.accident;

import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.persistence.criteria.CriteriaQuery;
import jakarta.persistence.criteria.Predicate;
import jakarta.persistence.criteria.Root;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.UUID;

/** {@link AccidentSearchRepository} 구현. 이름이 {@code …Impl} 이어야 Spring Data 가 붙여 준다. */
@Repository
public class AccidentSearchRepositoryImpl implements AccidentSearchRepository {

    @PersistenceContext
    private EntityManager em;

    @Override
    public Page<Accident> search(Collection<AccidentStatus> visible, Collection<AccidentStatus> statuses,
                                 UUID shipId, Instant from, Instant to, Pageable pageable) {
        CriteriaBuilder cb = em.getCriteriaBuilder();

        CriteriaQuery<Accident> q = cb.createQuery(Accident.class);
        Root<Accident> root = q.from(Accident.class);
        q.where(predicates(cb, root, visible, statuses, shipId, from, to));

        // 진행 중(REPORT)을 0, 나머지를 1 로 만들어 앞세운다 — W-02 "진행 중 상단 고정".
        // 값이 아니라 순서만 쓰는 자리라 숫자에 의미를 두지 않는다.
        var inProgressFirst = cb.selectCase()
                .when(cb.equal(root.get("status"), AccidentStatus.REPORT), 0)
                .otherwise(1);
        q.orderBy(cb.asc(inProgressFirst), cb.desc(root.get("createdAt")));

        List<Accident> content = em.createQuery(q)
                .setFirstResult((int) pageable.getOffset())
                .setMaxResults(pageable.getPageSize())
                .getResultList();

        return new PageImpl<>(content, pageable,
                count(cb, visible, statuses, shipId, from, to));
    }

    private long count(CriteriaBuilder cb, Collection<AccidentStatus> visible,
                       Collection<AccidentStatus> statuses, UUID shipId, Instant from, Instant to) {
        CriteriaQuery<Long> q = cb.createQuery(Long.class);
        Root<Accident> root = q.from(Accident.class);
        q.select(cb.count(root)).where(predicates(cb, root, visible, statuses, shipId, from, to));
        return em.createQuery(q).getSingleResult();
    }

    /**
     * 조건을 <b>있을 때만</b> 붙인다. 이게 이 클래스가 존재하는 이유다 —
     * {@code :param IS NULL OR ...} 로 쓰면 파라미터 타입을 못 정해 PostgreSQL 이 거부한다.
     */
    private Predicate[] predicates(CriteriaBuilder cb, Root<Accident> root,
                                   Collection<AccidentStatus> visible, Collection<AccidentStatus> statuses,
                                   UUID shipId, Instant from, Instant to) {
        List<Predicate> where = new ArrayList<>();
        // 관제가 볼 수 있는 범위. 호출자가 무엇을 넘기든 이 조건은 항상 남는다
        where.add(root.get("status").in(visible));
        if (statuses != null && !statuses.isEmpty()) {
            where.add(root.get("status").in(statuses));
        }
        if (shipId != null) {
            where.add(cb.equal(root.get("shipId"), shipId));
        }
        if (from != null) {
            where.add(cb.greaterThanOrEqualTo(root.get("createdAt"), from));
        }
        if (to != null) {
            // 끝은 열린 구간이다. 닫으면 경계 시각의 사고가 두 기간에 모두 들어간다
            where.add(cb.lessThan(root.get("createdAt"), to));
        }
        return where.toArray(Predicate[]::new);
    }
}

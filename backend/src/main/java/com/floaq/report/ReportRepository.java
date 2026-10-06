package com.floaq.report;

import com.floaq.report.entity.Report;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface ReportRepository extends JpaRepository<Report, Report.ReportId> {

    /** 채널별 1행이라 정렬은 보기 순서일 뿐이다. */
    List<Report> findByAccidentIdOrderByCreatedAtAsc(UUID accidentId);
}

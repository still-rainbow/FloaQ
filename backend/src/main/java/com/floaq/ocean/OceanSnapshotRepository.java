package com.floaq.ocean;

import com.floaq.ocean.entity.OceanSnapshot;
import org.springframework.data.jpa.repository.JpaRepository;

/** 소스당 1행. 키가 소스 이름이라 upsert 가 곧 findById + 저장이다 */
public interface OceanSnapshotRepository extends JpaRepository<OceanSnapshot, String> {
}

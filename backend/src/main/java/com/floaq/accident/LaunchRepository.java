package com.floaq.accident;

import com.floaq.accident.entity.Launch;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

/** 사고당 1회, 재투하 없음(E5)이라 PK 가 곧 {@code accidentId} 다. */
public interface LaunchRepository extends JpaRepository<Launch, UUID> {

    Optional<Launch> findByAccidentId(UUID accidentId);
}

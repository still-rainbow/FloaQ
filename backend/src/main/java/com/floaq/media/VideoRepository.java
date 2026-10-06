package com.floaq.media;

import com.floaq.media.entity.Video;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

/** 사고 영상. 사고당 한 건이지만 재인코딩을 대비해 최신 한 건을 고른다. */
public interface VideoRepository extends JpaRepository<Video, Long> {

    Optional<Video> findFirstByAccidentIdOrderByVideoIdDesc(UUID accidentId);
}

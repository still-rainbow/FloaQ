package com.floaq.pi;

import com.floaq.pi.entity.CommandState;
import com.floaq.pi.entity.PiCommand;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.UUID;

public interface PiCommandRepository extends JpaRepository<PiCommand, UUID> {

    List<PiCommand> findByAccidentIdOrderByIssuedAtAsc(UUID accidentId);

    /** 처리 전 명령. 화면이 "종료 요청함"을 표시하는 근거다. */
    List<PiCommand> findByAccidentIdAndStateInOrderByIssuedAtAsc(UUID accidentId,
                                                                   Collection<CommandState> states);
}

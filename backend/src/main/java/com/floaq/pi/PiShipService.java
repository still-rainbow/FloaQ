package com.floaq.pi;

import com.floaq.pi.dto.PiShipRegisterRequest;
import com.floaq.pi.dto.PiShipRegisterResponse;
import com.floaq.pi.dto.PiShipStatusResponse;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.ship.ShipRepository;
import com.floaq.ship.entity.Ship;
import com.floaq.ship.entity.ShipStatus;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;
import java.util.UUID;

/**
 * 선박 등록 신청·상태 확인 (docs/api.md §4.3).
 *
 * <p><b>등록 방향이 뒤집힌 결과다</b>(2026-09-16). 관제(SA)가 먼저 등록하는 안을 기각했다 —
 * 설치 현장에 있는 사람은 선주이고, SA 는 카메라 높이·발사장치 거리 같은 현장 값을 먼저 알 방법이 없다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PiShipService {

    private final ShipRepository ships;

    /**
     * 신청. 새 선박이면 {@code WAIT} 로 만들고 <b>선박 키를 한 번만</b> 내려준다.
     *
     * <p><b>멱등은 {@code registrationNo} 가 한다.</b> 새 키를 만들지 않았다 — 어선 등록번호가 이미
     * 자연키이고 DB 에 부분 UNIQUE 가 걸려 있다({@code uq_ship_registration_no}:
     * {@code is_deleted = false AND status <> 'REJECTED'}).</p>
     *
     * <p>응답이 유실돼 Pi 가 다시 보내면 <b>같은 선박</b>을 돌려준다. 이게 없으면 재시도마다
     * 선박이 늘고 그중 어느 것이 진짜인지 아무도 모른다.</p>
     *
     * <p><b>반려된 선박은 막지 않는다.</b> 부분 UNIQUE 가 {@code REJECTED} 를 제외하므로
     * 같은 등록번호로 고쳐서 다시 낼 수 있다 — 반려가 영구 차단이 되면 안 된다.</p>
     */
    @Transactional
    public Registered register(PiShipRegisterRequest req) {
        Optional<Ship> existing = ships.findByRegistrationNoAndDeletedFalseAndStatusNot(
                req.registrationNo(), ShipStatus.REJECTED);

        if (existing.isPresent()) {
            Ship ship = existing.get();
            log.info("이미 등록된 선박 재신청 — ship_id={} status={}", ship.getShipId(), ship.getStatus());
            // 키는 다시 주지 않는다. 해시만 갖고 있어 평문을 만들어 낼 수 없다 (재발급 절차는 미정)
            return new Registered(false,
                    new PiShipRegisterResponse(ship.getShipId(), null, ship.getStatus()));
        }

        String key = PiKeys.newKey();
        // saveAndFlush 인 이유: 두 Pi 가 동시에 같은 등록번호를 보내면 uq_ship_registration_no 가 잡는데,
        // 지연 플러시면 그 예외가 **커밋 시점**(이 메서드 밖)에 터져 500 으로 샌다.
        // 여기서 터뜨려야 잡을 자리가 생긴다.
        Ship ship = ships.saveAndFlush(Ship.register(req.name(), req.registrationNo(), req.mmsi(),
                req.hasBuoyOrFalse(), req.cameraHeightM(), req.launcherOffsetM(),
                PiKeys.hash(key)));

        log.info("선박 등록 신청 — ship_id={} registration_no={}", ship.getShipId(), ship.getRegistrationNo());
        return new Registered(true,
                new PiShipRegisterResponse(ship.getShipId(), key, ship.getStatus()));
    }

    /**
     * 승인 상태 확인. <b>자기 선박만 볼 수 있다</b> — 키가 가리키는 선박과 경로의 {@code shipId} 가
     * 다르면 404 다. 남의 선박 상태를 id 를 바꿔 가며 훑을 수 있으면 안 된다.
     */
    @Transactional(readOnly = true)
    public PiShipStatusResponse status(UUID shipId, UUID callerShipId) {
        if (!shipId.equals(callerShipId)) {
            throw new BusinessException(ErrorCode.PI_SHIP_UNKNOWN);
        }
        Ship ship = ships.findById(shipId)
                .orElseThrow(() -> new BusinessException(ErrorCode.PI_SHIP_UNKNOWN));
        return new PiShipStatusResponse(ship.getShipId(), ship.getName(), ship.getStatus());
    }

    /**
     * @param created 새로 만들어졌으면 true — 컨트롤러가 201/200 을 가른다.
     *                재전송을 201 로 주면 Pi 가 "또 만들어졌다"고 읽는다
     */
    public record Registered(boolean created, PiShipRegisterResponse body) {
    }
}

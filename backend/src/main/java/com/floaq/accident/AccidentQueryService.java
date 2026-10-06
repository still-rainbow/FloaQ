package com.floaq.accident;

import com.floaq.accident.dto.AccidentDetailView;
import com.floaq.accident.dto.AccidentSummaryView;
import com.floaq.accident.dto.BuoyPositionView;
import com.floaq.accident.dto.BuoyStateView;
import com.floaq.accident.dto.LaunchView;
import com.floaq.accident.dto.MediaView;
import com.floaq.accident.dto.PendingCommandView;
import com.floaq.accident.dto.ReportView;
import com.floaq.accident.dto.ShipBriefView;
import com.floaq.accident.dto.ShipPositionView;
import com.floaq.accident.dto.TimelineEntryView;
import com.floaq.accident.entity.Accident;
import com.floaq.accident.entity.AccidentStatus;
import com.floaq.auth.UserRepository;
import com.floaq.auth.entity.UserRole;
import com.floaq.buoy.BuoyRepository;
import com.floaq.global.storage.ObjectStorage;
import com.floaq.buoy.entity.Buoy;
import com.floaq.pi.PiCommandRepository;
import com.floaq.pi.entity.CommandState;
import com.floaq.pi.entity.PiCommand;
import com.floaq.global.error.BusinessException;
import com.floaq.global.error.ErrorCode;
import com.floaq.global.response.PageView;
import com.floaq.report.ReportRepository;
import com.floaq.ship.ShipPositionRepository;
import com.floaq.ship.ShipRepository;
import com.floaq.ship.entity.Ship;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 관제 웹 사고 조회 (docs/api.md §3.4).
 *
 * <p><b>서버는 사고를 만들거나 상태를 바꾸지 않는다.</b> 여기 있는 것은 전부 읽기다 —
 * 사고의 권위는 Pi 에 있고 서버는 받아 적은 것을 보여줄 뿐이다(계획.md §9.2).</p>
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AccidentQueryService {

    /**
     * 관제가 볼 수 있는 범위 — <b>신고된 사고만</b>이다 (WEB-03 · W-02).
     *
     * <p>{@code DETECT}·{@code WAIT} 는 아직 선내에서 판단 중이고 취소될 수 있다. 그 단계를 관제에
     * 보이면 취소된 사고가 "있었던 일"로 남는다. {@code CANCEL} 은 {@code WAIT} 에서만 오므로
     * 신고 전이고, {@code CLOSE} 는 {@code REPORT} 에서만 온다 — 그래서 두 값이면 충분하다.</p>
     *
     * <p>⚠ 이 전제는 <b>오종결 재개</b>(docs/api.md §9 10)에서 깨진다. 재개를 새 건으로 열면
     * 그 사고는 {@code DETECT} 로 시작해 잠시 관제에서 사라진다.</p>
     */
    static final Set<AccidentStatus> VISIBLE = Set.of(AccidentStatus.REPORT, AccidentStatus.CLOSE);

    /**
     * 운영 관리자(SA)가 보는 범위 — <b>전부</b>다.
     *
     * <p>해경이 취소 건을 못 보는 것은 "신고받은 적이 없는 사고"이기 때문이지 숨길 값이라서가 아니다.
     * 운영 쪽은 반대로 <b>그것을 봐야 한다</b> — 감지가 얼마나 헛돌았는지(오탐율)가 거기 있고,
     * 그게 장치를 고치는 근거다. 신고 전 단계(DETECT·WAIT)도 같은 이유로 보인다(2026-09-18).</p>
     */
    static final Set<AccidentStatus> VISIBLE_SA = Set.of(AccidentStatus.values());

    /**
     * 부르는 사람이 볼 수 있는 상태 집합.
     *
     * <p>역할을 <b>JWT 권한에서 읽는다</b> — 본문이나 파라미터로 받으면 보내는 쪽이 정하는 값이 되어
     * 증명이 되지 않는다. {@code ROLE_} 접두어는 SecurityConfig 의 {@code hasRole} 이 붙이는 것과 같다.</p>
     */
    static Set<AccidentStatus> scopeOf() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        boolean sa = auth != null && auth.getAuthorities().stream()
                .anyMatch(g -> ("ROLE_" + UserRole.SA.name()).equals(g.getAuthority()));
        return sa ? VISIBLE_SA : VISIBLE;
    }

    /**
     * 한 번에 돌려주는 점의 상한. 1초에 한 번이면 한 시간치다.
     *
     * <p>⚠ <b>사고가 한 시간 안에 끝난다는 뜻이 아니다.</b> 전에는 주석이 "사고 후 상한 1시간"이라
     * 적었는데, 그 1시간은 <b>사고 뒤 사진을 찍는 상한</b>(Pi {@code FRAME_POST_MAX_SEC})이지 사고 길이가
     * 아니다 — 사고는 사람이 끝낼 때까지 가고 수색은 몇 시간 이어진다(2026-09-21).</p>
     *
     * <p>그래서 처음 받을 때는 <b>가장 최근</b> 한 시간치를 준다. 그보다 앞선 자취는 지도에서 빠진다 —
     * 실시간 지도에 필요한 것은 지금이고, 익수 지점은 따로 찍힌다.</p>
     */
    static final int TRACK_LIMIT_MAX = 3600;

    private final AccidentRepository accidents;
    private final AccidentStateRepository states;
    private final LaunchRepository launches;
    private final BuoyRepository buoys;
    private final ReportRepository reports;
    private final PiCommandRepository commands;
    private final ShipRepository ships;
    private final ShipPositionRepository shipPositions;
    private final ObjectStorage storage;
    private final UserRepository users;

    // ── 목록 ────────────────────────────────────────────────

    public PageView<AccidentSummaryView> list(Collection<AccidentStatus> statuses, UUID shipId,
                                              Instant from, Instant to, int page, int size) {
        Pageable pageable = PageRequest.of(Math.max(page, 0), Math.clamp(size, 1, 100));
        Collection<AccidentStatus> filter = (statuses == null || statuses.isEmpty()) ? null : statuses;

        var found = accidents.search(scopeOf(), filter, shipId, from, to, pageable);

        // 선박을 행마다 조회하면 페이지 크기만큼 쿼리가 난다. 한 번에 모아 온다
        Map<UUID, Ship> fleet = shipsById(found.getContent().stream().map(Accident::getShipId).toList());

        return PageView.of(found.map(a -> AccidentSummaryView.of(a, briefOf(a.getShipId(), fleet))));
    }

    private Map<UUID, Ship> shipsById(List<UUID> shipIds) {
        if (shipIds.isEmpty()) {
            return Map.of();
        }
        return ships.findAllById(Set.copyOf(shipIds)).stream()
                .collect(Collectors.toMap(Ship::getShipId, s -> s));
    }

    /**
     * 목록에도 <b>등록번호·호출부호를 싣는다</b>(2026-09-21).
     *
     * <p>전에는 이름만 실었다. 그래서 관제 화면의 선박 칸이 "선박번호"라는 이름표만 띄우고
     * 값은 비어 있었다 — 해경 계정은 선박 관리 API 를 못 보므로 채울 길이 아예 없었다.
     * 배를 이미 한 번에 모아 오고 있어 <b>쿼리가 늘지 않는다.</b></p>
     */
    private ShipBriefView briefOf(UUID shipId, Map<UUID, Ship> fleet) {
        Ship s = fleet.get(shipId);
        return s == null
                ? ShipBriefView.brief(shipId, null)
                : new ShipBriefView(s.getShipId(), s.getName(), s.getRegistrationNo(), s.getMmsi());
    }

    // ── 상세 ────────────────────────────────────────────────

    public AccidentDetailView detail(UUID accidentId) {
        Accident a = visible(accidentId);

        ShipBriefView ship = ships.findById(a.getShipId())
                .map(s -> new ShipBriefView(s.getShipId(), s.getName(), s.getRegistrationNo(), s.getMmsi()))
                .orElseGet(() -> ShipBriefView.brief(a.getShipId(), null));

        return AccidentDetailView.of(a, ship,
                launches.findByAccidentId(accidentId).map(LaunchView::of).orElse(null),
                buoyState(accidentId),
                reports.findByAccidentIdOrderByCreatedAtAsc(accidentId).stream().map(ReportView::of).toList(),
                MediaView.empty(),
                pendingCommands(accidentId));
    }

    /**
     * 부표 현재 상태. <b>통신이 두절돼도 null 이 아니다</b> — 마지막 실측이 남는다.
     * null 은 "투하 자체가 없었다"는 뜻이다.
     */
    private BuoyStateView buoyState(UUID accidentId) {
        Optional<Buoy> last = buoys.findFirstByAccidentIdOrderByCreatedAtDesc(accidentId);
        if (last.isEmpty()) {
            return null;
        }
        Buoy b = last.get();
        Instant heldAt = buoys.findFirstByAccidentIdAndPressedTrueOrderByCreatedAtAsc(accidentId)
                .map(Buoy::getCreatedAt).orElse(null);
        return new BuoyStateView(b.getLat(), b.getLon(), b.isPressed(), b.getCreatedAt(), heldAt);
    }

    private List<PendingCommandView> pendingCommands(UUID accidentId) {
        return commands.findByAccidentIdAndStateInOrderByIssuedAtAsc(
                        accidentId, List.of(CommandState.ISSUED, CommandState.DELIVERED)).stream()
                .map(c -> new PendingCommandView(c.getCommandId(), c.getType(), c.getState(),
                        c.getIssuedAt(), c.getExpiredAt()))
                .toList();
    }

    // ── 타임라인 ────────────────────────────────────────────

    /**
     * 상태 전이와 관제 명령을 <b>한 줄기로 섞어</b> 시각순으로 준다.
     *
     * <p>명령의 시각은 {@code issuedAt}(낸 시각)이다 — 처리 시각으로 정렬하면 아직 처리 안 된 명령이
     * 타임라인에서 사라지고, 그게 바로 화면이 보여줘야 하는 상태다.</p>
     */
    public List<TimelineEntryView> timeline(UUID accidentId) {
        visible(accidentId);

        List<TimelineEntryView> out = new ArrayList<>(
                states.findByAccidentIdOrderByCreatedAtAsc(accidentId).stream()
                        .map(s -> TimelineEntryView.state(s.getCreatedAt(), s.getStatus(), s.getReason()))
                        .toList());

        List<PiCommand> issued = commands.findByAccidentIdOrderByIssuedAtAsc(accidentId);
        Map<Long, String> issuerNames = issuerNames(issued);
        issued.forEach(c -> out.add(TimelineEntryView.command(c.getIssuedAt(), c.getType(), c.getState(),
                new TimelineEntryView.IssuerView(c.getIssuedBy(), issuerNames.get(c.getIssuedBy())))));

        out.sort(Comparator.comparing(TimelineEntryView::at));
        return out;
    }

    private Map<Long, String> issuerNames(List<PiCommand> issued) {
        Set<Long> ids = issued.stream().map(PiCommand::getIssuedBy).collect(Collectors.toSet());
        if (ids.isEmpty()) {
            return Map.of();
        }
        return users.findAllById(ids).stream()
                .collect(Collectors.toMap(u -> u.getUserId(), u -> u.getName()));
    }

    // ── 부표 궤적 ───────────────────────────────────────────

    public List<BuoyPositionView> buoyPositions(UUID accidentId, Instant after, Integer limit) {
        visible(accidentId);
        int capped = limit == null ? TRACK_LIMIT_MAX : Math.clamp(limit, 1, TRACK_LIMIT_MAX);
        var page = PageRequest.of(0, capped);
        // 선택 조건을 한 쿼리에 합치지 않는다 — BuoyRepository 주석 참고
        // 처음 받을 때는 <b>가장 최근</b> N 개다 — 오래된 순으로 자르면 한 시간 뒤부터 새 점이 잘려
        // 지도의 부표가 멈춘다. 이어 받을 때(after)는 그 뒤로 순서대로라 원래 방식이 맞다
        List<com.floaq.buoy.entity.Buoy> found = (after == null)
                ? newestFirst(buoys.findByAccidentIdOrderByCreatedAtDesc(accidentId, page))
                : buoys.findByAccidentIdAndCreatedAtGreaterThanOrderByCreatedAtAsc(accidentId, after, page);
        return found.stream().map(BuoyPositionView::of).toList();
    }

    // ── 선박 위치 ───────────────────────────────────────────

    /**
     * 사고 선박의 항적. 측정 시각 오름차순, {@code after} 로 이어 받는다.
     *
     * <p><b>왜 필요한가.</b> 사고 행에 든 위도·경도는 <b>감지된 순간</b>의 배 위치다. 그 뒤로 배가
     * 어디로 갔는지는 {@code ship_position} 에만 있고 읽는 길이 없어, 관제 지도에서 배가 사고 지점에
     * 붙박여 있었다. 마지막 점의 측정 시각은 "언제 마지막으로 소식을 들었나"의 답이기도 하다 —
     * 화면은 그 자리에 사고 경과를 대신 넣고 있었다(2026-09-20).</p>
     *
     * <p><b>사고 번호로 찾지 않는다.</b> {@code ship_position.accident_id} 는 거의 늘 비어 있다 —
     * Pi 에 그 칸이 없고, 어느 위치가 어느 사고 것인지 붙이는 규칙이 아직 합의 전이다(api.md §0.1 #5).
     * 그래서 여기서 <b>사고가 난 배</b>와 <b>감지부터 종결까지</b>로 고른다. 수신 때 추측을 적어 두는 것과
     * 달리 이 방식은 표를 더럽히지 않고, 규칙이 서면 이 메서드만 고치면 된다.</p>
     *
     * <p>진행 중인 사고는 끝이 없으므로 <b>지금</b>까지 본다.</p>
     */
    public List<ShipPositionView> shipPositions(UUID accidentId, Instant after, Integer limit) {
        Accident a = visible(accidentId);
        int capped = limit == null ? TRACK_LIMIT_MAX : Math.clamp(limit, 1, TRACK_LIMIT_MAX);
        Instant from = (after != null && after.isAfter(a.getCreatedAt())) ? after : a.getCreatedAt();
        /*
         * 🔴 진행 중이면 끝을 <b>서버 시계로 자르지 않는다.</b> 위치 시각은 배 GPS 가 찍는데, 배 시계가
         * 서버보다 조금만 빨라도 최신 점들이 "미래"로 빠져 배가 한 박자씩 늦거나 멈춰 보였다(2026-09-21).
         * 한 배에 진행 중 사고는 하나뿐이라(uq_accident_active) 넉넉히 열어 둬도 다른 사고 점이 섞이지 않는다.
         */
        Instant to = a.getClosedAt() != null ? a.getClosedAt() : Instant.now().plus(LIVE_CLOCK_SKEW);
        // 종결 시각이 감지보다 앞설 수는 없지만, 그래도 뒤집힌 기간을 넘기면 JPA 가 빈 목록 대신 경고를 낸다
        if (to.isBefore(from)) return List.of();
        var page = PageRequest.of(0, capped);
        List<com.floaq.ship.entity.ShipPosition> found = (after == null)
                // 처음 받을 때는 가장 최근 N 개 — 부표와 같은 이유다
                ? newestFirst(shipPositions.findByShipIdAndCreatedAtBetweenOrderByCreatedAtDesc(a.getShipId(), from, to, page))
                : shipPositions.findByShipIdAndCreatedAtBetweenOrderByCreatedAtAsc(a.getShipId(), from, to, page);
        return found.stream().map(ShipPositionView::of).toList();
    }

    // ── 신고 기록 ───────────────────────────────────────────

    public List<ReportView> reports(UUID accidentId) {
        visible(accidentId);
        return reports.findByAccidentIdOrderByCreatedAtAsc(accidentId).stream()
                .map(ReportView::of)
                .toList();
    }

    // ── 공통 ────────────────────────────────────────────────

    /**
     * 범위 밖 사고는 <b>404 다. 403 이 아니다</b> — 403 이면 "그런 사고가 있다"를 알려주는 셈이고,
     * 사고 ID 를 바꿔 가며 찔러 보면 어느 선박에 사고가 있었는지가 새어 나간다.
     */
    /** 최신순으로 받은 것을 시간순으로 되돌린다. 화면은 궤적을 앞에서부터 그린다 */
    private static <T> List<T> newestFirst(List<T> desc) {
        List<T> asc = new ArrayList<>(desc);
        java.util.Collections.reverse(asc);
        return asc;
    }

    /** 진행 중 사고의 배 위치를 받을 때 서버 시계보다 얼마나 앞선 점까지 받나. 배 시계가 빠를 수 있다 */
    private static final java.time.Duration LIVE_CLOCK_SKEW = java.time.Duration.ofHours(1);

    /** 다른 읽기 서비스가 같은 범위 규칙을 쓰게 연다 — 사진·영상도 볼 수 있는 사고만 답한다 */
    public void requireVisible(UUID accidentId) {
        visible(accidentId);
    }

    private Accident visible(UUID accidentId) {
        return accidents.findByAccidentIdAndStatusIn(accidentId, scopeOf())
                .orElseThrow(() -> new BusinessException(ErrorCode.ACCIDENT_NOT_FOUND));
    }
}

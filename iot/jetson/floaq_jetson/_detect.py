"""사고 승격 판정. **AI-02.**

YOLO 는 매 프레임 "사람 같은 게 있다" 를 말한다. 그걸 그대로 `detected()` 로 올리면
5fps × 카메라 2대 = 초당 10건의 탐지가 Pi 로 간다. 한 번 튄 오탐도 그대로 사고가 된다.

여기서 **연속성**으로 거른다.

    신뢰도 conf_min 이상인 프레임이 need_frames 개 **연달아** 나오면 승격

🔴 **임계값은 아직 정해지지 않았다** (`docs/mqtt.md` §7 항목 10, AI팀 몫).
   여기 기본값은 자리만 잡아 둔 것이고, 실제 모델·바다 장면으로 재봐야 한다.
   CLI 로 바꿀 수 있게 열어 둔 이유가 그것이다.

── 왜 카메라별로 세는가 ────────────────────────────────────────────
좌우가 번갈아 들어오는데 한 카운터로 세면 "L 한 장 + R 한 장"이 연속 2프레임으로
보인다. 같은 대상을 두 각도에서 본 것이지 2프레임 연속 검출이 아니다.

── 왜 시간 간격을 보는가 ───────────────────────────────────────────
5fps 면 프레임 간격이 0.2초다. 추론이 밀리거나 카메라가 끊겼다 붙으면 그 사이가
몇 초로 벌어지는데, 카운터만 보면 그것도 "연속"이다. `gap_sec` 을 넘으면 끊는다.

── 왜 쿨다운이 있는가 ──────────────────────────────────────────────
Pi 는 동시 사고 1건이라(E1) 두 번째 탐지에 409 를 준다. 그걸 받고 나서 버리는 것도
동작은 하지만, 초당 10번 409 를 받으면 로그가 그걸로 덮인다. 여기서 먼저 막는다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

#: 사고로 승격할 최소 신뢰도. `미정`⚠️ AI팀 — 실제 모델로 재야 한다.
CONF_MIN = 0.60

#: 연속 몇 프레임이면 승격인가. 5fps 라 5면 1초다. `미정`⚠️ AI팀.
NEED_FRAMES = 5

#: 이보다 오래 비면 연속이 끊긴 것으로 본다. 5fps 의 정상 간격은 0.2초다.
GAP_SEC = 1.0

#: 한 번 승격한 뒤 이만큼은 다시 안 올린다. Pi 의 동시 사고 1건(E1)과 짝이다.
COOLDOWN_SEC = 60.0


@dataclass(frozen=True, slots=True)
class Promotion:
    """승격 한 건. `Floaq.detected()` 에 그대로 넘길 값들."""

    camera: str
    #: 연속 프레임 수. `JetsonDetection.frame_count` 로 간다 (AI-02 근거)
    frame_count: int
    #: 연속 구간에서 가장 높았던 신뢰도. 평균이 아니라 최대다 —
    #: 판정 근거를 보수적으로 남기면 나중에 임계값을 올릴 때 기준이 흐려진다
    confidence: float
    #: 가장 신뢰도가 높았던 프레임의 bbox. (x, y, w, h)
    bbox: tuple[int, int, int, int] | None


class Judge:
    """프레임마다 먹이고, 승격할 때만 `Promotion` 을 돌려받는다.

    ⚠ 스레드 안전하다. 추론 스레드가 카메라별로 부른다.
    """

    def __init__(self, *, conf_min: float = CONF_MIN,
                 need_frames: int = NEED_FRAMES,
                 gap_sec: float = GAP_SEC,
                 cooldown_sec: float = COOLDOWN_SEC) -> None:
        if need_frames < 1:
            raise ValueError("need_frames 는 1 이상")
        if not 0.0 <= conf_min <= 1.0:
            raise ValueError("conf_min 은 0~1")
        self.conf_min = conf_min
        self.need_frames = need_frames
        self.gap_sec = gap_sec
        self.cooldown_sec = cooldown_sec

        self._lock = threading.Lock()
        #: 카메라별 (연속 수, 최고 신뢰도, 그때 bbox, 마지막 시각)
        self._run: dict[str, tuple[int, float, tuple | None, float]] = {}
        self._last_promo = 0.0

    def feed(self, camera: str, conf: float | None,
             bbox: tuple[int, int, int, int] | None, now: float) -> Promotion | None:
        """프레임 하나의 결과. 사람이 없으면 `conf=None`.

        승격 조건을 채운 그 프레임에서만 `Promotion` 을 돌려준다. 그 뒤로는
        연속이 이어져도 쿨다운이 끝날 때까지 None 이다.
        """
        with self._lock:
            n, best, best_box, last = self._run.get(camera, (0, 0.0, None, 0.0))

            if conf is None or conf < self.conf_min:
                # 🔴 끊긴 것을 반드시 0 으로 되돌린다. 안 그러면 몇 분에 걸쳐
                #   띄엄띄엄 튄 오탐이 모여서 승격한다
                self._run[camera] = (0, 0.0, None, now)
                return None

            if now - last > self.gap_sec:
                n, best, best_box = 0, 0.0, None      # 간격이 벌어졌다. 새로 센다

            n += 1
            if conf > best:
                best, best_box = conf, bbox
            self._run[camera] = (n, best, best_box, now)

            if n < self.need_frames:
                return None
            if now - self._last_promo < self.cooldown_sec:
                return None

            self._last_promo = now
            # 승격했으면 카운터를 비운다. 안 그러면 쿨다운이 끝나는 순간
            # 다음 한 프레임에 바로 또 승격한다
            self._run[camera] = (0, 0.0, None, now)
            return Promotion(camera=camera, frame_count=n,
                             confidence=best, bbox=best_box)

    def reset(self) -> None:
        """사고가 끝났을 때 부른다. 쿨다운도 같이 푼다."""
        with self._lock:
            self._run.clear()
            self._last_promo = 0.0

    def state(self) -> dict:
        with self._lock:
            return {c: v[0] for c, v in self._run.items()}


class AimTrigger:
    """`--aim-detect` 의 사고 등록. **사고 등록 조건 = 발사 조건이다** (2026-09-28).

    🔴 Pi 는 스테레오 조준이 **한 번** 오면 쏜다(`--fire-stable-count 1`). 조준은
       좌우 두 대가 다 사람을 잡고, 두 시선이 만나고, 3m 안이고, 안정됐을 때만 나간다
       (`_stereo_aiming`). 전에는 사고를 카메라 한 대 기준(`Judge`)으로 따로 판정해서
       **쏘지도 않는데 사고가 생기거나**, 거리 15m·고각 20° 어림값이 기록됐다.
       이제는 조준을 **실제로 보낸 그 프레임**에서만 사고를 올린다.

    쓰는 법: 조준을 보냈으면 `aim_sent()`, 같은 프레임의 카메라 결과마다 `take()`.
    `take()` 가 값을 돌려주는 것은 그 조준 한 번에 한 번뿐이다.
    """

    def __init__(self, *, cooldown_sec: float = COOLDOWN_SEC) -> None:
        self.cooldown_sec = cooldown_sec
        self._lock = threading.Lock()
        self._pending = None
        self._last = 0.0

    def aim_sent(self, pointing, confidence: float) -> None:
        with self._lock:
            self._pending = (pointing, float(confidence))

    def take(self, conf: float | None, bbox, now: float):
        """이 카메라 결과로 사고를 올릴지. 올리면 `(pointing, confidence)`, 아니면 None."""
        with self._lock:
            if self._pending is None or conf is None or bbox is None:
                return None
            got, self._pending = self._pending, None
            if now - self._last < self.cooldown_sec:
                return None
            self._last = now
            return got

    def reset(self) -> None:
        """사고가 열려 있거나 끝났을 때. 쌓인 조준과 쿨다운을 비운다."""
        with self._lock:
            self._pending = None
            self._last = 0.0

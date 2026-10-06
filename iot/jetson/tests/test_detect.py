"""AI-02 사고 승격 판정 시험.

여기 걸린 것들은 전부 **조용히 틀리는** 종류다. 판정이 헐거우면 갈매기 한 마리에
조난 신고가 나가고, 빡빡하면 사람이 빠져도 아무 일이 안 일어난다. 둘 다 로그만
봐서는 모른다.

⚠ 임계값 자체는 `미정`(AI팀)이다. 여기서 보는 것은 **규칙이 의도대로 도는가**이지
  0.6 이 옳은 값인가가 아니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from floaq_jetson import FRAME_POST_SEC, FRAME_PRE_SEC
from floaq_jetson._detect import Judge
from floaq_jetson.__main__ import resolve_pre_sec

BOX = (100, 50, 40, 90)


def judge(**kw) -> Judge:
    base = dict(conf_min=0.6, need_frames=3, gap_sec=1.0, cooldown_sec=60.0)
    return Judge(**{**base, **kw})


def feed(j: Judge, confs, *, camera="L", t0=1000.0, step=0.2):
    """프레임을 순서대로 먹인다. 나온 승격들을 돌려준다."""
    out = []
    for i, c in enumerate(confs):
        p = j.feed(camera, c, BOX, t0 + i * step)
        if p is not None:
            out.append(p)
    return out


# ── 연속성 ───────────────────────────────────────────────────────────
def test_promotes_after_consecutive_frames():
    got = feed(judge(), [0.9, 0.9, 0.9])
    assert len(got) == 1
    assert got[0].frame_count == 3
    assert got[0].camera == "L"


def test_one_frame_short_does_not_promote():
    assert feed(judge(), [0.9, 0.9]) == []


def test_low_confidence_breaks_the_run():
    """🔴 끊긴 것을 0 으로 되돌려야 한다.

    안 그러면 몇 분에 걸쳐 띄엄띄엄 튄 오탐이 모여서 사고가 된다.
    """
    assert feed(judge(), [0.9, 0.9, 0.1, 0.9, 0.9]) == []


def test_no_person_breaks_the_run():
    """사람이 안 보인 프레임도 연속을 끊는다. `conf=None` 이 그 뜻이다."""
    assert feed(judge(), [0.9, 0.9, None, 0.9, 0.9]) == []


def test_gap_in_time_breaks_the_run():
    """🔴 추론이 밀리거나 카메라가 끊겼다 붙으면 카운터만으로는 연속처럼 보인다.

    5fps 의 정상 간격은 0.2초다. 몇 초가 비었는데 이어 세면 안 된다.
    """
    j = judge()
    assert j.feed("L", 0.9, BOX, 1000.0) is None
    assert j.feed("L", 0.9, BOX, 1000.2) is None
    # 5초 비었다. 여기서 새로 센다
    assert j.feed("L", 0.9, BOX, 1005.2) is None
    assert j.feed("L", 0.9, BOX, 1005.4) is None
    assert j.feed("L", 0.9, BOX, 1005.6) is not None


# ── 카메라 분리 ──────────────────────────────────────────────────────
def test_cameras_are_counted_separately():
    """🔴 좌우를 한 카운터로 세면 "L 한 장 + R 한 장"이 2프레임 연속이 된다.

    같은 대상을 두 각도에서 본 것이지 연속 검출이 아니다.
    """
    j = judge()
    for t in range(6):
        cam = "L" if t % 2 == 0 else "R"
        assert j.feed(cam, 0.9, BOX, 1000.0 + t * 0.2) is None or t >= 4

    j2 = judge()
    got = [j2.feed("L" if i % 2 == 0 else "R", 0.9, BOX, 1000.0 + i * 0.2)
           for i in range(4)]
    assert all(g is None for g in got)      # 각 카메라 2프레임씩이라 아직 아니다


def test_either_camera_can_promote_alone():
    assert len(feed(judge(), [0.9, 0.9, 0.9], camera="R")) == 1


# ── 쿨다운 ───────────────────────────────────────────────────────────
def test_cooldown_blocks_a_second_promotion():
    """Pi 는 동시 사고 1건(E1)이라 두 번째는 409 다. 그 전에 막는다."""
    j = judge()
    assert len(feed(j, [0.9] * 3, t0=1000.0)) == 1
    assert feed(j, [0.9] * 10, t0=1002.0) == []


def test_promotion_resumes_after_cooldown():
    j = judge(cooldown_sec=10.0)
    assert len(feed(j, [0.9] * 3, t0=1000.0)) == 1
    assert len(feed(j, [0.9] * 3, t0=1020.0)) == 1


def test_counter_is_cleared_on_promotion():
    """🔴 승격 뒤 카운터를 안 비우면 쿨다운이 끝나는 순간 한 프레임에 또 올라간다."""
    j = judge(cooldown_sec=1.0)
    feed(j, [0.9] * 3, t0=1000.0)
    # 쿨다운이 지난 직후 한 장. 카운터가 남아 있었다면 여기서 바로 승격한다
    assert j.feed("L", 0.9, BOX, 1002.0) is None


def test_reset_clears_cooldown():
    """사고가 끝나면 다음 사고를 받을 수 있어야 한다."""
    j = judge()
    assert len(feed(j, [0.9] * 3, t0=1000.0)) == 1
    j.reset()
    assert len(feed(j, [0.9] * 3, t0=1002.0)) == 1


# ── 값 ───────────────────────────────────────────────────────────────
def test_reports_the_highest_confidence_not_the_last():
    """판정 근거는 최대값이다. 마지막 값으로 남기면 나중에 임계를 올릴 때 기준이 흐려진다."""
    got = feed(judge(), [0.7, 0.95, 0.65])
    assert got[0].confidence == pytest.approx(0.95)


def test_reports_the_box_of_the_best_frame():
    j = judge()
    j.feed("L", 0.7, (1, 1, 1, 1), 1000.0)
    j.feed("L", 0.95, (9, 9, 9, 9), 1000.2)
    p = j.feed("L", 0.65, (2, 2, 2, 2), 1000.4)
    assert p is not None and p.bbox == (9, 9, 9, 9)


def test_confidence_exactly_at_the_threshold_counts():
    """경계값은 포함이다. 0.6 이상이라고 적었으면 0.6 도 통과해야 한다."""
    assert len(feed(judge(conf_min=0.6), [0.6, 0.6, 0.6])) == 1


def test_need_frames_one_promotes_immediately():
    assert len(feed(judge(need_frames=1), [0.9])) == 1


# ── 방어 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kw", [{"need_frames": 0}, {"conf_min": 1.5},
                                {"conf_min": -0.1}])
def test_bad_settings_fail_loudly(kw):
    with pytest.raises(ValueError):
        judge(**kw)


# ── --test 창 길이 ───────────────────────────────────────────────────
@pytest.mark.parametrize("test_sec,pre,post,want", [
    (30, FRAME_PRE_SEC, 10, 20),      # 기본: 30초 = 앞20 + 뒤10
    (45, FRAME_PRE_SEC, 10, 35),
    (30, FRAME_PRE_SEC, 5, 25),       # 뒤를 줄이면 앞이 늘어난다
    (30, 25, 10, 25),                 # --pre-sec 을 직접 주면 그것이 이긴다
])
def test_test_window_splits_into_pre_and_post(test_sec, pre, post, want):
    assert resolve_pre_sec(test_sec, pre, post) == want


def test_pre_sec_never_goes_to_zero():
    """🔴 앞 구간이 0 이면 링 버퍼 용량이 0 이라 프레임이 한 장도 안 쌓인다.

    `--test 5 --post-sec 10` 처럼 뒤가 더 긴 경우다.
    """
    assert resolve_pre_sec(5, FRAME_PRE_SEC, 10) >= 1
    assert resolve_pre_sec(1, FRAME_PRE_SEC, FRAME_POST_SEC) >= 1


# ── --aim-detect: 사고 등록 = 발사 조건 ──────────────────────────────
def test_aim_trigger_only_fires_on_a_sent_aim():
    """🔴 조준을 보내지 않았으면(두 대가 다 못 잡았거나 불안정) 사고도 없다."""
    from floaq_jetson._detect import AimTrigger

    t = AimTrigger(cooldown_sec=60.0)
    assert t.take(0.9, (1, 2, 3, 4), 100.0) is None        # 조준 없음 → 사고 없음
    t.aim_sent("POINTING", 0.8)
    assert t.take(0.9, (1, 2, 3, 4), 100.0) == ("POINTING", 0.8)
    assert t.take(0.9, (1, 2, 3, 4), 100.1) is None        # 한 조준에 한 번뿐


def test_aim_trigger_needs_a_person_box_and_honours_cooldown():
    from floaq_jetson._detect import AimTrigger

    t = AimTrigger(cooldown_sec=60.0)
    t.aim_sent("P", 0.8)
    assert t.take(None, None, 100.0) is None                # 이 카메라엔 사람 상자가 없다
    t.aim_sent("P", 0.8)
    assert t.take(0.9, (1, 2, 3, 4), 100.0) == ("P", 0.8)
    t.aim_sent("P", 0.8)
    assert t.take(0.9, (1, 2, 3, 4), 130.0) is None         # 쿨다운 60초 안
    t.reset()                                                # 사고가 열렸다 닫힘
    t.aim_sent("P", 0.8)
    assert t.take(0.9, (1, 2, 3, 4), 131.0) == ("P", 0.8)

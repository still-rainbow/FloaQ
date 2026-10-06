"""EC2 응답 분류. 잘못 분류하면 **행이 조용히 지워지거나 큐가 영원히 막힌다.**"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floaq.adapters.ec2 import Action, classify


def test_unsupported_version_halts_instead_of_dropping():
    """🔴 서버는 `PI_UNSUPPORTED_VERSION` 을 400 으로 준다. 400 기본값(DROP)으로 떨어지면
    버전만 맞추면 다시 보낼 수 있는 배치가 지워진다."""
    assert classify(400, "PI_UNSUPPORTED_VERSION") is Action.HALT
    assert classify(400, "EDGE_UNSUPPORTED_VERSION") is Action.HALT


def test_plain_bad_input_still_drops():
    assert classify(400, "COMMON_INVALID_INPUT") is Action.DROP
    assert classify(400, None) is Action.DROP

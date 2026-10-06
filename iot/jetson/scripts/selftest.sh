#!/usr/bin/env bash
# Pi 와의 경로를 끝까지 한 번 돌린다. 카메라도 모델도 없이 돈다.
#
#   ./scripts/selftest.sh 192.168.0.10
#   FLOAQ_PI=192.168.0.10 ./scripts/selftest.sh
#   ./scripts/selftest.sh 192.168.0.10 --no-aim     조준 해 없이 (NO_SOLUTION 확인)
#
# 여기서 안 되면 원인이 배관이고, 여기서 되면 AI 쪽이다.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

eval "$(take_pi "$@")"

# 🔴 탐지 시각이 1970 으로 찍히는 것을 여기서 막는다 (_common.sh sync_clock)
sync_clock "$PI"

echo "Pi $PI 로 탐지 한 번 + 프레임 보내기"
echo "⚠ 시험용 탐지다. Pi 에 실제로 사고가 하나 생긴다."
echo
run_py -m floaq_jetson --pi "$PI" "$@"

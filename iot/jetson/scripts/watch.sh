#!/usr/bin/env bash
# 붙어만 있고 상태를 지켜본다. 탐지를 만들지 않는다.
#
#   ./scripts/watch.sh 192.168.0.10
#
# 카메라 스트림도 같이 뜬다 — http://<jetson>:8080/
# /health 가 카메라 둘의 생사를 준다. 한쪽이 live:false 면 그쪽이 안 붙은 것이다.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PI="$(pi_host "${1:-}")"
[ $# -gt 0 ] && shift

echo "Pi $PI  ·  스트림 http://0.0.0.0:8080/"
echo "Ctrl+C 로 종료"
echo
run_py -m floaq_jetson --pi "$PI" --watch "$@"

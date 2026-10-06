#!/usr/bin/env bash
# 환경 확인. AI 코드를 붙이기 전에 이것부터 통과시킨다.
#
#   ./scripts/check.sh

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

echo "== 인터프리터 =="
"$JETPACK_PY" --version || die "$JETPACK_PY 가 없다. JetPack Python 경로를 JETPACK_PY 로 줄 것"
uname -m

echo
echo "== 의존성 동기화 =="
# --locked: lock 을 임의로 갱신하지 않는다. 갱신이 필요하면 uv lock 을 따로 친다.
# --inexact: lock 에 없는 수동 설치 패키지를 지우지 않는다 (JetPack 시스템 패키지).
uv sync --locked --inexact --python "$JETPACK_PY"

echo
echo "== JetPack 검증 =="
run_py verify_environment.py

echo
echo "== SDK import =="
run_py -c "import floaq_jetson; print('floaq_jetson ok'); print(floaq_jetson.__all__)"

echo
echo "전부 통과."

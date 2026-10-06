#!/usr/bin/env bash
# 시연용 초기화. 저장된 것을 전부 지우고 Pi 를 **등록 모드**로 띄운다.
#
#   ./scripts/demo-reset.sh                                 신고는 UDP 브로드캐스트
#   ./scripts/demo-reset.sh --report-host 127.0.0.1     OpenCPN PC 를 콕 집어서
#   FLOAQ_REPORT_HOST=127.0.0.1 ./scripts/demo-reset.sh  환경변수로도 된다
#
# 🔴 **신고는 기본이 UDP 다.** main.py 기본값(--report fake)은 전파를 안 쏜다.
#   시연 스크립트가 신고를 안 쏘면 OpenCPN 에 아무것도 안 뜨는데, 로그에는 사고가
#   정상으로 남아 원인이 안 보인다. 실제로 밟았다.
#
# 여기서 등록하지 않는다. **키오스크에서 등록하는 것까지가 검증 대상**이다.
#
#   ① 이 스크립트   DB·프레임 지우고 등록 모드로 기동
#   ② 키오스크      이름·등록번호·MMSI 입력 -> POST /api/ship
#   ③ Pi -> EC2     즉시 올린다 (대기 없음)
#   ④ 관제 웹       승인 -> EC2 전송 시작
#
# 🔴 **등록번호는 매번 새 값이어야 한다.** 서버는 같은 registration_no 로
#   ship_key 를 다시 주지 않는다(실측: 재전송이면 200 + ship_key: null).
#   DB 를 지우면 키도 같이 지워지므로, 같은 번호를 다시 넣은 배는 영영 EC2 에
#   못 붙는다. 웹 등록 화면이 새 번호를 만들어 주는지 확인할 것.
#
# ⚠ .env 는 안 지운다. 등록 키가 거기 있고 초기화 대상이 아니다.

set -euo pipefail
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-C.UTF-8}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${FLOAQ_HTTP_PORT:-8000}"
# 목적지를 안 주면 브로드캐스트. 같은 랜의 OpenCPN 이 받는다
REPORT_HOST="${FLOAQ_REPORT_HOST:-255.255.255.255}"

die() { echo "$*" >&2; exit 1; }

[ -f .env ] || die ".env 가 없다.  cp .env.example .env  후 FLOAQ_SHIP_REGISTER_KEY 를 채울 것"
# 8자만 붙여넣어 조용히 401 이 난 적이 있다. 길이를 먼저 본다
grep -q '^FLOAQ_SHIP_REGISTER_KEY=.\{32,\}' .env \
    || die ".env 의 FLOAQ_SHIP_REGISTER_KEY 가 비었거나 짧다 (64자여야 한다)"

# ── 1. 내린다 ────────────────────────────────────────────────────────
# ⚠ 떠 있으면 DB 파일이 잠긴다. 지우기 전에 반드시 내린다.
if pkill -f "main.py" 2>/dev/null; then
    echo "돌고 있던 main.py 를 내렸다"
    sleep 1
fi

# ── 2. 지운다 ────────────────────────────────────────────────────────
rm -f floaq.db floaq.db-wal floaq.db-shm
rm -f floaq.db.pending-ship.json floaq.db.pending-ship.json.part
rm -f .ship_id .aid pi.log
rm -rf data
echo "지웠다: DB · 등록 대기 · 프레임(data/)"
echo "남겼다: .env (등록 키)"

# ── 3. 띄운다 ────────────────────────────────────────────────────────
# 배가 없으니 등록 모드로 뜬다. 브로커가 없어도 죽지 않는다(재접속).
# --fake-hw: GPIO·IMU 어댑터가 아직 없다.
echo
echo "등록 모드로 기동한다. Ctrl+C 로 종료"
echo "  키오스크에서 등록:  POST http://<pi>:$PORT/api/ship"
echo "  상태 확인:          curl -s localhost:$PORT/api/ship"
echo "  조난 신고 UDP:      $REPORT_HOST:10110  (OpenCPN)"
echo
# ⚠ 뒤에 오는 "$@" 가 앞의 기본값을 덮는다 — --report-host 를 주면 그게 이긴다.
#   --gps fake 도 기본으로 둔다. 배 GPS 가 없으면 시각 기준이 안 서서
#   카운트다운이 아예 안 돈다(clock_is_valid).
#   --lora fake: 가짜 부표가 1Hz 로 흐른다. 실물 E22 면 --lora serial 로 덮는다.
exec uv run main.py --fake-hw --gps fake --lora fake --report udp --report-host "$REPORT_HOST" "$@"

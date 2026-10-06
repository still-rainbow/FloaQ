#!/usr/bin/env bash
# FloaQ Pi 개발 스크립트 (Linux / Raspberry Pi)
#
# 사용:
#   ./scripts/dev.sh reset     DB·프레임·등록 대기 전부 지운다. 등록부터 다시
#   ./scripts/dev.sh broker    mosquitto 기동 (1883 + 9001)
#   ./scripts/dev.sh pi        오케스트레이터 기동 (배가 없으면 등록 모드)
#                              --servos 면 실장비 — 🔴 기본이 발사다
#   ./scripts/dev.sh aim       시험: 실제 CH0/CH1 조준만. CH2 를 열지 않는다 (--no-fire)
#   ./scripts/dev.sh aim-fire  자동 조준 뒤 실제 발사 1회
#   ./scripts/dev.sh sub       전체 메시지 덤프
#   ./scripts/dev.sh detect    가짜 탐지 1회
#   ./scripts/dev.sh close     진행 중 사고 닫기 (반복 시험용)
#
# 시연 초기화는 따로 있다 — 지우고 등록 모드로 기동까지:
#   ./scripts/demo-reset.sh
#   ./scripts/dev.sh kiosk     개발용 키오스크 열기 (ws://9001)
#   ./scripts/dev.sh lora-b    LoRa 수신 검증 (UDP 또는 시리얼)
#   ./scripts/dev.sh lora-a    LoRa 송신 검증 (부표 역할)
#   ./scripts/dev.sh distress  조난 신고 UDP 송출 (DSC + AIS)
#   ./scripts/dev.sh status    떠 있는 것 확인
#   ./scripts/dev.sh stop      전부 종료
#
# broker / pi / sub 는 각각 별도 창에서 띄운다. 셋 다 포그라운드로 돈다.

set -euo pipefail

# ── UTF-8 고정 ───────────────────────────────────────────────────────
# Pi 는 보통 C.UTF-8 이지만 systemd 나 cron 에서 부르면 LANG 이 비어 있다.
# 그러면 파이썬이 ascii 로 stdout 을 열고 한글 로그에서 UnicodeEncodeError 가 난다.
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # IoT/PI
SCHEMA="$ROOT/../../database/pi.sql"
SHIP_FILE="$ROOT/.ship_id"
cd "$ROOT"

# 🔴 `uv run` 이어야 한다. 맨 python3 은 venv 밖이라 paho·fastapi 가 없다 —
#   "ModuleNotFoundError: No module named 'paho'" 로 죽는다. 실제 Pi 에서 밟았다.
#   uv 가 없는 환경이면 PYTHON=.venv/bin/python 으로 덮을 수 있다.
# ⚠ 배열이다. `PY="uv run python"` 을 `"${PY[@]}"` 로 쓰면 그 전체가 **한 명령어 이름**이
#   되어 "command not found" 가 난다.
if [ -n "${PYTHON:-}" ]; then
    PY=("$PYTHON")
else
    PY=(uv run python)
fi

die() { echo "$*" >&2; exit 1; }

# ship_id 는 **DB 가 정본**이다. 서버가 발급한 값이라 여기서 만들지 않는다.
# (.ship_id 파일은 로컬 발급 시절의 잔재다. 있으면 읽어주되 우선순위는 DB 다.)
ship_id() {
    local v=""
    if [ -f floaq.db ] && command -v sqlite3 >/dev/null; then
        v="$(sqlite3 floaq.db 'SELECT ship_id FROM pi_ship WHERE is_deleted = 0 LIMIT 1' 2>/dev/null || true)"
    fi
    if [ -z "$v" ] && [ -f "$SHIP_FILE" ]; then
        v="$(tr -d '[:space:]' < "$SHIP_FILE")"
    fi
    [ -n "$v" ] || die "등록된 배가 없다. 먼저:  uv run main.py  (등록 모드) 후 POST /api/ship"
    echo "$v"
}

cmd_reset() {
    # 🔴 **선박 키가 같이 날아간다.** pi_credential 이 DB 안에 있고, 서버는 같은
    #   registration_no 로 다시 등록해도 ship_key 를 **다시 주지 않는다**(실측:
    #   재전송이면 200 + ship_key: null). 그 배는 영영 EC2 에 못 붙는다.
    #
    #   그래서 초기화 뒤에는 **새 registration_no 로** 등록해야 한다.
    local ship=""
    if [ -f floaq.db ]; then
        ship="$(sqlite3 floaq.db 'SELECT ship_id FROM pi_credential LIMIT 1' 2>/dev/null || true)"
    fi
    if [ -n "$ship" ]; then
        echo "경고: 선박 키가 지워진다 (ship_id $ship)." >&2
        echo "      서버는 같은 등록번호로 키를 다시 주지 않는다." >&2
        echo "      초기화 뒤에는 **새 등록번호**로 등록할 것." >&2
        printf "      계속하려면 'yes' 입력: " >&2
        read -r ans
        [ "$ans" = "yes" ] || die "취소했다"
    fi

    "$0" stop >/dev/null 2>&1 || true
    sleep 0.5
    rm -f floaq.db floaq.db-wal floaq.db-shm
    rm -f floaq.db.pending-ship.json floaq.db.pending-ship.json.part
    rm -f .ship_id .aid
    rm -rf data
    echo "지웠다: DB · 등록 대기 · 프레임(data/)"
    echo "⚠ .env 는 그대로 둔다 (등록 키)"
    echo
    echo "다음:"
    echo "  ./scripts/dev.sh broker           별도 터미널"
    echo "  uv run main.py                    등록 모드로 뜬다"
    echo "  curl -X POST http://localhost:8000/api/ship -H 'Content-Type: application/json' \\"
    echo "    -d '{\"name\":\"Pi Demo\",\"registration_no\":\"pi-$(date +%m%d%H%M)\",\"mmsi\":\"440222201\",\"has_buoy\":true}'"
}

cmd_broker() {
    command -v mosquitto >/dev/null || die "mosquitto 가 없다.  sudo apt install mosquitto mosquitto-clients"
    # ⚠ apt 로 깔면 systemd 서비스가 자동으로 뜬다. 1883 을 먼저 잡아서 우리 conf 가 무시된다.
    #   sudo systemctl stop mosquitto && sudo systemctl disable mosquitto
    if systemctl is-active --quiet mosquitto 2>/dev/null; then
        echo "경고: mosquitto 서비스가 돌고 있다. 우리 conf 가 무시되고 9001 이 안 열린다." >&2
        echo "  sudo systemctl stop mosquitto && sudo systemctl disable mosquitto" >&2
    fi
    echo "브로커 기동  1883(TCP) + 9001(WebSocket)"
    exec mosquitto -c mosquitto.conf -v
}

cmd_pi() {
    # --ship-id 를 주지 않는다. main.py 가 DB 에서 찾고, 없으면 등록 모드로 뜬다.
    # --fake-hw: 발사 장치만 가짜다(FakeLauncher). 실제로 발사되지 않는다.
    #
    # 🔴 --lora fake 가 기본이다. **실물 부표를 받으려면 덮어써야 한다** —
    #    안 덮으면 가짜 부표가 1Hz 로 기록되고, 진짜 부표는 읽지도 않는다.
    #    같은 이유로 --report 도 기본이 fake 라 조난신고가 안 나간다.
    #
    #      ./scripts/dev.sh pi --lora serial --imu i2c --report udp     #                          --report-host <OpenCPN PC>
    #
    #    "$@" 가 뒤에 오므로 argparse 가 나중 값을 쓴다 — 덮어쓰기가 그대로 먹는다.
    # bash 의 tee 는 stderr 를 그냥 텍스트로 다룬다(PowerShell 과 달리 에러로 감싸지 않는다).
    # 다만 양쪽 동작을 맞추려고 여기서도 파이썬이 직접 파일에 쓰게 한다.
    echo "오케스트레이터 기동 (로그는 pi.log 에도 남는다)"
    # 🔴 `--fake-hw` 를 무조건 붙이면 `--servos` 를 줄 수 없다 — 둘은 배타다.
    #    실장비를 직접 고른 경우에는 빼고, 안 고르면 가짜를 기본으로 둔다.
    local hw=--fake-hw
    case " $* " in *" --servos "*|*" --aim-only-servos "*) hw= ;; esac
    # 🔴 실장비를 고르면 조준 보정도 같이 준다. 안 주면 main.py 기본값이라
    #    ±15° 까지만 돌고 그 밖은 "outside the calibrated range" 로 버려진다.
    #    전에는 이 분기가 추가 인자를 통째로 버려서 항상 --fake-hw 였고,
    #    그래서 이 문제가 드러나지 않았다 (2026-09-22).
    local cal=
    if [ -z "$hw" ]; then
        case " $* " in
            *" --yaw-cal"*) ;;
            *) cal="--yaw-cal=-45:123.75 --yaw-cal=0:90 --yaw-cal=45:56.25" ;;
        esac
    fi
    FLOAQ_LOG_FILE=pi.log "${PY[@]}" main.py $hw $cal --lora fake -v "$@"
}

cmd_aim() {
    # 기존 수동 서보 스크립트 대신 Jetson의 jetson/aim을 받아 CH0/CH1만 움직인다.
    # 🔴 실장비의 기본은 발사다. 시험이라 --no-fire 를 여기서 붙인다.
    echo "시험: 자동 조준 전용 기동 (CH0 yaw, CH1 pitch, 발사 비활성)"
    FLOAQ_LOG_FILE=pi.log "${PY[@]}" main.py \
        --servos --no-fire --gps fake --lora fake --offline -v "$@"
}

cmd_aim_fire() {
    echo "자동 조준+1회 발사 기동 (CH0 yaw, CH1 pitch, CH2 plus)"
    FLOAQ_LOG_FILE=pi.log "${PY[@]}" main.py \
        --servos --gps fake --lora fake -v \
        --yaw-cal=-45:123.75 --yaw-cal=0:90 --yaw-cal=45:56.25 \
        "$@"
}

cmd_sub() {
    local ship; ship="$(ship_id)"
    command -v mosquitto_sub >/dev/null || die "mosquitto_sub 가 없다.  sudo apt install mosquitto-clients"
    echo "구독  ship/$ship/#"
    exec mosquitto_sub -t "ship/$ship/#" -v
}

cmd_detect() {
    # 거부 경로도 볼 수 있다: --no-solution / --bad-angle / --bad-profile / --stale
    "${PY[@]}" tools/fake_jetson.py --ship-id "$(ship_id)" "$@"
}

cmd_close() {
    # E1 때문에 앞 사고가 열려 있으면 새 탐지가 409 로 거부된다.
    # 반복 시험을 하려면 매번 닫아야 한다.  --rescue 로 구조 확정 처리도 된다.
    "${PY[@]}" tools/close_accident.py "$@"
}

cmd_kiosk() {
    # 개발용 키오스크. ws://localhost:9001 로 붙는다 — 브라우저는 raw TCP 를 못 연다.
    # 계약을 먼저 뽑는다. 키오스크가 이걸 읽어 토픽·유효명령을 채운다.
    "${PY[@]}" -m floaq.contracts -o tools/contract.json
    echo "브라우저에서 SHIP_ID 입력:  $(ship_id)"
    xdg-open "$ROOT/tools/kiosk.html" 2>/dev/null || echo "직접 열기: $ROOT/tools/kiosk.html"
}

cmd_lora_b() {
    # LoRa 수신기 역할. 먼저 띄운다. 라디오 없이 UDP 로 돈다.
    # 실물이 오면:  ./scripts/dev.sh lora-b --link serial --port /dev/ttyUSB0
    "${PY[@]}" -u tools/lora_ab.py b "$@"
}

cmd_lora_a() {
    # LoRa 송신기 역할(부표). --drop 0.2 로 유실을 흉내낼 수 있다.
    "${PY[@]}" -u tools/lora_ab.py a "$@"
}

cmd_distress() {
    # 조난 신고를 UDP 로 내보낸다. OpenCPN 등에서 확인용.
    #   OpenCPN: Options > Connections > Add > Network > UDP, 0.0.0.0 : 10110
    # ⚠ 실제 조난 신고가 아니다. 목적지를 확인할 것.
    "${PY[@]}" -u tools/distress_send.py "$@"
}

cmd_status() {
    echo
    echo "── 리스너 ──"
    if command -v ss >/dev/null; then
        ss -ltnp 2>/dev/null | grep -E ':1883|:9001' || echo "  없음"
    else
        netstat -ltnp 2>/dev/null | grep -E ':1883|:9001' || echo "  없음"
    fi
    echo
    echo "── 프로세스 ──"
    pgrep -af 'mosquitto.conf|main\.py' || echo "  없음"
    echo
    [ -f "$SHIP_FILE" ] && echo "SHIP_ID  $(ship_id)"
    echo
}

cmd_stop() {
    # 🔴 예전 패턴은 'main\.py --ship-id' 였는데 cmd_pi 는 --ship-id 를 안 준다
    #    (DB 에서 찾는다). 그래서 **한 번도 안 죽었다** — "종료 완료" 를 찍고
    #    프로세스는 살아 있었고, 이어서 reset -> pi 하면 :8000 바인드 충돌과
    #    같은 client_id 두 개의 재접속 루프가 났다 (2026-09-22 전수검사).
    #    demo-reset.sh 는 처음부터 'main.py' 만 봤다 — 그쪽이 맞다.
    pkill -f 'main\.py' 2>/dev/null && echo "  종료  main.py" || true
    pkill -f 'mosquitto -c mosquitto.conf' 2>/dev/null && echo "  종료  mosquitto" || true
    echo "종료 완료"
}

cmd_help() {
    cat <<'EOF'

FloaQ Pi 개발 스크립트

  ./scripts/dev.sh reset     DB 새로 만들고 SHIP_ID 발급
  ./scripts/dev.sh broker    mosquitto 기동      (별도 창)
  ./scripts/dev.sh pi        오케스트레이터 기동  (별도 창)
                             --servos 면 실장비, 🔴 기본이 발사
  ./scripts/dev.sh aim       시험: 실제 CH0/CH1 조준만 (CH2 안 엶, 별도 창)
  ./scripts/dev.sh aim-fire  자동 조준 후 CH2 plus 1회
  ./scripts/dev.sh sub       메시지 덤프         (별도 창)
  ./scripts/dev.sh detect    가짜 탐지 1회
  ./scripts/dev.sh kiosk     개발용 키오스크 열기 (ws://9001)
  ./scripts/dev.sh lora-b    LoRa 수신 검증      (별도 창, 먼저 띄움)
  ./scripts/dev.sh lora-a    LoRa 송신 검증      (별도 창)
  ./scripts/dev.sh distress  조난 신고 UDP 송출   (DSC + AIS)
  ./scripts/dev.sh status    상태 확인
  ./scripts/dev.sh stop      전부 종료

처음이면:
  1) 새 창에서 broker
  2) 새 창에서 pi        (배가 없으면 등록 모드로 뜬다)
  3) POST /api/ship     키오스크나 curl 로 선박 등록
  4) 새 창에서 sub
  5) detect

반복 시험:
  close  ->  detect      E1 때문에 앞 사고를 닫아야 새 탐지가 받아진다

EOF
}

case "${1:-help}" in
    reset)  cmd_reset ;;
    broker) cmd_broker ;;
    pi)     shift; cmd_pi "$@" ;;
    aim)    shift; cmd_aim "$@" ;;
    aim-fire) shift; cmd_aim_fire "$@" ;;
    sub)    cmd_sub ;;
    detect) shift; cmd_detect "$@" ;;
    close)  shift; cmd_close "$@" ;;
    lora-a) shift; cmd_lora_a "$@" ;;
    lora-b) shift; cmd_lora_b "$@" ;;
    distress) shift; cmd_distress "$@" ;;
    kiosk)  cmd_kiosk ;;
    status) cmd_status ;;
    stop)   cmd_stop ;;
    *)      cmd_help ;;
esac

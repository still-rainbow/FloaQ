#!/usr/bin/env bash
# 모든 스크립트가 맨 앞에서 source 한다. 직접 실행하지 않는다.

set -euo pipefail

# ── UTF-8 고정 ───────────────────────────────────────────────────────
# ⚠ systemd·cron 에서 부르면 LANG 이 비어 있다. 그러면 파이썬이 ascii 로 stdout 을
#   열고 한글 로그 첫 줄에서 UnicodeEncodeError 로 죽는다. Pi 쪽 dev.sh 와 같은 이유다.
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # IoT/JetSon
cd "$ROOT"

# 🔴 JetPack 인터프리터를 명시한다. pyproject 가 python-preference = only-system 이라
#   uv 가 다운로드하지 않는데, 경로를 안 주면 다른 3.10 을 집을 수 있다.
JETPACK_PY="${JETPACK_PY:-/usr/bin/python3.10}"

die() { echo "$*" >&2; exit 1; }

# Pi 주소. 인자 > 환경변수 > .env 순.
pi_host() {
    if [ -n "${1:-}" ]; then echo "$1"; return; fi
    if [ -n "${FLOAQ_PI:-}" ]; then echo "$FLOAQ_PI"; return; fi
    if [ -f "$ROOT/.env" ]; then
        local v; v="$(grep -E '^FLOAQ_PI=' "$ROOT/.env" | tail -1 | cut -d= -f2-)"
        [ -n "$v" ] && { echo "$v"; return; }
    fi
    die "Pi 주소가 없다.  ./scripts/$(basename "$0") <pi주소>  또는  FLOAQ_PI=... 로 줄 것"
}

# 첫 인자가 Pi 주소인지 옵션인지 가른다. 주소면 먹고 $PI 에 담는다.
#
# 🔴 그냥 `$1` 을 주소로 쓰면 `./scripts/live.sh --camera L=2,R=0` 이
#   "Pi 주소 = --camera" 가 되고, 남은 `L=2,R=0` 이 argparse 에 위치 인자로
#   들어가 usage 만 뱉고 죽는다. 실제로 밟았다.
#
# 쓰는 쪽:  eval "$(take_pi "$@")"   -> $PI 가 서고 인자가 shift 된다
take_pi() {
    local v
    if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
        # ⚠ `pi_host` 의 die 는 `$( )` 안에서 죽으므로 **바깥 스크립트가 안 멈춘다.**
        #   빈 PI 로 계속 가면 argparse 가 엉뚱한 곳에서 터진다. exit 를 흘려보낸다
        v="$(pi_host "$1")" || { printf 'exit 1
'; return; }
        printf 'PI=%q; shift 1
' "$v"
    else
        v="$(pi_host "")" || { printf 'exit 1
'; return; }
        printf 'PI=%q
' "$v"
    fi
}

# Pi 의 시계로 젯슨 시계를 맞춘다.
#
# 🔴 **젯슨에는 RTC 배터리가 없고 이 망은 UDP 123 을 막는다.** NTP 가 영영 안 붙어서
#    (`systemd-timesyncd` 는 active 인데 `synchronized: no`) 시계가
#    `1970-01-01 + 업타임` 에서 시작한다. 그 값이 `detected_at` 으로 Pi 에 실려
#    `pi_accident.created_at` 에 박히고 EC2 까지 올라갔다 — 2026-09-22 관제에서
#    `1970-01-01T01:29:34Z` 로 확인했다(업타임 1:29:34). Pi 17건 중 3건이 그랬다.
#
# Pi 는 GPS UTC 를 쓰므로 시각이 맞다. HTTP `Date` 헤더로 받는다 — 80/443 만 열려
# 있으면 되고, 초 단위면 우리 용도엔 충분하다(표류 경과는 초, 프레임 5fps).
#
# ⚠ **실패해도 멈추지 않는다.** 시계가 틀려도 익수자는 감지해야 한다. Pi 쪽
#   `orchestrator._stamp` 가 이상한 시각을 자기 GPS 시계로 갈아 끼우므로, 여기는
#   그 보정이 필요 없게 만드는 1차 방어다.
# ⚠ `sudo -n` 이다. 비밀번호를 물으면 그냥 넘어간다 — 자동 실행이 프롬프트에서
#   멈춰 서면 시연이 통째로 선다. 대신 사람이 칠 명령을 찍어 준다.
sync_clock() {
    local host="$1" hdr
    # 이미 맞으면 건드리지 않는다. sudo 를 매번 부를 이유가 없다
    if [ "$(date -u +%s)" -gt 1757000000 ]; then return 0; fi

    hdr="$(curl -sI --max-time 5 "http://$host:8000/health" | grep -i '^date:' | cut -d' ' -f2- | tr -d '\r')" || true
    if [ -z "$hdr" ]; then
        echo "[경고] 시계가 1970 인데 Pi($host) 가 답을 안 한다. 그대로 간다" >&2
        return 0
    fi

    echo "시계가 1970 이다. Pi($host) 시각으로 맞춘다: $hdr" >&2
    if sudo -n date -s "$hdr" >/dev/null 2>&1; then
        sudo -n hwclock -w >/dev/null 2>&1 || true
        echo "  -> $(date)" >&2
    else
        echo "  sudo 가 비밀번호를 원한다. 직접 실행할 것:" >&2
        echo "    sudo date -s \"$hdr\" && sudo hwclock -w" >&2
    fi
}

# venv 가 있으면 쓰고, 없으면 uv 가 알아서 만들게 둔다.
run_py() {
    if [ -x "$ROOT/.venv/bin/python" ]; then
        "$ROOT/.venv/bin/python" "$@"
    else
        uv run --python "$JETPACK_PY" python "$@"
    fi
}

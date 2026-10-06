#!/usr/bin/env bash
# 실제 카메라 + 추론 + Pi 업로드. **시연에서 쓰는 것이 이것이다.**
#
#   ./scripts/live.sh 127.0.0.1
#   FLOAQ_PI=127.0.0.1 ./scripts/live.sh
#   ./scripts/live.sh 127.0.0.1 --detect-frames 3      판정을 느슨하게
#   ./scripts/live.sh 127.0.0.1 --fov 0                조준 해 없이
#   ./scripts/live.sh 127.0.0.1 --dry-run              판정만, Pi 로 안 보냄
#   ./scripts/live.sh 127.0.0.1 --aim                  스테레오 조준만 (사고 안 만듦)
#   ./scripts/live.sh 127.0.0.1 --aim-detect           조준 + 탐지·사진·신고 (시연)
#   ./scripts/live.sh 127.0.0.1 --test                 AI 없이 30초분 올리기
#   ./scripts/live.sh 127.0.0.1 --test 45              45초분
#
# 사슬:
#
#   카메라 --5fps--> 추론 --매 프레임--> Judge (AI-02)
#      |                                    |
#      +--> 링버퍼 (앞 15초)           승격하면 탐지 발행
#                                           |
#                                   Pi 가 사고를 만들고
#                                   앞 15초 + 뒤 10초가 올라간다
#
# 🔴 **Pi 를 먼저 띄운다.** ship_id 를 Pi 의 /health 에서 가져오고 브로커도 Pi 에 있다.
#
# 🔴 **배 GPS 가 없으면 탐지를 안 올린다.** Jetson 에 GPS 가 없어서 Pi 가 1Hz 로
#    뿌리는 `pi/sensor/gps` 를 받아 쓴다. 좌표를 지어내면 구조대가 그 좌표로 간다.
#    Pi 를 `--gps fake` 로라도 띄워야 한다.
#
# ⚠ 판정 임계값은 `미정`이다 (docs/mqtt.md §7 항목 10, AI팀). 기본값은 자리만
#   잡아 둔 것이라 실제 모델·바다 장면으로 재야 한다.
#
# `--aim` / `--aim-detect` 는 좌우 원본 bbox 중심을 삼각측량해 거리·yaw·pitch 를 낸다
# (rectification 을 쓰지 않는다 — `_stereo_aiming.triangulate_raw_bboxes`).
# 🔴 `--aim-detect` 는 **같은 실행에서 탐지·사진·신고까지 한다.** 전에는 조준 시연과
#    신고 시연을 두 번 나눠 돌렸다.
# ⚠ 여기 인자는 발사를 막지 못한다. 발사는 Pi 가 정한다 (`--servos` 면 쏜다,
#   `--no-fire` 면 안 쏜다).

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

eval "$(take_pi "$@")"

# 🔴 탐지 시각이 1970 으로 찍히는 것을 여기서 막는다 (_common.sh sync_clock)
sync_clock "$PI"

# ⚠ 기본값을 여기 두고 "$@" 를 뒤에 붙인다. 뒤에 오는 것이 앞을 덮으므로
#   `./scripts/live.sh <pi> --fov 0` 같은 덮어쓰기가 그대로 먹는다.
# 🔴 video2 가 **왼쪽**, video0 이 **오른쪽** 카메라다. 2026-09-23 에 발사관 뒤에서
#    오른쪽 렌즈를 손으로 가렸더니 video0 화면이 가려졌다. 전 기본값 L=0,R=2 는
#    좌우가 바뀌어 있어서 두 시선이 앞에서 안 만나 `no stereo intersection` 이 났다.
CAMERA="${FLOAQ_CAMERA:-L=2,R=0}"
# 🔴 저장소에 있는 모델은 `best_performance.pt` 하나다. 전에 여기 적혀 있던
#    `best.pt` 는 **존재하지 않는 파일**이라 아래 if 가 `--weights` 를 빼 버렸고,
#    그러면 `--aim-only` 가 "`--camera`와 `--weights`가 필요하다" 로 즉사했다.
WEIGHTS="${FLOAQ_WEIGHTS:-../../ai/models/best_performance.pt}"
FOV="${FLOAQ_FOV:-60}"
# 🔴 `best_performance.pt` 의 클래스는 animal=0, fish=1, float=2, **person=3** 이다
#    (`ai/models/README.md`). `__main__.py` 의 기본값 0 은 COCO 기준이라 이 모델에서는
#    **동물**이다 — 그대로 두면 사람을 영영 못 잡고 탐지가 0 건이다.
CLS="${FLOAQ_CLS:-3}"

if [ ! -f "$WEIGHTS" ]; then
    echo "[경고] 모델이 없다: $WEIGHTS" >&2
    echo "        추론 없이 프레임만 흐른다 — 탐지는 안 난다." >&2
    echo "        FLOAQ_WEIGHTS=/경로/best.pt 로 지정할 것" >&2
    echo
    set -- --camera "$CAMERA" --fov "$FOV" "$@"
else
    set -- --camera "$CAMERA" --weights "$WEIGHTS" --cls "$CLS" --fov "$FOV" "$@"
fi

echo "Pi        $PI"
echo "카메라     $CAMERA"
[ -f "$WEIGHTS" ] && echo "모델      $WEIGHTS  (cls=$CLS)"
echo "화면      http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080/"
echo
run_py -m floaq_jetson --pi "$PI" "$@"

#!/usr/bin/env bash
# 카메라 스트림 서버만 띄운다. Pi 도 카메라도 필요 없다.
#
#   ./scripts/stream.sh --camera 0,1      실제 카메라 두 대
#   ./scripts/stream.sh --camera 0          한 대
#   ./scripts/stream.sh --camera 0,1 --weights /path/to/best.pt  모델 검출 상자
#   ./scripts/stream.sh                     시험 패턴 (카메라 없이)
#
# 카메라 번호는 `ls /dev/video*` 로 확인한다. CSI 카메라가 인덱스로 안 열리면
# GStreamer 파이프라인을 준다:
#   ./scripts/stream.sh --camera 'L=nvarguscamerasrc sensor-id=0 ! ... ! appsink'
#
# 카메라를 붙이기 전에 키오스크·Pi 에서 이 포트가 보이는지 확인하는 용도다.
# 여기서 안 보이면 원인이 네트워크·방화벽이고, 보이면 카메라 쪽이다.
#
# ⚠ 시험 패턴이 흐른다. 실제 카메라 영상이 아니다.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

echo "브라우저에서 열기:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080/"
echo
run_py -m floaq_jetson --stream-only "$@"

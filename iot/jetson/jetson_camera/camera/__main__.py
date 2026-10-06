#!/usr/bin/env python3
"""CLI — IOT-01 / Jira floaq-18

  # 실물 스테레오
  python -m camera --left /dev/video0 --right /dev/video2

  # 카메라 없이 파이프라인만 확인
  python -m camera --left synthetic --right synthetic --seconds 10

  # 장치 확인
  v4l2-ctl --list-devices
  v4l2-ctl -d /dev/video0 --list-formats-ext
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from .config import CameraConfig, ServiceConfig, config_from_env
from .service import CaptureService, install_signal_handlers


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="camera", description="FloaQ 실시간 영상 촬영")
    p.add_argument("--left", default=None, help="왼쪽 장치 (/dev/video0 | 0 | synthetic)")
    p.add_argument("--right", default=None, help="오른쪽 장치. 'none' 이면 단안 운용")
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--capture-fps", type=float, default=None)
    p.add_argument("--publish-fps", type=float, default=None, help="기본 5 (DES-31 C-8)")
    p.add_argument("--quality", type=int, default=None, help="JPEG 품질 (기본 85)")
    p.add_argument("--endpoint", default=None, help="ZMQ 바인드 주소")
    p.add_argument("--max-skew-ms", type=float, default=None)
    p.add_argument("--seconds", type=float, default=None, help="이 시간 뒤 자동 종료 (시험용)")
    p.add_argument("--stats-interval", type=float, default=None)
    p.add_argument("--verbose", action="store_true")
    return p


def apply_args(cfg: ServiceConfig, args: argparse.Namespace) -> ServiceConfig:
    if args.left:
        cfg.left.device = args.left
    if args.right is not None:
        cfg.right = None if args.right.lower() == "none" else CameraConfig(
            cam_id="right", device=args.right,
        )
    for cam in cfg.cameras:
        if args.width:
            cam.width = args.width
        if args.height:
            cam.height = args.height
        if args.capture_fps:
            cam.capture_fps = args.capture_fps
    if args.publish_fps is not None:
        cfg.publish_fps = args.publish_fps
    if args.quality is not None:
        cfg.jpeg_quality = args.quality
    if args.endpoint:
        cfg.endpoint = args.endpoint
    if args.max_skew_ms is not None:
        cfg.max_skew_ms = args.max_skew_ms
    if args.stats_interval is not None:
        cfg.stats_interval_s = args.stats_interval
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    )

    cfg = apply_args(config_from_env(), args)
    service = CaptureService(cfg)
    install_signal_handlers(service)

    if args.seconds:
        # 지정 시간 뒤 정상 종료. 종료 통계를 남기려면 kill 이 아니라
        # 정상 경로로 빠져나와야 한다.
        threading.Timer(args.seconds, service.request_stop).start()

    try:
        service.run()
    except Exception:
        logging.getLogger("floaq.camera").exception("촬영 서비스 비정상 종료")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

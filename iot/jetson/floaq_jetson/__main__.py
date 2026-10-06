"""배선 확인용 CLI. `python -m floaq_jetson --pi <주소>`

AI 코드를 붙이기 **전에** 이걸로 Pi 와의 경로가 살아 있는지 본다. 카메라도 모델도
없이 돌기 때문에, 여기서 안 되면 원인이 우리 쪽이고 여기서 되면 AI 쪽이다.

    python -m floaq_jetson --pi 192.168.0.10            탐지 한 번 + 프레임 25장
    python -m floaq_jetson --pi 192.168.0.10 --no-aim   조준 해 없이 (NO_SOLUTION)
    python -m floaq_jetson --pi 192.168.0.10 --watch    상태만 지켜보기
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from pathlib import Path

from . import FRAME_FPS, FRAME_POST_SEC, FRAME_PRE_SEC, Floaq, InvalidCall
from ._detect import COOLDOWN_SEC as DET_COOLDOWN
from ._detect import CONF_MIN as DET_CONF
from ._detect import NEED_FRAMES as DET_FRAMES
from ._detect import AimTrigger

#: 최소 JPEG. 실제 이미지가 아니어도 경로 확인에는 충분하다.
FAKE = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" \
       + b"\x00" * 512 + b"\xff\xd9"

#: 부산 앞바다. Pi 의 가짜 GPS 기본값과 같은 자리다.
LAT, LON = 35.0500, 129.1000

#: `--test` 기본 길이(초). 앞 구간 + 뒤 구간을 합친 값이다.
TEST_SEC = 30.0

#: 업로드 진도가 이만큼 없으면 포기한다. 느린 것과 멈춘 것을 가른다.
STUCK_SEC = 15

#: 큐를 비운 뒤 업로드 스레드를 기다리는 시간(초).
#: 🔴 그 스레드는 daemon 이라 프로세스가 끝나면 같이 죽는다. 짧게 잡으면
#:   마지막 몇 장이 조용히 사라진다.
CLOSE_WAIT_SEC = 30.0


def _stream_only(args) -> int:
    """`:8080` 만 띄운다. `--camera` 를 주면 실제 카메라, 없으면 시험 패턴.

    카메라를 붙이기 전후에 경로가 사는지 눈으로 보는 용도다. 여기서 안 보이면
    원인이 네트워크·방화벽이고, 보이면 카메라 쪽이다.
    """
    from ._stream import StreamServer

    srv = StreamServer(args.stream_port)
    if not srv.start():
        print(f"[실패] :{args.stream_port} 를 못 열었다", file=sys.stderr)
        return 2
    print(f"스트림  http://0.0.0.0:{args.stream_port}/")

    cap = None
    inference = None
    if args.camera:
        from ._capture import Capture, parse_sources

        on_frame = srv.put
        if args.weights:
            from ._inference import InferenceStream

            try:
                inference = InferenceStream(
                    srv.put, weights=args.weights, imgsz=args.imgsz,
                    conf=args.conf, device=args.device, quality=args.quality)
            except Exception as e:
                srv.stop()
                print(f"[실패] 모델을 불러올 수 없다: {e}", file=sys.stderr)
                return 2
            inference.start()
            on_frame = inference.submit

        sources = parse_sources(args.camera)
        cap = Capture(sources, fps=args.fps, quality=args.quality,
                      width=args.width, height=args.height)
        n = cap.start(on_frame)
        if n == 0:
            if inference is not None:
                inference.stop()
            srv.stop()
            print("[실패] 카메라를 하나도 못 열었다. `ls /dev/video*` 로 확인할 것",
                  file=sys.stderr)
            return 2
        print(f"카메라 {n}대: {', '.join(cap.opened)}  ({args.fps}fps)")
    else:
        print("[경고] 시험 패턴이다. 실제 카메라 영상이 아니다. "
              "--camera 0,1 로 실제 카메라를 열 것")

    print("Ctrl+C 로 종료")
    try:
        n = 0
        while True:
            if cap is None:
                # 프레임이 흐르는지 눈으로 보려고 매 장 조금씩 바꾼다.
                # 정지 이미지면 "스트림이 멈춘 것"과 구분이 안 된다.
                for name in ("L", "R"):
                    srv.put(FAKE + bytes([n % 251]), name)
                n += 1
            time.sleep(1.0 / max(1, args.fps))
    except KeyboardInterrupt:
        return 0
    finally:
        if cap is not None:
            cap.stop()
        if inference is not None:
            inference.stop()
        srv.stop()


def _live(args) -> int:
    """실제 카메라 + 추론 + Pi 업로드. **시연에서 쓰는 경로다.**

        python -m floaq_jetson --pi 127.0.0.1 --camera L=2,R=0             --weights ../../ai/models/best.pt --fov 60

    사슬:

        카메라 --5fps--> 추론 --매 프레임--> Judge (AI-02)
           |                                    |
           +--> fq.frame() (링버퍼)        승격하면 fq.detected()
                                                |
                                        Pi 가 사고를 만들고
                                        앞 15초 + 뒤 10초가 올라간다

    🔴 **좌표는 배 GPS 에서 온다.** Jetson 에 GPS 가 없어서 Pi 가 1Hz 로 뿌리는
       `pi/sensor/gps` 를 받아 쓴다. 그게 없으면 탐지를 **안 올린다** — 좌표를
       지어내면 구조대가 그 좌표로 간다.

    ⚠ `distance_m` 과 조준 해는 아직 어림값이다. 스테레오 거리(AI-03)가 붙기
      전까지 `--distance` 고정값이고, yaw 는 `--fov` 를 주면 bbox 가로 위치로
      어림한다. `--fov` 를 안 주면 조준 해 없이 보내고 Pi 가 NO_SOLUTION 으로
      기록한다 — 탐지 자체는 유효하다.
    """
    from ._capture import Capture, parse_sources
    from ._detect import Judge

    try:
        fq = Floaq(args.pi, ship_id=args.ship_id, mqtt_port=args.mqtt_port,
                   http_port=args.http_port, fps=args.fps,
                   pre_sec=args.pre_sec, post_sec=args.post_sec,
                   stream_port=args.stream_port,
                   model_version=Path(args.weights).stem if args.weights else "none")
    except InvalidCall as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 2

    print(f"ship_id  {fq.ship_id}")
    if not fq.start(timeout=5.0):
        print("[경고] MQTT 에 아직 못 붙었다. 재접속은 계속한다", file=sys.stderr)

    judge = Judge(conf_min=args.detect_conf, need_frames=args.detect_frames,
                  cooldown_sec=args.detect_cooldown)
    # 🔴 --aim-detect: 사고 등록 = 발사 조건 (`_detect.AimTrigger`). judge 는 안 쓴다
    trigger = AimTrigger(cooldown_sec=args.detect_cooldown)
    stable_frames = 1
    if args.aim_detect:
        import yaml
        with Path(args.aim_config).open(encoding="utf-8") as fh:
            stable_frames = int(yaml.safe_load(fh)["stability"]["sample_count"])
    if args.aim_only or args.aim_detect:
        print("[스테레오 조준] 좌우 카메라로 거리·yaw·pitch를 계산한다")
        print("  탐지·사진·신고까지 한다" if args.aim_detect
              else "  jetson/aim 만 보낸다. 사고·사진·신고는 안 만든다")
        print("  ⚠ 발사 여부는 Pi 가 정한다 — Pi 가 --servos 면 쏜다 (--no-fire 면 안 쏜다)")
    if args.dry_run:
        print("[안 보냄 모드] 판정만 한다. Pi 에 사고가 안 생기고 프레임도 안 올라간다")
    if args.test is None and args.aim_detect:
        print("판정  사고 등록 = 발사 조건 — 스테레오 조준을 보낸 순간에만 올린다"
              f"  (좌우 둘 다·3m 안·{stable_frames}쌍 안정, 쿨다운 {args.detect_cooldown:g}초)")
    elif args.test is None:
        print(f"판정  신뢰도 {args.detect_conf} 이상이 {args.detect_frames}프레임 연속"
              f"  (쿨다운 {args.detect_cooldown:g}초)  [미정값 - AI팀]")
    else:
        # 🔴 시험 모드는 AI 판정을 **아예 안 쓴다.** 둘을 같이 돌리면 어느 쪽이
        #   쏜 탐지인지 못 가리고, E1 때문에 하나는 409 로 버려진다
        print(f"[시험] 판정 없이 {args.test:g}초분을 올린다"
              f"  앞 {args.pre_sec}초 + 뒤 {args.post_sec}초"
              f"  = 약 {int((args.pre_sec + args.post_sec) * args.fps)}장/대")

    state = {"width": 0, "height": 0, "shots": 0, "skipped_no_fix": 0,
             # 마지막으로 본 신뢰도. 0 만 찍히면 "왜 안 잡히나"를 못 가린다
             "conf": {}}

    def detect_on_aim(camera, jpeg, conf, bbox):
        """`--aim-detect`. 조준을 방금 보낸 프레임이면 그 해로 사고를 올린다."""
        if fq.accident_open() and not args.dry_run:
            trigger.reset()              # Pi 가 E1 으로 409 를 준다. 닫힌 뒤 새로 센다
            return
        got = trigger.take(conf, bbox, time.time())
        if got is None:
            return
        pointing, confidence = got
        fix = fq.ship_fix()
        if args.dry_run:
            state["shots"] += 1
            print(f"[안 보냄] {camera}  conf={confidence:.2f}  range={pointing.range_m:.2f}m"
                  f"  bbox={bbox}  좌표={'있음' if fix else '없음'}")
            return
        if fix is None:
            state["skipped_no_fix"] += 1
            if state["skipped_no_fix"] % 10 == 1:
                print("[경고] 배 GPS 가 없어 탐지를 안 올린다. "
                      "Pi 가 pi/sensor/gps 를 뿌리는지 확인할 것", file=sys.stderr)
            return
        aim = _aim_stereo(args, pointing, fix)
        det = fq.detected(lat=fix["lat"], lon=fix["lon"],
                          distance_m=pointing.range_m, confidence=confidence,
                          camera=camera, bbox=bbox, frame_count=stable_frames,
                          snapshot=jpeg, **aim)
        state["shots"] += 1
        print(f"탐지 발행  {det.detection_id}  {camera}  conf={confidence:.2f}"
              f"  range={pointing.range_m:.2f}m  (조준을 보낸 순간 = 발사 조건)"
              f"  published={det.published}")

    def on_detect(camera, jpeg, conf, bbox, pointing=None):
        """추론 스레드에서 불린다. **무거운 일을 하면 추론이 밀린다.**

        `pointing` 은 스테레오가 방금 낸 조준 해다. `InferenceStream`(단안)은
        주지 않으므로 기본값이 있어야 한다.
        """
        if args.test is not None:
            return                       # 시험 모드는 타이머가 쏜다
        state["conf"][camera] = None if conf is None else round(conf, 2)
        if args.aim_detect:
            # 🔴 카메라 한 대 판정(judge)·단안 어림값을 쓰지 않는다 — 사고 = 발사 조건
            detect_on_aim(camera, jpeg, conf, bbox)
            return
        if fq.accident_open() and not args.dry_run:
            # 🔴 사고가 열려 있으면 Pi 가 E1 으로 409 를 준다. 그걸 모르고 계속
            #   승격하면 쿨다운마다 프레임 200장을 만들었다 버린다. 연속 카운터도
            #   비워 둔다 — 사고가 닫힌 뒤 처음부터 세야 맞다
            judge.reset()
            return
        promo = judge.feed(camera, conf, bbox, time.time())
        if promo is None:
            return
        fix = fq.ship_fix()
        if args.dry_run:
            # 🔴 여기서 끝낸다. `detected()` 를 안 부르므로 Pi 에 사고가 안 생기고,
            #   프레임도 안 올라간다(업로드는 탐지 뒤에만 큐에 들어간다).
            #   임계값을 맞출 때 사고를 매번 닫지 않아도 된다.
            state["shots"] += 1
            print(f"[안 보냄] {promo.camera}  conf={promo.confidence:.2f}"
                  f"  {promo.frame_count}프레임  bbox={promo.bbox}"
                  f"  좌표={'있음' if fix else '없음'}")
            return
        if fix is None:
            # 🔴 좌표 없이 올리지 않는다. 한 번은 크게 알린다 - 조용하면
            #   "왜 탐지가 안 올라가지" 를 영영 못 찾는다
            state["skipped_no_fix"] += 1
            if state["skipped_no_fix"] % 10 == 1:
                print("[경고] 배 GPS 가 없어 탐지를 안 올린다. "
                      "Pi 가 pi/sensor/gps 를 뿌리는지 확인할 것", file=sys.stderr)
            return

        # 🔴 스테레오가 낸 해가 있으면 **그걸 쓴다.** `_aim` 은 화각 어림값이고,
        #    실제 발사 각도는 여기 실은 값이다(Pi 는 `det.launch` 로 쏜다).
        aim = (_aim_stereo(args, pointing, fix) if pointing is not None
               else _aim(args, promo, fix, state["width"]))
        # 🔴 잰 거리를 쓴다. 전에는 --distance 고정값(기본 15.0)을 올려서
        #    DB·EC2·키오스크가 전부 15.0 을 봤다 — 스테레오가 잰 값은 아무 데도
        #    안 갔다 (AimCommand 에도 거리 필드가 없다).
        distance = pointing.range_m if pointing is not None else args.distance
        det = fq.detected(lat=fix["lat"], lon=fix["lon"],
                          distance_m=distance, confidence=promo.confidence,
                          camera=promo.camera, bbox=promo.bbox,
                          frame_count=promo.frame_count, snapshot=jpeg, **aim)
        state["shots"] += 1
        print(f"탐지 발행  {det.detection_id}  {promo.camera}"
              f"  conf={promo.confidence:.2f}  {promo.frame_count}프레임"
              f"  published={det.published}  aim={'있음' if aim else '없음'}")

    on_frame = None
    inference = None
    if args.aim_only or args.aim_detect:
        from ._stereo_aiming import StereoAimStream

        def on_stereo_aim(pointing, confidence):
            sent = fq.aim(yaw=pointing.yaw_deg, pitch=pointing.pitch_deg,
                          confidence=confidence)
            print(f"스테레오 조준 conf={confidence:.2f} range={pointing.range_m:.2f}m "
                  f"yaw={pointing.yaw_deg:+.2f}° pitch={pointing.pitch_deg:+.2f}° "
                  f"sent={sent}")
            # 🔴 Pi 가 쏘는 것은 이 조준이 **닿았을 때**다. 안 나간 조준으로는 사고도 안 만든다
            if sent and args.aim_detect:
                trigger.aim_sent(pointing, confidence)

        try:
            inference = StereoAimStream(
                lambda jpeg, cam, size=None: _feed(fq, state, jpeg, cam, size),
                on_aim=on_stereo_aim,
                weights=args.weights,
                config_path=args.aim_config,
                imgsz=args.imgsz,
                conf=args.conf,
                device=args.device,
                quality=args.quality,
                cls=args.cls,
                # 🔴 `--aim-detect` 일 때만 붙인다. `--aim-only` 는 예전 그대로
                #    조준만 한다 — 사고도 사진도 신고도 안 만든다.
                on_detect=on_detect if args.aim_detect else None,
            )
        except Exception as e:
            fq.close()
            print(f"[실패] 스테레오 조준 초기화 실패: {e}", file=sys.stderr)
            return 2
        inference.start()
        on_frame = inference.submit
        _report_classes(inference, args.cls)
    elif args.weights:
        from ._inference import InferenceStream
        try:
            inference = InferenceStream(
                lambda jpeg, cam, size=None: _feed(fq, state, jpeg, cam, size),
                weights=args.weights, imgsz=args.imgsz, conf=args.conf,
                device=args.device, quality=args.quality,
                on_detect=on_detect, cls=args.cls)
        except Exception as e:
            fq.close()
            print(f"[실패] 모델을 불러올 수 없다: {e}", file=sys.stderr)
            return 2
        inference.start()
        on_frame = inference.submit
        _report_classes(inference, args.cls)
    else:
        # 모델 없이도 프레임은 흐른다. 업로드 경로만 볼 때 쓴다
        print("[경고] --weights 가 없다. 추론 없이 프레임만 흐른다 - 탐지는 안 난다")
        on_frame = lambda jpeg, cam, size=None: _feed(fq, state, jpeg, cam, size)

    sources = parse_sources(args.camera)
    cap = Capture(sources, fps=args.fps, quality=args.quality,
                  width=args.width, height=args.height)
    n = cap.start(on_frame)
    if n == 0:
        if inference is not None:
            inference.stop()
        fq.close()
        print("[실패] 카메라를 하나도 못 열었다. `ls /dev/video*` 로 확인할 것",
              file=sys.stderr)
        return 2
    print(f"카메라 {n}대: {', '.join(cap.opened)}  ({args.fps}fps)")
    print(f"스트림  http://0.0.0.0:{args.stream_port}/")
    print("Ctrl+C 로 종료")

    try:
        if args.test is not None:
            return _test_run(args, fq, state)
        while True:
            time.sleep(5)
            st = fq.stats()
            # 🔴 젯슨의 생존 신호다. 15초 안 오면 Pi 가 죽은 것으로 본다. 이게
            #    없으면 키오스크 장치 패널의 카메라·AI 가 통째로 '모름' 이다
            _publish_status(fq, cap, inference, state)
            print(f"  {st['phase']}  fix_age={st['fix_age']}  ring={st['ring']}"
                  f"  queued={st['queued']} sent={st['sent']} failed={st['failed']}"
                  f"  {st['up_ms']}ms/장 {st['up_mbps']}MB/s"
                  f"  탐지 {state['shots']}건  연속 {judge.state()}"
                  f"  conf {state['conf']}"
                  + (f"  본것 {inference.last_seen}" if inference else ""))
    except KeyboardInterrupt:
        return 0
    finally:
        cap.stop()
        if inference is not None:
            inference.stop()
        fq.close()


def resolve_pre_sec(test_sec: float, pre_sec: int, post_sec: int) -> int:
    """`--test` 총 길이에서 앞 구간을 낸다.

    총 길이에서 뒤 구간을 뺀 나머지가 앞 구간이다. `--pre-sec` 을 직접 줬으면
    그것을 존중한다 — 기본값과 다르면 사용자가 정한 것이다.

    ⚠ 최소 1초는 남긴다. `--test 5 --post-sec 10` 처럼 뒤가 더 길면 앞이
      0이나 음수가 되는데, 그러면 링 버퍼 용량이 0 이라 프레임이 한 장도 안 쌓인다.
    """
    if pre_sec != FRAME_PRE_SEC:
        return pre_sec
    return max(1, int(test_sec) - post_sec)


def _test_run(args, fq, state) -> int:
    """시험 모드. **AI 판정 없이** 실제 카메라 프레임을 정해진 길이만큼 올린다.

    판정 임계값(AI-02)이 아직 미정이라, 그것과 무관하게 "실제 프레임이 실제로
    끝까지 올라가는가"만 보고 싶을 때 쓴다. 시연 리허설에도 이게 편하다 —
    카메라 앞에서 사람이 움직일 필요가 없다.

        앞 구간을 채운다 (pre_sec)
          -> 탐지 한 번 (타이머가 쏜다)
          -> 뒤 구간을 계속 보낸다 (post_sec)
          -> 업로드 큐가 빌 때까지 기다린다

    🔴 **Pi 에 실제로 사고가 하나 생긴다.** 시험이라고 다르게 취급하지 않는다 —
       그래야 저장·전송·타르볼까지 같은 길로 간다. 끝나면 사고를 닫을 것:
       Pi 에서 `uv run python tools/close_accident.py`
    """
    fps = max(1, args.fps)
    pre, post = args.pre_sec, args.post_sec

    # 🔴 **앞 구간을 채우기 전에 본다.** 진행 중 사고가 있으면 Pi 가 E1 으로
    #   409 를 주는데, 그걸 200장을 다 만들고 나서 알면 30초와 그 장수가 통째로
    #   버려진다. 실제로 그랬다 — "남은 212장을 버린다" 한 줄로 끝났다.
    busy = fq.busy_accident()
    if busy:
        print(f"[실패] 진행 중 사고가 있다: {busy}", file=sys.stderr)
        print("        Pi 에서 먼저:  uv run python tools/close_accident.py",
              file=sys.stderr)
        return 2

    print(f"앞 구간 {pre}초 채우는 중 ...")
    end = time.monotonic() + pre
    while time.monotonic() < end:
        time.sleep(1.0)
        st = fq.stats()
        print(f"  ring={st['ring']}  fix_age={st['fix_age']}")

    fix = fq.ship_fix()
    if fix is None:
        # 🔴 좌표 없이 올리지 않는다. 시험이어도 같다 — 지어낸 좌표가 DB 와
        #   EC2 에 남으면 나중에 그게 실측인 줄 안다
        print("[실패] 배 GPS 가 없다. Pi 가 pi/sensor/gps 를 뿌리는지 확인할 것 "
              "(Pi 를 --gps fake 로라도 띄울 것)", file=sys.stderr)
        return 2

    snap = None
    aim = {} if not args.fov else {
        "yaw": 0.0, "pitch": args.pitch,
        "target_lat": fix["lat"], "target_lon": fix["lon"],
    }
    det = fq.detected(lat=fix["lat"], lon=fix["lon"], distance_m=args.distance,
                      confidence=0.99, camera="L", bbox=None,
                      frame_count=int(pre * fps), snapshot=snap, **aim)
    state["shots"] += 1
    print(f"탐지 발행  {det.detection_id}  published={det.published}")

    print(f"뒤 구간 {post}초 ...")
    end = time.monotonic() + post
    while time.monotonic() < end:
        time.sleep(1.0)
        st = fq.stats()
        print(f"  {st['phase']}  queued={st['queued']} sent={st['sent']}"
              f" failed={st['failed']} dropped={st['dropped']}"
              f"  {st['up_ms']}ms/장 {st['up_mbps']}MB/s")

    print("업로드 큐 비우는 중 ...")
    # ⚠ 큐가 빌 때까지 기다린다. 여기서 바로 끝내면 아직 안 올라간 프레임이
    #   그대로 사라지고, Pi 에는 반쪽짜리 사고만 남는다.
    #
    # 🔴 **고정 시간으로 끊지 않는다.** 60초로 잘랐더니 200장 중 69장만 올라간
    #   채로 "완료"라고 찍혔다. 진도가 있으면 계속 기다리고, 멈췄을 때만 포기한다.
    stuck = 0
    prev = None
    while True:
        st = fq.stats()
        print(f"  queued={st['queued']} sent={st['sent']}"
              f" failed={st['failed']} dropped={st['dropped']}"
              f"  {st['up_ms']}ms/장 {st['up_mbps']}MB/s")
        if st["queued"] == 0:
            break
        stuck = stuck + 1 if st["queued"] == prev else 0
        if stuck >= STUCK_SEC:
            print(f"[경고] {STUCK_SEC}초째 진도가 없다. {st['queued']}장을 못 올렸다",
                  file=sys.stderr)
            break
        prev = st["queued"]
        time.sleep(1.0)

    # 🔴 **여기서 끝내면 안 된다.** 업로드 스레드는 daemon 이라 프로세스가 끝나면
    #   같이 죽는다. Floaq.close() 의 기본 대기가 5초라, 꼬리가 남아 있으면 그만큼만
    #   더 보내고 나머지는 조용히 사라진다. 큐가 비었어도 마지막 요청이 날아가는
    #   중일 수 있으므로 넉넉히 기다린다.
    fq.close(timeout=CLOSE_WAIT_SEC)

    st = fq.stats()
    print("")
    print(f"올린 프레임 {st['sent']}장  실패 {st['failed']}  버림 {st['dropped']}"
          f"  못 올림 {st['queued']}장")
    print(f"요청당 {st['up_ms']}ms  실효 {st['up_mbps']}MB/s")
    print("Pi 에서 확인:  sqlite3 floaq.db "
          "'SELECT file_type, count(*) FROM pi_accident_file GROUP BY 1'")
    print("사고 닫기:     uv run python tools/close_accident.py")
    # ⚠ 큐가 남았거나 실패가 있으면 **성공으로 끝내지 않는다.** 0 을 돌려주면
    #   스크립트가 "다 올라갔다"로 읽고 다음 단계로 넘어간다
    if st["queued"] or st["failed"]:
        print("[실패] 전부 올라가지 않았다", file=sys.stderr)
        return 1
    return 0


def _feed(fq, state, jpeg: bytes, camera: str, size=None) -> None:
    """추론을 거친(또는 안 거친) 프레임을 링버퍼로.

    ⚠ 화면에 보이는 것과 기록되는 것이 같아야 오탐 분석이 된다. 상자를 그린
      프레임이 여기로 오는 것은 의도다 - 원본은 `on_detect` 가 따로 받는다.
    """
    if size and size[0]:
        state["width"] = size[0]
        state["height"] = size[1]
    try:
        fq.frame(jpeg, camera=camera)
    except InvalidCall:
        pass          # 카메라 이름이 L/R 이 아닌 경우. 스트림에는 이미 갔다


def _aim(args, promo, fix, width: int) -> dict:
    """조준 해. `--fov` 가 없거나 bbox 가 없으면 빈 dict (NO_SOLUTION).

    🔴 **어림값이다.** 카메라 화각으로 bbox 가로 위치를 각도로 바꾼 것뿐이고,
       렌즈 왜곡도 카메라 장착 방위도 안 본다. 스테레오 거리(AI-03)와 실제
       외부 파라미터가 나오면 통째로 갈아야 한다.
    """
    if not args.fov or not promo.bbox or width <= 0:
        return {}
    x, _, w, _ = promo.bbox
    # 화면 가운데를 0도로. 오른쪽이 +
    offset = ((x + w / 2) / width) - 0.5
    yaw = offset * args.fov

    # 배 위치에서 yaw 방향으로 distance 만큼 간 지점. 선수 방위를 더한다
    brg = math.radians((fix.get("heading_deg") or 0.0) + yaw)
    dlat = args.distance * math.cos(brg) / 111_132.0
    dlon = args.distance * math.sin(brg) / (111_320.0
                                            * math.cos(math.radians(fix["lat"])))
    return {"yaw": round(yaw, 1), "pitch": args.pitch,
            "target_lat": fix["lat"] + dlat, "target_lon": fix["lon"] + dlon}


#: 이 시간 안에 프레임이 안 오면 그 카메라를 고장으로 본다. 기본 5fps 라 넉넉하다.
CAMERA_STALE_S = 3.0


def _publish_status(fq, cap, inference, state) -> None:
    """`jetson/status` 한 번. **실패해도 루프를 멈추지 않는다.**

    🔴 카메라 상태는 **최근에 프레임이 왔는가**로 본다. `cap.opened` 는 연 적이
       있다는 뜻일 뿐이라, 케이블이 빠져도 목록에 계속 남아 키오스크가 죽은
       카메라를 정상으로 그린다.

    ⚠ `--camera` 에 없는 이름은 UNKNOWN 이다 — 안 붙인 것과 고장 난 것은 다르다.
    """
    now = time.monotonic()

    def cam(name: str) -> str:
        if name not in getattr(cap, "sources", {}):
            return "UNKNOWN"
        at = getattr(cap, "last_frame_at", {}).get(name)
        return "OK" if at is not None and now - at <= CAMERA_STALE_S else "ERROR"

    done = getattr(inference, "processed", 0)
    prev_n, prev_t = state.get("proc", (0, now))
    fps = (done - prev_n) / (now - prev_t) if now > prev_t else 0.0
    state["proc"] = (done, now)
    try:
        fq.status(camera_l=cam("L"), camera_r=cam("R"),
                  inference_fps=max(0.0, fps))
    except Exception:
        import logging
        logging.getLogger(__name__).debug("jetson/status 발행 실패", exc_info=True)


def _report_classes(inference, cls: int) -> None:
    """모델이 아는 클래스를 찍고 `--cls` 를 대조한다.

    🔴 여기서 안 알려주면 화면에는 상자가 뜨는데 탐지는 영영 0 이다. 배포 모델은
       person 이 3 이고 기본값 0 은 animal 이다 (`ai/models/README.md`).
       전에는 단안 분기에만 있어서 `--aim-only` 는 조용히 동물만 찾았다.
    """
    names = inference.names
    print(f"모델 클래스  {names}")
    if cls not in names:
        print(f"[경고] --cls {cls} 가 모델에 없다. "
              f"쓸 수 있는 번호: {sorted(names)}", file=sys.stderr)
        return
    print(f"찾는 것    {cls} = {names[cls]}")
    if "person" in str(names[cls]).lower():
        return
    # 🔴 번호는 유효하다. 다만 사람이 아니다 — 이게 제일 조용한 실패다
    people = [k for k, v in names.items() if "person" in str(v).lower()]
    if people:
        print(f"[경고] --cls {cls} 는 '{names[cls]}' 다. 사람은 --cls {people[0]} "
              f"('{names[people[0]]}')", file=sys.stderr)


def _aim_stereo(args, pointing, fix) -> dict:
    """스테레오 조준 해를 탐지에 실을 형태로.

    `_aim` 과 달리 거리도 실측이다 — `args.distance` 대신 삼각측량 값을 쓴다.

    ⚠ `pitch` 는 `_stereo_aiming` 이 계산한 시선각을 `stereo_targeting.yaml` 의
      `min_pitch_deg ~ max_pitch_deg` 에 붙여 놓은 값이다.
    """
    brg = math.radians((fix.get("heading_deg") or 0.0) + pointing.yaw_deg)
    dlat = pointing.range_m * math.cos(brg) / 111_132.0
    dlon = pointing.range_m * math.sin(brg) / (111_320.0
                                               * math.cos(math.radians(fix["lat"])))
    return {"yaw": round(pointing.yaw_deg, 1),
            "pitch": round(pointing.pitch_deg, 1),
            "target_lat": fix["lat"] + dlat, "target_lon": fix["lon"] + dlon}


def main() -> int:
    p = argparse.ArgumentParser(
        prog="floaq_jetson", description="Jetson — 카메라·추론·조준",
        epilog="⚠ 발사는 여기서 정하지 않는다. Pi 가 정한다 (--servos 면 쏜다, --no-fire 면 안 쏜다).",
    )

    g = p.add_argument_group("Pi 연결")
    g.add_argument("--pi", help="Pi 주소 (예: 192.168.0.10). --stream-only 면 필요 없다")
    g.add_argument("--ship-id", default=None, help="안 주면 Pi /health 에서 가져온다")
    g.add_argument("--mqtt-port", type=int, default=1883, help="브로커 TCP 포트")
    g.add_argument("--http-port", type=int, default=8000,
                   help="Pi 의 HTTP 포트. 사진을 여기로 올린다")

    g = p.add_argument_group("카메라 · 화면")
    g.add_argument("--camera", default=None,
                   help="실제 카메라를 연다. 예: 0,1  또는  L=2,R=0  또는 GStreamer "
                        "파이프라인. 생략하면 시험 패턴")
    g.add_argument("--fps", type=int, default=FRAME_FPS, help="프레임 수집 주기")
    g.add_argument("--quality", type=int, default=80, help="JPEG 품질 1~100")
    g.add_argument("--width", type=int, default=0, help="0 이면 드라이버 기본값")
    g.add_argument("--height", type=int, default=0, help="0 이면 드라이버 기본값")
    g.add_argument("--stream-only", action="store_true",
                   help="Pi·카메라 없이 :8080 만 띄운다. 네트워크 경로 확인용")
    g.add_argument("--stream-port", type=int, default=8080,
                   help="라이브 화면 MJPEG. /stream.mjpg?camera=L")

    g = p.add_argument_group("모델 · 판정")
    g.add_argument("--weights", default=None,
                   help="--camera 영상에 적용할 YOLO .pt 또는 .onnx 모델")
    g.add_argument("--cls", type=int, default=0,
                   help="사람 클래스 번호. COCO 는 0 이지만 배포 모델"
                        "(ai/models/best_performance.pt)은 3 이다. 틀리면 탐지가 영영 0 건")
    g.add_argument("--imgsz", type=int, default=640, help="추론 입력 크기")
    g.add_argument("--conf", type=float, default=0.25, help="YOLO 자체 임계값")
    g.add_argument("--device", default=None,
                   help="YOLO 추론 장치 (예: cpu 또는 0). 생략하면 자동 선택")
    g.add_argument("--detect-conf", type=float, default=DET_CONF,
                   help="사고 승격 최소 신뢰도 (기본 0.6). 미정값이다")
    g.add_argument("--detect-frames", type=int, default=DET_FRAMES,
                   help="연속 몇 프레임이면 승격인가 (기본 5). 미정값이다")
    g.add_argument("--detect-cooldown", type=float, default=DET_COOLDOWN,
                   help="한 번 올린 뒤 다시 안 올리는 시간(초)")

    g = p.add_argument_group("조준  ⚠ 이 인자들은 발사를 막지 못한다")
    # 🔴 발사는 Pi 가 정한다 (`--servos` 면 쏜다, `--no-fire` 면 안 쏜다). 여기는 "사고·사진·신고를
    #    만드느냐" 만 가른다. 2026-09-22 에 `--aim-only` 를 발사 차단으로
    #    읽었다가 조준만 보려던 자리에서 부표가 나갔다.
    m = g.add_mutually_exclusive_group()
    m.add_argument("--aim", "--aim-only", dest="aim_only", action="store_true",
                   help="스테레오 조준만. jetson/aim 만 보내고 사고·사진·신고는 "
                        "안 만든다. (Pi 가 --servos 면 그래도 발사한다)")
    m.add_argument("--aim-detect", action="store_true",
                   help="위 조준에 탐지·사진·신고까지 한 실행으로 붙인다. 시연용")
    g.add_argument("--aim-config", default="configs/stereo_targeting.yaml",
                   help="스테레오 장착 좌표·안정화 설정")
    g.add_argument("--fov", type=float, default=0.0,
                   help="단안용. 카메라 수평 화각(도). 주면 bbox 로 yaw 를 어림한다. "
                        "0 이면 조준 해 없이 보낸다 (NO_SOLUTION)")
    g.add_argument("--pitch", type=float, default=20.0,
                   help="단안용. --fov 를 줬을 때 쓸 발사 고각")
    g.add_argument("--distance", type=float, default=15.0,
                   help="단안용. 익수자까지 거리(m) 고정값")
    g.add_argument("--no-aim", action="store_true", help="조준 해 없이 탐지만 보낸다")

    g = p.add_argument_group("사진 · 시험")
    g.add_argument("--pre-sec", type=int, default=FRAME_PRE_SEC, help="사고 전 구간 초")
    g.add_argument("--post-sec", type=int, default=FRAME_POST_SEC, help="사고 후 구간 초")
    g.add_argument("--dry-run", action="store_true",
                   help="탐지를 판정만 하고 Pi 로 **안 보낸다**. 사고가 안 생기므로 "
                        "--cls 나 --detect-conf 를 맞출 때 쓴다")
    g.add_argument("--test", nargs="?", type=float, const=TEST_SEC, default=None,
                   metavar="SEC",
                   help="AI 판정 없이 실제 카메라 프레임을 30초분 올린다 "
                        "(--test 45 처럼 길이 지정 가능)")
    g.add_argument("--watch", action="store_true", help="탐지 없이 상태만 본다")
    g.add_argument("-v", "--verbose", action="store_true", help="DEBUG 까지 찍는다")


    args = p.parse_args()

    if args.weights and not args.camera:
        p.error("--weights 는 --camera 와 함께 써야 한다")
    if args.detect_frames < 1:
        p.error("--detect-frames 는 1 이상")
    if args.aim_only and args.aim_detect:
        p.error("--aim 과 --aim-detect 는 같이 쓸 수 없다. 조준만이면 --aim")
    stereo = args.aim_only or args.aim_detect
    if stereo and (not args.weights or not args.camera):
        p.error("--aim/--aim-detect 는 --camera 와 --weights 가 필요하다")
    if stereo and (args.test is not None or args.no_aim):
        p.error("--aim/--aim-detect 는 --test, --no-aim 과 같이 쓸 수 없다")
    if args.aim_only and args.dry_run:
        # --aim-only 는 이미 사고를 안 만든다. --dry-run 은 붙일 것이 없다
        p.error("--aim 은 원래 사고를 안 만든다. --dry-run 이 필요 없다")
    if args.dry_run and args.test is not None:
        # 시험 모드는 타이머가 탐지를 쏘는 것이 전부다. 안 보내면 할 일이 없다
        p.error("--dry-run 과 --test 는 같이 쓸 수 없다")
    if args.test is not None:
        if args.test <= 0:
            p.error("--test 는 양수여야 한다")
        args.pre_sec = resolve_pre_sec(args.test, args.pre_sec, args.post_sec)
    if not 0.0 <= args.conf <= 1.0:
        p.error("--conf 는 0~1 이어야 한다")
    if args.imgsz <= 0:
        p.error("--imgsz 는 양수여야 한다")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")

    if args.stream_only:
        return _stream_only(args)

    if args.pi and args.camera:
        return _live(args)

    if not args.pi:
        print("[실패] --pi 가 필요하다 (또는 --stream-only)", file=sys.stderr)
        return 2

    try:
        fq = Floaq(args.pi, ship_id=args.ship_id, mqtt_port=args.mqtt_port,
                   http_port=args.http_port, model_version="selftest")
    except InvalidCall as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 2

    print(f"ship_id  {fq.ship_id}")
    if not fq.start(timeout=5.0):
        print("[경고] MQTT 에 아직 못 붙었다. 재접속은 계속한다", file=sys.stderr)

    try:
        if args.watch:
            while True:
                print(fq.stats())
                time.sleep(2)
            return 0

        # 앞 구간을 채운다 — 실제 루프라면 계속 돌고 있었을 자리다
        print(f"링 버퍼 채우는 중 (앞 {FRAME_PRE_SEC}초)")
        for _ in range(FRAME_PRE_SEC * FRAME_FPS):
            fq.frame(FAKE, camera="L")
        print(f"  보유 {len(fq.ring)}장")

        aim = {} if args.no_aim else {
            "yaw": 12.5, "pitch": 20.0,
            "target_lat": LAT + 0.0005, "target_lon": LON + 0.0005,
        }
        det = fq.detected(lat=LAT, lon=LON, distance_m=12.4, confidence=0.93,
                          camera="L", bbox=(320, 180, 64, 128),
                          frame_count=5, snapshot=FAKE, **aim)
        print(f"탐지 발행  {det.detection_id}  published={det.published}")

        print(f"뒤 {FRAME_POST_SEC}초 프레임 보내는 중")
        for _ in range(FRAME_POST_SEC * FRAME_FPS):
            fq.frame(FAKE, camera="L")
            time.sleep(1.0 / FRAME_FPS)

        # 큐가 빠질 시간을 준다
        for _ in range(20):
            st = fq.stats()
            print("  ", st)
            if st["queued"] == 0:
                break
            time.sleep(1)

        st = fq.stats()
        ok = st["sent"] > 0 and st["failed"] == 0
        print("\n" + ("[성공] 경로가 살아 있다" if ok else
                      "[실패] sent=%(sent)d failed=%(failed)d dropped=%(dropped)d" % st))
        return 0 if ok else 1
    except KeyboardInterrupt:
        return 0
    finally:
        fq.close()


if __name__ == "__main__":
    sys.exit(main())

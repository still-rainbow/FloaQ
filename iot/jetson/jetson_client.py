# /// script
# requires-python = ">=3.10"
# dependencies = ["paho-mqtt>=2.1"]
# ///
"""Jetson -> Pi 연동 참조 클라이언트. **이 파일 하나만 Jetson 에 옮기면 된다.**

floaq 패키지를 import 하지 않는다. 표준 라이브러리 + paho-mqtt 뿐이다.

    uv run jetson_client.py --pi <주소> --ship-id <uuid>

위 한 줄이면 된다. PEP 723 블록이 머리에 있어서 uv 가 의존성을 알아서 받는다 —
가상환경도 pip install 도 따로 안 한다.

IoT/JetSon 프로젝트 안에서 돌리면 pyproject.toml 에 paho-mqtt==2.1.0 이 이미 있다:

    uv run python jetson_client.py --pi <주소> --ship-id <uuid>

사용
    # 전 과정: 탐지 발행 -> 프레임 업로드 -> 스냅샷
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid>

    # 반복 시험. 진행 중 사고를 먼저 닫는다 (시험 전용)
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid> --reset

    # 150장. 소요 시간과 처리량이 찍힌다
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid> --frames 150

    # 인터넷 없는 곳이면 가짜 바이트로
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid> --fake

    # 업로드만 (MQTT 없이 HTTP 경로만 확인)
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid> --http-only

    # 배 GPS 만 받아보기 (조준 해 입력이 실제로 오는지)
    python jetson_client.py --pi 192.168.0.10 --ship-id <uuid> --watch-gps

── 두 갈래로 보낸다 ────────────────────────────────────────────────
    MQTT 1883   이벤트. 작고 잦다
        jetson/detection   탐지. **이게 사고를 만든다**
        jetson/snapshot    스냅샷 1장. base64, retained
        jetson/status      상태. 5초

    HTTP 8000   파일. 크고 드물다
        PUT /api/detections/{detection_id}/files/{file_type}/{sequence_no}

프레임 150장을 MQTT 로 밀면 브로커 RAM 에 상주하고 1Hz GPS·부표 위치가 밀린다.
반대로 스냅샷 1장은 retained 라 키오스크가 접속만 해도 떠서 MQTT 가 낫다.

🔴 **POST 가 아니라 PUT 이다.** 응답을 못 받고 재전송해도 같은 자리에 덮어쓴다.
   POST 면 `pi_accident_file` 에 행이 두 배로 쌓인다.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


# ── 봉투 ─────────────────────────────────────────────────────────────
def envelope(data: dict) -> bytes:
    """모든 MQTT 페이로드가 이 봉투에 담긴다.

    🔴 **`data` 는 언제나 배열이다.** 원소가 하나여도 감싼다. 객체를 그대로 넣으면
       Pi 가 `Input should be a valid array` 로 버리고 **응답도 주지 않는다.**

    ⚠ `ts` 는 **초**다. 밀리초를 넣으면 1970년이 아니라 훨씬 미래로 찍힌다.
    """
    return json.dumps({
        "request_id": str(uuid.uuid4()),
        "v": 1,
        "ts": int(time.time()),
        "data": [data],
    }).encode()


# ── HTTP ─────────────────────────────────────────────────────────────
def put_frame(pi: str, port: int, detection_id: str, file_type: str,
              sequence_no: int, jpeg: bytes, camera: str = "L",
              timeout: float = 10.0) -> dict:
    """프레임 한 장 업로드.

    ⚠ 탐지 발행보다 먼저 도착하면 **404** 다. Pi 가 아직 사고를 안 만들었기 때문이다.
      호출자가 재시도한다.
    """
    url = (f"http://{pi}:{port}/api/detections/{detection_id}"
           f"/files/{file_type}/{sequence_no}")
    req = urllib.request.Request(url, data=jpeg, method="PUT")
    req.add_header("Content-Type", "image/jpeg")
    req.add_header("X-Camera", camera)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def put_frame_retry(pi: str, port: int, detection_id: str, file_type: str,
                    sequence_no: int, jpeg: bytes, camera: str = "L",
                    attempts: int = 5) -> dict | None:
    """404 면 잠깐 기다렸다 다시 건다.

    🔴 Jetson 은 `accident_id` 를 모른다. 탐지 시점엔 사고가 아직 없고 Pi 가
       `jetson/detection` 을 받고 나서 만든다. 그래서 업로드가 탐지보다 빠르면
       404 가 나고, 재시도하면 붙는다.
    """
    for n in range(attempts):
        try:
            return put_frame(pi, port, detection_id, file_type, sequence_no,
                             jpeg, camera)
        except urllib.error.HTTPError as e:
            if e.code == 409:
                # 🔴 진행 중 사고가 있어 이 탐지가 거부됐다. **재시도해도 안 붙는다.**
                #    404 와 갈라져 있어야 여기서 바로 포기할 수 있다.
                print(f"  거부됨: 진행 중 사고가 있다 (동시 1건). --reset 을 쓸 것")
                return None
            if e.code == 404 and n < attempts - 1:
                # Pi 가 아직 탐지를 처리하지 않았다. 재시도하면 붙는다.
                time.sleep(0.5 * (n + 1))
                continue
            body = e.read().decode("utf-8", "replace")[:160]
            print(f"  업로드 실패 seq={sequence_no}: HTTP {e.code} {body}")
            return None
        except OSError as e:
            print(f"  업로드 실패 seq={sequence_no}: {e}")
            return None
    return None


def fetch_contract(pi: str, port: int) -> dict | None:
    """계약을 Pi 에서 받는다. **손으로 옮겨 적지 않는다.**

    토픽·페이로드 스키마·enum·상태 전이표가 전부 들어 있다. 파이썬이 정본이고
    요청할 때마다 새로 만들어지므로 코드와 갈라지지 않는다.
    """
    try:
        with urllib.request.urlopen(f"http://{pi}:{port}/contract.json",
                                    timeout=5) as r:
            return json.loads(r.read())
    except OSError as e:
        print(f"계약을 못 받았다: {e}")
        return None


# ── 페이로드 ─────────────────────────────────────────────────────────
def make_detection(ship_id: str, detection_id: str, *,
                   lat: float, lon: float, with_solution: bool = True) -> dict:
    """`jetson/detection`.

    Jetson 은 "사람을 봤고 쏜다면 이 각도다"까지만 말한다. **사고 판정은 Pi 가 한다.**
    그래서 `accident_id` 가 없다.

    🔴 Pi 가 거부하는 조건 다섯 가지:

        target_yaw_deg 가 -45 ~ +45 밖       -> OUT_OF_RANGE
        target_pitch_deg 가 0 ~ +45 밖        -> OUT_OF_RANGE
        launch_profile 이 미등록             -> OUT_OF_RANGE
        solved_at 이 3초 넘게 묵음            -> OUT_OF_RANGE
        launch 이 null                       -> NO_SOLUTION

    거부돼도 **사고는 그대로 진행된다.** 부표 없이 신고까지 간다 (E5).

    ⚠ `solved_at` 이 3초다. 10노트면 1초에 약 5m 움직여서 해가 묵으면 목표점이
      그만큼 어긋난다. 발행 직전에 계산할 것.
    """
    d = {
        "detection_id": detection_id,
        "ship_id": ship_id,
        "lat": lat,
        "lon": lon,
        "distance_m": 12.5,
        "confidence": 0.93,
        "frame_count": 5,
        "model_version": "v1",
        "camera": "L",
        "bbox": [10, 20, 30, 40],
        "detected_at": int(time.time()),
        "launch": None,
    }
    if with_solution:
        d["launch"] = {
            "target_yaw_deg": 12.5,       # 선수 기준. -45 ~ +45
            "target_pitch_deg": 20.0,     # 수평 기준. 0 ~ +45
            "launch_profile": "demo-low-v1",
            "target_lat": lat + 0.0001,
            "target_lon": lon + 0.0001,
            "solved_at": int(time.time()),
        }
    return d


def make_snapshot(accident_id: str, jpeg: bytes) -> dict:
    """`jetson/snapshot` — retained. 사고당 1회라 놓치면 다시 안 온다.

    ⚠ base64 는 원본보다 33% 크다. 300KB 상한을 넘기지 않게 품질을 조절할 것.
    ⚠ `data:` 접두사를 붙이지 않는다. 순수 base64 문자열이다.
    """
    return {
        "accident_id": accident_id,
        "format": "jpeg",
        "width": 1920,
        "height": 1080,
        "bytes": len(jpeg),
        "data": base64.b64encode(jpeg).decode(),
        "captured_at": int(time.time()),
        "confidence": 0.93,
        "bbox": [10, 20, 30, 40],
        "camera": "L",
    }


def make_status() -> dict:
    """`jetson/status` — retained, 5초.

    ⚠ Pi 는 LWT 가 아니라 이걸로 Jetson 생존을 본다. 15초 미수신이면 죽은 것으로 친다.
    ⚠ `gps_received` 가 false 면 조준 해를 못 낸다는 뜻이다. Pi 가 화면에 띄운다.
    """
    return {
        "model_version": "v1",
        "inference_fps": 14.8,
        "camera_l": "OK",
        "camera_r": "OK",
        "camera_dirty": False,
        "gps_received": True,
        "uptime_sec": 120,
    }


# ── 시험 이미지 ──────────────────────────────────────────────────────
#: http.cat 은 HTTP 상태코드마다 고양이 사진을 준다. 시험용으로 좋다 —
#: **진짜 JPEG** 이고 50~100KB 라 실제 프레임 크기에 가깝다. 되받아서 열어보면
#: 고양이가 보이므로 바이트가 온전한지 눈으로 확인된다.
CAT_CODES = (200, 404, 418, 500, 503, 301, 403, 502)

_cats: list[bytes] = []


def load_cats(codes=CAT_CODES) -> list[bytes]:
    """http.cat 에서 받아 캐시한다. 한 번만 받고 그 뒤로는 돌려 쓴다.

    ⚠ Jetson 에 인터넷이 있어야 한다. 없으면 가짜 바이트로 떨어진다.
    """
    global _cats
    if _cats:
        return _cats
    for c in codes:
        try:
            with urllib.request.urlopen(f"https://http.cat/{c}.jpg", timeout=10) as r:
                _cats.append(r.read())
        except OSError as e:
            print(f"  http.cat/{c} 실패: {e}")
    if _cats:
        kb = [len(b) // 1024 for b in _cats]
        print(f"  고양이 {len(_cats)}장 ({min(kb)}~{max(kb)}KB)")
    return _cats


# ── 실행 ─────────────────────────────────────────────────────────────
def fake_jpeg(n: int) -> bytes:
    """가짜 바이트. JPEG 머리와 꼬리만 맞춰 둔다.

    ⚠ Pi 는 Content-Type 만 보고 내용을 검사하지 않는다. 경로 시험에는 쓸 수 있지만
      **바이트 무결성 확인에는 쓸모가 없다** — 무엇이 돌아오든 눈으로 구분이 안 된다.
      그때는 `--real` 을 쓴다.
    """
    return b"\xff\xd8\xff\xe0" + f"frame-{n:04d}".encode() + b"P" * 400 + b"\xff\xd9"


def frame_bytes(n: int, real: bool) -> bytes:
    if not real:
        return fake_jpeg(n)
    cats = load_cats()
    return cats[(n - 1) % len(cats)] if cats else fake_jpeg(n)


def connect_mqtt(pi: str, port: int, ship_id: str):
    if mqtt is None:
        sys.exit("paho-mqtt 가 없다:  pip install paho-mqtt")
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"jetson-{ship_id[:8]}", protocol=mqtt.MQTTv311)
    c.connect(pi, port, keepalive=15)
    c.loop_start()
    return c


def _collect(out: list, msg) -> None:
    """수신 메시지를 봉투에서 꺼내 모은다.

    🔴 **빈 페이로드를 반드시 걸러낸다.** 사고가 닫히면 Pi 가 0바이트를 retain 으로
       발행해 `pi/accident/state` 의 retained 를 지운다. 그게 구독자에게 빈 메시지로
       도착하는데, `json.loads(b"")` 는 예외를 던진다.

    ⚠ paho 콜백에서 예외가 나면 **그 스레드가 죽고 그 뒤 메시지를 전부 못 받는다.**
      실제로 이 참조 클라이언트에서 밟았다.
    """
    if not msg.payload:
        return
    try:
        out.append(json.loads(msg.payload)["data"][0])
    except (ValueError, KeyError, IndexError):
        # 모르는 모양이면 버린다. 죽지 않는다.
        pass


def reset_accident(client, ship_id: str, wait: float = 2.0) -> bool:
    """진행 중 사고를 닫는다. **시험 전용이다.**

    🔴 **운영에서 Jetson 이 이걸 하면 안 된다.** `kiosk/command/*` 는 키오스크의
       발행자 세그먼트다. 브로커 ACL 이 켜지는 순간 막힌다. 반복 시험 때
       "진행 중 사고 1건(E1)" 때문에 새 탐지가 무시되는 걸 피하려고 둔 것뿐이다.

    현재 사고는 `pi/accident/state` 가 retained 라 구독하는 순간 온다.
    """
    state: list[dict] = []
    client.on_message = lambda cl, u, m: _collect(state, m)
    client.subscribe(f"ship/{ship_id}/pi/accident/state", 1)
    time.sleep(1.0)                      # retained 가 오는 데 충분하다

    active = [s for s in state if s["status"] in ("DETECT", "WAIT", "REPORT")]
    if not active:
        print("  진행 중 사고 없음")
        client.unsubscribe(f"ship/{ship_id}/pi/accident/state")
        client.on_message = None
        return False

    cur = active[-1]
    # DETECT/WAIT 은 취소, REPORT 는 이미 신고가 나가서 취소가 무효다 -> 종료
    cmd = "close" if cur["status"] == "REPORT" else "cancel"
    print(f"  진행 중 {cur['status']} -> {cmd}")
    client.publish(f"ship/{ship_id}/kiosk/command/{cmd}",
                   envelope({"accident_id": cur["accident_id"]}), qos=1)
    time.sleep(wait)
    client.unsubscribe(f"ship/{ship_id}/pi/accident/state")
    client.on_message = None
    return True


def watch_gps(pi: str, mqtt_port: int, ship_id: str, seconds: float) -> None:
    """`pi/sensor/gps` 를 받아본다.

    🔴 **조준 해의 필수 입력이다.** 배 위치·속력·침로가 있어야 선수 기준 각도를
       절대 좌표로 옮길 수 있다. 이게 안 오면 `launch` 를 null 로 보내야 한다.

    ⚠ retained 라 구독하는 순간 마지막 값이 즉시 온다. 그 뒤로 1Hz.
    """
    c = connect_mqtt(pi, mqtt_port, ship_id)
    got = []
    c.on_message = lambda cl, u, m: _collect(got, m)
    c.subscribe(f"ship/{ship_id}/pi/sensor/gps", 0)
    print(f"pi/sensor/gps 구독 {seconds}초...")
    time.sleep(seconds)
    c.loop_stop()
    c.disconnect()
    print(f"  {len(got)}건 수신")
    for d in got[:5]:
        print(f"  {d['lat']:.7f}, {d['lon']:.7f}  {d['speed_kn']}kn  "
              f"{d['heading_deg']}deg  measured_at={d['measured_at']}")
    if not got:
        print("  ⚠ 안 온다. Pi 가 --gps 옵션으로 떠 있는지 확인할 것")


def main() -> int:
    p = argparse.ArgumentParser(description="Jetson -> Pi 연동 참조 클라이언트")
    p.add_argument("--pi", required=True, help="Pi 주소 (192.168.0.10)")
    p.add_argument("--ship-id", required=True, help="UUID v7 36자")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--http-port", type=int, default=8000)
    p.add_argument("--frames", type=int, default=5, help="업로드할 프레임 수")
    p.add_argument("--lat", type=float, default=35.1234567)
    p.add_argument("--lon", type=float, default=129.7654321)
    p.add_argument("--no-solution", action="store_true",
                   help="조준 해 없이 보낸다 -> Pi 가 NO_SOLUTION 으로 거부")
    # 🔴 시험 전용. 운영에서 Jetson 이 kiosk/command/* 를 쏘면 안 된다
    #    (발행자 세그먼트 규약. 브로커 ACL 이 켜지면 막힌다)
    p.add_argument("--reset", action="store_true",
                   help="진행 중 사고를 먼저 닫는다. 시험 전용")
    # 기본이 진짜 JPEG 이다. 키오스크에서 확인하려면 화면에 뭐라도 떠야 하는데
    # 가짜 바이트는 깨진 이미지로 나온다.
    p.add_argument("--fake", action="store_true",
                   help="http.cat 대신 가짜 바이트를 쓴다. 인터넷 없을 때")
    p.add_argument("--http-only", action="store_true", help="업로드만 시험")
    p.add_argument("--watch-gps", action="store_true", help="배 GPS 만 받아본다")
    p.add_argument("--detection-id", default=None,
                   help="--http-only 에서 기존 detection_id 로 올릴 때")
    args = p.parse_args()

    if args.watch_gps:
        watch_gps(args.pi, args.mqtt_port, args.ship_id, 6.0)
        return 0

    print(f"Pi   {args.pi}  MQTT {args.mqtt_port} / HTTP {args.http_port}")
    c = fetch_contract(args.pi, args.http_port)
    if c:
        print(f"계약 v{c['version']} · 토픽 {len(c['topics'])}개")

    detection_id = args.detection_id or str(uuid.uuid4())

    # ── 1. 탐지 발행. 사고가 여기서 생긴다 ──────────────────────────
    if not args.http_only:
        client = connect_mqtt(args.pi, args.mqtt_port, args.ship_id)
        if args.reset:
            # ⚠ 진행 중 사고가 있으면 새 탐지가 E1(동시 1건)으로 무시되고,
            #   그 detection_id 는 사고에 안 붙어 업로드가 전부 404 가 난다.
            print("0) 진행 중 사고 정리")
            reset_accident(client, args.ship_id)
        det = make_detection(args.ship_id, detection_id,
                             lat=args.lat, lon=args.lon,
                             with_solution=not args.no_solution)
        client.publish(f"ship/{args.ship_id}/jetson/detection",
                       envelope(det), qos=1)
        print(f"\n1) jetson/detection  detection_id={detection_id}")
        time.sleep(1.5)          # Pi 가 사고를 만들 시간
    else:
        print(f"\ndetection_id={detection_id} (HTTP 만)")

    # ── 2. 프레임 업로드 ────────────────────────────────────────────
    kind = "가짜 바이트" if args.fake else "http.cat"
    print(f"\n2) 프레임 {args.frames}장 업로드  ({kind})")
    if not args.fake:
        load_cats()
    ok = sent = 0
    accident_id = None
    quiet = args.frames > 20          # 150장이면 줄마다 찍으면 화면이 넘친다
    t0 = time.monotonic()
    for n in range(1, args.frames + 1):
        body = frame_bytes(n, not args.fake)
        r = put_frame_retry(args.pi, args.http_port, detection_id,
                            "BEFORE", n, body)
        if r:
            ok += 1
            sent += len(body)
            accident_id = r["accident_id"]
            if not quiet:
                print(f"  seq={n}  file_id={r['file_id']}  {r['url']}")
            elif n % 25 == 0:
                print(f"  {n}/{args.frames} …")
    dt = time.monotonic() - t0
    rate = f"  ({sent / 1024 / dt:.0f}KB/s, {ok / dt:.1f}장/s)" if dt > 0 else ""
    print(f"  {ok}/{args.frames} 성공  {sent / 1024:.0f}KB  {dt:.2f}초{rate}")

    # ── 3. 스냅샷 ───────────────────────────────────────────────────
    if not args.http_only and accident_id:
        client.publish(f"ship/{args.ship_id}/jetson/snapshot",
                       envelope(make_snapshot(accident_id, frame_bytes(1, not args.fake))),
                       qos=1, retain=True)
        client.publish(f"ship/{args.ship_id}/jetson/status",
                       envelope(make_status()), qos=1, retain=True)
        print(f"\n3) jetson/snapshot (retained) · jetson/status")
        time.sleep(1.0)
        client.loop_stop()
        client.disconnect()

    if accident_id:
        print(f"\naccident_id  {accident_id}")
        print(f"목록 확인    curl http://{args.pi}:{args.http_port}"
              f"/api/accidents/{accident_id}/files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

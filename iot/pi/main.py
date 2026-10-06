"""Pi 오케스트레이터 진입점. 배선만 한다.

여기가 유일하게 **모든 층을 아는 곳**이다. core 는 ports 만 보고, 어댑터는 도메인을 모른다.
둘을 맞붙이는 건 이 파일뿐이라, 구현체를 갈아끼울 때 여기만 고친다.

실행:
    mosquitto -c mosquitto.conf -v          # 별도 터미널
    python main.py --ship-id <uuid> --db floaq.db

⚠ 하드웨어 어댑터가 아직 없다. `--fake-hw` 로 FakeLauncher·FakeReporter 를 쓴다.
  GPIO·LoRa·GPS·UDP 어댑터가 나오면 여기서 교체한다.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from floaq import config
from floaq.adapters import gps, lora
from floaq.adapters.memory import FakeLauncher, FakeReporter
from floaq.adapters.report import UdpReporter
from floaq.adapters.mqtt import MqttBus, wire
from floaq.adapters.sqlite import SqliteRepo, assert_schema_matches, connect
from floaq import provision
from floaq.adapters.ec2 import EdgeClient
from floaq.contracts import ReportStatus, SensorGps
from floaq.contracts import lora as lora_codec
from floaq.enroll import Enroller
from floaq.sync import SyncPump
from floaq.archive import ArchivePump
from floaq.web.files import FileStore
from floaq.ocean import OceanPump, OceanStore
from floaq.web.ocean import OceanProxy
from floaq.core.orchestrator import Orchestrator
from floaq.device import DeviceStatusPump, JetsonWatch

log = logging.getLogger("floaq")

SCHEMA = Path(__file__).resolve().parents[2] / "database" / "pi.sql"


class SystemClock:
    """`ports.Clock` 의 시스템 시계 구현. **이제 기본이 아니다.**

    시각 기준은 GPS UTC 다 `확정` 2026-09-11 — `adapters/gps.GpsClock` 이 정본이고
    `main()` 이 그쪽을 쓴다. 이 클래스는 GPS 가 아예 없는 개발 환경에서만 의미가 있다.

    ⚠ 이걸 쓰면 `is_valid()` 가 시스템 시계만 보므로, 시계가 틀린 채로 자동 신고가
      나갈 수 있다. GPS 나 RTC 없이 실장비에 올리지 않는다.
    """

    def now(self) -> int:
        return int(time.time())

    def is_valid(self) -> bool:
        return config.clock_is_valid(self.now())


def _parse_calibration(values: list[str]) -> list[tuple[float, float]]:
    points = []
    for value in values:
        try:
            angle, command = value.split(":", 1)
            points.append((float(angle), float(command)))
        except ValueError as exc:
            raise ValueError(f"보정점은 ANGLE:COMMAND 형식이어야 한다: {value!r}") from exc
    return points


def build_args() -> argparse.Namespace:
    """인자를 묶어서 보여준다.

    🔴 **`--help` 가 읽히지 않으면 사람이 위험한 조합을 만든다.** 2026-09-22 에
       `--aim-only-servos` 를 "발사 안 함" 으로 읽고 `--armed` 를 같이 줬다가
       조준만 보려던 자리에서 부표가 나갔다. 그래서 발사 인자를 따로 묶었다.

    🔴 **실장비의 기본은 발사다.** 실전에서 인자를 빠뜨려 부표가 안 나가면 안
       된다. 인자는 시험 쪽이 붙인다 — 조준만 볼 때 `--no-fire`.
    """
    p = argparse.ArgumentParser(
        description="FloaQ Pi 오케스트레이터",
        epilog="실전은 --servos (발사한다). 시험으로 조준만 보려면 --servos --no-fire.",
    )

    g = p.add_argument_group("선박 · 저장")
    # ⚠ ship_id 주입 절차가 `미정`⚠ TODO(웹) — 부록 C 선박 등록.
    #   모든 MQTT 토픽 경로가 여기 걸려 있다. 확정 전까지는 인자로 받는다.
    g.add_argument("--ship-id", default=None,
                   help="서버가 발급한 uuid. 없으면 프로비저닝 모드로 뜬다")
    g.add_argument("--db", default="floaq.db", help="SQLite 경로")
    g.add_argument("--files", default="data", help="사고 사진·영상 저장 경로")
    g.add_argument("--mmsi", default=None,
                   help="선박 MMSI 9자리. 기본은 pi_ship.mmsi 이고 이 인자가 그걸 덮어쓴다")

    g = p.add_argument_group("MQTT · HTTP")
    g.add_argument("--host", default=config.MQTT_HOST, help="브로커 주소")
    g.add_argument("--port", type=int, default=config.MQTT_PORT_TCP,
                   help="브로커 TCP 포트. 키오스크는 9001(WebSocket)로 붙는다")
    # ⚠ 9001 을 쓰지 않는다. mosquitto WebSocket 리스너가 그 포트다.
    g.add_argument("--http-port", type=int, default=8000,
                   help="선내 HTTP. 사진 업로드·조회와 키오스크 페이지. 0 이면 안 띄운다")

    g = p.add_argument_group("발사 장치  🔴 여기만 부표를 쏜다")
    # 🔴 둘 중 하나만 고른다. 전에는 둘 다 받아서 조용히 aim_only 가 이겼다.
    m = g.add_mutually_exclusive_group()
    m.add_argument("--fake-hw", action="store_true",
                   help="가짜 발사 장치·신고기. 실물 없이 전 과정을 돈다")
    # 🔴 이름이 오해를 불렀다. 옛 `--aim-only-servos` 는 "발사 안 함" 이 아니라
    #    "CH0/CH1 서보를 쓰는 실장비" 라는 뜻이었다. 옛 이름도 계속 받는다.
    m.add_argument("--servos", "--aim-only-servos", dest="aim_only_servos",
                   action="store_true",
                   help="🔴 실장비. PCA9685 CH0 yaw·CH1 pitch 를 구동하고 **발사한다** — "
                        "조준이 --fire-stable-count 회(기본 1회) 연속 안정되면 CH2 로 "
                        "부표가 나간다. 탐지도 사고도 필요 없다. 조준만 보려면 --no-fire")
    g.add_argument("--no-fire", action="store_true",
                   help="시험용. CH2 를 열지 않는다 — CH0/CH1 조준만 본다. "
                        "CH2 객체 자체가 안 만들어져 발사가 불가능하다")
    # 🔴 CH0/CH1 은 명령을 쓰는 즉시 **함께** 움직인다 (servokit._move). 이 대기는
    #    서보가 도착할 시간이다. MG996R 은 60° 에 약 0.2초라 시작 자세에서 목표까지도
    #    0.3초면 닿는다. 1초는 시연에서 느렸다 (2026-09-23).
    g.add_argument("--fire-settle-seconds", type=float, default=0.3,
                   help="CH0/CH1 조준 후 CH2 구동 전 대기 (0~10초). 기본 0.3초")
    # 🔴 Jetson 이 좌우 2쌍 안정된 뒤에만 조준을 보낸다. 여기서 또 여러 번 기다리면
    #    시연에서 느리다 (2026-09-23). 기본 1 = 첫 조준에 바로 쏜다.
    g.add_argument("--fire-stable-count", type=int, default=1,
                   help="조준이 몇 번 연속 같은 곳(yaw ±2°, pitch ±1°)을 가리키면 쏘는가 "
                        "(1~10). 기본 1 — 첫 조준에 바로 쏜다")
    # 시연용 시작 자세. 켜자마자 왼쪽·아래를 본다. 이 자세로는 쏘지 않는다.
    # 🔴 각도가 아니라 **서보 명령값**이다(`2servo.py` 와 같은 숫자). 각도로 주면
    #    보정표·소프트 리밋 끝(-45° / -10°)에서 막혀 더 못 간다 (2026-09-23).
    #    기본값은 2026-09-23 에 `2servo.py` 로 돌려 보고 고른 자세다.
    g.add_argument("--start-ch0", type=float, default=120.0,
                   help="기동 직후 CH0 명령값. 90 초과가 왼쪽. 기본 120")
    g.add_argument("--start-ch1", type=float, default=150.0,
                   help="기동 직후 CH1 명령값. 110 이 기본 자세, 클수록 아래. 기본 150")
    g.add_argument("--ch2-max-seconds", type=float, default=1.3,
                   help="CH2 정방향 구동 시간 (기본 1.3초, 최대 5초). "
                        "이후 중립 0.5초, 역방향 1.2초")
    g.add_argument("--yaw-cal", action="append", default=None, metavar="ANGLE:COMMAND",
                   help="yaw 보정점. 기본은 -15:101.25, 0:90, 15:78.75. 이 범위 밖 각도는 "
                        "거부된다 — 넓히려면 세 점을 직접 준다")
    g.add_argument("--pitch-cal", action="append", default=None, metavar="ANGLE:COMMAND",
                   help="pitch 보정점. 기본은 floaq/config.py 의 PITCH_CAL "
                        "(-10:148.9, 0:140, 25:117.8 — 0:140 만 실측, 임시값)")
    g.add_argument("--pca-address", type=lambda v: int(v, 0), default=0x60,
                   help="PCA9685 I2C 주소. 기본 0x60 (i2cdetect 실측, 2servo.py 와 같다)")

    g = p.add_argument_group("배 GPS  (시각의 출처이기도 하다 — Pi 5 에 RTC 가 없다)")
    g.add_argument("--gps", choices=["fake", "serial", "udp"], default="fake",
                   help="fake 는 고정 좌표를 1Hz 로 흘린다")
    g.add_argument("--gps-port", default=None,
                   help="--gps serial 의 포트 (COM3, /dev/ttyUSB0)")
    g.add_argument("--gps-lat", type=float, default=35.05,
                   help="--gps fake 의 출발 위도. 기본은 부산 앞바다")
    g.add_argument("--gps-lon", type=float, default=129.10,
                   help="--gps fake 의 출발 경도")

    g = p.add_argument_group("선체 IMU")
    g.add_argument("--imu", choices=["off", "i2c", "fake"], default="off",
                   help="i2c 가 실물 MPU6050 이다")
    g.add_argument("--imu-bus", type=int, default=1, help="/dev/i2c-N 의 N")
    g.add_argument("--imu-addr", type=lambda v: int(v, 0), default=0x68,
                   help="AD0 이 HIGH 면 0x69")
    g.add_argument("--imu-zero", default="floaq.imu-zero.json",
                   help="설치 영점 파일. 없으면 각도를 발행하지 않는다 "
                        "(tools/imu_zero.py 로 한 번 잡는다)")

    g = p.add_argument_group("부표 LoRa")
    g.add_argument("--lora", choices=["off", "serial", "udp", "fake"], default="off",
                   help="serial 이 실물 E22 다")
    g.add_argument("--lora-port", default=lora.LORA_PORT,
                   help="--lora serial 의 포트. 배선으로 정해진다 — "
                        "tools/uart_scan.py 로 확인할 것 (/dev/serial0 은 아니다)")
    g.add_argument("--lora-baud", type=int, default=lora.LORA_BAUD, help="기본 9600")
    g.add_argument("--lora-rssi", action="store_true",
                   help="E22 REG3 bit7 을 켜둔 경우. 패킷 뒤 1바이트가 RSSI 라 "
                        "단위가 20바이트가 된다")
    g.add_argument("--lora-any-ship", action="store_true",
                   help="ship_tag 검사를 끈다. 벤치 시험 전용 — 남의 배 부표가 섞인다")

    g = p.add_argument_group("조난 신고")
    g.add_argument("--report", choices=["fake", "udp"], default="fake",
                   help="udp 면 DSC·AIS-MOB·AIS-SART 를 NMEA 로 내보낸다 (시뮬레이션)")
    g.add_argument("--report-host", default="255.255.255.255",
                   help="목적지. OpenCPN 이 도는 PC 주소나 브로드캐스트")
    g.add_argument("--report-port", type=int, default=10110,
                   help="NMEA 0183 over UDP. IETF 할당 포트")

    g = p.add_argument_group("조용한 모드")
    g.add_argument("--offline", action="store_true",
                   help="EC2 로 나가는 것을 전부 끈다 — 선박 등록·전송 펌프·산출물 "
                        "업로더·해양 수집. 조준만 볼 때 로그가 그쪽 재시도로 "
                        "덮이지 않게 한다. 사고 처리·조준·발사는 그대로 돈다")

    g = p.add_argument_group("로그")
    g.add_argument("-v", "--verbose", action="store_true", help="DEBUG 까지 찍는다")
    g.add_argument("--log-file", default=None,
                   help="로그를 이 파일에도 남긴다. 환경변수 FLOAQ_LOG_FILE 로도 지정 가능")


    args = p.parse_args()
    if args.no_fire and not args.aim_only_servos:
        p.error("--no-fire 는 --servos 와 함께 쓴다")
    args.armed = args.aim_only_servos and not args.no_fire
    if not 0 <= args.fire_settle_seconds <= 10:
        p.error("--fire-settle-seconds는 0~10초여야 합니다")
    if not 0 < args.ch2_max_seconds <= 5:
        p.error("--ch2-max-seconds는 0초 초과, 최대 5초여야 합니다")
    if not 1 <= args.fire_stable_count <= 10:
        p.error("--fire-stable-count 는 1~10 이어야 한다")
    return args


def _wait_for_registration(args, conn):
    """배가 없을 때. HTTP 와 등록 루프만 띄우고 `ship_id` 가 생길 때까지 기다린다.

    돌려주는 값은 `(ship_id, name, mmsi)`. Ctrl+C 면 None.

    🔴 MQTT 에 붙지 않는다. 토픽이 전부 `ship/{ship_id}/…` 라서 ship_id 없이는
      브로커에 붙어도 말할 방이 없다. 오케스트레이터도 안 띄운다 — 사고를 만들면
      `pi_accident.ship_id` FK 가 걸린다.

    ⚠ 기다리는 동안 띄운 HTTP·등록 루프는 여기서 정리한다. 정상 모드가 같은 포트로
      다시 띄우므로, 안 내리면 :8000 바인드가 충돌한다.
    """
    pending = provision.PendingShip(Path(str(args.db) + ".pending-ship.json"))
    ocean = OceanProxy(os.environ.get("FLOAQ_EDGE_URL", "https://floaq.example.com"),
                       kiosk_key=os.environ.get("FLOAQ_KIOSK_KEY", ""))

    log.warning("등록 모드 — 선박이 없다. 키오스크에서 등록할 것")
    log.warning("  POST http://<pi>:%d/api/ship  {name, registration_no, mmsi}",
                args.http_port)

    clock = SystemClock()
    http, http_app = _start_http(args, repo=None, clock=clock, conn=conn,
                                 pending=pending, ocean=ocean)
    enroller, _, _ = _start_enroll(args, conn, None, clock, pending, pump=False)
    # 🔴 POST /api/ship 이 이걸 깨운다. 없으면 신청 직후 RETRY_SEC(30초)를 기다리는데,
    #   그동안 화면에 아무 변화가 없어 고장으로 보인다
    http_app.state.enroller = enroller

    try:
        while True:
            found = provision.registered_ship(conn)
            if found is not None:
                log.warning("선박 등록 완료: %s (%s). 이어서 기동한다",
                            found[1], found[0])
                return found
            time.sleep(2)
    except KeyboardInterrupt:
        return None
    finally:
        # 정상 모드가 같은 포트로 다시 띄운다. 여기서 확실히 내린다
        if enroller is not None:
            enroller.stop()
        if http is not None:
            http.should_exit = True
            time.sleep(1.0)


def _start_enroll(args, conn, repo, clock, pending, *, pump=True):
    """등록·승인 루프를 띄운다. 등록 키가 없으면 안 띄운다.

    ⚠ 등록이 안 돼도 선내 동작은 전부 돌아간다 — 사고 판정·투하·조난 신고는
      인터넷과 무관하다. EC2 전송만 대기한다.
    """
    key = os.environ.get("FLOAQ_SHIP_REGISTER_KEY", "")
    url = os.environ.get("FLOAQ_EDGE_URL", "https://floaq.example.com")
    # 🔴 `--ship-id` 로 지정한 배의 키를 본다. registered_ship() 으로 고르면 개발 DB 에
    #   섞인 다른 배를 잡을 수 있고, 그러면 MQTT 토픽과 EC2 전송이 서로 다른 배가 된다.
    got = provision.credential(conn, args.ship_id)
    ship_key = got[0] if got else None

    if not key and not ship_key:
        log.warning("FLOAQ_SHIP_REGISTER_KEY 가 없다. 선박 등록을 건너뛴다 "
                    "(선내 동작은 그대로, EC2 전송만 안 된다)")
        return None, None, None

    client = EdgeClient(url, register_key=key, ship_key=ship_key or "")
    enroller = Enroller(conn, client, pending, clock)
    enroller.start()
    log.info("선박 등록 루프 시작  %s", url)

    # ⚠ 전송 펌프는 등록·승인과 **같은 클라이언트**를 쓴다. `requests.Session` 이
    #   스레드 안전을 보장하지 않아 원래는 안 되는데, 등록 루프가 ACTIVE 를 확인하면
    #   스스로 끝나고(`step()` 이 0 을 돌려준다) 그 뒤로는 펌프만 남는다.
    #   펌프도 승인 전에는 아무것도 안 보내므로 둘이 겹쳐 쓰는 구간이 없다.
    if not pump:
        return enroller, None, None
    sync_pump = SyncPump(conn, repo, client, clock, args.ship_id)
    sync_pump.start()

    # 🔴 산출물 업로더는 **클라이언트를 따로 만든다.** 사고 하나가 수십 MB 라
    #   같은 세션을 쓰면 업로드가 도는 동안 사고·신고 기록이 그만큼 멈춘다.
    #   `requests.Session` 이 스레드 안전이 아닌 것도 같은 이유다.
    files = EdgeClient(url, register_key=key, ship_key=ship_key or "")
    # 🔴 `pi_accident_file.file_path` 는 이 루트 기준 상대경로다. 안 주면 현재 작업
    #   디렉터리에서 찾다가 전부 FileNotFoundError 가 된다.
    archive_pump = ArchivePump(conn, repo, files, clock, args.ship_id,
                               FileStore(Path(args.files)))
    archive_pump.start()
    return enroller, sync_pump, archive_pump


def _start_http(args, repo, clock, conn=None, pending=None, ocean=None):
    """uvicorn 을 데몬 스레드로 띄운다.

    ⚠ uvicorn.run() 을 쓰지 않는다. 그건 블로킹이라 메인 루프의 `tick()` 이 멈춘다.
      30초 카운트다운 판정이 거기 걸려 있다.

    ⚠ 0.0.0.0 에 바인드한다. 키오스크와 Jetson 이 **다른 컴퓨터**다. 127.0.0.1 이면
      Pi 위에서만 보인다. (선내 폐쇄망 전제 — 인터넷에서 들어오는 경로가 없다.)
    """
    import threading

    import uvicorn

    from floaq.web.app import create_app

    kiosk_dir = Path(__file__).parent / "tools"
    app = create_app(ship_id=args.ship_id, repo=repo, clock=clock,
                     store_root=Path(args.files), kiosk_dir=kiosk_dir,
                     conn=conn, pending=pending, ocean=ocean)
    config = uvicorn.Config(app, host="0.0.0.0", port=args.http_port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="http", daemon=True).start()
    log.info("HTTP  http://0.0.0.0:%d  (키오스크 /kiosk/kiosk.html)", args.http_port)
    # ⚠ app 도 돌려준다. uvicorn 내부(`server.config.loaded_app`)를 뒤지면 그쪽 구조가
    #   바뀔 때 조용히 None 이 된다 — 등록 깨우기가 안 먹고 원인이 안 보인다
    return server, app


def main() -> int:
    args = build_args()

    # 🔴 `.env` 를 여기서 읽는다. 셸에서 `set -a && . ./.env` 로 실어주는 방식은
    #   systemd·cron·재부팅 자동 실행에서 안 먹는다 — 그때 키가 조용히 비고,
    #   "EC2 전송만 안 되는" 상태로 뜬다.
    #   override=False 라 이미 환경에 있는 값이 이긴다. 시연 때 한 번만 다른 키를
    #   쓰려면 `FLOAQ_SHIP_REGISTER_KEY=... uv run main.py` 로 덮을 수 있다.
    load_dotenv(Path(__file__).parent / ".env", override=False)

    # ⚠ 로그를 파일로도 남길 때 셸 리다이렉트(`2>&1 | tee`)를 쓰지 않는다.
    #   PowerShell 은 네이티브 exe 의 stderr 를 **에러 레코드로 감싸서** 로그 한 줄마다
    #   NativeCommandError 를 찍는다. 파이썬이 직접 파일에 쓰는 편이 양쪽에서 깨끗하다.
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = args.log_file or os.environ.get("FLOAQ_LOG_FILE")
    if log_file:
        # encoding 을 명시하지 않으면 Windows 에서 cp949 로 열려 한글 로그가 깨진다.
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        handlers=handlers,
    )

    # ── 저장 ─────────────────────────────────────────────────────────
    # 🔴 **파일 존재가 아니라 테이블 존재로 판단한다.** 스키마 적용이 중간에 실패해도
    #   파일은 남는다 — database/pi.sql 이 없어서 죽은 경우가 그렇다. 다음 실행이 그걸
    #   "기존 DB" 로 보고 스키마를 건너뛰면, 빈 DB 로 계속 가면서 원인이 안 보인다.
    conn = connect(args.db)
    has_schema = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pi_accident'"
    ).fetchone() is not None
    if not has_schema:
        if not Path(SCHEMA).exists():
            log.error("스키마가 없다: %s", SCHEMA)
            log.error("  sparse checkout 이면:  git sparse-checkout add sql")
            return 2
        conn.executescript(Path(SCHEMA).read_text(encoding="utf-8"))
    # 코드가 기대하는 컬럼·인덱스가 실제 스키마에 있는지. 드리프트 가드.
    assert_schema_matches(conn)
    repo = SqliteRepo(conn)
    log.info("DB %s (%s)", args.db, "신규 생성" if not has_schema else "기존")

    # ── 선박 등록 확인 ───────────────────────────────────────────────
    # pi_accident 가 pi_ship 을 FK 로 참조한다. 배 정보가 없으면 사고를 만들 수 없다.
    #
    # 🔴 배가 없으면 **프로비저닝 모드**로 뜬다. 예전에는 여기서 종료했는데, 그러면
    #   새 Pi 가 아무것도 못 한다 — 배를 등록하는 `POST /api/ship` 이 이 main.py 가
    #   띄우는 FastAPI 안에 있어서 닭-달걀이 된다.
    #   프로비저닝 모드는 HTTP 와 등록 루프만 돌린다. MQTT 토픽이 ship/{ship_id}/…
    #   라서 ship_id 없이는 브로커에 붙어도 말할 방이 없다.
    if args.ship_id is None:
        found = provision.registered_ship(conn)
        if found is not None:
            args.ship_id = found[0]
            log.info("--ship-id 를 안 줬다. DB 의 배를 쓴다: %s", args.ship_id)

    ship = None
    if args.ship_id is not None:
        ship = conn.execute("SELECT name, mmsi FROM pi_ship WHERE ship_id = ?",
                            (args.ship_id,)).fetchone()
        if ship is None:
            log.error("pi_ship 에 %s 가 없다. --ship-id 를 빼고 실행하면 "
                      "등록 모드로 뜬다", args.ship_id)
            return 2

    if ship is None:
        # 등록될 때까지 기다린 뒤 **그대로 이어서** 뜬다. 재시작하지 않는다 —
        # 등록 모드에서는 MQTT·오케스트레이터가 아직 안 떠 있어서 갈아끼울 게 없다.
        got = _wait_for_registration(args, conn)
        if got is None:
            return 0                      # Ctrl+C
        args.ship_id, name, mmsi_reg = got
        ship = conn.execute("SELECT name, mmsi FROM pi_ship WHERE ship_id = ?",
                            (args.ship_id,)).fetchone()
    log.info("선박 %s  MMSI %s", ship["name"], ship["mmsi"] or "(미등록)")

    # 🔴 MMSI 의 원본은 pi_ship 이다. DSC·AIS 가 전파에 싣는 자기 식별자와
    #   EC2 로 올라가는 선박 정보가 **같은 값이어야 한다.**
    #   갈라져도 OpenCPN 에는 똑같이 잘 뜬다 — 시연 때까지 모르는 종류다.
    #   `--mmsi` 는 등록 전 시험용 덮어쓰기로만 남긴다.
    mmsi = args.mmsi or ship["mmsi"]
    if args.mmsi and ship["mmsi"] and args.mmsi != ship["mmsi"]:
        log.warning("--mmsi %s 가 pi_ship.mmsi %s 를 덮어쓴다. "
                    "전파에 실리는 값과 서버 기록이 갈린다", args.mmsi, ship["mmsi"])

    # ── 하드웨어 ─────────────────────────────────────────────────────
    if args.aim_only_servos:
        from floaq.adapters.servokit import ServoKitAimOnlyLauncher
        try:
            # 🔴 기울기 **음수**다 — 명령값 90 초과가 **왼쪽**이다. 서보가 규약
            #    (+yaw = 오른쪽)과 반대로 달려 있다.
            #
            #    실측 2026-09-23, 발사관 **뒤에서 앞을 보고**, Jetson 을 끄고
            #    `jetson/aim` 을 손으로 쏴서 확인했다. 그때는 CH0/CH1 펄스 범위를
            #    안 걸어 라이브러리 기본 750~2250µs 였다 — 괄호 안이 지금 규약
            #    (500~2500µs, `servokit.POSITION_PULSE_US`) 으로 같은 자세인 값:
            #        yaw -30 -> CH0 60  (67.5)  -> 오른쪽
            #        yaw +30 -> CH0 120 (112.5) -> 왼쪽
            #    `2servo.py` 로도 확인했다: 70 -> 오른쪽, 90 초과 -> 왼쪽.
            #    Jetson 의 yaw 부호는 맞다(왼쪽 사람 -> 음수).
            #
            #    기본값은 그때 앱이 내던 자세를 그대로 유지하도록 환산했다
            #    (`새 숫자 = 22.5 + 0.75 × 옛 숫자`). 1도당 얼마나 도는지는 아직
            #    아무도 안 쟀다 — 방향만 실측이다.
            #
            # ⚠ ai/docs/stereo_targeting.md 와 iot/pi/README.md 의
            #   `-15°→75, +15°→105` 는 "임시" 값이었다(문서가 스스로 그렇게 적었다).
            #   이 실측이 그 임시값을 뒤집는다.
            #
            # ⚠ 방향을 다시 의심하면 코드를 보지 말고 같은 시험을 반복한다.
            #   yaw 가 보정표 **밖**이면 servokit.py:21 이 예외를 던져 서보가
            #   **얼어붙는다** — 반대로 도는 것과 구분이 안 되니 범위 안 각도로 본다.
            yaw_cal = args.yaw_cal or ["-15:101.25", "0:90", "15:78.75"]
            pitch_points = (_parse_calibration(args.pitch_cal) if args.pitch_cal
                            else list(config.PITCH_CAL))
            launcher = ServoKitAimOnlyLauncher(
                yaw_points=_parse_calibration(yaw_cal),
                pitch_points=pitch_points,
                address=args.pca_address,
                armed=args.armed,
                fire_settle_seconds=args.fire_settle_seconds,
                ch2_max_seconds=args.ch2_max_seconds,
                fire_stable_count=args.fire_stable_count,
            )
            # 시연: 켜자마자 왼쪽·아래를 본다 (CH0 90 초과가 왼쪽, 09-23 실측).
            # ⚠ aim() 이 아니라 point() 다 — aim() 은 발사 안정 횟수에 들어간다.
            launcher.point(args.start_ch0, args.start_ch1)
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            log.error("서보 초기화 실패: %s", exc)
            return 2
        if args.yaw_cal is None:
            log.warning("yaw 실측 보정 사용: -15°→101.25, 정면 0°→90, +15°→78.75 "
                        "(명령값 90 초과가 왼쪽)")
        if args.armed:
            log.warning("=" * 62)
            log.warning("🔴 실발사 무장. 조준이 %d회 안정되면 부표가 나간다",
                        args.fire_stable_count)
            log.warning("   발사관 앞을 비울 것. 조준만 보려면 --no-fire")
            log.warning("=" * 62)
        else:
            log.warning("시험 (--no-fire) — CH0/CH1 만 쓴다. CH2 는 열지도 않는다 (발사 불가)")
    elif args.fake_hw:
        launcher = FakeLauncher()
        log.warning("가짜 하드웨어로 실행 중 — 실제로 발사되지 않는다")
    else:
        log.error("--fake-hw 또는 --aim-only-servos 중 하나를 선택할 것")
        return 2

    if args.report == "udp" and mmsi is None:
        # MMSI 없이 DSC 를 만들면 자기 식별자 자리가 비거나 0 으로 채워진다.
        # ITU-R M.493 에서 그 호출은 누구의 조난인지 말하지 못한다.
        log.error("MMSI 가 없다. pi_ship.mmsi 를 등록하거나 --mmsi 를 줄 것")
        return 2

    # ── 배 GPS ───────────────────────────────────────────────────────
    # 🔴 Pi 에 GPS 모듈을 달지 않는다. DSC·AIS 장비를 단 배는 GPS 가 필수라
    #    플로터가 NMEA 를 계속 뱉는다. 그 선에 붙는다.
    #
    # 시계도 여기서 나온다 — Pi 5 는 RTC 배터리가 없고 폐쇄망이라 NTP 도 없다.
    if args.gps == "serial":
        if not args.gps_port:
            log.error("--gps serial 은 --gps-port 가 필요하다")
            return 2
        gnss = gps.SerialGnss(args.gps_port)
    elif args.gps == "udp":
        gnss = gps.UdpGnss()
    else:
        # 시연 기본 위치는 부산 앞바다다 (웹 팀 요청 `확정` 2026-09-17).
        gnss = gps.FakeGnss(lat=args.gps_lat, lon=args.gps_lon)
        log.warning("가짜 GPS  %.4f, %.4f  — 실제 측위가 아니다",
                    gnss.lat, gnss.lon)
        log.warning("가짜 GPS 로 실행 중 — 고정 좌표가 흐른다")
    gnss.start()

    # ── 부표 LoRa ────────────────────────────────────────────────────
    # 🔴 `ship_tag` 를 반드시 넣는다. 남의 배 부표 패킷은 깨끗하게 수신되고 CRC 도
    #    통과한다 — 걸러낼 곳이 어댑터밖에 없고, 빠뜨리면 남의 익수자 좌표가
    #    우리 사고에 기록된다 (`docs/lora.md` §3.4).
    tag = None if args.lora_any_ship else lora_codec.ship_tag(args.ship_id)
    if args.lora == "serial":
        buoy = lora.SerialLoRa(tag, port=args.lora_port, baud=args.lora_baud,
                               rssi=args.lora_rssi)
        log.warning("부표 LoRa %s @%d  ship_tag=0x%02X  RSSI바이트=%s",
                    args.lora_port, args.lora_baud,
                    tag if tag is not None else 0, "on" if args.lora_rssi else "off")
    elif args.lora == "udp":
        buoy = lora.UdpLoRa(tag)
        log.warning("부표 LoRa UDP :%d — 라디오 없이 상류만 시험한다", lora.LORA_UDP_PORT)
    elif args.lora == "fake":
        # 가짜 부표는 반드시 우리 태그로 쏜다. 아니면 어댑터가 자기 것을 걸러낸다
        buoy = lora.FakeLoRa(lora_codec.ship_tag(args.ship_id),
                             lat=args.gps_lat, lon=args.gps_lon)
        log.warning("가짜 부표 1Hz — 실제 수신이 아니다")
    else:
        buoy = None
    if buoy is not None:
        buoy.start()

    # ── 배선 ─────────────────────────────────────────────────────────
    clock = gps.GpsClock(gnss)
    bus = MqttBus(args.ship_id, host=args.host, port=args.port)

    def on_report_status(accident_id: str, st) -> None:
        """신고 채널 상태가 바뀔 때마다 DB 에 남기고 키오스크에 알린다.

        🔴 **이 콜백이 없으면 `pi_report` 가 영영 비어 있다.** UDP 로 실제로 쏴도
          기록이 안 남아 EC2 로 올릴 것도, 관제가 볼 것도 없다. 실제로 그 상태였다.

        어댑터끼리 엮지 않으려고 `UdpReporter` 안에서 SQLite·MQTT 를 만지지 않는다.
        배선은 여기 한 곳이다.
        """
        acc = repo.get(accident_id)
        if acc is None:          # 사고가 지워졌다. 발신은 계속되지만 기록할 곳이 없다
            return
        now = clock.now()
        # 전송 좌표는 **첫 행에 박제**된다. upsert 가 report_lat/lon 을 갱신하지 않으므로
        # 사고 좌표가 나중에 갱신돼도 "무엇을 쐈는지"는 안 흔들린다.
        report_id = repo.upsert_report(
            accident_id, channel=str(st.channel), trigger_kind=st.trigger_kind,
            status=st.status, sent_count=st.sent_count,
            report_lat=acc.accident_lat, report_lon=acc.accident_lon,
            first_sent_at=st.first_sent_at, last_sent_at=st.last_sent_at,
            acked_at=st.acked_at, acked_by=st.acked_by,
            fail_reason=st.fail_reason, now=now)
        bus.publish("pi/report/status", ReportStatus(
            accident_id=accident_id, report_id=report_id, channel=st.channel,
            status=st.status, sent_count=st.sent_count,
            first_sent_at=st.first_sent_at, last_sent_at=st.last_sent_at,
            acked_at=st.acked_at, acked_by=st.acked_by,
            fail_reason=st.fail_reason), retain=True)

    if args.report == "udp":
        # 🔴 **시뮬레이션이다.** 실제 전파가 나가지 않으며 형식 승인된 GMDSS 장비를
        #    대신할 수 없다. 목적지를 반드시 확인할 것 — 사내망 밖으로 나가면
        #    남의 해도에 허위 조난 표적이 뜬다.
        reporter = UdpReporter(ship_mmsi=mmsi, host=args.report_host,
                               port=args.report_port, on_status=on_report_status)
        log.warning("조난 신고 UDP 송출  %s:%d  MMSI %s  (시뮬레이션)",
                    args.report_host, args.report_port, mmsi)
    else:
        reporter = FakeReporter()

    orch = Orchestrator(ship_id=args.ship_id, clock=clock, bus=bus,
                        repo=repo, launcher=launcher, reporter=reporter,
                        # 두절 중 표류 추정에 쓴다. **캐시에서만 읽는다** —
                        # 그 순간 인터넷이 있다는 보장이 없다 (floaq/ocean.py)
                        ocean=OceanStore(repo, args.ship_id))
    # 🔴 `jetson/status` 를 받아 둘 곳. 전에는 구독조차 안 해서 키오스크의
    #    장치 패널(카메라·AI)이 통째로 '모름' 이었다 (`floaq/device.py`).
    jetson_watch = JetsonWatch()
    wire(bus, orch, jetson_watch)

    if not clock.is_valid():
        # 죽이지는 않는다. orchestrator 가 자동 전이를 보류할 뿐이고,
        # GPS fix 를 받으면 그때부터 정상 동작한다.
        log.warning("시계를 믿을 수 없다 (GPS fix 전). 자동 신고를 보류한다")

    bus.start()

    # ── 선체 IMU ─────────────────────────────────────────────────────
    # 🔴 **bus 가 만들어진 뒤여야 한다.** 전에는 GPS 기동 직후에 뒀는데
    #    그 시점에 bus 가 없어서 `--imu` 를 켜면 UnboundLocalError 로
    #    **기동 자체가 죽었다** (2026-09-22). 시험은 MemoryBus 를 직접
    #    넣어서 이 배선 순서를 못 봤다 — main 을 실제로 띄워야 걸린다.
    # 🔴 **인메모리 링버퍼를 쓰지 않는다.** 필요한 것이 "사고 10분 전" 인데,
    #    메모리에만 두면 재부팅에 통째로 사라진다 — 사고는 그 직후에도 난다.
    imu_pump = None
    if args.imu != "off":
        from floaq.adapters.imu import FakeImu, Mpu6050, Tilt
        from floaq.imu import ImuPump

        zero = Tilt.load(args.imu_zero)
        if zero is None:
            # 각도를 0 으로 대신하지 않는다. 화면이 "수평" 으로 읽는다
            log.warning("IMU 영점이 없다 (%s). 가속도만 기록하고 각도는 발행하지 "
                        "않는다 — tools/imu_zero.py 로 한 번 잡을 것", args.imu_zero)
        try:
            dev = (FakeImu(roll=0.0, pitch=0.0, zero=zero) if args.imu == "fake"
                   else Mpu6050(bus=args.imu_bus, addr=args.imu_addr, zero=zero))
            dev.start()
            imu_pump = ImuPump(repo, bus, clock, args.ship_id, dev)
            imu_pump.start()
        except OSError as e:
            # ⚠ IMU 가 없다고 사고 처리를 멈추지 않는다. 기울기 판정만 못 한다
            log.warning("IMU 기동 실패 — 계속 진행한다: %s", e)
            imu_pump = None

    # ⚠ 부팅 복구는 브로커 접속 뒤에 부른다. 복구한 상태를 retained 로 재발행해야 하는데
    #   접속 전이면 그 발행이 버려진다.
    orch.boot()

    # ── 선내 HTTP ────────────────────────────────────────────────────
    # 파일과 키오스크 페이지만 나른다. 이벤트·상태·명령은 MQTT 몫이다.
    #
    # ⚠ **HTTP 가 죽어도 사고 처리는 돌아야 한다.** 그래서 오케스트레이터 뒤에 띄우고,
    #   기동에 실패해도 죽이지 않는다. 화면이 없어도 Pi 는 혼자 신고한다.
    # 키오스크가 넣어둔 등록 대기 값. DB 옆에 둔다 — `pi_ship` 은 PK 가 NOT NULL 이라
    # `ship_id` 없는 행을 담을 수 없다 (floaq/provision.py).
    pending = provision.PendingShip(Path(str(args.db) + ".pending-ship.json"))

    # 키오스크가 EC2 를 직접 부르지 않게 Pi 가 중계한다 `확정` 2026-09-17.
    # 🔴 repo 를 준다. 안 주면 재부팅 뒤 인터넷 없는 바다에서 화면에 조류·바람이
    #    하나도 안 뜬다 — 메모리 캐시는 비었는데 값은 pi_ocean_data 에 있다.
    ocean = OceanProxy(os.environ.get("FLOAQ_EDGE_URL", "https://floaq.example.com"),
                       kiosk_key=os.environ.get("FLOAQ_KIOSK_KEY", ""),
                       repo=repo, ship_id=args.ship_id)

    # 표류 계산에 넣을 값을 미리 받아 둔다. 🔴 **인터넷이 끊긴 뒤에는 못 받는다** —
    # 두절이 나는 순간에는 이미 늦다. 프록시를 같이 쓰므로 키오스크 조회도 덥혀진다.
    # 🔴 `--offline` 이면 EC2 로 나가는 것을 전부 끈다. 조준만 보는데 로그가
    #    409/404 재시도로 덮이면 정작 `aim yaw=` 줄을 못 찾는다.
    ocean_pump = OceanPump(repo, ocean, clock, args.ship_id, gnss)
    if not args.offline:
        ocean_pump.start()

    http = None
    if args.http_port:
        try:
            http, http_app = _start_http(args, repo, clock, conn=conn,
                                         pending=pending, ocean=ocean)
        except Exception:
            log.exception("HTTP 서버 기동 실패 — 사고 처리는 계속한다")

    # ── 선박 등록 ────────────────────────────────────────────────────
    # ⚠ 등록이 안 돼도 선내 동작은 전부 돈다. EC2 전송만 기다린다.
    enroller = pump = archiver = None
    if args.offline:
        log.warning("--offline: EC2 등록·전송·산출물 업로드·해양 수집을 모두 끈다")
    else:
        try:
            enroller, pump, archiver = _start_enroll(args, conn, repo, clock, pending)
            if http is not None:
                http_app.state.enroller = enroller
        except Exception:
            log.exception("선박 등록 루프 기동 실패 — 사고 처리는 계속한다")

    # ── 장치 상태 ────────────────────────────────────────────────────
    # 🔴 **여기가 키오스크 장치 패널의 유일한 원천이다** (`pi/device/status`).
    #    발행하는 쪽이 아예 없어서 카메라·AI·흔들림·부표가 전부 '모름' 이었다.
    #
    # ⚠ 등록 뒤에 만든다. 인터넷 판정을 `EdgeClient.last_ok_at` 으로 하는데
    #   그 객체가 `_start_enroll` 에서 나온다. 등록이 실패해도 None 으로 계속 간다.
    device_pump = DeviceStatusPump(
        bus, clock, launcher=launcher, jetson=jetson_watch,
        gnss=gnss, buoy=buoy, imu=imu_pump,
        edge=getattr(pump, "client", None))
    device_pump.start()

    # ── 종료 처리 ────────────────────────────────────────────────────
    stopping = False

    def shutdown(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── 루프 ─────────────────────────────────────────────────────────
    # 수신은 MqttBus 의 워커 스레드가 처리한다. 이 루프는 주기 작업만 한다.
    log.info("실행 중. Ctrl+C 로 종료")
    last_prune = 0
    last_gps = 0
    last_persist = 0
    last_error_log = 0.0
    # 부표 LoRa 요약 로그 (config.BUOY_LOG_SEC 마다)
    lora_prev = buoy.stats.as_dict() if buoy is not None else {}
    lora_outcomes: dict[str, int] = {}
    lora_last = None
    last_lora_log = time.monotonic()
    try:
        while not stopping:
            # 🔴 **여기서 난 예외가 Pi 전체를 죽였다.** try/finally 만 있어서 SQLite 오류
            #    하나(락 경합·FK·InterfaceError)로 카운트다운·두절 감시·GPS 발행이 전부
            #    멈췄다 (2026-09-23). 한 바퀴를 버리고 다음 바퀴를 돈다. Ctrl+C 는
            #    Exception 이 아니라 그대로 빠져나간다.
            try:
                # 카운트다운 만료와 부표 두절 감시.
                # **키오스크가 살아있든 아니든 Pi 가 혼자 판단한다.**
                orch.tick()

                now = clock.now()

                # 부표 LoRa. 수신은 어댑터 스레드가 하고 여기서는 쌓인 것을 비운다 —
                # 그 스레드에서 SQLite·MQTT 를 만지지 않으려는 것이다.
                #
                # ⚠ 한 프레임이 `pi_buoy` 한 행이라 최신 하나만 쓰면 궤적에 구멍이 난다.
                #   GPS 처럼 스냅샷을 읽지 않고 전부 가져가는 이유다.
                if buoy is not None:
                    for rx in buoy.drain():
                        lora_last = rx
                        # 프레임 하나가 실패해도 이미 꺼낸 나머지는 살린다
                        try:
                            result = orch.on_buoy(rx)
                        except Exception:
                            result = "error"
                            log.exception("부표 프레임 처리 오류 — 이 프레임만 버린다 (seq %s)",
                                          rx.frame.seq)
                        lora_outcomes[result] = lora_outcomes.get(result, 0) + 1

                    # 🔴 받는지·왜 버리는지를 주기마다 한 줄로 찍는다. 받은 게 없어도 찍는다
                    if time.monotonic() - last_lora_log >= config.BUOY_LOG_SEC:
                        last_lora_log = time.monotonic()
                        cur = buoy.stats.as_dict()
                        delta = {k: cur[k] - lora_prev.get(k, 0) for k in cur}
                        log.info("%s", lora.link_summary(
                            delta, lora_outcomes, lora_last, our_tag=tag,
                            foreign_tag=getattr(buoy, "last_foreign_tag", None),
                            window_sec=config.BUOY_LOG_SEC))
                        lora_prev, lora_outcomes, lora_last = cur, {}, None

                # 선박 위치 1Hz 발행. Jetson 의 조준 해 입력이라 5초 전 값을 쓰면 안 된다 —
                # 10노트면 5초에 26m 움직인다.
                if now - last_gps >= config.GPS_PUBLISH_SEC:
                    last_gps = now
                    fix = gnss.read()
                    if fix is not None and fix.valid:
                        bus.publish("pi/sensor/gps", SensorGps(
                            ship_id=args.ship_id, lat=fix.lat, lon=fix.lon,
                            speed_kn=fix.sog_knots or 0.0,
                            heading_deg=fix.cog_deg or 0.0, accuracy_m=None,
                            # ⚠ 발행 시각이 아니라 **측위 시각**이다. Jetson 이 조준 해의
                            #   신선도를 이걸로 판단한다 (LAUNCH_SOLUTION_TTL_SEC).
                            measured_at=fix.utc))

                        # 🔴 **DB 기록 주기는 발행 주기와 다르다.** 발행은 항상 1Hz 지만
                        #   기록은 평시 5초 · 사고 중 1초다. 1Hz 로 다 쌓으면 하루 86,400행
                        #   이고 EC2 배치 상한(`api.md` §4.1 1MB)에 반나절이면 부딪힌다.
                        #   10노트면 5초에 26m 라 지도에서 충분히 부드럽다.
                        period = (config.GPS_PERSIST_SEC_INCIDENT if repo.active()
                                  else config.GPS_PERSIST_SEC)
                        if now - last_persist >= period:
                            last_persist = now
                            # ⚠ created_at 은 **측위 시각**이다. 수신 시각으로 쓰면 두절
                            #   복귀 때 몇 시간 전 위치가 "방금"이 된다 (`api.md` §1.3).
                            #   accuracy_m 은 항상 None — RMC 에 오차 필드가 없다.
                            #   가짜 값을 넣으면 화면의 오차원이 거짓말이 된다.
                            repo.add_position(
                                args.ship_id, lat=fix.lat, lon=fix.lon,
                                speed_kn=fix.sog_knots, heading_deg=fix.cog_deg,
                                accuracy_m=None, measured_at=fix.utc, now=now)

                # 명령 중복 제거 테이블 정리. 키오스크 재시도는 2초 안에 끝나므로 길게 둘 이유가 없다.
                if now - last_prune > 3600:
                    n = repo.prune_commands(now - 86400)
                    if n:
                        log.debug("pi_command_log %d행 정리", n)
                    last_prune = now
            except Exception:
                # 같은 오류가 매초 나면 로그가 덮이므로 1분에 한 번만 스택을 찍는다
                if time.monotonic() - last_error_log >= 60:
                    last_error_log = time.monotonic()
                    log.exception("메인 루프 오류 — 이번 바퀴만 건너뛰고 계속 돈다")

            time.sleep(1)
    finally:
        log.info("종료 중")
        if pump is not None:
            pump.stop()
        if archiver is not None:
            archiver.stop()
        ocean_pump.stop()
        device_pump.stop()
        if imu_pump is not None:
            imu_pump.stop()
        if enroller is not None:
            enroller.stop()
        if http is not None:
            http.should_exit = True
        gnss.stop()
        if buoy is not None:
            log.info("LoRa 링크 통계 %s", buoy.stats.as_dict())
            buoy.stop()
        if hasattr(reporter, "close"):
            reporter.close()
        bus.stop()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

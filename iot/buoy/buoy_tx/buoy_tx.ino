/*
 * 부표 송신기 — GPS 를 읽어 19바이트 프레임을 1Hz 로 쏜다.
 *
 * 규격 정본은 `iot/pi/floaq/contracts/lora.py` 다. 이 파일과 어긋나면 그쪽이 맞다.
 * 받는 쪽은 `iot/pi/floaq/adapters/lora.py` (Pi 5 + E22 직결).
 *
 *     [GPS] --NMEA 9600--> [Uno] --SoftwareSerial 9600--> [E22] ))) --> [Pi]
 *
 * 이 스케치가 하는 일은 넷뿐이다.
 *   1. `$xxRMC` 한 줄을 정수로만 파싱한다
 *   2. 19바이트 빅엔디안 프레임을 만든다 (CRC-16/CCITT-FALSE)
 *   3. GPS 가 조용한 구간에 E22 로 내보낸다
 *   4. 압력 스위치와 전지 눈금을 flags 에 싣는다
 *
 * ── 배선 (Arduino Uno R3) ───────────────────────────────────────────
 *   GPS TXD   ->  D0 (RX, 하드웨어 UART)      ⚠ 아래 "업로드" 와 "콘솔" 참고
 *   GPS RXD   ->  연결 안 함 (설정 안 바꾼다)
 *   E22 TXD   ->  D2                           (안 쓴다. 단방향이다)
 *   E22 RXD   <-  D3                           🔴 분압 필요
 *   E22 M0    ->  GND                          전송 모드
 *   E22 M1    ->  GND                          전송 모드
 *   E22 AUX   ->  연결 안 함
 *   압력 스위치 -> D4 와 GND                    INPUT_PULLUP, 눌리면 LOW
 *   전지 분압  ->  A0
 *
 * ⚠ D2/D3 는 **이미 깔려 있는 배선**이다 (`iot/lora/sketch_sep16a.ino` 의 PING/ACK
 *   응답기와 같은 핀). 그 링크로 Pi 와 왕복이 확인됐으므로 전파 경로는 바꾸지 않는다.
 *   이 스케치는 그 응답기를 **부표 송신기로 갈아끼우는 것**이다:
 *     텍스트 PING/ACK -> 19바이트 이진 프레임 단방향
 *     `String` / `readStringUntil` 제거 (아래 "AVR 함정")
 *
 * 🔴 **D3 -> E22 RXD 에 분압을 넣는다.** Uno 출력은 5V, E22 입력은 3.3V 다.
 *    직결하면 당장은 되다가 나중에 죽는다. 1kΩ + 2kΩ 또는 직렬 2kΩ 하나.
 *    자세한 이유는 `docs/edge/lora.md` §7.3.
 *
 * 🔴 **업로드할 때 GPS TXD 를 D0 에서 빼야 한다.**
 *    Uno 의 D0/D1 은 USB 시리얼 칩(ATmega16U2)과 물리적으로 공유된다. 물려 있으면
 *    업로드가 `avrdude: not in sync: resp=0x00` 으로 실패한다. 이 프로젝트에서
 *    실제로 밟았다 (`docs/edge/lora.md` §9.2).
 *
 *    ⚠ 그런데도 GPS 를 하드웨어 UART 에 둔다. Uno 에는 UART 가 하나뿐인데
 *      **받는 쪽을 SoftwareSerial 에 두면 안 되기 때문**이다. SoftwareSerial 은
 *      송신 중 인터럽트를 꺼서 그 사이 들어온 바이트를 통째로 잃는다. GPS 는 1Hz
 *      로 계속 쏟아지므로 그 손실이 곧 측위 손실이다. E22 는 우리가 **보내기만**
 *      하므로 SoftwareSerial 로 밀어도 잃을 것이 없다.
 *
 * ── 송신 시점 ───────────────────────────────────────────────────────
 * 🔴 **RMC 를 다 읽은 직후에 쏜다.** 아무 때나 쏘면 안 된다.
 *    SoftwareSerial 로 19바이트를 밀면 9600baud 에서 약 20ms 동안 인터럽트가 꺼진다.
 *    그동안 하드웨어 UART 에 들어온 NMEA 는 2바이트 하드웨어 버퍼를 넘겨 버려진다.
 *    GPS 는 매 초 앞쪽 200ms 안에 문장을 몰아 보내고 나머지 800ms 는 조용하다.
 *    그 조용한 구간에 넣으면 충돌이 없다.
 *
 *    ⚠ RMC 가 몰아치기의 앞쪽에 오는 모듈이면 뒤따르던 GGA·GSV 를 잃는다.
 *      **해가 없다.** 우리가 쓰는 문장은 RMC 하나뿐이고, 깨진 줄은 파싱이 실패해
 *      그냥 버려진다. 다음 초에 온전한 RMC 가 다시 온다.
 *
 * ── 지터 ────────────────────────────────────────────────────────────
 * ⚠ 주기가 정확히 1.000초면 근처 부표와 한 번 겹친 뒤 락스텝으로 계속 겹친다.
 *   `docs/edge/lora.md` §5 의 수신 성공률 표는 지터가 있다는 전제다.
 *   여기서는 RMC 도착 시점 자체가 GPS 마다 달라 자연 지터가 있고, 그 위에
 *   TX_JITTER_MS 를 더한다.
 *
 * ── AVR 함정 ────────────────────────────────────────────────────────
 * 🔴 **`int` 가 16비트다.** `era * 146097` 같은 식이 조용히 넘친다.
 *    이 파일의 산술은 전부 `int32_t` / `uint32_t` 로 못 박았다. 고칠 때 유지할 것.
 * 🔴 **`String` 을 쓰지 않는다.** 2KB SRAM 에서 힙이 조각나 며칠 뒤 멈춘다.
 * 🔴 **좌표에 float 을 쓰지 않는다.** float32 는 유효숫자가 7자리라 경도 129도대에서
 *    약 1m 틀어진다. 프레임이 int32 × 1e-7(1.1cm)인 이유가 그것이다.
 *
 * ── 규격 대조 ───────────────────────────────────────────────────────
 * 아래 값으로 만든 프레임은 파이썬과 바이트까지 같아야 한다.
 *
 *   ship_tag=0xC9 seq=7 lat=35.0500000 lon=129.1000000
 *   measured_at=1789000000 is_pressed=1 gps_fix=1 battery=3
 *
 *   10 c9 00 07 14 e4 34 a0 4c f3 18 c0 6a a1 f9 40 0f d7 21
 *
 * `SELFTEST` 를 켜면 부팅 때 이 벡터를 만들어 대조하고 결과를 콘솔에 찍는다.
 * 같은 벡터를 `iot/pi/tests/test_lora_codec.py` 가 파이썬 쪽에서 검사한다 —
 * 한쪽 코덱만 바뀌면 둘 중 하나가 깨진다.
 *
 * ── 가져오는 순서 ───────────────────────────────────────────────────
 * 🔴 **한 번에 하나만 바꾼다.** GPS 와 이진 프레임을 같이 올리면, 프레임이 안 올
 *    때 원인이 셋으로 갈린다 — fix 가 없는가 / 파싱이 틀렸는가 / 프레이밍이 틀렸는가.
 *
 *   1단계  FAKE_GPS 1  — GPS 를 안 붙인다. 고정 좌표를 1Hz 로 쏜다.
 *          바뀌는 것은 "텍스트 PING/ACK -> 19바이트 이진" 하나뿐이다.
 *          전파 경로는 `iot/lora/sketch_sep16a.ino` 로 이미 증명돼 있다.
 *
 *              Pi:  uv run main.py --lora serial --lora-any-ship -v
 *              봐야 할 것: pi_buoy 행이 늘어나는가, LinkStats 의 ok 가 오르는가
 *
 *          ⚠ D0/D1 이 비어 있어 USB 콘솔이 살아 있다. 업로드도 선을 안 빼도 된다.
 *
 *   2단계  FAKE_GPS 0  — NEO-6M 을 D0 에 붙인다. 이때부터 D0/D1 은 GPS 것이다.
 *          업로드할 때마다 GPS TXD 를 뽑아야 한다.
 *
 * ── GPS (u-blox NEO-6M) ─────────────────────────────────────────────
 *   기본 9600 8N1 / 1Hz / RMC 켜져 있음 / 토커는 `$GPRMC` (GPS 전용이라 GN 이 아니다)
 *   좌표 소수 4자리(18.5cm). 프레임은 1.1cm 를 담을 수 있지만 GPS 가 그만큼 안 준다.
 *   TX 가 3.3V 라 Uno 가 HIGH 로 읽는다. GPS RXD 는 안 쓰므로 분압이 필요 없다.
 *
 * ⚠ **실내에서는 fix 가 안 잡힌다.** status 가 계속 `V` 라 프레임이 0개다. 고장이
 *   아니다. 창가나 밖에서 fix 를 잡고 들어올 것.
 *
 * ⚠ 콜드 스타트 약 27초. 발사관 안에서 전원이 꺼져 있으면 투하 후 그만큼 좌표가 없다.
 *   상시 미약 전원을 주면 핫 스타트(약 1초)가 된다.
 */

#include <SoftwareSerial.h>

/* ── 배마다 바꾸는 값 ─────────────────────────────────────────────── */

/*
 * 🔴 `sha256(ship_id)` 의 **첫 바이트**다. 배마다 다르고, 부표를 그 배에 굽는다.
 *
 *    구하는 법:
 *        cd iot/pi
 *        uv run python -c "from floaq.contracts.lora import ship_tag; \
 *                          print(hex(ship_tag('<ship_id>')))"
 *
 *    ⚠ 틀리면 Pi 가 **전부 버린다.** 조용히 버린다 — 로그에 foreign 카운터만 오른다.
 *      부표를 굽고 나서 Pi 의 `LinkStats.foreign` 이 오르면 여기부터 의심할 것.
 */
/* 현재 배: 01a0b2e2-8adf-7d9d-8724-c4b6ae5a5dce (DDD, MMSI 441411223)
 *   sha256(ship_id)[0] = 0x64   `실측` 2026-09-22
 *
 * ⚠ 전에 0xC9 였다. 배를 다시 등록해 ship_id 가 바뀌면서 안 맞게 됐고, Pi 가
 *   부표 프레임을 **전부 조용히 버렸다** — 로그에 foreign 카운터만 올랐다.
 *   등록을 새로 할 때마다 여기를 다시 구해 굽는다. */
#define SHIP_TAG 0x64

/* 부팅 때 규격 대조 벡터를 확인한다. 배포할 때 0 으로 둬도 된다. */
#define SELFTEST 1

/*
 * 1 이면 GPS 를 읽지 않고 고정 좌표를 1Hz 로 쏜다. 위 "가져오는 순서" 1단계다.
 * `adapters/gps.FakeGnss` · `adapters/lora.FakeLoRa` 와 같은 발상이다 —
 * 가짜라도 **진짜 코덱을 통과시켜** 코덱 버그가 시연 날까지 숨지 않게 한다.
 */
#ifndef FAKE_GPS            /* 컴파일 인자로도 덮을 수 있게 둔다 (CI 가 양쪽을 다 짓는다) */
#define FAKE_GPS 1
#endif

/* ── 핀 ───────────────────────────────────────────────────────────── */
const uint8_t PIN_E22_RX = 2;    /* E22 TXD -> 여기. 단방향이라 안 쓴다 */
const uint8_t PIN_E22_TX = 3;    /* 여기 -> E22 RXD. 분압 필요 */
const uint8_t PIN_SWITCH = 4;    /* 압력 스위치. INPUT_PULLUP, 눌리면 LOW */
const uint8_t PIN_BATTERY = A0;

/* ── 상수 ─────────────────────────────────────────────────────────── */
const long GPS_BAUD = 9600;
const long E22_BAUD = 9600;

const uint8_t LORA_VERSION = 1;
const uint8_t MSG_BUOY_POSITION = 0;
const uint8_t FRAME_LEN = 19;

/* GPS 문장이 끝난 뒤 이만큼 기다렸다 쏜다. 200ms 몰아치기가 끝난 다음이다. */
const uint16_t TX_DELAY_MS = 120;
/* ± 이만큼 흔든다. 근처 부표와의 락스텝 충돌을 푼다 */
const uint16_t TX_JITTER_MS = 50;

/* 스위치 흔들림. 파도에 채터링이 난다 */
const uint16_t DEBOUNCE_MS = 50;

#if FAKE_GPS
/* 콘솔 속도. GPS 를 안 붙이므로 D0/D1 이 비어 있다.
 *
 * 🔴 **115200 을 쓰지 않는다.** SoftwareSerial 은 E22 로 19바이트를 밀 때 약 20ms
 *   동안 인터럽트를 끈다. 그동안 하드웨어 UART 가 115200 으로 돌면 바이트를 흘려
 *   **문장 중간이 깨진다.** 증상이 인코딩 문제처럼 보여서 엉뚱한 데를 고치게 된다 —
 *   실제로 그랬다. 9600 이면 한 바이트에 1ms 라 같은 20ms 에 흘릴 것이 훨씬 적다.
 *
 * ⚠ FAKE_GPS 0 일 때의 GPS 속도와도 같은 값이다. 단계를 바꿔도 모니터 속도를
 *   안 건드려도 된다.
 */
const long DEBUG_BAUD = 9600;
/* 부산 앞바다. Pi 의 `gps.BUSAN_OFFSHORE` 와 같은 자리다 — 화면에서 배 옆에 뜬다 */
const int32_t FAKE_LAT_1E7 = 350500000L;
const int32_t FAKE_LON_1E7 = 1291000000L;
/*
 * 시각의 출발점. 부표에 RTC 가 없으니 여기서부터 millis() 로 센다.
 *
 * 🔴 **손으로 박지 않는다.** 전에는 상수 하나였는데(1789000000 = 2026-09-10),
 *    아무도 안 고쳐서 실물 수신 프레임의 measured_at 이 **12.2일 전**으로 왔다
 *    (2026-09-22 실측). 지도와 타임라인에서 익수자가 12일 전에 표류한 것으로
 *    그려지는데, 값이 그럴듯해서 아무도 안 알아챈다.
 *
 *    그래서 **컴파일 시각**에서 만든다 — 굽는 순간이 곧 출발점이라 다시 낡지
 *    않는다. 사람이 기억해야 할 단계가 하나 없어진다.
 *
 * ⚠ 컴파일하는 PC 의 **로컬 시각**이다. UTC 로 바꾸려고 아래 오프셋을 뺀다.
 *   PC 시계가 틀려 있으면 그만큼 틀린다 — 부팅 로그가 그 값을 찍으니 대조할 것.
 * ⚠ 굽고 나서 며칠 뒤에 켜면 그 며칠만큼 과거다. 시연 당일에 굽는 것이 맞다.
 */
#ifndef BUILD_TZ_OFFSET_SEC
#define BUILD_TZ_OFFSET_SEC (9L * 3600L)     /* KST. 다른 표준시면 여기만 고친다 */
#endif
/*
 * 1초에 이만큼 동쪽으로 흘린다(1e-7도 단위). 30 이면 약 0.27m/s.
 *
 * 🔴 **0 이다 — 움직이지 않는다** (2026-09-28). 관제 웹이 부표 이동으로 해류를 잰다
 *    (`FloaQ-web/.../apps/web/src/lib/api/accidents.ts` obsOf: 15분에 30m 이상 움직이면
 *    그 이동에서 풍압을 뺀 값을 **그 자리 해류**로 쓴다). 가짜로 흘리면 관제가 그 가짜
 *    흐름을 진짜 해류로 믿고 수색 계획·표류 예측을 짠다. 0 이면 30m 를 못 넘어 관제는
 *    원래대로 해류 격자(KHOA ROMS)를 쓴다.
 * ⚠ 다시 움직이게 하려면 3 이하로 둔다 — 15분에 약 25m 라 관제의 30m 문턱을 안 넘는다.
 */
const int32_t FAKE_DRIFT_1E7 = 0L;
#endif

/*
 * 전지 눈금 경계 (A0 raw, 0~1023).
 * ⚠ 분압비와 전지 화학에 따라 달라진다. 실측해서 고칠 것 — 지금은 자리만 잡아 둔 값이다.
 */
const uint16_t BATT_LEVEL[3] = { 700, 780, 860 };

/* ── 전역 ─────────────────────────────────────────────────────────── */
SoftwareSerial e22(PIN_E22_RX, PIN_E22_TX);

/* 🔴 전원 인가 시 0. Pi 가 이 값으로 유실을 센다. 순환(18.2시간)은 정상이다 */
uint16_t g_seq = 0;

/* NMEA 한 줄. 표준 상한이 82바이트고 여유를 조금 둔다 */
char g_line[96];
uint8_t g_len = 0;

/* 스위치 디바운스 */
uint8_t g_switch_stable = 0;
uint8_t g_switch_last = 0;
uint32_t g_switch_at = 0;

/* ── CRC-16/CCITT-FALSE ───────────────────────────────────────────── */
/* poly 0x1021, init 0xFFFF. `contracts/lora.py` 의 crc16_ccitt 와 같아야 한다 */
static uint16_t crc16_ccitt(const uint8_t *data, uint8_t len) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
  }
  return crc;
}

/* ── 프레임 ───────────────────────────────────────────────────────── */
/*
 * 🔴 구조체에 대입하지 않는다. AVR 은 리틀엔디안이고 프레임은 빅엔디안이다.
 *    바이트마다 명시적으로 채운다. 이걸 틀리면 **조용히** 좌표가 엉뚱해진다.
 */
static void build_frame(uint8_t *out, uint16_t seq, int32_t lat_1e7, int32_t lon_1e7,
                        uint32_t measured_at, uint8_t is_pressed, uint8_t gps_fix,
                        uint8_t battery) {
  out[0] = (uint8_t)((LORA_VERSION << 4) | (MSG_BUOY_POSITION & 0x0F));
  out[1] = SHIP_TAG;
  out[2] = (uint8_t)(seq >> 8);
  out[3] = (uint8_t)(seq);

  uint32_t la = (uint32_t)lat_1e7;          /* 음수는 2의 보수 그대로 실린다 */
  out[4] = (uint8_t)(la >> 24); out[5] = (uint8_t)(la >> 16);
  out[6] = (uint8_t)(la >> 8);  out[7] = (uint8_t)(la);

  uint32_t lo = (uint32_t)lon_1e7;
  out[8]  = (uint8_t)(lo >> 24); out[9]  = (uint8_t)(lo >> 16);
  out[10] = (uint8_t)(lo >> 8);  out[11] = (uint8_t)(lo);

  out[12] = (uint8_t)(measured_at >> 24); out[13] = (uint8_t)(measured_at >> 16);
  out[14] = (uint8_t)(measured_at >> 8);  out[15] = (uint8_t)(measured_at);

  out[16] = (uint8_t)((is_pressed ? 0x01 : 0) | (gps_fix ? 0x02 : 0)
                      | ((battery & 0x03) << 2));

  uint16_t crc = crc16_ccitt(out, 17);
  out[17] = (uint8_t)(crc >> 8);
  out[18] = (uint8_t)(crc);
}

/* ── 시각 ─────────────────────────────────────────────────────────── */
/*
 * 1970-01-01 부터의 날수. Howard Hinnant 의 days_from_civil 을 AVR 용으로 좁혔다.
 *
 * 🔴 `int` 가 16비트라 `era * 146097`(=730485) 이 그냥 쓰면 넘친다. uint32_t 로 못 박는다.
 */
static uint32_t days_from_civil(uint16_t y, uint8_t m, uint8_t d) {
  uint16_t yy = (uint16_t)(y - (m <= 2 ? 1 : 0));
  uint32_t era = (uint32_t)(yy / 400);
  uint16_t yoe = (uint16_t)(yy - (uint16_t)(era * 400));
  uint16_t doy = (uint16_t)((153U * (uint16_t)(m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1);
  uint32_t doe = (uint32_t)yoe * 365UL + yoe / 4 - yoe / 100 + doy;
  return era * 146097UL + doe - 719468UL;
}

#if FAKE_GPS
/*
 * 컴파일 시각 -> Unix 초.
 *
 * `__DATE__` = "Sep 22 2026" (일이 한 자리면 앞이 공백), `__TIME__` = "14:18:42".
 * 컴파일러가 문자열로 박아 주므로 굽을 때마다 저절로 갱신된다.
 *
 * ⚠ 런타임에 한 번만 판다. constexpr 로 접으려면 C++ 버전을 타고, 32KB 플래시에서
 *   얻는 것이 없다 — setup() 에서 한 번 부르고 끝이다.
 */
static uint32_t build_epoch(void) {
  const char *d = __DATE__;
  const char *t = __TIME__;
  const char *names = "JanFebMarAprMayJunJulAugSepOctNovDec";

  uint8_t mon = 1;
  for (uint8_t i = 0; i < 12; i++) {
    if (names[i * 3] == d[0] && names[i * 3 + 1] == d[1] && names[i * 3 + 2] == d[2]) {
      mon = (uint8_t)(i + 1);
      break;
    }
  }
  /* 일이 한 자리면 d[4] 가 공백이다. 그대로 빼면 음수가 된다 */
  uint8_t day = (uint8_t)((d[4] == ' ' ? 0 : (d[4] - '0') * 10) + (d[5] - '0'));
  uint16_t year = (uint16_t)((d[7] - '0') * 1000 + (d[8] - '0') * 100
                             + (d[9] - '0') * 10 + (d[10] - '0'));

  uint32_t hh = (uint32_t)((t[0] - '0') * 10 + (t[1] - '0'));
  uint32_t mi = (uint32_t)((t[3] - '0') * 10 + (t[4] - '0'));
  uint32_t ss = (uint32_t)((t[6] - '0') * 10 + (t[7] - '0'));

  uint32_t local = days_from_civil(year, mon, day) * 86400UL
                   + hh * 3600UL + mi * 60UL + ss;
  return local - (uint32_t)BUILD_TZ_OFFSET_SEC;
}

/* 부팅 때 한 번 정해진다. 이후 millis() 로 센다 */
uint32_t g_epoch_base = 0;
#endif  /* FAKE_GPS */

/* ── NMEA 파싱 ────────────────────────────────────────────────────── */
/* ⚠ FAKE_GPS 단계에서는 안 쓴다. Uno 플래시가 32KB 라 통째로 뺀다 */
#if !FAKE_GPS
/* n 번째 쉼표 구분 필드의 시작 위치. 없으면 -1 */
static int16_t field_at(const char *s, uint8_t n) {
  uint8_t seen = 0;
  for (int16_t i = 0; s[i]; i++) {
    if (seen == n) return i;
    if (s[i] == ',') seen++;
  }
  return (seen == n) ? (int16_t)strlen(s) : -1;
}

static uint32_t digits(const char *s, uint8_t n) {
  uint32_t v = 0;
  for (uint8_t i = 0; i < n; i++) {
    if (s[i] < '0' || s[i] > '9') return 0;
    v = v * 10 + (uint32_t)(s[i] - '0');
  }
  return v;
}

/*
 * `ddmm.mmmmm` -> 1e-7 도. **정수만 쓴다.**
 *
 * 🔴 점 위치로 자르면 안 된다. `4807.038` 은 48.07도가 아니라 48도 07.038분이다.
 *    그냥 atof 하면 약 5.7km 틀어진다.
 *
 * 소수 5자리로 정규화한다 (모자라면 0 을 채우고 남으면 버린다). 5자리면 1.85cm 라
 * 프레임 해상도(1.1cm)와 사실상 같다.
 */
static int32_t dm_to_1e7(const char *s, char hemi, uint8_t *ok) {
  *ok = 0;
  int16_t dot = -1;
  for (int16_t i = 0; s[i] && s[i] != ','; i++) {
    if (s[i] == '.') { dot = i; break; }
  }
  if (dot < 3) return 0;                       /* 도 2자리 + 분 2자리가 최소 */

  uint32_t deg = digits(s, (uint8_t)(dot - 2));
  uint32_t min_int = digits(s + dot - 2, 2);

  uint32_t frac = 0;
  uint8_t taken = 0;
  for (int16_t i = dot + 1; taken < 5; i++) {
    char c = s[i];
    uint8_t is_digit = (c >= '0' && c <= '9');
    frac = frac * 10 + (is_digit ? (uint32_t)(c - '0') : 0);
    taken++;
    if (!is_digit) {                           /* 자릿수가 모자란다. 0 으로 채운다 */
      for (uint8_t k = taken; k < 5; k++) frac *= 10;
      break;
    }
  }

  uint32_t min_1e5 = min_int * 100000UL + frac;      /* 최대 5,999,999 */
  if (min_1e5 >= 6000000UL) return 0;                /* 분은 60 미만이어야 한다 */
  if (deg > 180) return 0;

  /* 1e-7도 = 도*1e7 + 분_1e5 * 100 / 60. 중간 최대 6.0e8 이라 int32 안이다 */
  int32_t v = (int32_t)(deg * 10000000UL + (min_1e5 * 100UL + 30UL) / 60UL);
  if (hemi == 'S' || hemi == 'W') v = -v;
  *ok = 1;
  return v;
}

/*
 * `$xxRMC` 한 줄에서 위치·시각·fix 를 뽑는다. 성공하면 1.
 *
 * ⚠ 토커 ID 를 `$GP` 로 고정하지 않는다. 요즘 수신기는 대부분 **$GNRMC** 를 낸다.
 *   `$GP` 만 보면 한 줄도 안 잡힌다. 5번째 문자부터 "RMC" 인지로 판정한다.
 */
static uint8_t parse_rmc(const char *s, int32_t *lat, int32_t *lon,
                         uint32_t *utc, uint8_t *fix) {
  if (s[0] != '$') return 0;
  if (s[3] != 'R' || s[4] != 'M' || s[5] != 'C') return 0;

  int16_t f1 = field_at(s, 1);   /* hhmmss.ss  */
  int16_t f2 = field_at(s, 2);   /* A / V      */
  int16_t f3 = field_at(s, 3);   /* ddmm.mmmm  */
  int16_t f4 = field_at(s, 4);   /* N / S      */
  int16_t f5 = field_at(s, 5);   /* dddmm.mmmm */
  int16_t f6 = field_at(s, 6);   /* E / W      */
  int16_t f9 = field_at(s, 9);   /* ddmmyy     */
  if (f1 < 0 || f2 < 0 || f3 < 0 || f4 < 0 || f5 < 0 || f6 < 0 || f9 < 0) return 0;

  /* 🔴 상태가 V 면 fix 가 없다. 좌표도 시각도 쓸 수 없다 */
  *fix = (s[f2] == 'A') ? 1 : 0;
  if (!*fix) return 0;

  uint8_t ok1 = 0, ok2 = 0;
  int32_t la = dm_to_1e7(s + f3, s[f4], &ok1);
  int32_t lo = dm_to_1e7(s + f5, s[f6], &ok2);
  if (!ok1 || !ok2) return 0;

  uint32_t hh = digits(s + f1, 2), mi = digits(s + f1 + 2, 2), ss = digits(s + f1 + 4, 2);
  uint32_t dd = digits(s + f9, 2), mo = digits(s + f9 + 2, 2), yy = digits(s + f9 + 4, 2);
  if (mo < 1 || mo > 12 || dd < 1 || dd > 31) return 0;

  /* ⚠ 연도가 2자리다. NMEA 0183 이 세기를 안 준다 — 2000년대로 본다 */
  uint32_t days = days_from_civil((uint16_t)(2000 + yy), (uint8_t)mo, (uint8_t)dd);

  *lat = la;
  *lon = lo;
  *utc = days * 86400UL + hh * 3600UL + mi * 60UL + ss;
  return 1;
}
#endif  /* !FAKE_GPS */

/* ── 센서 ─────────────────────────────────────────────────────────── */
/*
 * 압력 스위치. 파도에 채터링이 나서 디바운스가 필요하다.
 *
 * ⚠ `is_pressed = 0` 이 "사람이 없다"는 뜻은 아니다 (E9). 잡지 못한 채 떠 있을 수 있다.
 *   그래서 이 값으로 구조 여부를 판단하지 않는다 — 기록만 한다.
 */
static uint8_t read_switch(void) {
  uint8_t now = (digitalRead(PIN_SWITCH) == LOW) ? 1 : 0;
  uint32_t t = millis();
  if (now != g_switch_last) {
    g_switch_last = now;
    g_switch_at = t;
  } else if ((uint32_t)(t - g_switch_at) >= DEBOUNCE_MS) {
    g_switch_stable = now;
  }
  return g_switch_stable;
}

/* 0~3 눈금. 정밀한 전압이 아니다 — 1바이트도 아까운 매체다 */
static uint8_t read_battery(void) {
  uint16_t raw = analogRead(PIN_BATTERY);
  uint8_t level = 0;
  for (uint8_t i = 0; i < 3; i++) {
    if (raw >= BATT_LEVEL[i]) level = (uint8_t)(i + 1);
  }
  return level;
}

/* ── 송신 ─────────────────────────────────────────────────────────── */
static void send_frame(int32_t lat, int32_t lon, uint32_t utc,
                       uint8_t pressed, uint8_t battery) {
  uint8_t frame[FRAME_LEN];
  build_frame(frame, g_seq, lat, lon, utc, pressed, 1, battery);
  e22.write(frame, FRAME_LEN);
  /*
   * ⚠ flush() 로 끝까지 밀어낸 뒤 돌아간다. 안 하면 다음 루프의 GPS 읽기와
   *   송신이 겹쳐, 인터럽트가 꺼진 구간이 NMEA 도착과 부딪힌다.
   */
  e22.flush();
  g_seq++;                                     /* uint16 순환은 정상이다 */
}

/* ── 자가시험 ─────────────────────────────────────────────────────── */
#if SELFTEST
static void selftest(void) {
  const uint8_t want[FRAME_LEN] = {
    0x10, 0xC9, 0x00, 0x07, 0x14, 0xE4, 0x34, 0xA0, 0x4C, 0xF3,
    0x18, 0xC0, 0x6A, 0xA1, 0xF9, 0x40, 0x0F, 0xD7, 0x21
  };
  uint8_t got[FRAME_LEN];
  build_frame(got, 7, 350500000L, 1291000000L, 1789000000UL, 1, 1, 3);

  /*
   * SHIP_TAG 는 배마다 다르므로 그 바이트와 거기 딸린 CRC 는 빼고 본다.
   * 나머지 16바이트가 엔디안·좌표 스케일·flags 배치를 전부 덮는다.
   */
  uint8_t bad = 0;
  for (uint8_t i = 0; i < FRAME_LEN; i++) {
    if (i == 1 || i == 17 || i == 18) continue;
    if (got[i] != want[i]) bad++;
  }

  /* CRC 는 CCITT-FALSE 표준 검사값으로 따로 본다. "123456789" -> 0x29B1 */
  if (crc16_ccitt((const uint8_t *)"123456789", 9) != 0x29B1) bad++;

  /* 시각 변환. 윤년과 3월 경계가 days_from_civil 의 단골 함정이다 */
  if (days_from_civil(2024, 2, 29) * 86400UL + 86399UL != 1709251199UL) bad++;
  if (days_from_civil(2026, 3, 1) * 86400UL != 1772323200UL) bad++;

#if FAKE_GPS
  /* 🔴 컴파일 시각 변환. 여기가 틀리면 프레임 시각이 조용히 며칠씩 밀린다 —
   *   값이 CHECK 를 통과해서 화면에서는 멀쩡해 보인다. 한 자리 일(공백 패딩)과
   *   윤년이 단골 함정이다. 파이썬 쪽과 대조해 확인한 값이다 */
  {
    uint32_t e = build_epoch();
    /* 굽는 시각이 2026-01-01 ~ 2100-01-01 밖이면 파싱이 깨진 것이다 */
    if (e < 1767225600UL || e > 4102444800UL) bad++;
  }
#endif

  Serial.print(F("selftest "));
  Serial.println(bad ? F("FAIL - contracts/lora.py 와 어긋난다") : F("ok"));
}
#endif

/* ── 수명주기 ─────────────────────────────────────────────────────── */
void setup(void) {
  pinMode(PIN_SWITCH, INPUT_PULLUP);
#if FAKE_GPS
  Serial.begin(DEBUG_BAUD);      /* GPS 가 없으니 D0/D1 은 콘솔이다 */
#else
  Serial.begin(GPS_BAUD);        /* GPS. 업로드할 때는 D0 를 빼둘 것 */
#endif
  e22.begin(E22_BAUD);
  randomSeed(analogRead(A1));    /* 지터용. 띄워 둔 핀의 잡음을 쓴다 */
#if SELFTEST
  selftest();
#endif
#if FAKE_GPS
  Serial.println(F("FAKE_GPS - 고정 좌표를 1Hz 로 쏜다. 실제 측위가 아니다"));
  /* 굽는 순간이 시각의 출발점이다. 손으로 고칠 상수가 없다 */
  g_epoch_base = build_epoch();
  /* 🔴 그래도 찍는다. 컴파일한 PC 의 시계가 틀려 있으면 그만큼 틀리고, 그 값은
   *   CHECK 를 통과해서 조용히 지나간다. `date +%s` 와 눈으로 대조할 것. */
  Serial.print(F("  빌드 시각 "));
  Serial.print(F(__DATE__));
  Serial.print(' ');
  Serial.print(F(__TIME__));
  Serial.print(F(" -> epoch "));
  Serial.print(g_epoch_base);
  Serial.println(F("   <- date +%s 와 비교할 것"));
#endif
}

#if FAKE_GPS
/* 1단계. GPS 없이 링크와 프레이밍만 본다 */
void loop(void) {
  static uint32_t last = 0;
  read_switch();

  uint32_t t = millis();
  if ((uint32_t)(t - last) < 1000UL) return;
  last = t;

  uint32_t elapsed = t / 1000UL;
  int32_t lon = FAKE_LON_1E7 + (int32_t)(FAKE_DRIFT_1E7 * (int32_t)elapsed);
  send_frame(FAKE_LAT_1E7, lon, g_epoch_base + elapsed,
             g_switch_stable, read_battery());

  Serial.print(F("TX seq="));
  Serial.println((unsigned)(g_seq - 1));
}
#else
/*
 * 2단계. NEO-6M 을 D0 에 붙인 뒤.
 *
 * 🔴 **조용히 실패하지 않게 한다.** fix 가 없으면 프레임이 0개인데, 그 상태가
 *   "배선이 틀렸다" 와 "실내라 하늘이 안 보인다" 와 **똑같이 생겼다.**
 *   5초마다 세 숫자를 찍어 구분한다:
 *
 *     rx=0            바이트가 아예 안 온다. D0 배선이나 GPS 전원 문제다
 *     rx>0 rmc=0      바이트는 오는데 RMC 가 없다. 보레이트나 문장 설정이다
 *     rmc>0 fix=0     하늘이 안 보인다. 창가로 나갈 것 (콜드 스타트 약 27초)
 *     fix=1 seq 증가   정상
 *
 * ⚠ 이 출력은 D1(USB TX) 로 나간다. GPS 는 D0 만 쓰므로 부딪히지 않는다.
 *   시리얼 모니터를 **9600** 으로 열 것 — 여기서는 Serial 이 GPS 속도다.
 */
void loop(void) {
  static uint32_t last_report = 0;
  static uint16_t n_rx = 0, n_rmc = 0;
  static uint8_t last_fix = 0;

  read_switch();                 /* 디바운스는 계속 돌려야 한다 */

  uint32_t t = millis();
  if ((uint32_t)(t - last_report) >= 5000UL) {
    last_report = t;
    Serial.print(F("rx="));   Serial.print(n_rx);
    Serial.print(F(" rmc=")); Serial.print(n_rmc);
    Serial.print(F(" fix=")); Serial.print(last_fix);
    Serial.print(F(" seq=")); Serial.println(g_seq);
    n_rx = 0;
    n_rmc = 0;
  }

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (n_rx < 0xFFFF) n_rx++;
    if (c == '\r') continue;
    if (c == '\n') {
      g_line[g_len] = '\0';
      /* 파싱이 실패해도 fix 유무는 알아야 한다. 상태 필드만 먼저 본다 */
      if (g_line[0] == '$' && g_line[3] == 'R' && g_line[4] == 'M' && g_line[5] == 'C') {
        n_rmc++;
        int16_t f2 = field_at(g_line, 2);
        last_fix = (f2 >= 0 && g_line[f2] == 'A') ? 1 : 0;
      }
      int32_t lat = 0, lon = 0;
      uint32_t utc = 0;
      uint8_t fix = 0;
      if (parse_rmc(g_line, &lat, &lon, &utc, &fix)) {
        /*
         * 🔴 여기서 바로 쏘지 않고 조금 기다린다. GPS 는 매 초 앞쪽 200ms 에
         *   문장을 몰아 보낸다. 그 와중에 SoftwareSerial 로 밀면 인터럽트가 꺼져
         *   나머지 문장을 잃는다. 몰아치기가 끝난 뒤 조용한 구간을 노린다.
         */
        delay(TX_DELAY_MS + (uint16_t)random(0, TX_JITTER_MS * 2));
        send_frame(lat, lon, utc, g_switch_stable, read_battery());
      }
      g_len = 0;
    } else if (g_len < sizeof(g_line) - 1) {
      g_line[g_len++] = c;
    } else {
      g_len = 0;                 /* 82바이트를 넘었다. 깨진 줄이다 — 버린다 */
    }
  }
}
#endif

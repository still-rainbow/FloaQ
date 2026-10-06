/*
 * Ebyte E22-900T22D <-> PC 다리. 아두이노는 아무 판단도 하지 않는다.
 *
 * 받은 바이트를 반대쪽으로 그대로 넘긴다. 순번·유실률 집계는 전부 PC 가 한다:
 *
 *     python tools\lora_ping.py rx --port COM9
 *     python tools\lora_ping.py tx --port COM10
 *
 * 왜 이렇게 하나
 *   로직을 아두이노에 넣으면 고칠 때마다 업로드해야 한다. 여기 두면 PC 쪽만 고친다.
 *   `tools/lora_ping.py` 는 이미 동작을 확인한 코드다.
 *
 * 모듈 정보 (E22-900T22D)
 *   무선칩   SX1262
 *   주파수   850.125 ~ 930.125 MHz (채널로 선택)
 *   출력     최대 22dBm
 *   UART     공장 기본 9600 8N1
 *   ⚠ 로직 레벨 3.3V. VCC 를 5V 로 줘도 신호선은 3.3V 다.
 *
 * ── 배선 (Arduino Uno R3) ───────────────────────────────────────────
 *   E22 TXD  ->  D10        SoftwareSerial RX   (그대로 연결)
 *   E22 RXD  <-  D11        SoftwareSerial TX   ⚠ 분압 필요
 *   E22 M0   ->  GND        전송 모드
 *   E22 M1   ->  GND        전송 모드
 *   E22 AUX  ->  연결 안 함  (송신 완료 신호. 9600 다리 역할엔 불필요)
 *   E22 VCC  ->  아래 "전원" 참고
 *   E22 GND  ->  GND
 *
 * 🔴 **D0 / D1 을 쓰지 않는다.**
 *    Uno 의 D0/D1 은 USB 시리얼 칩(ATmega16U2)과 물리적으로 공유된다.
 *    여기에 모듈을 물리면 업로드가 `not in sync: resp=0x00` 으로 실패한다.
 *    실제로 이 프로젝트에서 밟았다.
 *
 * ⚠ TX/RX 는 **크로스**다. 모듈 TXD 가 아두이노 수신(D10)으로 들어온다.
 *   같은 이름끼리 맞추면 아무것도 안 온다.
 *
 * 🔴 **D11 -> E22 RXD 에 분압을 넣는다.** Uno 출력은 5V, E22 입력은 3.3V 다.
 *    직결하면 모듈이 손상된다.
 *
 *        D11 ──[ 1kΩ ]──┬── E22 RXD
 *                       │
 *                    [ 2kΩ ]
 *                       │
 *                      GND
 *
 *    반대 방향(E22 TXD 3.3V -> D10)은 그대로 둔다. Uno 는 3.3V 를 HIGH 로 읽는다.
 *    M0 / M1 은 GND 직결이라 레벨 문제가 없다.
 *
 * 🔴 **전원.** 22dBm 송신 순간 전류가 수백 mA 로 튄다.
 *    Uno 의 3.3V 핀은 최대 50mA 라 절대 못 댄다 — 여기서 따면 보드가 브라운아웃된다.
 *    USB 5V 도 빠듯하다. VCC 를 5V 로 주되(E22 VCC 는 2.3~5.5V),
 *    리셋이 반복되면 별도 전원을 쓰고 VCC-GND 사이에 100uF 이상을 단다.
 *
 * ⚠ 안테나 없이 송신하지 않는다. PA 가 손상된다.
 *
 * ⚠ 공장 기본 주파수는 915MHz 대다. **한국 920MHz 대역이 아니다.**
 *   링크 시험은 기본값으로 되지만 실제 운용 전에 채널을 바꿔야 한다.
 *   채널 변경은 설정 모드(M0=1, M1=1)에서 0xC0 프레임으로 한다.
 *
 * ⚠ 양쪽 모듈의 **주소 · 채널 · 공기속도 · UART 속도**가 전부 같아야 한다.
 *   하나만 달라도 패킷이 0 개다. 고장으로 오해하기 쉽다.
 */

#include <SoftwareSerial.h>

// SoftwareSerial(수신핀, 송신핀)
//   D10 = 아두이노가 받는 쪽  -> E22 TXD
//   D11 = 아두이노가 보내는 쪽 -> E22 RXD (분압 거쳐서)
SoftwareSerial lora(10, 11);

// E22 공장 기본값 9600 8N1. 바꿨다면 여기와 PC 쪽 --baud 를 같이 맞춘다.
//
// ⚠ SoftwareSerial 은 Uno 에서 9600 이 안전하다. 38400 까지는 대체로 되고
//   115200 은 취한다. 1Hz 에 19바이트라 9600 으로 충분하다.
const long BAUD = 9600;

void setup() {
  Serial.begin(BAUD);     // PC 쪽 (USB)
  lora.begin(BAUD);       // E22 쪽
}

void loop() {
  // ⚠ SoftwareSerial 은 송신과 수신을 동시에 못 한다.
  //   1Hz 에 19바이트면 겹칠 일이 없다. 더 빠르게 쏘려면 하드웨어 UART 가 있는
  //   보드(Mega, ESP32)로 옮겨야 한다.
  while (lora.available())   { Serial.write(lora.read()); }
  while (Serial.available()) { lora.write(Serial.read()); }
}

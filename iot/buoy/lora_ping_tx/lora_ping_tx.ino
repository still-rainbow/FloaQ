/*
 * LoRa 링크 A/B 핑 — 송신(A, 부표 역할)
 *
 * 규격 검증이 아니다. "전파가 닿느냐"만 본다.
 * 짝: iot/buoy/lora_ping_rx/lora_ping_rx.ino
 *     또는 모듈을 PC 에 직접 꽂았다면 iot/pi/tools/lora_ping.py
 *
 * 필요한 것
 *   라이브러리  Sandeep Mistry "LoRa"  (라이브러리 매니저에서 LoRa 검색)
 *   모듈        SX1276 / SX1278 / RFM95 계열 (SPI)
 *
 * 배선 (Arduino Uno 기준)
 *   MISO  D12      NSS    D10
 *   MOSI  D11      RESET  D9
 *   SCK   D13      DIO0   D2
 *   3.3V / GND
 *
 * ⚠ SX1276 은 3.3V 다. Uno 의 5V 로직을 그대로 물리면 모듈이 죽는다.
 *   3.3V 아두이노를 쓰거나 레벨 시프터를 넣는다.
 *
 * ⚠ 안테나 없이 송신하지 않는다. 모듈 PA 가 손상된다.
 *
 * ⚠ 양쪽(TX/RX)의 주파수 · SF · BW · CR · 동기워드가 전부 같아야 한다.
 *   하나만 달라도 패킷이 0 개다. 고장으로 오해하기 쉽다.
 */

#include <SPI.h>
#include <LoRa.h>

// 한국 920MHz 대역. 실제 채널은 대역 요건 확인 후 확정한다.
const long FREQ_HZ = 920E6;

// 19바이트 프레임 airtime 계산이 이 셋을 전제로 한다 (51.4 ms).
const int SF = 7;
const long BW_HZ = 125E3;
const int CR4 = 5;      // 4/5

const unsigned long PERIOD_MS = 1000;

// 부표 seq 와 같은 의미. 전원 인가 시 0 부터.
unsigned long seq = 0;

void setup() {
  Serial.begin(9600);
  while (!Serial) { ; }

  LoRa.setPins(10, 9, 2);   // NSS, RESET, DIO0
  if (!LoRa.begin(FREQ_HZ)) {
    Serial.println("LoRa 시작 실패 - 배선과 전원을 확인할 것");
    while (1) { ; }
  }
  LoRa.setSpreadingFactor(SF);
  LoRa.setSignalBandwidth(BW_HZ);
  LoRa.setCodingRate4(CR4);

  Serial.println("TX 시작");
}

void loop() {
  // 수신 쪽 파서가 기대하는 모양:  PING <6자리 순번> <초.밀리>
  // ⚠ millis() 는 부팅 후 경과 시간이다. PC 시계와 기준이 달라 '지연' 값은
  //   의미가 없다. 수신 도구가 알아서 무시한다. 여기서 재는 건 유실률이다.
  char line[40];
  unsigned long ms = millis();
  snprintf(line, sizeof(line), "PING %06lu %lu.%03lu", seq, ms / 1000, ms % 1000);

  LoRa.beginPacket();
  LoRa.print(line);
  LoRa.endPacket();          // 전송이 끝날 때까지 블로킹한다

  Serial.print("-> ");
  Serial.println(line);

  seq++;
  delay(PERIOD_MS);
}

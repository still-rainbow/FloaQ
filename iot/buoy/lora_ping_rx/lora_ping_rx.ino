/*
 * LoRa 링크 A/B 핑 — 수신(B, Pi 역할)
 *
 * 받은 것을 그대로 USB 시리얼로 흘린다. 통계는 PC 가 낸다:
 *
 *     python tools\lora_ping.py rx --port COM4
 *
 * 시리얼 모니터로 직접 봐도 된다. 다만 유실률·수신률 집계는 PC 도구가 한다.
 *
 * 설정은 송신(lora_ping_tx)과 **완전히 같아야** 한다.
 * 주파수 · SF · BW · CR 중 하나만 달라도 패킷이 0 개다.
 */

#include <SPI.h>
#include <LoRa.h>

const long FREQ_HZ = 920E6;
const int SF = 7;
const long BW_HZ = 125E3;
const int CR4 = 5;

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

  Serial.println("RX 시작");
}

void loop() {
  int size = LoRa.parsePacket();
  if (size == 0) { return; }

  // 페이로드를 그대로 옮긴다. 여기서 해석하지 않는다.
  while (LoRa.available()) {
    Serial.write((char)LoRa.read());
  }

  // RSSI 를 4번째 칸으로 덧붙인다. PC 도구가 이 칸을 읽는다.
  // 유실이 RSSI 정상인데 나면 충돌, RSSI 가 낮으면 거리다 — 둘을 가르는 근거다.
  Serial.print(' ');
  Serial.println(LoRa.packetRssi());
}

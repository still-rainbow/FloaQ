/*
 * E22 자가진단. 모듈이 UART 로 대답하는지 본다.
 *
 * 🔴 설정 모드여야 한다: M0 = 3.3V, M1 = 3.3V
 *    GND 면 명령이 무선으로 나가버리고 응답이 없다. 이게 가장 흔한 원인이다.
 *
 * 배선 (브리지와 같다)
 *   E22 TXD -> D10,  E22 RXD -> D11(분압),  VCC -> 5V,  GND -> GND
 *
 * ⚠ D10-D11 을 점퍼로 잇는 루프백 시험은 **의미가 없다.**
 *   SoftwareSerial 은 송신 중 인터럽트를 꺼서 그 사이 들어온 바이트를 못 받는다.
 *   되돌아온 바이트가 전부 송신 구간에 도착하므로 항상 0 바이트가 나온다.
 *   하드웨어 UART 였다면 됐을 시험이다.
 *
 * 두 가지 명령 형식을 모두 시험한다:
 *   C1 00 09   SX126x 계열 (E22-900T22D) 레지스터 읽기
 *   C1 C1 C1   구형 SX127x 계열 (E32 등) 파라미터 읽기
 * 어느 쪽이든 응답이 오면 UART 는 살아 있다는 뜻이다.
 */

#include <SoftwareSerial.h>

SoftwareSerial lora(10, 11);   // RX=D10(E22 TXD), TX=D11(E22 RXD)

// 모듈 설정 모드의 UART 는 모듈 설정과 무관하게 항상 9600 8N1 이다.
const long BAUD = 9600;

void setup() {
  Serial.begin(9600);
  while (!Serial) { ; }
  lora.begin(BAUD);

  Serial.println();
  Serial.println("=== E22 자가진단 ===");
  Serial.println("이 줄이 보이면 아두이노와 USB 는 정상이다.");
  Serial.println("M0=3.3V, M1=3.3V 인지 확인할 것. GND 면 응답이 없다.");
  Serial.println();
}

// 명령 하나 보내고 응답 바이트를 전부 긁어서 hex 로 찍는다.
uint8_t probe(const char *label, const uint8_t *cmd, uint8_t len) {
  while (lora.available()) { lora.read(); }      // 찌꺼기 비우기

  Serial.print(label);
  Serial.print("  ");
  lora.write(cmd, len);
  lora.flush();                                   // 송신이 끝나야 수신이 살아난다

  unsigned long deadline = millis() + 800;        // 플래시 접근이 느리다. 넉넉히
  uint8_t buf[32];
  uint8_t n = 0;
  while (millis() < deadline && n < sizeof(buf)) {
    if (lora.available()) { buf[n++] = lora.read(); }
  }

  if (n == 0) {
    Serial.println("-> 0 바이트");
  } else {
    Serial.print("-> ");
    Serial.print(n);
    Serial.print(" 바이트: ");
    for (uint8_t i = 0; i < n; i++) {
      if (buf[i] < 0x10) { Serial.print('0'); }
      Serial.print(buf[i], HEX);
      Serial.print(' ');
    }
    Serial.println();
  }
  return n;
}

void loop() {
  const uint8_t sx126x[3] = { 0xC1, 0x00, 0x09 };   // E22-900T22D
  const uint8_t sx127x[3] = { 0xC1, 0xC1, 0xC1 };   // 구형 E32 계열

  uint8_t a = probe("C1 00 09 (SX126x)", sx126x, 3);
  uint8_t b = probe("C1 C1 C1 (SX127x)", sx127x, 3);

  if (a == 0 && b == 0) {
    Serial.println("   둘 다 무응답. 물리 배선 문제다:");
    Serial.println("     1) M0/M1 이 3.3V 인가  <- 가장 흔함");
    Serial.println("     2) E22 TXD -> D10 크로스가 맞는가");
    Serial.println("     3) E22 GND 가 아두이노 GND 에 연결됐는가");
    Serial.println("     4) VCC 가 5V 핀인가 (3.3V 핀이면 전류 부족)");
  } else {
    Serial.println("   응답 있음. UART 는 살아 있다.");
  }

  Serial.println();
  delay(3000);
}

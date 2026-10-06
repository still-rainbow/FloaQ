#include <SoftwareSerial.h>

// E22 TXD → D2
// D3 → 분압 → E22 RXD
SoftwareSerial lora(2, 3);

void setup() {
  Serial.begin(115200);
  lora.begin(9600);
  lora.setTimeout(500);

  Serial.println("Arduino LoRa 수신 대기");
}

void loop() {
  if (!lora.available()) {
    return;
  }

  String packet = lora.readStringUntil('\n');
  packet.trim();

  if (packet.length() == 0) {
    return;
  }

  Serial.print("RX: ");
  Serial.println(packet);

  lora.print("ACK,");
  lora.println(packet);
  lora.flush();

  Serial.print("TX: ACK,");
  Serial.println(packet);
}

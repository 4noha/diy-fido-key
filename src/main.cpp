#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

// Integrated C3 0.42-inch OLED boards commonly use SDA=5, SCL=6.
// The address probe below verifies communication before initialization.
// Visible window layout reported by Tama79:
// https://qiita.com/Tama79/items/66047c95ccd0864dd203
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE, 6, 5);
constexpr uint8_t X = 28, Y = 24;
bool found = false;
unsigned long frame = 0;

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.printf("DIY OLED TEST boot: chip=%s flash=%u\n", ESP.getChipModel(), ESP.getFlashChipSize());
  Wire.begin(5, 6);
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  for (uint8_t addr = 0x3c; addr <= 0x3d; ++addr) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("I2C ACK 0x%02X SDA=5 SCL=6\n", addr);
      if (addr == 0x3c || addr == 0x3d) {
        oled.setI2CAddress(addr * 2);
        found = true;
        break;
      }
    }
  }
  if (found) {
    Serial.println("Starting OLED initialization");
    Wire.end();
    oled.setBusClock(100000);
    oled.initDisplay();
    Serial.println("OLED initDisplay done");
    oled.clearDisplay();
    Serial.println("OLED clearDisplay done");
    oled.setPowerSave(0);
    oled.setContrast(128);
    Serial.println("OLED initialized SSD1306 128x64 window=72x40 offset=28,24 U8g2");
  } else {
    Serial.println("OLED not found; verify pin mapping");
  }
}

void loop() {
  if (found) {
    oled.clearBuffer();
    oled.drawFrame(X, Y, 72, 40);
    oled.setFont(u8g2_font_5x7_tr);
    oled.drawStr(X + 5, Y + 11, "ESP32-C3");
    oled.drawStr(X + 5, Y + 21, "OLED 72x40");
    oled.setCursor(X + 5, Y + 31);
    oled.print(frame);
    oled.drawBox(X + 2 + frame % 64, Y + 35, 4, 3);
    oled.sendBuffer();
  }
  Serial.printf("HEARTBEAT frame=%lu uptime=%lu oled=%s\n", frame++, millis(), found ? "ACK" : "missing");
  delay(1000);
}

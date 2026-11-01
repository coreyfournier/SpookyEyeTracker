// Animatronic eye - receives gaze targets from the PC tracker over UDP.
//
// Protocol (JSON, one message per datagram, PC -> eye on EYE_PORT):
//   {"t":"look","tgt":1,"pan":12.5,"tilt":-3.0,"new":0}  ~20 Hz, tgt=0 means nobody
//   {"t":"cfg","ver":123,...}                             -> {"t":"ack","ver":123}
//   {"t":"manual","pan":0,"tilt":0,"lid":1,"raw":[0,0,0,0],"hold_s":15}
//   {"t":"release"}
//   {"t":"ping"}                                          -> {"t":"status",...}
//
// Status output depends on the board (see platformio.ini):
//   HAS_OLED        - built-in 128x64 OLED shows activity, IP, signal, pan/tilt
//   PIN_STATUS_LED  - single LED: fast blink = no WiFi, short blip = waiting for the PC,
//                     double blip = idle/wander/sleep, solid = tracking, 2 Hz = manual
// Activity changes are always logged to the serial monitor.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "behavior.h"
#include "eye_config.h"

#ifndef EYE_NAME
#define EYE_NAME "eye"
#endif

#if HAS_OLED
#include <U8g2lib.h>
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, RST_OLED, SCL_OLED, SDA_OLED);
#endif

static WiFiUDP udp;
static char packet[1500];
static uint32_t lastPacketMs = 0;
static uint32_t lastDisplayMs = 0;
static const char *lastActivity = "";

static void wifiBegin() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("animatronic-" EYE_NAME);
#ifdef EYE_STATIC_IP
  IPAddress ip, gw, mask;
  ip.fromString(EYE_STATIC_IP);
  gw.fromString(EYE_GATEWAY);
  mask.fromString(EYE_SUBNET);
  WiFi.config(ip, gw, mask, gw);
#endif
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t) {
    Serial.printf("WiFi connected, ip %s\n", WiFi.localIP().toString().c_str());
  }, ARDUINO_EVENT_WIFI_STA_GOT_IP);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  WiFi.setSleep(false);  // power-save adds 100ms+ of latency to incoming UDP
}

static void reply(const JsonDocument &doc) {
  char out[256];
  size_t n = serializeJson(doc, out, sizeof(out));
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.write((const uint8_t *)out, n);
  udp.endPacket();
}

static void sendStatus() {
  JsonDocument doc;
  doc["t"] = "status";
  doc["id"] = EYE_NAME;
  doc["ver"] = cfg.ver;
  doc["state"] = behaviorStateName();
  doc["act"] = behaviorActivity();
  doc["pan"] = roundf(behaviorPan() * 10) / 10;
  doc["tilt"] = roundf(behaviorTilt() * 10) / 10;
  doc["rssi"] = WiFi.RSSI();
  doc["up"] = millis() / 1000;
  reply(doc);
}

static void handlePacket(int len) {
  len = udp.read(packet, sizeof(packet) - 1);
  if (len <= 0) return;
  packet[len] = 0;
  JsonDocument doc;
  if (deserializeJson(doc, packet, len) != DeserializationError::Ok) return;
  lastPacketMs = millis();
  const char *t = doc["t"] | "";

  if (!strcmp(t, "look")) {
    LookCmd cmd;
    cmd.hasTarget = doc["tgt"] | 0;
    cmd.pan = doc["pan"] | 0.0f;
    cmd.tilt = doc["tilt"] | 0.0f;
    cmd.atMs = lastPacketMs;
    behaviorOnLook(cmd, doc["new"] | 0);
  } else if (!strcmp(t, "cfg")) {
    configFromJson(doc.as<JsonObjectConst>(), cfg);
    configSave(packet);
    JsonDocument ack;
    ack["t"] = "ack";
    ack["ver"] = cfg.ver;
    reply(ack);
    Serial.printf("config v%08lx applied\n", (unsigned long)cfg.ver);
  } else if (!strcmp(t, "manual")) {
    ManualCmd m;
    m.pan = doc["pan"] | 0.0f;
    m.tilt = doc["tilt"] | 0.0f;
    m.lid = doc["lid"] | 1.0f;
    JsonArrayConst raw = doc["raw"];
    for (int i = 0; i < 4 && i < (int)raw.size(); i++) m.rawUs[i] = raw[i] | 0;
    m.untilMs = lastPacketMs + (uint32_t)((doc["hold_s"] | 15.0f) * 1000);
    behaviorOnManual(m);
  } else if (!strcmp(t, "release")) {
    behaviorRelease();
  } else if (!strcmp(t, "ping")) {
    sendStatus();
  }
}

#if HAS_OLED
static void drawStatus() {
  char line[32];
  oled.clearBuffer();

  // Line 1: what the eye is doing right now, large, with the eye's name on the right.
  char act[12];
  snprintf(act, sizeof(act), "%s", behaviorActivity());
  for (char *c = act; *c; c++) *c = toupper(*c);
  oled.setFont(u8g2_font_helvB14_tr);
  oled.drawStr(0, 15, act);
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(128 - oled.getStrWidth(EYE_NAME), 10, EYE_NAME);

  if (WiFi.status() == WL_CONNECTED) {
    oled.drawStr(0, 28, WiFi.localIP().toString().c_str());
    if (lastPacketMs) {
      snprintf(line, sizeof(line), "%d dBm  pc %.1fs ago", WiFi.RSSI(), (millis() - lastPacketMs) / 1000.0f);
    } else {
      snprintf(line, sizeof(line), "%d dBm  waiting for pc", WiFi.RSSI());
    }
  } else {
    oled.drawStr(0, 28, "WiFi connecting...");
    snprintf(line, sizeof(line), "%.21s", WIFI_SSID);
  }
  oled.drawStr(0, 40, line);

  snprintf(line, sizeof(line), "pan %+5.1f tilt %+5.1f", behaviorPan(), behaviorTilt());
  oled.drawStr(0, 52, line);

  // Bottom line: which optional behaviors are switched on.
  snprintf(line, sizeof(line), "%s%s%s", cfg.blinkEnabled ? "blink " : "", cfg.wanderEnabled ? "wander " : "",
           cfg.spookyEnabled ? "spooky" : "");
  oled.drawStr(0, 63, line[0] ? line : "no behaviors on");
  oled.sendBuffer();
}
#elif defined(PIN_STATUS_LED)
static void drawStatus() {
  uint32_t t = millis();
  bool pcOk = lastPacketMs && t - lastPacketMs < 3000;
  const char *act = behaviorActivity();
  bool on;
  if (WiFi.status() != WL_CONNECTED) {
    on = (t / 125) % 2;                                    // fast blink: no WiFi
  } else if (!pcOk) {
    on = t % 2000 < 80;                                    // short blip: waiting for the PC
  } else if (!strcmp(act, "track") || !strcmp(act, "hold") || !strcmp(act, "startle")) {
    on = true;                                             // solid: following someone
  } else if (!strcmp(act, "manual")) {
    on = (t / 250) % 2;                                    // 2 Hz: manual / calibration
  } else {
    uint32_t p = t % 1500;
    on = p < 60 || (p > 200 && p < 260);                   // double blip: idle / wander / sleep
  }
  digitalWrite(PIN_STATUS_LED, on);
}
#else
static void drawStatus() {}
#endif

void setup() {
  Serial.begin(115200);
#if HAS_OLED
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, LOW);  // power the OLED
  delay(50);
  oled.begin();
#elif defined(PIN_STATUS_LED)
  pinMode(PIN_STATUS_LED, OUTPUT);
#endif

  configLoad();
  behaviorBegin();
  wifiBegin();
  udp.begin(EYE_PORT);
  Serial.printf("eye '%s' listening on udp %d\n", EYE_NAME, EYE_PORT);
}

void loop() {
  int len;
  while ((len = udp.parsePacket()) > 0) handlePacket(len);
  behaviorUpdate();
  const char *act = behaviorActivity();
  if (strcmp(act, lastActivity)) {
    lastActivity = act;
    Serial.printf("activity: %s\n", act);
  }
#if HAS_OLED
  if (millis() - lastDisplayMs > 250) {   // the OLED redraw is slow-ish; the LED is cheap
    lastDisplayMs = millis();
    drawStatus();
  }
#else
  drawStatus();
#endif
  delay(1);
}

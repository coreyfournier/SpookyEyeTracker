#include "eye_config.h"
#include <Preferences.h>

EyeConfig cfg;

static void readAxis(JsonObjectConst o, ServoAxis &a) {
  if (o.isNull()) return;
  a.center = o["center"] | a.center;
  a.usPerDeg = o["us_per_deg"] | a.usPerDeg;
  a.minDeg = o["min"] | a.minDeg;
  a.maxDeg = o["max"] | a.maxDeg;
}

static void readLid(JsonObjectConst o, LidServo &l) {
  if (o.isNull()) return;
  l.openUs = o["open"] | l.openUs;
  l.closedUs = o["closed"] | l.closedUs;
}

static void readRgb(JsonArrayConst a, Rgb &c) {
  if (a.size() != 3) return;
  c = {a[0].as<uint8_t>(), a[1].as<uint8_t>(), a[2].as<uint8_t>()};
}

void configFromJson(JsonObjectConst o, EyeConfig &c) {
  c.ver = o["ver"] | c.ver;

  JsonObjectConst s = o["servos"];
  readAxis(s["pan"], c.pan);
  readAxis(s["tilt"], c.tilt);
  readLid(s["lid_upper"], c.lidUpper);
  readLid(s["lid_lower"], c.lidLower);

  JsonObjectConst m = o["motion"];
  c.maxSpeed = m["max_speed"] | c.maxSpeed;
  c.smoothing = m["smoothing"] | c.smoothing;
  c.trackHold = m["track_hold"] | c.trackHold;

  JsonObjectConst b = o["behaviors"];

  JsonObjectConst blink = b["blink"];
  c.blinkEnabled = blink["enabled"] | c.blinkEnabled;
  c.blinkMin = blink["min_s"] | c.blinkMin;
  c.blinkMax = blink["max_s"] | c.blinkMax;
  c.blinkMs = blink["duration_ms"] | c.blinkMs;
  c.doubleBlink = blink["double_chance"] | c.doubleBlink;

  JsonObjectConst w = b["wander"];
  c.wanderEnabled = w["enabled"] | c.wanderEnabled;
  c.wanderMin = w["min_s"] | c.wanderMin;
  c.wanderMax = w["max_s"] | c.wanderMax;
  c.wanderPan = w["range_pan"] | c.wanderPan;
  c.wanderTilt = w["range_tilt"] | c.wanderTilt;

  JsonObjectConst iris = b["iris"];
  c.irisEnabled = iris["enabled"] | c.irisEnabled;
  readRgb(iris["idle"], c.irisIdle);
  readRgb(iris["track"], c.irisTrack);
  readRgb(iris["sleep"], c.irisSleep);
  readRgb(iris["pupil"], c.pupil);
  c.brightness = iris["brightness"] | c.brightness;

  JsonObjectConst sp = b["spooky"];
  c.spookyEnabled = sp["enabled"] | c.spookyEnabled;
  c.flicker = sp["flicker"] | c.flicker;
  c.pulseHz = sp["pulse_hz"] | c.pulseHz;
  c.startle = sp["startle"] | c.startle;

  JsonObjectConst sl = b["sleep"];
  c.sleepEnabled = sl["enabled"] | c.sleepEnabled;
  c.sleepAfter = sl["after_s"] | c.sleepAfter;
  c.sleepLid = sl["lid"] | c.sleepLid;

  JsonObjectConst lids = b["lids"];
  c.lidFollow = lids["follow_gaze"] | c.lidFollow;
  c.lidIdle = lids["idle_open"] | c.lidIdle;
}

void configLoad() {
  Preferences p;
  p.begin("eye", false);  // read-write so the namespace is created on first boot
  String json = p.isKey("cfg") ? p.getString("cfg", "") : String();
  p.end();
  if (json.isEmpty()) return;
  JsonDocument doc;
  if (deserializeJson(doc, json) == DeserializationError::Ok) {
    configFromJson(doc.as<JsonObjectConst>(), cfg);
    Serial.printf("config v%08lx loaded from flash\n", (unsigned long)cfg.ver);
  }
}

void configSave(const char *json) {
  Preferences p;
  p.begin("eye", false);
  p.putString("cfg", json);
  p.end();
}

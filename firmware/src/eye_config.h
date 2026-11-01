#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

// Runtime configuration. Pushed from the PC as JSON ({"t":"cfg", ...}) and
// persisted to flash so the eye behaves sensibly even before the PC connects.
// Field names mirror the `firmware:` block of each eye in tracker/config.yaml.

struct ServoAxis {
  int center;       // microseconds at 0 deg
  float usPerDeg;   // signed: flip to reverse direction
  float minDeg;     // eye-space limits
  float maxDeg;
};

struct LidServo {
  int openUs;
  int closedUs;
};

struct Rgb {
  uint8_t r, g, b;
};

struct EyeConfig {
  uint32_t ver = 0;

  ServoAxis pan{1500, 30.0f, -25.0f, 25.0f};
  ServoAxis tilt{1500, 30.0f, -15.0f, 15.0f};
  LidServo lidUpper{1100, 1700};
  LidServo lidLower{1900, 1300};

  // motion
  float maxSpeed = 400.0f;   // deg/s
  float smoothing = 0.08f;   // s, exponential time constant
  float trackHold = 2.0f;    // s to hold last gaze after target is lost

  // blink
  bool blinkEnabled = true;
  float blinkMin = 2.0f, blinkMax = 7.0f;  // s between blinks
  int blinkMs = 180;
  float doubleBlink = 0.15f;               // probability

  // idle wander
  bool wanderEnabled = true;
  float wanderMin = 1.5f, wanderMax = 5.0f;  // s between glances
  float wanderPan = 15.0f, wanderTilt = 6.0f;

  // LEDs: centre LED = iris (colour by state), ring LEDs = white of the eye
  bool irisEnabled = true;
  Rgb irisIdle{255, 110, 0};
  Rgb irisTrack{255, 0, 0};
  Rgb irisSleep{40, 0, 0};
  Rgb sclera{90, 80, 60};  // white of the eye (the six ring LEDs)
  uint8_t brightness = 160;        // centre LED (iris)
  uint8_t scleraBrightness = 160;  // six ring LEDs (white of the eye)

  // spooky mode
  bool spookyEnabled = false;
  float flicker = 0.3f;   // 0..1 flicker intensity
  float pulseHz = 1.0f;
  bool startle = true;    // snap wide open + flash on new person

  // sleep
  bool sleepEnabled = true;
  float sleepAfter = 60.0f;  // s with nobody around
  float sleepLid = 0.0f;     // lid openness while asleep

  // lids
  bool lidFollow = true;     // lids follow vertical gaze
  float lidIdle = 0.85f;     // normal openness (tracking opens to 1.0)
};

extern EyeConfig cfg;

void configFromJson(JsonObjectConst o, EyeConfig &c);
void configLoad();                 // from flash (defaults if none)
void configSave(const char *json); // raw JSON as received

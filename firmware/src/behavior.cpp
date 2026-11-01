#include "behavior.h"
#include <Adafruit_NeoPixel.h>
#include <ESP32Servo.h>
#include "eye_config.h"

static constexpr uint32_t TICK_MS = 20;          // 50 Hz servo/LED update
static constexpr uint32_t LOOK_STALE_MS = 700;   // PC packets older than this = no target
static constexpr uint32_t STARTLE_MS = 450;

static Servo sPan, sTilt, sLidU, sLidL;
static Adafruit_NeoPixel leds(NUM_LEDS, PIN_LEDS, NEO_GRB + NEO_KHZ800);

static EyeState state = EyeState::Idle;
static LookCmd look;
static ManualCmd manual;

static float curPan = 0, curTilt = 0;      // smoothed gaze
static float goalPan = 0, goalTilt = 0;    // where we want to look
static uint32_t lastTick = 0;
static uint32_t lastTargetMs = 0;          // last time a person was visible
static uint32_t nextBlinkMs = 0, blinkStartMs = 0;
static bool blinkQueuedDouble = false;
static uint32_t nextWanderMs = 0;
static uint32_t startleUntil = 0;
static uint32_t flickerUntil = 0;
static float flickerLevel = 1.0f;
static bool holding = false;
static uint32_t identifyUntil = 0;
static uint8_t identifyRgb[3] = {0, 255, 255};               // tracking a person who just went out of view

static float frand(float a, float b) { return a + (b - a) * (esp_random() / 4294967295.0f); }
static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

static int axisUs(const ServoAxis &a, float deg) {
  deg = clampf(deg, a.minDeg, a.maxDeg);
  return constrain((int)lroundf(a.center + deg * a.usPerDeg), 500, 2500);
}

static int lidUs(const LidServo &l, float open) {
  open = clampf(open, 0, 1);
  return (int)lroundf(l.closedUs + (l.openUs - l.closedUs) * open);
}

static void scheduleBlink(uint32_t now) {
  float k = cfg.spookyEnabled ? 0.5f : 1.0f;
  nextBlinkMs = now + (uint32_t)(frand(cfg.blinkMin, cfg.blinkMax) * 1000 * k);
}

static void scheduleWander(uint32_t now) {
  nextWanderMs = now + (uint32_t)(frand(cfg.wanderMin, cfg.wanderMax) * 1000);
}

void behaviorBegin() {
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  for (Servo *s : {&sPan, &sTilt, &sLidU, &sLidL}) s->setPeriodHertz(50);
  sPan.attach(PIN_SERVO_PAN, 500, 2500);
  sTilt.attach(PIN_SERVO_TILT, 500, 2500);
  sLidU.attach(PIN_SERVO_LID_UPPER, 500, 2500);
  sLidL.attach(PIN_SERVO_LID_LOWER, 500, 2500);
  leds.begin();
  leds.clear();
  leds.show();
  uint32_t now = millis();
  scheduleBlink(now);
  scheduleWander(now);
  lastTargetMs = now;
}

void behaviorOnLook(const LookCmd &cmd, bool newTarget) {
  bool wasTracking = state == EyeState::Track;
  look = cmd;
  if (cmd.hasTarget) {
    if ((newTarget || !wasTracking) && cfg.spookyEnabled && cfg.startle) {
      startleUntil = cmd.atMs + STARTLE_MS;
    }
    lastTargetMs = cmd.atMs;
  }
}

void behaviorOnManual(const ManualCmd &cmd) { manual = cmd; }

void behaviorRelease() { manual.untilMs = 0; }

void behaviorIdentify(bool on, uint8_t r, uint8_t g, uint8_t b, uint32_t holdMs) {
  identifyRgb[0] = r, identifyRgb[1] = g, identifyRgb[2] = b;
  identifyUntil = on ? millis() + holdMs : 0;
}

bool behaviorIdentifying() { return millis() < identifyUntil; }

// Blink envelope: 1 = open, dips to 0 and back over blinkMs.
static float blinkFactor(uint32_t now, bool allowed) {
  if (!cfg.blinkEnabled || !allowed) {
    blinkStartMs = 0;
    return 1.0f;
  }
  if (blinkStartMs == 0 && now >= nextBlinkMs) {
    blinkStartMs = now;
    blinkQueuedDouble = frand(0, 1) < cfg.doubleBlink;
  }
  if (blinkStartMs == 0) return 1.0f;
  uint32_t t = now - blinkStartMs;
  if (t >= (uint32_t)cfg.blinkMs) {
    blinkStartMs = 0;
    if (blinkQueuedDouble) {
      nextBlinkMs = now + 80;  // short gap, then blink again
    } else {
      scheduleBlink(now);
    }
    return 1.0f;
  }
  float x = (float)t / cfg.blinkMs;  // 0..1
  return fabsf(1.0f - 2.0f * x);     // triangle: 1 -> 0 -> 1
}

static Rgb scale(Rgb c, float k) {
  k = clampf(k, 0, 1);
  return {(uint8_t)(c.r * k), (uint8_t)(c.g * k), (uint8_t)(c.b * k)};
}

static void updateLeds(uint32_t now) {
  if (now < identifyUntil) {   // one slowly pulsing colour on every LED, nothing else
    float k = 0.55f + 0.45f * sinf(now * 0.001f * TWO_PI * 0.7f);
    leds.setBrightness(255);
    for (int i = 0; i < NUM_LEDS; i++)
      leds.setPixelColor(i, identifyRgb[0] * k, identifyRgb[1] * k, identifyRgb[2] * k);
    leds.show();
    return;
  }
  Rgb iris;
  float level = 1.0f;
  if (!cfg.irisEnabled) {
    iris = cfg.irisIdle;
  } else {
    switch (state) {
      case EyeState::Track:
      case EyeState::Manual: iris = cfg.irisTrack; break;
      case EyeState::Sleep:
        iris = cfg.irisSleep;
        level = 0.55f + 0.45f * sinf(now * 0.001f * TWO_PI * 0.2f);  // slow breathing
        break;
      default: iris = cfg.irisIdle; break;
    }
  }

  if (cfg.spookyEnabled) {
    level *= 0.75f + 0.25f * sinf(now * 0.001f * TWO_PI * cfg.pulseHz);
    if (now >= flickerUntil) {
      bool dip = frand(0, 1) < cfg.flicker * 0.08f;  // per-tick chance
      flickerLevel = dip ? frand(0.05f, 0.5f) : 1.0f;
      flickerUntil = now + (dip ? (uint32_t)frand(40, 160) : TICK_MS);
    }
    level *= flickerLevel;
  }

  bool flash = now < startleUntil && (now + STARTLE_MS - startleUntil) < 150;
  // the iris and the white have their own brightness, so scale each colour here rather than
  // with the strip's single setBrightness()
  Rgb centre = scale(flash ? Rgb{255, 255, 255} : scale(iris, level), cfg.brightness / 255.0f);
  Rgb white = scale(flash ? Rgb{255, 255, 255} : scale(cfg.sclera, level), cfg.scleraBrightness / 255.0f);

  leds.setBrightness(255);
  // Jewel: LED 0 is the centre - the LED insert's funnel carries it to the iris.
  // LEDs 1..6 are the ring, outside the funnel - they light the white of the eye.
  leds.setPixelColor(0, centre.r, centre.g, centre.b);
  for (int i = 1; i < NUM_LEDS; i++) leds.setPixelColor(i, white.r, white.g, white.b);
  leds.show();
}

void behaviorUpdate() {
  uint32_t now = millis();
  if (now - lastTick < TICK_MS) return;
  float dt = (now - lastTick) / 1000.0f;
  lastTick = now;

  bool targetFresh = look.hasTarget && (now - look.atMs) < LOOK_STALE_MS;
  float lidBase;

  holding = false;
  if (now < manual.untilMs) {
    state = EyeState::Manual;
    goalPan = manual.pan;
    goalTilt = manual.tilt;
    lidBase = manual.lid;
  } else if (now < identifyUntil) {
    state = EyeState::Identify;
    goalPan = goalTilt = 0;
    lidBase = 1.0f;
  } else if (targetFresh) {
    state = EyeState::Track;
    goalPan = look.pan;
    goalTilt = look.tilt;
    lidBase = 1.0f;
  } else if (state == EyeState::Track && now - lastTargetMs < cfg.trackHold * 1000) {
    holding = true;
    lidBase = 1.0f;  // hold gaze where the person was last seen
  } else if (cfg.sleepEnabled && now - lastTargetMs > cfg.sleepAfter * 1000) {
    state = EyeState::Sleep;
    goalPan = 0;
    goalTilt = cfg.tilt.minDeg * 0.5f;  // droop
    lidBase = cfg.sleepLid;
  } else {
    state = EyeState::Idle;
    lidBase = cfg.lidIdle;
    if (cfg.wanderEnabled) {
      if (now >= nextWanderMs) {
        goalPan = frand(-cfg.wanderPan, cfg.wanderPan);
        goalTilt = frand(-cfg.wanderTilt, cfg.wanderTilt);
        scheduleWander(now);
      }
    } else {
      goalPan = goalTilt = 0;
    }
  }

  goalPan = clampf(goalPan, cfg.pan.minDeg, cfg.pan.maxDeg);
  goalTilt = clampf(goalTilt, cfg.tilt.minDeg, cfg.tilt.maxDeg);

  // Smooth towards the goal with a speed cap.
  float alpha = cfg.smoothing > 0 ? 1.0f - expf(-dt / cfg.smoothing) : 1.0f;
  float maxStep = cfg.maxSpeed * dt;
  curPan += clampf((goalPan - curPan) * alpha, -maxStep, maxStep);
  curTilt += clampf((goalTilt - curTilt) * alpha, -maxStep, maxStep);

  // Lids
  if (now < startleUntil) lidBase = 1.0f;
  float upper = lidBase, lower = lidBase;
  if (cfg.lidFollow && state != EyeState::Sleep) {
    float t = cfg.tilt.maxDeg > 0 ? curTilt / cfg.tilt.maxDeg : 0;  // ~ -1..1
    upper = clampf(upper + 0.15f * t, 0, 1);
    lower = clampf(lower - 0.15f * t, 0, 1);
  }
  float blink = blinkFactor(now, state != EyeState::Sleep && state != EyeState::Manual && state != EyeState::Identify);
  upper *= blink;
  lower *= blink;

  bool raw = state == EyeState::Manual;
  sPan.writeMicroseconds(raw && manual.rawUs[0] ? manual.rawUs[0] : axisUs(cfg.pan, curPan));
  sTilt.writeMicroseconds(raw && manual.rawUs[1] ? manual.rawUs[1] : axisUs(cfg.tilt, curTilt));
  sLidU.writeMicroseconds(raw && manual.rawUs[2] ? manual.rawUs[2] : lidUs(cfg.lidUpper, upper));
  sLidL.writeMicroseconds(raw && manual.rawUs[3] ? manual.rawUs[3] : lidUs(cfg.lidLower, lower));

  updateLeds(now);
}

EyeState behaviorState() { return state; }
float behaviorPan() { return curPan; }
float behaviorTilt() { return curTilt; }

const char *behaviorActivity() {
  switch (state) {
    case EyeState::Manual: return "manual";
    case EyeState::Identify: return "identify";
    case EyeState::Sleep: return "sleep";
    case EyeState::Track:
      if (millis() < startleUntil) return "startle";
      return holding ? "hold" : "track";
    default: return cfg.wanderEnabled ? "wander" : "idle";
  }
}

const char *behaviorStateName() {
  switch (state) {
    case EyeState::Track: return "track";
    case EyeState::Sleep: return "sleep";
    case EyeState::Manual: return "manual";
    default: return "idle";
  }
}

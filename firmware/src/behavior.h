#pragma once
#include <Arduino.h>

enum class EyeState { Idle, Track, Sleep, Manual, Identify };

// Latest command from the PC.
struct LookCmd {
  bool hasTarget = false;
  float pan = 0, tilt = 0;  // eye-space degrees (+pan right, +tilt up)
  uint32_t atMs = 0;        // millis() when received
};

struct ManualCmd {
  float pan = 0, tilt = 0, lid = 1.0f;
  int rawUs[4] = {0, 0, 0, 0};  // pan, tilt, lidUpper, lidLower; 0 = use pan/tilt/lid
  uint32_t untilMs = 0;
};

void behaviorBegin();
void behaviorOnLook(const LookCmd &cmd, bool newTarget);
void behaviorOnManual(const ManualCmd &cmd);
void behaviorRelease();
// Identify: all LEDs one pulsing colour, eye centred and still with lids open, no tracking,
// wander or blink - so you can tell which physical eye you're configuring. Manual control
// still works (LEDs keep the identify colour). Ends at untilMs or behaviorIdentify(false).
void behaviorIdentify(bool on, uint8_t r = 0, uint8_t g = 255, uint8_t b = 255, uint32_t holdMs = 60000);
bool behaviorIdentifying();
void behaviorUpdate();  // call every loop; runs at ~50 Hz internally

EyeState behaviorState();
const char *behaviorStateName();
const char *behaviorActivity();  // what the eye is doing right now: track, hold, wander, sleep, ...
float behaviorPan();
float behaviorTilt();

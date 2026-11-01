#pragma once
#include <Arduino.h>

enum class EyeState { Idle, Track, Sleep, Manual };

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
void behaviorUpdate();  // call every loop; runs at ~50 Hz internally

EyeState behaviorState();
const char *behaviorStateName();
float behaviorPan();
float behaviorTilt();

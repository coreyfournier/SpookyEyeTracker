# Eye firmware

## Keep the simulator in step

The tracker's eye simulator (`tracker/eyetracker/static/sim/behavior.js`) is a line-for-line
port of this firmware's logic. Any change to the eye's logic here must be made there too, in
the same commit, using the same names and order:

| Firmware | Simulator (`behavior.js`) |
|---|---|
| `src/behavior.cpp`: states, blink, wander, sleep, startle, smoothing, lids, LED colours | `EyeBehavior` methods of the same names (`tick` is `behaviorUpdate`) |
| `src/eye_config.h`: defaults | `defaultConfig()` |
| `src/eye_config.cpp`: `configFromJson` keys | `configFromJson()` |
| `src/main.cpp`: how look/manual/identify/release packets become behaviour calls | `pollSent()` in `tracker/eyetracker/static/sim.html` |

If a change can't be mirrored (hardware-only: pins, servo attach, OTA, OLED, WiFi), say so
in the commit message. After changing both, check the simulator at `/sim` in demo mode.

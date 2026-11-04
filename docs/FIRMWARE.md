# Eye controller firmware (ESP32)

Each eye runs its own ESP32. It drives four servos (pan, tilt, upper lid, lower lid) and a
7-LED WS2812B jewel, and runs the eye's behaviours by itself: blinking, glancing around,
sleeping, and colours by mood. The tracker on the PC only tells it where to look, so an
eye keeps acting alive even when the PC is off. Settings are pushed from the tracker's UI
and stored in the eye's flash, and new firmware can be installed over WiFi.

[← Back to the overview](../README.md)

- [Supported boards](#supported-boards)
- [Shopping list](#shopping-list)
- [Build and flash](#build-and-flash)
- [Over-the-air updates](#over-the-air-updates)
- [Firmware versions](#firmware-versions)
- [Adding an eye](#adding-an-eye)
- [What the eye shows](#what-the-eye-shows)
- [Behaviours](#behaviours)
- [Settings and config push](#settings-and-config-push)
- [Protocol (UDP, JSON, port 4210)](#protocol-udp-json-port-4210)
- [Source layout](#source-layout)

## Supported boards

| Eye | Board | PlatformIO board | Display / status |
|-----|-------|------------------|------------------|
| `eye1` | [HiLetgo ESP32 OLED WiFi Kit](https://www.amazon.com/dp/B07DKD79Y9) | `heltec_wifi_kit_32_v2` | 0.96" OLED: activity, IP, WiFi, pan/tilt |
| `eye2` | Adafruit HUZZAH32 ESP32 Feather | `featheresp32` | Red LED on GPIO 13 (blink patterns) |

Both are classic ESP32s. Pins, power and the LED ring's order are in
[WIRING.md](WIRING.md). Servos use GPIO 26/27/32/33 on both boards; the LED data pin is 13
on the HiLetgo and 21 on the Feather.

## Shopping list

Per eye, unless noted.

| Qty | Part | Notes |
|----:|------|-------|
| 1 | [HiLetgo ESP32 OLED WiFi Kit](https://www.amazon.com/dp/B07DKD79Y9) | Classic ESP32 + 0.96" OLED. Firmware target `heltec_wifi_kit_32_v2` |
| *or* | Adafruit HUZZAH32 ESP32 Feather | Classic ESP32, no display; status on the red LED. Firmware target `featheresp32` |
| 1 | [WS2812B 7-LED RGB ring ("jewel")](https://www.amazon.com/dp/B0B2D6JDVJ) | One ring per eye; the pack has 7, enough for 7 eyes. Lights the iris and the white of the eye |
| 4 | SG90 micro servo (9 g) | Pan, tilt, upper lid, lower lid. MG90S (metal gear) is a drop-in upgrade, and worth it for pan: that servo carries the eye on its shaft |
| 1 | 5 V USB-C power supply, **3 A or more**, and a USB-C cable | Powers the servos, LEDs and board. Four servos can stall at over 2 A, so don't use a PC port or a 1–2 A phone charger |
| 1 | [USB-C panel-mount pigtail, 5-wire, 24 AWG](https://www.amazon.com/dp/B0D2M91MSJ) (MEIRIYFA, pack of 5) | Power socket in the frame's 7/16 in side-wall hole. Wires V, G, CC (D+/D− unused). Needs a 5.1 kΩ resistor from CC to G, see [WIRING.md](WIRING.md#power) |
| 1 | 5.1 kΩ resistor | CC to GND on the pigtail, so a USB-C charger turns its 5 V on |
| 1 | 1000 µF electrolytic capacitor, 10 V+ | Across 5 V/GND near the servos |
| 1 | 330 Ω resistor | In series with the LED data line |
| — | Jumper wires / 22 AWG hookup wire | Servo leads to GPIO 26/27/32/33, shared ground. See [WIRING.md](WIRING.md) |
| 1 | USB data cable | Flashing and serial monitor (USB-C on the HiLetgo kit) |
| *opt.* | 74AHCT125 level shifter | Only if the LED colours glitch with 3.3 V data |

## Build and flash

You need [PlatformIO](https://platformio.org/) (the VS Code extension or `pip install platformio`).

**WiFi credentials** come from the `ENV_WIFI_SSID` / `ENV_WIFI_PW` environment variables at
build time (set them in your shell, not in `.env`). The OTA password comes from
`EYE_OTA_PASSWORD` (environment, else `.env`). The build warns if any of these is missing.

First flash, over USB:

```powershell
cd firmware
pio run -e eye1 -t upload        # HiLetgo OLED kit
pio run -e eye2 -t upload        # Adafruit HUZZAH32 Feather
pio device monitor
```

The serial log (and the OLED, on the HiLetgo board) shows the eye's IP address once it
joins WiFi. Put that IP in the tracker's config for this eye.

Flash with the servo horns removed the first time: on boot the servos go to their
configured centres. See [WIRING.md → first power-up](WIRING.md#first-power-up).

## Over-the-air updates

After the first USB flash, update an eye over WiFi:

```powershell
pio run -e eye1_ota -t upload    # builds eye1 and uploads it; IP comes from the running tracker
pio run -e eye2_ota -t upload --upload-port 192.168.2.144    # or give the IP yourself
```

You can also use **Update firmware…** on an eye's card in the tracker UI and pick
`firmware/.pio/build/<eye>/firmware.bin`.

During an update the eye holds still and shows `UPDATING n%` on the OLED (the Feather's
LED flickers). It then reboots into the new firmware, and its firmware badge in the UI
turns green once it's current.

How OTA is protected:
- Updates need `EYE_OTA_PASSWORD`. It's baked into the firmware at build time and checked
  on each upload (HTTP Basic auth, user `eye`). Builds without it have no update endpoint.
- The eye rejects an image built for the other board type (HTTP 409), since the pins differ.
- Both board layouts keep two app slots, so a failed upload leaves the old firmware running.

`scripts/ota_upload.py` is the uploader behind the `_ota` environments. It can also be run
on its own: `python scripts/ota_upload.py --eye eye1 .pio/build/eye1/firmware.bin`.

## Firmware versions

Each build is stamped with:
- **version:** the first 7 characters of the last git commit that touched `firmware/`, plus
  `-dirty` if there are uncommitted changes;
- **built:** the build date;
- **board:** the PlatformIO board id.

The eye reports these in its status. The tracker compares the version with the latest
commit, or with the version baked into its Docker image by CI. Each eye's badge in the UI
shows **current**, **outdated** (red: reflash it), **dev** (built from uncommitted changes)
or **unknown**.

## Adding an eye

Each `[env:eyeN]` in `firmware/platformio.ini` is one physical eye. It builds on a board
section (`[heltec]` or `[feather]`) and sets `EYE_NAME`. To add another eye:
1. Copy an env (and its `_ota` twin), and give it the next name.
2. Flash it.
3. Add a matching entry under `eyes:` in the tracker config (or on the UI's Eyes tab) with
   its IP.

## What the eye shows

**OLED (HiLetgo).**
- At boot: a splash with the eye's name, firmware version, build date and board.
- Top line, large: what the eye is doing right now: **TRACK**, **HOLD**, **STARTLE**,
  **WANDER**, **IDLE**, **SLEEP**, **MANUAL** or **IDENTIFY**.
- Below that: the IP, WiFi signal, time since the last PC packet, the current pan/tilt,
  and which optional behaviours are on.
- During an update: `UPDATING n%`.

**Status LED (Feather).**

| Pattern | Meaning |
|---------|---------|
| Fast blink | No WiFi |
| Short blip | On WiFi, waiting for the PC |
| Double blip | Idle / wandering |
| Solid | Tracking someone (or holding / startled) |
| 1 Hz blink | Identify |
| 2 Hz blink | Manual control |
| Flicker | Firmware update in progress |

The tracker UI shows the same activity on each eye's card.

## Behaviours

Each one is a setting on the eye's card in the tracker UI, and can be switched off.

| Behaviour | What it does |
|-----------|--------------|
| **Track** | Looks at the person the tracker picked, easing toward them (`motion.smoothing`) at up to `motion.max_speed`. Holds its gaze for `motion.track_hold` seconds after they disappear |
| **Blink** | Random blinks every `min_s`-`max_s` seconds, sometimes a double blink |
| **Wander** | With nobody around, glances to random spots within `range_pan`/`range_tilt` |
| **Iris colour** | The centre LED (iris) shows a colour per state: idle, track, sleep. The six ring LEDs light the white of the eye in the `sclera` colour. `brightness` sets the iris and `sclera_brightness` the white, so you can make the iris stand out |
| **Spooky** | Flickering, a slow glow pulse, and a startle (white flash, eyes wide) when someone new appears |
| **Sleep** | After `after_s` seconds with nobody around, the eye droops, the lids close to `lid`, and the light breathes slowly |
| **Lids** | `follow_gaze` moves the lids with the eye like a real one; `idle_open` sets how open they are while idling |
| **Identify** | Triggered from the UI: one pulsing colour on all 7 LEDs, eye centred with the lids open, nothing else running |
| **Manual** | Triggered from the UI's sliders or the phone calibration page: direct control of the servos, for 15-20 s at a time |

The priority, highest first, is Manual, Identify, Track, Hold, Sleep, then Idle/Wander.

## Settings and config push

The eye's settings (everything under `firmware:` for that eye in the tracker config) are
pushed over UDP and saved in the ESP32's flash (NVS), so they survive a reboot or a PC
outage.
- Each push carries a version (a checksum of the settings), and the eye acknowledges it.
- The tracker UI shows *config differs* if an eye missed a push. **Push** re-sends the
  saved settings, and with `director.auto_push` the tracker re-sends them automatically
  when an eye comes online out of sync.

## Protocol (UDP, JSON, port 4210)

The tracker sends from one socket; the eye replies to whoever sent the packet.

| PC → eye | Purpose |
|----------|---------|
| `{"t":"look","tgt":1,"pan":12.5,"tilt":-3,"new":0}` | Gaze target at 20 Hz in degrees (`tgt:0` = nobody; `new:1` = a new person, which can trigger a startle) |
| `{"t":"cfg","ver":N,...}` | Settings push; the eye replies `{"t":"ack","ver":N}` |
| `{"t":"manual","pan":0,"tilt":0,"lid":1,"raw":[0,0,0,0],"hold_s":15}` | Manual control in degrees. `raw` is pan, tilt, upper lid, lower lid in servo µs; a non-zero value drives that servo directly |
| `{"t":"release"}` | End manual control |
| `{"t":"identify","on":1,"rgb":[0,255,255],"hold_s":60}` | Identify on/off |
| `{"t":"ping"}` | Ask for a status reply |

| Eye → PC | Fields |
|----------|--------|
| `{"t":"status",...}` | `id`, `ver` (settings version), `state`, `act` (activity), `pan`, `tilt`, `rssi`, `up` (seconds), `fw`, `built`, `board`, `ota`, `ident` |
| `{"t":"ack","ver":N}` | Settings version N was saved |

**OTA (HTTP, port 80).** `GET /` returns the eye's id, firmware and board as JSON.
`POST /update?board=<board>` takes a multipart firmware image (Basic auth `eye` /
`EYE_OTA_PASSWORD`).

## Source layout

| Path | What |
|------|------|
| `firmware/platformio.ini` | Board sections, one env per eye, and the `_ota` upload envs |
| `firmware/src/main.cpp` | WiFi, UDP messages, status, OLED and status LED |
| `firmware/src/behavior.*` | State machine, motion smoothing, blink, wander, sleep, LEDs |
| `firmware/src/eye_config.*` | Settings: defaults, JSON parsing, saving to flash |
| `firmware/src/ota.*` | Over-the-air update endpoint |
| `firmware/scripts/wifi_env.py` | Injects WiFi credentials and the OTA password at build time |
| `firmware/scripts/version.py` | Stamps the firmware version, build date and board |
| `firmware/scripts/ota_upload.py` | WiFi uploader used by the `_ota` envs |

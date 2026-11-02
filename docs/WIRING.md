# Wiring - one eye

[← Back to the overview](../README.md) · [Firmware](FIRMWARE.md)

Two boards are supported. Servo pins are the same on both; the LED data pin differs.
The board mounts on the outside of the frame's side rails; see
[Printed parts → mounting the ESP32](PRINTED_PARTS.md#mounting-the-esp32).

## HiLetgo ESP32 OLED WiFi Kit (`eye1`)

Board: HiLetgo **ESP32 OLED WiFi Kit V3**. Despite the name, this is a classic ESP32
(ESP32-D0WDQ6 chip revision 3) using the Heltec WiFi Kit 32 V2 layout, with a built-in
0.96" OLED. The pins avoid the OLED (4/15/16), Vext (21), the onboard LED (25), the boot
strapping pins (0/2/5/12/15), the flash pins (6-11) and the input-only pins (34-39). They
are set in `firmware/platformio.ini`.

| Function            | ESP32 GPIO | Goes to                                   |
|---------------------|-----------:|-------------------------------------------|
| Pan servo signal    | 26         | SG90 #1 orange wire (yaw tab, frame right) |
| Tilt servo signal   | 27         | SG90 #2 orange wire (pitch tab)            |
| Upper lid servo     | 32         | SG90 #3 orange wire                        |
| Lower lid servo     | 33         | SG90 #4 orange wire                        |
| LED jewel DIN       | 13         | WS2812 7-LED jewel **DIN** via 330 Ω       |
| Ground              | GND        | Common ground with the 5 V supply          |

## Adafruit HUZZAH32 ESP32 Feather (`eye2`)

Classic ESP32 (4 MB flash), no display. The red LED on GPIO 13 shows status:

| LED | Meaning |
|-----|---------|
| Fast blink | Connecting to WiFi |
| Short blip every 2 s | On WiFi, waiting for the tracker |
| Double blip | Idle / wander / sleep |
| Solid | Tracking someone |
| 2 Hz blink | Manual control (calibration) |

The IP and every activity change are printed to the serial monitor (`pio device monitor -e eye2`).

| Function            | Feather pin | GPIO | Goes to |
|---------------------|-------------|-----:|---------|
| Pan servo signal    | A0          | 26   | SG90 #1 orange wire |
| Tilt servo signal   | 27          | 27   | SG90 #2 orange wire |
| Upper lid servo     | 32          | 32   | SG90 #3 orange wire |
| Lower lid servo     | 33          | 33   | SG90 #4 orange wire |
| LED jewel DIN       | 21          | 21   | WS2812 jewel **DIN** via 330 Ω (GPIO 13 is the red LED, so it isn't used) |
| Ground              | GND         |      | Common ground with the 5 V supply |

Power the Feather from USB or its `USB` pin. Don't feed the 5 V servo supply into the `BAT`
pin, which is for a 3.7 V LiPo only.

## Power

```
 5V 3A+ supply ──┬──────────────► servo red wires (x4)
                 ├──────────────► jewel 5V / VCC
                 │   1000 µF cap across 5V/GND near the servos
                 └──► (optional) board 5V pin - or power the board over USB-C
 Supply GND ─────┴──────────────► servo brown wires, jewel GND, ESP32 GND   <- must be shared
```

* Do **not** power the servos from the ESP32's 3.3 V or USB 5 V pin - 4 SG90s can stall at over 2 A
  and will brown out the board (random resets / WiFi drops).
* If you power the board from the same supply through its 5V pin, don't also plug in USB
  at the same time unless you know your board has a protection diode.
* The jewel's data line is 3.3 V logic; this nearly always works with the LED at 5 V for short
  wires (< 20 cm). If the colours glitch, add a 74AHCT125 level shifter, or run the jewel
  from about 4.5 V (through a diode drop).

## Jewel LED order

The firmware treats LED 0 as the centre and LEDs 1-6 as the ring, which is the standard
order for 7-LED jewels. The LED insert's funnel carries the **centre LED to the iris** (iris
colours: idle / track / sleep). The **six ring LEDs sit outside the funnel and light the white
of the eye** (`sclera` colour). If your board numbers them differently, the iris and the
white will swap colours: change the indices in `behavior.cpp` `updateLeds()`.

## First power-up

1. Flash with the servo horns **removed**. On boot the servos go to the configured centre.
2. Open the tracker UI → Eyes → Calibration. Move **Pan µs** until the eye looks straight
   ahead, then press **Set centre**. Do the same for tilt, then set open/closed for each lid.
3. Fit the horns/pushrods at those positions, then tune `us_per_deg` (and flip its sign if a
   servo moves the wrong way). Use the **Pan °/Tilt °** sliders to confirm ±20° looks right.
4. **Save & Push**. This is the eye's *mechanical* calibration and is stored on the ESP32.
   Aiming at people (correcting for camera placement) is done separately with calibrate by
   pointing, which stays on the PC and never needs another push. See
   [Tracker → calibration](TRACKER.md#calibration).

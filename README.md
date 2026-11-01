# Spooky Eye Tracker

[![CI](https://github.com/coreyfournier/SpookyEyeTracker/actions/workflows/ci.yml/badge.svg)](https://github.com/coreyfournier/SpookyEyeTracker/actions/workflows/ci.yml)

Up to two Hikvision cameras watch the front yard. A tracker (on a PC or in Docker) detects
people with YOLO, works out where each one is standing in the yard (in metres) and how
tall they are, and streams pan/tilt targets over UDP to one or more 3D-printed animatronic
eyes, each driven by an ESP32.

```
 0-2 cameras ─RTSP─► CameraWorker (YOLO pose + ByteTrack, per camera)
                        │ box + face keypoints → ground position + eye-level height
                        ▼
                    World (fuses the cameras into "people"; triangulates faces both cameras see)
                        ▼
                    Director (picks a person per eye: closest / spread)
                        │ pan/tilt per eye, 20 Hz UDP
                        ▼
                    ESP32 eye(s) - smoothing, blink, wander, iris colour, spooky mode
```

Detection knows nothing about eyes, and eyes know nothing about cameras. To add an eye,
flash another board and add an entry under `eyes:` in the config (or the UI).

## How it works - a tour of the web UI

The tracker serves a web UI on port 8080. These screenshots are from the real system on
Halloween night, before calibration (the camera positions are still the first guesses).

### 1. Each camera finds people

![Both camera views with a detected person](docs/images/live-cameras.jpg)

Each camera's stream runs through a YOLO pose model. The **red box** is a detected person,
and the **yellow dot** is their eyes (from face keypoints, falling back to ears, shoulders,
or 1/16 of the way down the box). The faint **grid** is the ground plane drawn every 2 m
from the camera's configured pose. When the pose is right, the grid lies flat on the lawn,
and that's how you check camera calibration. The label shows the person's estimated
position in the yard and their measured eye-level height.

### 2. Everyone is placed on a yard map

![Top-down yard map with cameras, the eye, people and the gaze line](docs/images/yard-map.png)

The **Live** tab's top-down map shows:
- each camera (blue square and field-of-view wedge)
- the eye (orange dot) and its current gaze (orange line)
- every person the tracker knows about

People seen by both cameras are fused into a single person, and their face is
triangulated for an exact height. **This screenshot shows why calibration matters.** The
cameras are still at their guessed positions, so the same person appears as two (#1 and
#3) about 3 m apart, and the left camera reads their eye level as 2.04 m. Once the camera
poses are corrected (step 4 below), those collapse into one person at the right height.
Click anywhere on the map to make the eye look at that spot.

### 3. Each eye is configured and pushed from the UI

![Eye settings: servo calibration, behaviors and manual control](docs/images/eyes-tab.png)

The **Eyes** tab has one card per eye:
- **Settings:** servo centers and limits, motion smoothing, and each behavior, all
  switchable (blink, idle wander, iris colors by state, spooky mode, sleep, lids following
  the gaze).
- **Manual-control sliders:** take over the servos to find their positions.
- **Save & Push:** writes the config file and sends the settings to the ESP32 over UDP.
- **Push:** re-sends the saved settings if the eye missed them. The status chip shows
  whether the eye is online and its config is in sync.

### 4. Cameras: 0, 1 or 2

![Camera settings with add/remove](docs/images/cameras-tab.png)

Each camera's address, stream and pose (position, heading, pitch, field of view) can be
edited live. Cameras can be added or removed, up to two, without restarting.

### 5. Calibrate an eye from your phone

<img src="docs/images/calibrate-phone.png" alt="Phone calibration page" width="300" align="right">

Open `/calibrate` on your phone and stand in the yard. The page shows who the cameras
see, how far away they are, and their eye-level height.

1. **Snap to me** points the eye where the tracker thinks you are.
2. Use the arrows to nudge it until it's looking right at you, then tap **Capture this spot**.
3. Repeat at 4-5 spots.

The tracker fits each servo's center and scale (µs per degree) from those samples. This
absorbs servo offsets, linkage ratios and camera-pose errors in one step. **Apply** saves
and pushes the result.

<br clear="right">

## Layout

| Path | What |
|------|------|
| `tracker/` | Python tracker + web UI; `config.default.yaml` is the config template; `tests/` has the unit tests |
| `tracker-data/` | Your live `config.yaml` + `calibration.json` (git-ignored, created on first run) |
| `firmware/` | PlatformIO project for the HiLetgo ESP32 OLED kit (classic ESP32) |
| `cad/` | `build.py` generates the printable parts into `cad/stl/` |
| `docs/WIRING.md` | Pins, power and the servo calibration procedure |
| `Dockerfile`, `docker-compose*.yml` | Container image for the tracker |
| `.github/workflows/ci.yml` | Tests, firmware compile, Docker build + push |

## 1. Configure

1. Copy `.env.example` to `.env` and fill in the camera username, password and IPs.
   (`.env` is git-ignored. If the password contains quotes, wrap it in double quotes.)
2. The live config is `tracker-data/config.yaml` (`/config/config.yaml` in Docker), copied from
   `tracker/config.default.yaml` on first run. Cameras are optional: **0, 1 or 2** (2 is the
   maximum). Each camera takes either a literal `ip` or `ip_env` (the name of a variable in
   `.env`). You can also add and remove cameras from the UI's **Cameras** tab; changes
   apply without a restart. With no cameras the eyes still idle, wander and blink, and can
   be calibrated by hand.
3. Set each eye's `ip` (shown on its OLED - reserve it in your router's DHCP).

## 2. Run the tracker

### Option A - Docker (recommended)

Images are built by CI and published to GitHub Container Registry:

| Image | Use |
|-------|-----|
| `ghcr.io/coreyfournier/spookyeyetracker:latest` | NVIDIA GPU (CUDA). Also runs on CPU if no GPU is visible |
| `ghcr.io/coreyfournier/spookyeyetracker:cpu` | CPU only, much smaller. ~3-6 fps per camera instead of 10-15 |

On **Windows (this PC)**: install Docker Desktop with the WSL2 backend (GPU passthrough
works out of the box with a current NVIDIA driver), then:

```powershell
docker login ghcr.io -u coreyfournier      # only if the package is private: use a PAT with read:packages
docker compose pull
docker compose up -d                        # GPU
# or, without a GPU:
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
docker compose logs -f
```

Open http://localhost:8080. On first start the container copies the default
`config.yaml` into `./tracker-data/`. Edit it there or through the UI; calibration samples
are saved next to it. To build the image locally instead of pulling it, run
`docker compose build`.

The eyes are reached over UDP from inside the container. Docker's NAT handles the replies,
so no extra ports are needed beyond 8080 for the UI.

### Option B - directly on Windows

```powershell
python -m venv .venv
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\pip install -r tracker\requirements.txt
.\run_tracker.ps1                 # cameras + eyes + UI on http://localhost:8080
.\run_tracker.ps1 --no-cameras    # just UI + eyes (servo calibration)
```

### Opening the UI from a phone

Windows Firewall blocks inbound connections by default. In an **admin** PowerShell, run:

```powershell
New-NetFirewallRule -DisplayName "Eye tracker UI (TCP 8080)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private -RemoteAddress Any
```

Then browse to `http://<PC IP>:8080` (or `/calibrate`).

## 3. Flash an eye

```powershell
cd firmware
pio run -e eye1 -t upload
pio device monitor
```

WiFi credentials come from the `ENV_WIFI_SSID` / `ENV_WIFI_PW` environment variables at
build time. The serial log and OLED show the IP. The eye stores its last pushed config in
flash. The UI shows *config differs* if it missed a push. **Push** re-sends the saved
config, and with `director.auto_push` the tracker re-sends it automatically.

## 4. Calibrate

**Cameras.** The camera poses in the config are a first guess. Open **Live**: each camera
view draws a 2 m ground grid, a ★ where the eye should be, and a yellow dot on each
detected face. Adjust `position`/`heading`/`pitch` on the **Cameras** tab until the grid
lies flat on the lawn. Stand at a measured spot and check the yard map puts you there.

**Eyes (calibrate by pointing).** Open `/calibrate` on your phone and stand in the yard.
1. **Snap to me**, nudge the eye with the arrows until it looks right at you, then **Capture**.
2. One spot sets zero. 4-5 spots (left, centre, right, near, far) also fit the scale and
   catch a reversed servo.
3. **Apply — Save & Push** writes `center`/`us_per_deg` and pushes them to the eye.

**Eye-level height.** The pose model finds each person's eyes, falling back to their ears,
then shoulders, then 1/16 of the way down the box. With the feet visible, one camera
measures eye level from the ground position. When both cameras see the face, they
triangulate it. `world.look_height` is used only when height can't be measured.

## 5. Print

Generate the parts with `.venv\Scripts\python cad\build.py` (needs `trimesh` and
`manifold3d`). `eye_front.stl` includes a snap-off support ring under its mating rim. Print
it seam-face down and remove the ring afterwards. `eye_front_nosupport.stl` is the same part
for slicer-generated supports. Use tree supports for the inside of the iris dome.

## Tests and CI

Run the unit tests locally (no GPU, cameras or ESP32 needed):

```powershell
.venv\Scripts\pip install -r tracker\requirements-test.txt
cd tracker
..\.venv\Scripts\python -m pytest
```

They cover the camera geometry, keypoint fallbacks, person fusion and height triangulation,
the director's assignment strategies, the calibration fit, config validation (including
the 2-camera limit), the UDP protocol against a fake eye, the camera manager and the web API.

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push and PR:

1. **Unit tests** - pytest, with a JUnit report uploaded as an artifact.
2. **Firmware build** - compiles the PlatformIO project (placeholder WiFi credentials).
3. **Docker image** - built for both `cuda` and `cpu` once the other jobs pass. On `main`,
   pushes `:latest` and `:cpu` plus `:sha-<commit>` tags to `ghcr.io`. A `v1.2.3` git tag
   also publishes `:1.2.3` / `:1.2.3-cpu`. Pull requests build but don't push. The CPU
   image gets a smoke test.

The workflow uses the built-in `GITHUB_TOKEN`, so no secrets are needed. The first push
creates the package as **private**. Change its visibility under the repo's **Packages**
if you want to pull without logging in.

## Protocol (UDP, JSON, port 4210)

| PC → eye | Purpose |
|----------|---------|
| `{"t":"look","tgt":1,"pan":12.5,"tilt":-3,"new":0}` | gaze target at 20 Hz (`tgt:0` = nobody) |
| `{"t":"cfg","ver":N,...}` | config push → eye replies `{"t":"ack","ver":N}` |
| `{"t":"manual",...}` / `{"t":"release"}` | calibration override |
| `{"t":"ping"}` | → `{"t":"status","state":"track",...}` |

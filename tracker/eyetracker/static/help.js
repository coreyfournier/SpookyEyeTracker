// Plain-language help for config fields, shown by the ⓘ buttons in the main UI's forms.
// Keys are "<form>:<dotted path>" (form = eye | camera | settings). A function gets L(metres),
// which formats a length in the chosen units. Self-explanatory fields have no entry.
const FIELD_HELP = L => ({
  // ---------------- tracking settings ----------------
  'settings:world': 'Settings about the yard itself.',
  'settings:world.look_height': `How high above the ground to aim when a person's real eye height can't be measured
    (for example when their feet are out of view). It's an average adult's eye level, about ${L(1.55)}. Set it lower
    if most visitors are kids (trick-or-treaters!) and the eyes look over their heads. Ignored whenever "measure height"
    is on and the cameras can measure the person.`,
  'settings:tracking': 'How detections from the cameras are turned into people on the yard map.',
  'settings:tracking.merge_distance': `Two detections closer together than this are treated as the same person. If one
    person shows up as two dots, raise it a little. If two people walking together become one dot, lower it. After
    calibrating the cameras, about ${L(1)}–${L(1.5)} works well.`,
  'settings:tracking.max_age': `Seconds a person is remembered after the cameras last saw them, so a brief blip (passing
    behind a tree) doesn't make the eye lose them. Longer = steadier but slower to notice someone left.`,
  'settings:tracking.smoothing': `How quickly a person's dot follows new detections, from 0 to 1. Higher = snappier but
    jittery; lower = smooth but lags behind fast walkers. 0.3–0.4 is a good start.`,
  'settings:tracking.measure_height': `Aim at each person's actual eye level (measured by the cameras) instead of the fixed
    "look height". Leave on so the eye looks kids and adults in the eye.`,
  'settings:tracking.height_smoothing': `How quickly a person's measured height can change, from 0 to 1. People don't change
    height, so keep it low; it filters out bad measurements (e.g. while someone bends down).`,
  'settings:director': 'Decides which person each eye looks at.',
  'settings:director.strategy': `"closest": every eye watches the person nearest to it. "spread": with several eyes,
    different eyes prefer different people, so a group gets watched by everyone.`,
  'settings:director.switch_margin': `How much closer a new person must be before an eye stops watching its current target and
    switches. Prevents the eye flicking back and forth between two people at similar distances. Raise it if the eye
    keeps switching.`,
  'settings:director.max_pan': `Degrees to either side. People further to the side than this are ignored, so the eye
    doesn't strain against its limits staring at someone it can't really face.`,
  'settings:director.rate_hz': `How many times per second the eyes are sent where to look. 20 is smooth; lower only if your
    WiFi struggles.`,
  'settings:director.auto_push': `When an eye comes online with different settings than saved here (e.g. after it was
    reflashed), send it the saved settings automatically.`,
  'settings:detection': 'The AI model that finds people in the camera images.',
  'settings:detection.model': `Which YOLO model file to use. The "-pose" model also finds eyes, ears and shoulders, which is
    what lets the tracker aim at faces. Leave as is unless you know you need another.`,
  'settings:detection.confidence': `How sure (0–1) the model must be before something counts as a person. Raise it if bushes
    or shadows get detected as people; lower it if real people at a distance are missed.`,
  'settings:detection.imgsz': `Size, in pixels, the camera image is shrunk to before looking for people. Bigger finds people
    further away but is slower. 640 suits most yards; try 960 or 1280 for long distances on a good GPU.`,
  'settings:detection.device': `Where the model runs. "auto" uses the graphics card if there is one, else the processor.
    "cpu" forces the processor; "0" forces the first NVIDIA GPU.`,

  // ---------------- cameras ----------------
  'camera:ip_env': `Name of a setting in the .env file that holds this camera's IP address (keeps addresses out of the
    config). Leave empty and fill in "ip" instead to type the address here.`,
  'camera:rtsp_port': 'Network port of the camera\'s video stream. Hikvision cameras use 554 unless you changed it.',
  'camera:channel': `Which video stream to read. 101 = main (full quality), 102 = sub stream (lower quality; on these
    cameras only 2 frames a second, which is too slow for tracking).`,
  'camera:position': `Where the camera is, as X, Y, height. X is along the house (+ = right when you look out at the
    street), Y is out toward the street, height is above the ground. Measured from the front wall of the house. The
    camera calibration wizard (Calibrate cameras ↗) works this out for you.`,
  'camera:heading': `Which way the camera faces, in degrees: 0 = straight at the street, +90 = to the right (looking out),
    −90 = to the left.`,
  'camera:pitch': 'How much the camera tilts up or down, in degrees. Negative = looking down (most cameras are around −10 to −25).',
  'camera:roll': 'How much the camera image is rotated (tilted sideways), in degrees. Usually close to 0.',
  'camera:hfov': `Horizontal field of view: how wide the camera sees, in degrees, edge to edge. Wide-angle security cameras
    are typically 80–110. The calibration wizard measures it.`,

  // ---------------- eyes ----------------
  'eye:ip': `The eye's IP address on your network. It's shown on the eye's screen (or in its serial log). Reserve it in your
    router so it never changes.`,
  'eye:port': 'Network port the eye listens on. Leave at 4210 unless you changed the firmware.',
  'eye:position': `Where the eye is, as X, Y, height, in the same yard coordinates as the cameras: X along the house
    (+ = right looking out), Y toward the street, height above the ground. Used to work out the angle to each person.`,
  'eye:heading': 'Which way the eye faces when centred, in degrees: 0 = straight at the street, + = turned right (looking out).',
  'eye:pitch': 'Up/down tilt of the eye when centred, in degrees. Negative if the eye is mounted tilted down.',
  'eye:identify_color': 'The colour this eye glows when you press Identify, so you can tell which physical eye you\'re setting up.',
  'eye:aim': `Small corrections the tracker applies to every angle it sends this eye, so it looks exactly at people. You
    don't normally type these: "Calibrate by pointing" measures them. sent angle = offset + scale × calculated angle.`,
  'eye:aim.pan_offset': 'Degrees added to every left/right angle. Fixes an eye that always looks a bit to one side.',
  'eye:aim.pan_scale': 'Multiplies every left/right angle. Above 1 = turn further than calculated, below 1 = less.',
  'eye:aim.tilt_offset': 'Degrees added to every up/down angle. Fixes an eye that always looks a bit high or low.',
  'eye:aim.tilt_scale': 'Multiplies every up/down angle.',
  'eye:firmware': 'Settings sent to the eye and stored in it, so it keeps behaving (idle, blink, sleep) even when this PC is off.',
  'eye:firmware.servos': `Mechanical setup of each servo. Set once per build using the sliders on the right: find the
    values, copy them in, Save & Push.`,
  'eye:firmware.servos.pan.center': 'Servo pulse (µs) that points the eye straight ahead, left/right.',
  'eye:firmware.servos.pan.us_per_deg': `Pulse change per degree of eye movement. Make it negative if the eye moves the wrong
    way (left when it should go right).`,
  'eye:firmware.servos.pan.min': 'Furthest the eye may turn to one side, in degrees (negative). Stops it hitting the shell.',
  'eye:firmware.servos.pan.max': 'Furthest the eye may turn to the other side, in degrees.',
  'eye:firmware.servos.tilt.center': 'Servo pulse (µs) that points the eye straight ahead, up/down.',
  'eye:firmware.servos.tilt.us_per_deg': 'Pulse change per degree. Make it negative if up and down are reversed.',
  'eye:firmware.servos.tilt.min': 'Furthest the eye may look down, in degrees (negative).',
  'eye:firmware.servos.tilt.max': 'Furthest the eye may look up, in degrees.',
  'eye:firmware.servos.lid_upper': 'Servo pulses (µs) for the upper eyelid fully open and fully closed.',
  'eye:firmware.servos.lid_lower': 'Servo pulses (µs) for the lower eyelid fully open and fully closed.',
  'eye:firmware.motion': 'How the eye moves.',
  'eye:firmware.motion.max_speed': `Fastest the eye may turn, in degrees per second. Lower = slow and creepy; higher =
    darting. Real eyes can do 400+.`,
  'eye:firmware.motion.smoothing': `Seconds the eye takes to ease toward where it should look. Lower = twitchy and
    immediate; higher = smooth, lazy glide.`,
  'eye:firmware.motion.track_hold': `Seconds the eye keeps staring where a person was last seen after they disappear, before
    going back to idling.`,
  'eye:firmware.behaviors': 'Things the eye does on its own. Each can be switched off.',
  'eye:firmware.behaviors.blink': 'Random blinking.',
  'eye:firmware.behaviors.blink.min_s': 'Shortest time between blinks, in seconds.',
  'eye:firmware.behaviors.blink.max_s': 'Longest time between blinks, in seconds. Each gap is random between min and max.',
  'eye:firmware.behaviors.blink.duration_ms': 'How long one blink takes, in milliseconds.',
  'eye:firmware.behaviors.blink.double_chance': 'Chance (0–1) that a blink is a quick double blink.',
  'eye:firmware.behaviors.wander': 'When nobody is around, the eye glances around randomly.',
  'eye:firmware.behaviors.wander.min_s': 'Shortest pause between glances, in seconds.',
  'eye:firmware.behaviors.wander.max_s': 'Longest pause between glances, in seconds.',
  'eye:firmware.behaviors.wander.range_pan': 'How far left/right it glances, in degrees.',
  'eye:firmware.behaviors.wander.range_tilt': 'How far up/down it glances, in degrees.',
  'eye:firmware.behaviors.iris': `LED colours. The centre LED lights the iris and changes colour with what the eye is doing;
    the ring of 6 lights the white of the eye.`,
  'eye:firmware.behaviors.iris.idle': 'Iris colour while nobody is around.',
  'eye:firmware.behaviors.iris.track': 'Iris colour while watching someone.',
  'eye:firmware.behaviors.iris.sleep': 'Iris colour while asleep (it also slowly breathes).',
  'eye:firmware.behaviors.iris.sclera': 'Colour of the white of the eye (the 6 outer LEDs). A warm, dim off-white looks most natural.',
  'eye:firmware.behaviors.iris.brightness': 'Brightness of the iris (the centre LED), 0–255.',
  'eye:firmware.behaviors.iris.sclera_brightness': `Brightness of the white of the eye (the 6 outer LEDs), 0–255.
    Lower it to make the iris stand out more.`,
  'eye:firmware.behaviors.spooky': 'Halloween mode: flickering, pulsing light, and a jump-scare when someone appears.',
  'eye:firmware.behaviors.spooky.flicker': 'How often the light flickers and dips, 0–1. 0 = never.',
  'eye:firmware.behaviors.spooky.pulse_hz': 'Speed of the slow glow pulse, in pulses per second.',
  'eye:firmware.behaviors.spooky.startle': 'When someone new appears, the eye flashes and opens wide.',
  'eye:firmware.behaviors.sleep': 'After a while with nobody around, the eye droops, closes and dims.',
  'eye:firmware.behaviors.sleep.after_s': 'Seconds with nobody around before the eye falls asleep.',
  'eye:firmware.behaviors.sleep.lid': 'How open the lids are while asleep: 0 = shut, 1 = wide open.',
  'eye:firmware.behaviors.lids': 'Eyelid behaviour.',
  'eye:firmware.behaviors.lids.follow_gaze': 'Lids move with the eye like a real one: looking up opens them a little, looking down lowers them.',
  'eye:firmware.behaviors.lids.idle_open': 'How open the lids are while idling: 0 = shut, 1 = wide open. Below 1 looks relaxed; tracking always opens wide.',
});

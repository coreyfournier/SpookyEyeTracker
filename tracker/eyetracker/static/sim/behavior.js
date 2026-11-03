// A line-for-line port of firmware/src/behavior.cpp (and the config parsing in eye_config.cpp)
// so the simulator moves and lights exactly as an eye would. Keep it in step with the firmware:
// same names, same order. Time is the simulator's clock in ms (it can run faster than real time).

const TICK_MS = 20;          // 50 Hz servo/LED update
const LOOK_STALE_MS = 700;   // PC packets older than this = no target
const STARTLE_MS = 450;

const frand = (a, b) => a + (b - a) * Math.random();
const clampf = (v, lo, hi) => v < lo ? lo : (v > hi ? hi : v);

// eye_config.h defaults
export function defaultConfig() {
  return {
    pan: {center: 1500, usPerDeg: 11, minDeg: -25, maxDeg: 25},
    tilt: {center: 1500, usPerDeg: 27, minDeg: -15, maxDeg: 15},
    lidUpper: {openUs: 1100, closedUs: 1700},
    lidLower: {openUs: 1900, closedUs: 1300},
    maxSpeed: 400, smoothing: 0.08, trackHold: 2,
    blinkEnabled: true, blinkMin: 2, blinkMax: 7, blinkMs: 180, doubleBlink: 0.15,
    wanderEnabled: true, wanderMin: 1.5, wanderMax: 5, wanderPan: 15, wanderTilt: 6,
    irisEnabled: true, irisIdle: [255, 110, 0], irisTrack: [255, 0, 0], irisSleep: [40, 0, 0],
    sclera: [90, 80, 60], brightness: 160, scleraBrightness: 160,
    spookyEnabled: false, flicker: 0.3, pulseHz: 1, startle: true,
    sleepEnabled: true, sleepAfter: 60, sleepLid: 0,
    lidFollow: true, lidIdle: 0.85,
  };
}

// configFromJson: the eye's `firmware:` block from config.yaml; missing keys keep their value
export function configFromJson(o, c = defaultConfig()) {
  const v = (x, d) => x ?? d;
  const axis = (j, a) => j && Object.assign(a, {center: v(j.center, a.center), usPerDeg: v(j.us_per_deg, a.usPerDeg),
    minDeg: v(j.min, a.minDeg), maxDeg: v(j.max, a.maxDeg)});
  const lid = (j, l) => j && Object.assign(l, {openUs: v(j.open, l.openUs), closedUs: v(j.closed, l.closedUs)});
  const rgb = (a, d) => Array.isArray(a) && a.length === 3 ? a.map(Number) : d;
  const s = o?.servos || {}, m = o?.motion || {}, b = o?.behaviors || {};
  axis(s.pan, c.pan); axis(s.tilt, c.tilt); lid(s.lid_upper, c.lidUpper); lid(s.lid_lower, c.lidLower);
  c.maxSpeed = v(m.max_speed, c.maxSpeed); c.smoothing = v(m.smoothing, c.smoothing); c.trackHold = v(m.track_hold, c.trackHold);
  const bl = b.blink || {};
  c.blinkEnabled = v(bl.enabled, c.blinkEnabled); c.blinkMin = v(bl.min_s, c.blinkMin); c.blinkMax = v(bl.max_s, c.blinkMax);
  c.blinkMs = v(bl.duration_ms, c.blinkMs); c.doubleBlink = v(bl.double_chance, c.doubleBlink);
  const w = b.wander || {};
  c.wanderEnabled = v(w.enabled, c.wanderEnabled); c.wanderMin = v(w.min_s, c.wanderMin); c.wanderMax = v(w.max_s, c.wanderMax);
  c.wanderPan = v(w.range_pan, c.wanderPan); c.wanderTilt = v(w.range_tilt, c.wanderTilt);
  const ir = b.iris || {};
  c.irisEnabled = v(ir.enabled, c.irisEnabled); c.irisIdle = rgb(ir.idle, c.irisIdle); c.irisTrack = rgb(ir.track, c.irisTrack);
  c.irisSleep = rgb(ir.sleep, c.irisSleep); c.sclera = rgb(ir.sclera, c.sclera);
  c.brightness = v(ir.brightness, c.brightness); c.scleraBrightness = v(ir.sclera_brightness, c.scleraBrightness);
  const sp = b.spooky || {};
  c.spookyEnabled = v(sp.enabled, c.spookyEnabled); c.flicker = v(sp.flicker, c.flicker); c.pulseHz = v(sp.pulse_hz, c.pulseHz);
  c.startle = v(sp.startle, c.startle);
  const sl = b.sleep || {};
  c.sleepEnabled = v(sl.enabled, c.sleepEnabled); c.sleepAfter = v(sl.after_s, c.sleepAfter); c.sleepLid = v(sl.lid, c.sleepLid);
  const li = b.lids || {};
  c.lidFollow = v(li.follow_gaze, c.lidFollow); c.lidIdle = v(li.idle_open, c.lidIdle);
  return c;
}

export class EyeBehavior {
  constructor(cfg = defaultConfig(), now = 0) {
    this.cfg = cfg;
    this.state = 'idle';                 // idle | track | sleep | manual | identify
    this.look = {hasTarget: false, pan: 0, tilt: 0, atMs: 0};
    this.manual = {pan: 0, tilt: 0, lid: 1, rawUs: [0, 0, 0, 0], untilMs: 0};
    this.curPan = 0; this.curTilt = 0; this.goalPan = 0; this.goalTilt = 0;
    this.lastTick = now; this.lastTargetMs = now;
    this.nextBlinkMs = 0; this.blinkStartMs = 0; this.blinkQueuedDouble = false;
    this.nextWanderMs = 0; this.startleUntil = 0; this.flickerUntil = 0; this.flickerLevel = 1;
    this.holding = false; this.identifyUntil = 0; this.identifyRgb = [0, 255, 255];
    // outputs: servo pulses and LED colours, as the firmware writes them
    this.us = [1500, 1500, 1500, 1500];  // pan, tilt, lidUpper, lidLower
    this.leds = {centre: [0, 0, 0], ring: [0, 0, 0]};
    this.scheduleBlink(now); this.scheduleWander(now);
  }

  axisUs(a, deg) {
    deg = clampf(deg, a.minDeg, a.maxDeg);
    return clampf(Math.round(a.center + deg * a.usPerDeg), 500, 2500);
  }
  lidUs(l, open) {
    open = clampf(open, 0, 1);
    return Math.round(l.closedUs + (l.openUs - l.closedUs) * open);
  }
  scheduleBlink(now) {
    const k = this.cfg.spookyEnabled ? 0.5 : 1.0;
    this.nextBlinkMs = now + frand(this.cfg.blinkMin, this.cfg.blinkMax) * 1000 * k;
  }
  scheduleWander(now) { this.nextWanderMs = now + frand(this.cfg.wanderMin, this.cfg.wanderMax) * 1000; }

  onLook(cmd, newTarget) {
    const wasTracking = this.state === 'track';
    this.look = cmd;
    if (cmd.hasTarget) {
      if ((newTarget || !wasTracking) && this.cfg.spookyEnabled && this.cfg.startle) this.startleUntil = cmd.atMs + STARTLE_MS;
      this.lastTargetMs = cmd.atMs;
    }
  }
  onManual(cmd) { this.manual = cmd; }
  release() { this.manual.untilMs = 0; }
  identify(on, rgb, holdMs, now) { this.identifyRgb = rgb; this.identifyUntil = on ? now + holdMs : 0; }

  blinkFactor(now, allowed) {
    const c = this.cfg;
    if (!c.blinkEnabled || !allowed) { this.blinkStartMs = 0; return 1; }
    if (this.blinkStartMs === 0 && now >= this.nextBlinkMs) {
      this.blinkStartMs = now;
      this.blinkQueuedDouble = frand(0, 1) < c.doubleBlink;
    }
    if (this.blinkStartMs === 0) return 1;
    const t = now - this.blinkStartMs;
    if (t >= c.blinkMs) {
      this.blinkStartMs = 0;
      if (this.blinkQueuedDouble) this.nextBlinkMs = now + 80;   // short gap, then blink again
      else this.scheduleBlink(now);
      return 1;
    }
    return Math.abs(1 - 2 * t / c.blinkMs);   // triangle: 1 -> 0 -> 1
  }

  updateLeds(now) {
    const c = this.cfg, scale = (rgb, k) => rgb.map(v => Math.floor(v * clampf(k, 0, 1)));
    if (now < this.identifyUntil) {
      const k = 0.55 + 0.45 * Math.sin(now * 0.001 * 2 * Math.PI * 0.7);
      this.leds.centre = this.leds.ring = this.identifyRgb.map(v => Math.floor(v * k));
      return;
    }
    let iris, level = 1;
    if (!c.irisEnabled) iris = c.irisIdle;
    else if (this.state === 'track' || this.state === 'manual') iris = c.irisTrack;
    else if (this.state === 'sleep') {
      iris = c.irisSleep;
      level = 0.55 + 0.45 * Math.sin(now * 0.001 * 2 * Math.PI * 0.2);   // slow breathing
    } else iris = c.irisIdle;
    if (c.spookyEnabled) {
      level *= 0.75 + 0.25 * Math.sin(now * 0.001 * 2 * Math.PI * c.pulseHz);
      if (now >= this.flickerUntil) {
        const dip = frand(0, 1) < c.flicker * 0.08;   // per-tick chance
        this.flickerLevel = dip ? frand(0.05, 0.5) : 1;
        this.flickerUntil = now + (dip ? frand(40, 160) : TICK_MS);
      }
      level *= this.flickerLevel;
    }
    const flash = now < this.startleUntil && (now + STARTLE_MS - this.startleUntil) < 150;
    const white = [255, 255, 255];
    this.leds.centre = scale(flash ? white : scale(iris, level), c.brightness / 255);
    this.leds.ring = scale(flash ? white : scale(c.sclera, level), c.scleraBrightness / 255);
  }

  // behaviorUpdate(): call as often as you like; it ticks at 50 Hz of simulator time
  update(now) {
    while (now - this.lastTick >= TICK_MS) this.tick(this.lastTick + TICK_MS);
  }

  tick(now) {
    const c = this.cfg, dt = (now - this.lastTick) / 1000;
    this.lastTick = now;
    const targetFresh = this.look.hasTarget && (now - this.look.atMs) < LOOK_STALE_MS;
    let lidBase;
    this.holding = false;
    if (now < this.manual.untilMs) {
      this.state = 'manual';
      this.goalPan = this.manual.pan; this.goalTilt = this.manual.tilt; lidBase = this.manual.lid;
    } else if (now < this.identifyUntil) {
      this.state = 'identify';
      this.goalPan = this.goalTilt = 0; lidBase = 1;
    } else if (targetFresh) {
      this.state = 'track';
      this.goalPan = this.look.pan; this.goalTilt = this.look.tilt; lidBase = 1;
    } else if (this.state === 'track' && now - this.lastTargetMs < c.trackHold * 1000) {
      this.holding = true; lidBase = 1;   // hold gaze where the person was last seen
    } else if (c.sleepEnabled && now - this.lastTargetMs > c.sleepAfter * 1000) {
      this.state = 'sleep';
      this.goalPan = 0; this.goalTilt = c.tilt.minDeg * 0.5; lidBase = c.sleepLid;   // droop
    } else {
      this.state = 'idle';
      lidBase = c.lidIdle;
      if (c.wanderEnabled) {
        if (now >= this.nextWanderMs) {
          this.goalPan = frand(-c.wanderPan, c.wanderPan);
          this.goalTilt = frand(-c.wanderTilt, c.wanderTilt);
          this.scheduleWander(now);
        }
      } else this.goalPan = this.goalTilt = 0;
    }
    this.goalPan = clampf(this.goalPan, c.pan.minDeg, c.pan.maxDeg);
    this.goalTilt = clampf(this.goalTilt, c.tilt.minDeg, c.tilt.maxDeg);

    // Smooth towards the goal with a speed cap.
    const alpha = c.smoothing > 0 ? 1 - Math.exp(-dt / c.smoothing) : 1;
    const maxStep = c.maxSpeed * dt;
    this.curPan += clampf((this.goalPan - this.curPan) * alpha, -maxStep, maxStep);
    this.curTilt += clampf((this.goalTilt - this.curTilt) * alpha, -maxStep, maxStep);

    // Lids
    if (now < this.startleUntil) lidBase = 1;
    let upper = lidBase, lower = lidBase;
    if (c.lidFollow && this.state !== 'sleep') {
      const t = c.tilt.maxDeg > 0 ? this.curTilt / c.tilt.maxDeg : 0;   // ~ -1..1
      upper = clampf(upper + 0.15 * t, 0, 1);
      lower = clampf(lower - 0.15 * t, 0, 1);
    }
    const blink = this.blinkFactor(now, !['sleep', 'manual', 'identify'].includes(this.state));
    upper *= blink; lower *= blink;

    const raw = this.state === 'manual', r = this.manual.rawUs;
    this.us = [
      raw && r[0] ? r[0] : this.axisUs(c.pan, this.curPan),
      raw && r[1] ? r[1] : this.axisUs(c.tilt, this.curTilt),
      raw && r[2] ? r[2] : this.lidUs(c.lidUpper, upper),
      raw && r[3] ? r[3] : this.lidUs(c.lidLower, lower),
    ];
    this.updateLeds(now);
  }

  // behaviorActivity()
  activity(now) {
    if (this.state === 'track') return now < this.startleUntil ? 'startle' : this.holding ? 'hold' : 'track';
    if (this.state === 'idle') return this.cfg.wanderEnabled ? 'wander' : 'idle';
    return this.state;
  }

  // What the servo pulses do to the mechanism, read back through the same calibration:
  // pan/tilt in degrees and each lid's openness 0..1. Raw manual pulses show up here too.
  pose() {
    const c = this.cfg, [p, t, u, l] = this.us;
    const deg = (a, us) => a.usPerDeg ? (us - a.center) / a.usPerDeg : 0;
    const open = (lid, us) => lid.openUs !== lid.closedUs ? clampf((us - lid.closedUs) / (lid.openUs - lid.closedUs), 0, 1) : 1;
    return {pan: deg(c.pan, p), tilt: deg(c.tilt, t), upper: open(c.lidUpper, u), lower: open(c.lidLower, l)};
  }
}
